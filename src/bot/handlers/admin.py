"""Панель администратора — inline-only single-message UI.

Все операции: каталог CRUD, пользователи, заказы, настройки, аккаунты, статистика, логи.
"""
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.handlers.start import is_admin, is_developer
from src.bot.keyboards import (
    admin_account_actions_kb,
    admin_accounts_menu_kb,
    admin_broadcast_kb,
    admin_categories_list_kb,
    admin_category_edit_kb,
    admin_menu_kb,
    admin_order_status_filter_kb,
    admin_orders_kb,
    admin_products_list_kb,
    admin_products_menu_kb,
    admin_role_kb,
    admin_settings_kb,
    admin_settings_keys_kb,
    admin_user_detail_kb,
    admin_users_kb,
    back_admin_kb,
    cancel_input_kb,
    close_notification_kb,
    confirm_kb,
)
from src.bot.states import AdminStates
from src.bot.utils import answer_callback, safe_edit
from src.config import settings
from src.database.models import (
    Account,
    AuditLog,
    Category,
    Log,
    Order,
    Payment,
    Product,
    Setting,
    User,
)

logger = logging.getLogger(__name__)
router = Router()

_back_btn = lambda cb: InlineKeyboardButton(text="◀️ Назад", callback_data=cb, style="primary")


def _admin_check(user_id: int) -> bool:
    return is_admin(user_id)


# ═══════════════════════════════════════════════════
# ЗАКРЫТИЕ УВЕДОМЛЕНИЙ
# ═══════════════════════════════════════════════════

@router.callback_query(F.data == "close_notification")
async def close_notification(callback: CallbackQuery):
    """Удалить сообщение-уведомление по кнопке «Закрыть»."""
    try:
        await callback.message.delete()
    except Exception:
        pass
    await answer_callback(callback)


# ═══════════════════════════════════════════════════
# МЕНЮ АДМИНА
# ═══════════════════════════════════════════════════

@router.callback_query(F.data == "menu:admin")
async def admin_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not _admin_check(callback.from_user.id):
        await answer_callback(callback, "⛔ Нет доступа.")
        return
    user = (await session.execute(
        select(User).where(User.telegram_id == callback.from_user.id)
    )).scalar_one_or_none()
    if user and not is_admin(callback.from_user.id, user):
        await answer_callback(callback, "⛔ Нет доступа.")
        return
    await state.clear()
    await safe_edit(callback, "⚙️ <b>Панель управления</b>\n\nВыберите раздел:", admin_menu_kb())
    await answer_callback(callback)


# ═══════════════════════════════════════════════════
# ЗАКАЗЫ
# ═══════════════════════════════════════════════════

@router.callback_query(F.data == "adm:orders")
async def orders_menu(callback: CallbackQuery, state: FSMContext):
    if not _admin_check(callback.from_user.id):
        return
    await state.clear()
    await safe_edit(callback, "📦 <b>Управление заказами</b>", admin_orders_kb())
    await answer_callback(callback)


@router.callback_query(F.data == "adm:orders:all")
async def orders_all(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    stmt = select(Order).order_by(Order.created_at.desc()).limit(30)
    orders = (await session.execute(stmt)).scalars().all()
    if not orders:
        await safe_edit(callback, "📦 Заказов пока нет.", back_admin_kb("adm:orders"))
        await answer_callback(callback)
        return
    rows = []
    emoji = {"ОЖИДАЕТ ОПЛАТЫ": "⏳", "ОПЛАЧЕНО": "✅", "ВЫПОЛНЕНО": "✔️", "ОТМЕНЕНО": "❌"}
    for o in orders:
        rows.append([InlineKeyboardButton(
            text=f"{emoji.get(o.status, '❓')} #{o.id} — {o.total_amount:.2f}₽ [{o.status}]",
            callback_data=f"adm:order:{o.id}",
        )])
    rows.append([_back_btn("adm:orders")])
    await safe_edit(callback, "📦 <b>Последние 30 заказов:</b>", InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_callback(callback)


@router.callback_query(F.data == "adm:orders:search")
async def orders_search(callback: CallbackQuery, state: FSMContext):
    if not _admin_check(callback.from_user.id):
        return
    await state.update_data(_menu_msg_id=callback.message.message_id)
    await state.set_state(AdminStates.waiting_order_id)
    await safe_edit(callback, "🔍 Введите ID заказа:", cancel_input_kb("adm:orders"))
    await answer_callback(callback)


@router.message(AdminStates.waiting_order_id)
async def orders_search_result(message: Message, state: FSMContext, session: AsyncSession):
    if not _admin_check(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    await state.clear()

    try:
        order_id = int(message.text.strip())
    except (ValueError, TypeError, AttributeError):
        await message.bot.edit_message_text(
            "❌ Введите числовой ID.", chat_id=message.chat.id, message_id=msg_id,
            reply_markup=cancel_input_kb("adm:orders"), parse_mode="HTML",
        )
        return

    order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if not order:
        await message.bot.edit_message_text(
            f"❌ Заказ #{order_id} не найден.", chat_id=message.chat.id, message_id=msg_id,
            reply_markup=back_admin_kb("adm:orders"), parse_mode="HTML",
        )
        return

    user = (await session.execute(select(User).where(User.id == order.user_id))).scalar_one_or_none()
    product = (await session.execute(select(Product).where(Product.id == order.product_id))).scalar_one_or_none()
    text = _order_detail_text(order, user, product)
    kb = _order_detail_kb(order)
    await message.bot.edit_message_text(text, chat_id=message.chat.id, message_id=msg_id, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("adm:order:"))
async def order_detail(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    try:
        order_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        return

    order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if not order:
        await safe_edit(callback, "❌ Заказ не найден.", back_admin_kb("adm:orders"))
        await answer_callback(callback)
        return

    user = (await session.execute(select(User).where(User.id == order.user_id))).scalar_one_or_none()
    product = (await session.execute(select(Product).where(Product.id == order.product_id))).scalar_one_or_none()
    text = _order_detail_text(order, user, product)
    kb = _order_detail_kb(order)
    await safe_edit(callback, text, kb)
    await answer_callback(callback)


def _order_detail_text(order, user, product) -> str:
    u = f"@{user.username}" if user and user.username else (str(user.telegram_id) if user else "?")
    p = product.name if product else f"ID {order.product_id}"
    return (
        f"📦 <b>Заказ #{order.id}</b>\n\n"
        f"👤 Пользователь: {u}\n"
        f"📦 Товар: {p}\n"
        f"📊 Количество: {order.quantity}\n"
        f"💰 Сумма: {order.total_amount:.2f} ₽\n"
        f"📋 Статус: {order.status}\n"
        f"💳 Оплата: {order.payment_method or '—'}\n"
        f"📅 Создан: {order.created_at:%d.%m.%Y %H:%M}"
    )


def _order_detail_kb(order) -> InlineKeyboardMarkup:
    rows = []
    if order.status == "ОЖИДАЕТ ОПЛАТЫ":
        rows.append([InlineKeyboardButton(text="❌ Отменить", callback_data=f"adm:ocancel:{order.id}", style="danger")])
    if order.status in ("ОЖИДАЕТ ОПЛАТЫ", "ОПЛАЧЕНО"):
        rows.append([InlineKeyboardButton(text="✅ Выполнить", callback_data=f"adm:ocomplete:{order.id}", style="success")])
    rows.append([_back_btn("adm:orders:all")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("adm:ocancel:"))
async def order_cancel(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    order_id = int(callback.data.split(":")[2])
    order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if not order:
        await answer_callback(callback, "❌ Заказ не найден.")
        return
    # Возвращаем аккаунты
    await session.execute(
        sa_update(Account).where(Account.order_id == order_id).values(is_sold=False, order_id=None, sold_at=None)
    )
    product = (await session.execute(select(Product).where(Product.id == order.product_id))).scalar_one_or_none()
    if product:
        accs = (await session.execute(
            select(func.count(Account.id)).where(Account.product_id == product.id, Account.is_sold == False)
        )).scalar() or 0
        product.stock_count = accs

    order.status = "ОТМЕНЕНО"
    await session.commit()
    await safe_edit(callback, f"✅ Заказ #{order_id} отменён.", back_admin_kb("adm:orders"))
    await answer_callback(callback)


@router.callback_query(F.data.startswith("adm:ocomplete:"))
async def order_complete(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    order_id = int(callback.data.split(":")[2])
    order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if not order:
        await answer_callback(callback, "❌ Заказ не найден.")
        return
    order.status = "ВЫПОЛНЕНО"
    order.completed_at = datetime.now()
    await session.commit()
    await safe_edit(callback, f"✅ Заказ #{order_id} выполнен.", back_admin_kb("adm:orders"))
    await answer_callback(callback)


@router.callback_query(F.data == "adm:orders:date")
async def orders_date_start(callback: CallbackQuery, state: FSMContext):
    if not _admin_check(callback.from_user.id):
        return
    await state.update_data(_menu_msg_id=callback.message.message_id)
    await state.set_state(AdminStates.waiting_order_date_from)
    await safe_edit(callback, "📅 Введите дату начала (ДД.ММ.ГГГГ):", cancel_input_kb("adm:orders"))
    await answer_callback(callback)


@router.message(AdminStates.waiting_order_date_from)
async def orders_date_from(message: Message, state: FSMContext):
    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    try:
        dt = datetime.strptime(message.text.strip(), "%d.%m.%Y")
        await state.update_data(_date_from=dt.isoformat())
        await state.set_state(AdminStates.waiting_order_date_to)
        await message.bot.edit_message_text(
            "📅 Введите дату конца (ДД.ММ.ГГГГ):",
            chat_id=message.chat.id, message_id=msg_id,
            reply_markup=cancel_input_kb("adm:orders"), parse_mode="HTML",
        )
    except ValueError:
        await message.bot.edit_message_text(
            "❌ Неверный формат. Используйте ДД.ММ.ГГГГ:",
            chat_id=message.chat.id, message_id=msg_id,
            reply_markup=cancel_input_kb("adm:orders"), parse_mode="HTML",
        )


@router.message(AdminStates.waiting_order_date_to)
async def orders_date_to(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    await state.clear()
    try:
        dt_to = datetime.strptime(message.text.strip(), "%d.%m.%Y").replace(hour=23, minute=59, second=59)
        dt_from = datetime.fromisoformat(data.get("_date_from", ""))
    except (ValueError, TypeError):
        await message.bot.edit_message_text(
            "❌ Ошибка формата даты.", chat_id=message.chat.id, message_id=msg_id,
            reply_markup=back_admin_kb("adm:orders"), parse_mode="HTML",
        )
        return

    stmt = select(Order).where(Order.created_at.between(dt_from, dt_to)).order_by(Order.created_at.desc()).limit(30)
    orders = (await session.execute(stmt)).scalars().all()
    if not orders:
        await message.bot.edit_message_text(
            "📦 Заказов за этот период нет.", chat_id=message.chat.id, message_id=msg_id,
            reply_markup=back_admin_kb("adm:orders"), parse_mode="HTML",
        )
        return

    rows = []
    emoji = {"ОЖИДАЕТ ОПЛАТЫ": "⏳", "ОПЛАЧЕНО": "✅", "ВЫПОЛНЕНО": "✔️", "ОТМЕНЕНО": "❌"}
    for o in orders:
        rows.append([InlineKeyboardButton(
            text=f"{emoji.get(o.status, '❓')} #{o.id} — {o.total_amount:.2f}₽",
            callback_data=f"adm:order:{o.id}",
        )])
    rows.append([_back_btn("adm:orders")])
    await message.bot.edit_message_text(
        f"📦 <b>Заказы с {dt_from:%d.%m.%Y} по {dt_to:%d.%m.%Y}:</b>",
        chat_id=message.chat.id, message_id=msg_id,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML",
    )


@router.callback_query(F.data == "adm:orders:status")
async def orders_status_filter(callback: CallbackQuery):
    if not _admin_check(callback.from_user.id):
        return
    await safe_edit(callback, "📊 Выберите статус:", admin_order_status_filter_kb())
    await answer_callback(callback)


@router.callback_query(F.data.startswith("adm:orders:fs:"))
async def orders_status_result(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    status = callback.data.split(":", 3)[3]
    stmt = select(Order).where(Order.status == status).order_by(Order.created_at.desc()).limit(30)
    orders = (await session.execute(stmt)).scalars().all()
    if not orders:
        await safe_edit(callback, f"📦 Заказов со статусом «{status}» нет.", back_admin_kb("adm:orders"))
        await answer_callback(callback)
        return
    rows = []
    for o in orders:
        rows.append([InlineKeyboardButton(
            text=f"#{o.id} — {o.total_amount:.2f}₽",
            callback_data=f"adm:order:{o.id}",
        )])
    rows.append([_back_btn("adm:orders")])
    await safe_edit(callback, f"📦 <b>Заказы [{status}]:</b>", InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_callback(callback)


@router.callback_query(F.data == "adm:orders:user")
async def orders_by_user(callback: CallbackQuery, state: FSMContext):
    if not _admin_check(callback.from_user.id):
        return
    await state.update_data(_menu_msg_id=callback.message.message_id)
    await state.set_state(AdminStates.waiting_user_id)
    await safe_edit(callback, "👤 Введите Telegram ID пользователя:", cancel_input_kb("adm:orders"))
    await answer_callback(callback)


# ═══════════════════════════════════════════════════
# ТОВАРЫ — ПОДМЕНЮ
# ═══════════════════════════════════════════════════

@router.callback_query(F.data == "adm:products")
async def products_submenu(callback: CallbackQuery, state: FSMContext):
    if not _admin_check(callback.from_user.id):
        return
    await state.clear()
    await safe_edit(callback, "📂 <b>Управление товарами</b>\n\nВыберите раздел:", admin_products_menu_kb())
    await answer_callback(callback)


# ═══════════════════════════════════════════════════
# КАТЕГОРИИ — СПИСОК С EDIT/DELETE
# ═══════════════════════════════════════════════════

@router.callback_query(F.data == "adm:categories")
async def categories_list(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not _admin_check(callback.from_user.id):
        return
    await state.clear()
    cats = (await session.execute(select(Category).order_by(Category.name))).scalars().all()
    if not cats:
        from src.bot.keyboards import _back_menu_row
        rows = [
            [InlineKeyboardButton(text="➕ Добавить категорию", callback_data="adm:cat:add", style="success")],
            _back_menu_row("adm:products"),
        ]
        await safe_edit(callback, "📂 <b>Категории</b>\n\nКатегорий пока нет.", InlineKeyboardMarkup(inline_keyboard=rows))
        await answer_callback(callback)
        return
    await safe_edit(callback, "📂 <b>Категории</b>", admin_categories_list_kb(cats))
    await answer_callback(callback)


@router.callback_query(F.data.startswith("adm:cat:view:"))
async def category_view(callback: CallbackQuery, session: AsyncSession):
    """Просмотр категории — показываем товары в ней."""
    if not _admin_check(callback.from_user.id):
        return
    cat_id = int(callback.data.split(":")[3])
    cat = (await session.execute(select(Category).where(Category.id == cat_id))).scalar_one_or_none()
    if not cat:
        await answer_callback(callback, "❌ Категория не найдена.")
        return
    prods = (await session.execute(
        select(Product).where(Product.category_id == cat_id).order_by(Product.name)
    )).scalars().all()
    text = f"📂 <b>{cat.name}</b>\n\n"
    if prods:
        text += "Товары в категории:\n"
        for p in prods:
            text += f"• {p.name} — {p.price:.2f}₽ (склад: {p.stock_count})\n"
    else:
        text += "Товаров в категории нет."
    await safe_edit(callback, text, back_admin_kb("adm:categories"))
    await answer_callback(callback)


@router.callback_query(F.data.startswith("adm:cat:edit:"))
async def category_edit_menu(callback: CallbackQuery, session: AsyncSession):
    """Меню редактирования категории."""
    if not _admin_check(callback.from_user.id):
        return
    cat_id = int(callback.data.split(":")[3])
    cat = (await session.execute(select(Category).where(Category.id == cat_id))).scalar_one_or_none()
    if not cat:
        await answer_callback(callback, "❌ Категория не найдена.")
        return
    await safe_edit(callback, f"✏️ <b>Редактирование: {cat.name}</b>", admin_category_edit_kb(cat_id))
    await answer_callback(callback)


@router.callback_query(F.data.startswith("adm:cat:rename:"))
async def category_rename_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Начать переименование категории."""
    if not _admin_check(callback.from_user.id):
        return
    cat_id = int(callback.data.split(":")[3])
    cat = (await session.execute(select(Category).where(Category.id == cat_id))).scalar_one_or_none()
    if not cat:
        await answer_callback(callback, "❌ Категория не найдена.")
        return
    await state.update_data(_menu_msg_id=callback.message.message_id, _rename_cat_id=cat_id)
    await state.set_state(AdminStates.waiting_category_rename)
    await safe_edit(
        callback,
        f"✏️ Текущее название: <b>{cat.name}</b>\n\n Введите новое название:",
        cancel_input_kb("adm:categories"),
    )
    await answer_callback(callback)


@router.message(AdminStates.waiting_category_rename)
async def category_rename_finish(message: Message, state: FSMContext, session: AsyncSession):
    if not _admin_check(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    cat_id = data.get("_rename_cat_id")
    await state.clear()

    new_name = (message.text or "").strip()
    if not new_name:
        return

    cat = (await session.execute(select(Category).where(Category.id == cat_id))).scalar_one_or_none()
    if not cat:
        return

    old_name = cat.name
    cat.name = new_name
    await session.commit()
    await message.bot.edit_message_text(
        f"✅ Категория «{old_name}» переименована в «{new_name}».",
        chat_id=message.chat.id, message_id=msg_id,
        reply_markup=back_admin_kb("adm:categories"), parse_mode="HTML",
    )


@router.callback_query(F.data == "adm:cat:add")
async def cat_add_start(callback: CallbackQuery, state: FSMContext):
    if not _admin_check(callback.from_user.id):
        return
    await state.update_data(_menu_msg_id=callback.message.message_id)
    await state.set_state(AdminStates.waiting_category_name)
    await safe_edit(callback, "➕ Введите название новой категории:", cancel_input_kb("adm:categories"))
    await answer_callback(callback)


@router.message(AdminStates.waiting_category_name)
async def cat_add_finish(message: Message, state: FSMContext, session: AsyncSession):
    if not _admin_check(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    await state.clear()

    name = (message.text or "").strip()
    if not name:
        return

    existing = (await session.execute(select(Category).where(Category.name == name))).scalar_one_or_none()
    if existing:
        await message.bot.edit_message_text(
            f"❌ Категория «{name}» уже существует.",
            chat_id=message.chat.id, message_id=msg_id,
            reply_markup=back_admin_kb("adm:categories"), parse_mode="HTML",
        )
        return

    session.add(Category(name=name))
    await session.commit()
    await message.bot.edit_message_text(
        f"✅ Категория «{name}» создана.",
        chat_id=message.chat.id, message_id=msg_id,
        reply_markup=back_admin_kb("adm:categories"), parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("adm:cat:confirmdel:"))
async def cat_del_confirm(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    cat_id = int(callback.data.split(":")[3])
    cat = (await session.execute(select(Category).where(Category.id == cat_id))).scalar_one_or_none()
    if not cat:
        await answer_callback(callback, "❌ Не найдена.")
        return

    prod_count = (await session.execute(
        select(func.count(Product.id)).where(Product.category_id == cat_id)
    )).scalar() or 0

    await safe_edit(
        callback,
        f"❓ Удалить категорию <b>«{cat.name}»</b>?\n\nТоваров в категории: {prod_count}",
        confirm_kb("cat", cat_id),
    )
    await answer_callback(callback)


@router.callback_query(F.data.startswith("confirm:cat:"))
async def cat_del_execute(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    cat_id = int(callback.data.split(":")[2])
    cat = (await session.execute(select(Category).where(Category.id == cat_id))).scalar_one_or_none()
    if not cat:
        await answer_callback(callback, "❌ Не найдена.")
        return

    # Удаляем аккаунты и товары этой категории
    prods = (await session.execute(select(Product).where(Product.category_id == cat_id))).scalars().all()
    for p in prods:
        await session.execute(sa_delete(Account).where(Account.product_id == p.id))
        await session.delete(p)
    await session.delete(cat)
    await session.commit()

    await safe_edit(callback, f"✅ Категория «{cat.name}» удалена.", back_admin_kb("adm:categories"))
    await answer_callback(callback)


@router.callback_query(F.data.startswith("reject:cat:"))
async def cat_del_cancel(callback: CallbackQuery):
    await safe_edit(callback, "❌ Удаление отменено.", back_admin_kb("adm:categories"))
    await answer_callback(callback)


# ═══════════════════════════════════════════════════
# ТОВАРЫ — СПИСОК С EDIT/DELETE
# ═══════════════════════════════════════════════════

@router.callback_query(F.data == "adm:prod:list")
async def products_list(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not _admin_check(callback.from_user.id):
        return
    await state.clear()
    prods = (await session.execute(
        select(Product).where(Product.is_active == True).order_by(Product.name).limit(30)
    )).scalars().all()
    if not prods:
        from src.bot.keyboards import _back_menu_row
        rows = [
            [InlineKeyboardButton(text="➕ Добавить товар", callback_data="adm:prod:add", style="success")],
            _back_menu_row("adm:products"),
        ]
        await safe_edit(callback, "📦 <b>Товары</b>\n\nТоваров пока нет.", InlineKeyboardMarkup(inline_keyboard=rows))
        await answer_callback(callback)
        return
    await safe_edit(callback, "📦 <b>Товары</b>", admin_products_list_kb(prods))
    await answer_callback(callback)


# ═══════════════════════════════════════════════════
# ТОВАРЫ: ДОБАВЛЕНИЕ
# ═══════════════════════════════════════════════════

@router.callback_query(F.data == "adm:prod:add")
async def prod_add_start(callback: CallbackQuery, state: FSMContext):
    if not _admin_check(callback.from_user.id):
        return
    await state.update_data(_menu_msg_id=callback.message.message_id, _new_product={})
    await state.set_state(AdminStates.waiting_product_name)
    await safe_edit(callback, "📦 <b>Новый товар</b>\n\n✏️ Введите название:", cancel_input_kb("adm:products"))
    await answer_callback(callback)


@router.message(AdminStates.waiting_product_name)
async def prod_add_name(message: Message, state: FSMContext):
    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    prod = data.get("_new_product", {})
    prod["name"] = (message.text or "").strip()
    await state.update_data(_new_product=prod)
    await state.set_state(AdminStates.waiting_product_price)

    await message.bot.edit_message_text(
        f"📦 Товар: <b>{prod['name']}</b>\n\n💰 Введите цену (₽):",
        chat_id=message.chat.id, message_id=msg_id,
        reply_markup=cancel_input_kb("adm:products"), parse_mode="HTML",
    )


@router.message(AdminStates.waiting_product_price)
async def prod_add_price(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    prod = data.get("_new_product", {})

    try:
        price = float(message.text.replace(",", ".").strip())
        if price <= 0:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        await message.bot.edit_message_text(
            "❌ Введите положительное число:", chat_id=message.chat.id, message_id=msg_id,
            reply_markup=cancel_input_kb("adm:products"), parse_mode="HTML",
        )
        return

    prod["price"] = price
    await state.update_data(_new_product=prod)

    cats = (await session.execute(select(Category).order_by(Category.name))).scalars().all()
    if not cats:
        await state.clear()
        await message.bot.edit_message_text(
            "❌ Нет категорий. Сначала создайте категорию.",
            chat_id=message.chat.id, message_id=msg_id,
            reply_markup=back_admin_kb("adm:products"), parse_mode="HTML",
        )
        return

    rows = [[InlineKeyboardButton(text=c.name, callback_data=f"adm:prodcat:{c.id}")] for c in cats]
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="adm:products", style="danger")])
    await state.set_state(AdminStates.waiting_product_category)
    await message.bot.edit_message_text(
        f"📦 Товар: <b>{prod['name']}</b>\n💰 Цена: {price:.2f} ₽\n\n📂 Выберите категорию:",
        chat_id=message.chat.id, message_id=msg_id,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("adm:prodcat:"), AdminStates.waiting_product_category)
async def prod_add_category(callback: CallbackQuery, state: FSMContext):
    cat_id = int(callback.data.split(":")[2])
    data = await state.get_data()
    prod = data.get("_new_product", {})
    prod["category_id"] = cat_id
    await state.update_data(_new_product=prod)
    await state.set_state(AdminStates.waiting_product_description)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏩ Пропустить", callback_data="adm:prod:skip_desc")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:products", style="danger")],
    ])
    await safe_edit(callback, f"📦 <b>{prod['name']}</b>\n\n📝 Введите описание (или пропустите):", kb)
    await answer_callback(callback)


@router.message(AdminStates.waiting_product_description)
async def prod_add_desc(message: Message, state: FSMContext):
    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    prod = data.get("_new_product", {})
    prod["description"] = (message.text or "").strip()
    await state.update_data(_new_product=prod)
    await state.set_state(AdminStates.waiting_product_format)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏩ Пропустить", callback_data="adm:prod:skip_fmt")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:products", style="danger")],
    ])
    await message.bot.edit_message_text(
        f"📦 <b>{prod['name']}</b>\n\n📋 Введите формат данных (или пропустите):",
        chat_id=message.chat.id, message_id=msg_id,
        reply_markup=kb, parse_mode="HTML",
    )


@router.callback_query(F.data == "adm:prod:skip_desc", AdminStates.waiting_product_description)
async def prod_skip_desc(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    prod = data.get("_new_product", {})
    prod["description"] = ""
    await state.update_data(_new_product=prod)
    await state.set_state(AdminStates.waiting_product_format)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏩ Пропустить", callback_data="adm:prod:skip_fmt")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:products", style="danger")],
    ])
    await safe_edit(callback, f"📦 <b>{prod['name']}</b>\n\n📋 Введите формат данных (или пропустите):", kb)
    await answer_callback(callback)


@router.message(AdminStates.waiting_product_format)
async def prod_add_format(message: Message, state: FSMContext):
    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    prod = data.get("_new_product", {})
    prod["format_info"] = (message.text or "").strip()
    await state.update_data(_new_product=prod)
    await state.set_state(AdminStates.waiting_product_recommendations)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏩ Пропустить", callback_data="adm:prod:skip_rec")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:products", style="danger")],
    ])
    await message.bot.edit_message_text(
        f"📦 <b>{prod['name']}</b>\n\n💡 Введите рекомендации (или пропустите):",
        chat_id=message.chat.id, message_id=msg_id,
        reply_markup=kb, parse_mode="HTML",
    )


@router.callback_query(F.data == "adm:prod:skip_fmt", AdminStates.waiting_product_format)
async def prod_skip_fmt(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    prod = data.get("_new_product", {})
    prod["format_info"] = ""
    await state.update_data(_new_product=prod)
    await state.set_state(AdminStates.waiting_product_recommendations)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏩ Пропустить", callback_data="adm:prod:skip_rec")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:products", style="danger")],
    ])
    await safe_edit(callback, f"📦 <b>{prod['name']}</b>\n\n💡 Введите рекомендации (или пропустите):", kb)
    await answer_callback(callback)


@router.message(AdminStates.waiting_product_recommendations)
async def prod_add_rec(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    prod = data.get("_new_product", {})
    prod["recommendations"] = (message.text or "").strip()
    await state.clear()

    await _save_product(prod, session, message.bot, message.chat.id, msg_id)


@router.callback_query(F.data == "adm:prod:skip_rec", AdminStates.waiting_product_recommendations)
async def prod_skip_rec(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    prod = data.get("_new_product", {})
    prod["recommendations"] = ""
    await state.clear()

    await _save_product(prod, session, callback.bot, callback.message.chat.id, msg_id)
    await answer_callback(callback)


async def _save_product(prod: dict, session: AsyncSession, bot, chat_id: int, msg_id: int):
    product = Product(
        name=prod.get("name", ""),
        price=prod.get("price", 0),
        category_id=prod.get("category_id"),
        description=prod.get("description") or None,
        format_info=prod.get("format_info") or None,
        recommendations=prod.get("recommendations") or None,
        stock_count=0,
    )
    session.add(product)
    await session.commit()
    await bot.edit_message_text(
        f"✅ Товар <b>«{product.name}»</b> создан!\n\n"
        f"💰 Цена: {product.price:.2f} ₽\n"
        f"Добавьте аккаунты через меню склада.",
        chat_id=chat_id, message_id=msg_id,
        reply_markup=back_admin_kb("adm:products"), parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════
# ТОВАРЫ: РЕДАКТИРОВАНИЕ
# ═══════════════════════════════════════════════════

@router.callback_query(F.data.startswith("adm:pedit:"))
async def prod_edit_select(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    pid = int(callback.data.split(":")[2])
    product = (await session.execute(select(Product).where(Product.id == pid))).scalar_one_or_none()
    if not product:
        await answer_callback(callback, "❌ Не найден.")
        return

    cat = (await session.execute(select(Category).where(Category.id == product.category_id))).scalar_one_or_none()
    text = (
        f"✏️ <b>Редактирование: {product.name}</b>\n\n"
        f"💰 Цена: {product.price:.2f} ₽\n"
        f"📂 Категория: {cat.name if cat else '—'}\n"
        f"📝 Описание: {product.description or '—'}\n"
        f"📋 Формат: {product.format_info or '—'}\n"
        f"💡 Рекомендации: {product.recommendations or '—'}\n"
        f"📊 На складе: {product.stock_count}\n"
        f"🔄 Активен: {'Да' if product.is_active else 'Нет'}\n\n"
        "Выберите поле для редактирования:"
    )
    rows = [
        [InlineKeyboardButton(text="📦 Название", callback_data=f"adm:pfield:{pid}:name")],
        [InlineKeyboardButton(text="💰 Цена", callback_data=f"adm:pfield:{pid}:price")],
        [InlineKeyboardButton(text="📝 Описание", callback_data=f"adm:pfield:{pid}:description")],
        [InlineKeyboardButton(text="📋 Формат", callback_data=f"adm:pfield:{pid}:format_info")],
        [InlineKeyboardButton(text="💡 Рекомендации", callback_data=f"adm:pfield:{pid}:recommendations")],
        [InlineKeyboardButton(text="📂 Категория", callback_data=f"adm:pfield:{pid}:category")],
        [InlineKeyboardButton(
            text=f"{'🔴 Деактивировать' if product.is_active else '🟢 Активировать'}",
            callback_data=f"adm:ptoggle:{pid}",
            style="danger" if product.is_active else "success",
        )],
        [_back_btn("adm:prod:list")],
    ]
    await safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_callback(callback)


@router.callback_query(F.data.startswith("adm:ptoggle:"))
async def prod_toggle_active(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    pid = int(callback.data.split(":")[2])
    product = (await session.execute(select(Product).where(Product.id == pid))).scalar_one_or_none()
    if not product:
        return
    product.is_active = not product.is_active
    await session.commit()
    state_text = "активирован ✅" if product.is_active else "деактивирован 🔴"
    await safe_edit(callback, f"Товар <b>{product.name}</b> {state_text}.", back_admin_kb("adm:prod:list"))
    await answer_callback(callback)


@router.callback_query(F.data.startswith("adm:pfield:"))
async def prod_edit_field(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    parts = callback.data.split(":")
    pid = int(parts[2])
    field = parts[3]

    if field == "category":
        cats = (await session.execute(select(Category).order_by(Category.name))).scalars().all()
        rows = [[InlineKeyboardButton(text=c.name, callback_data=f"adm:psetcat:{pid}:{c.id}")] for c in cats]
        rows.append([_back_btn(f"adm:pedit:{pid}")])
        await safe_edit(callback, "📂 Выберите новую категорию:", InlineKeyboardMarkup(inline_keyboard=rows))
        await answer_callback(callback)
        return

    field_names = {
        "name": "название", "price": "цену", "description": "описание",
        "format_info": "формат данных", "recommendations": "рекомендации",
    }
    await state.update_data(
        _menu_msg_id=callback.message.message_id,
        _edit_product_id=pid,
        _edit_field=field,
    )
    await state.set_state(AdminStates.waiting_edit_product_value)
    await safe_edit(
        callback,
        f"✏️ Введите новое {field_names.get(field, field)}:",
        cancel_input_kb(f"adm:pedit:{pid}"),
    )
    await answer_callback(callback)


@router.callback_query(F.data.startswith("adm:psetcat:"))
async def prod_set_category(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    parts = callback.data.split(":")
    pid = int(parts[2])
    cat_id = int(parts[3])
    product = (await session.execute(select(Product).where(Product.id == pid))).scalar_one_or_none()
    if product:
        product.category_id = cat_id
        await session.commit()
    await safe_edit(callback, "✅ Категория обновлена.", back_admin_kb(f"adm:pedit:{pid}"))
    await answer_callback(callback)


@router.message(AdminStates.waiting_edit_product_value)
async def prod_edit_value(message: Message, state: FSMContext, session: AsyncSession):
    if not _admin_check(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    pid = data.get("_edit_product_id")
    field = data.get("_edit_field")
    await state.clear()

    product = (await session.execute(select(Product).where(Product.id == pid))).scalar_one_or_none()
    if not product:
        return

    new_val = (message.text or "").strip()
    if field == "price":
        try:
            new_val = float(new_val.replace(",", "."))
            if new_val <= 0:
                raise ValueError
            product.price = new_val
        except ValueError:
            await message.bot.edit_message_text(
                "❌ Введите положительное число.", chat_id=message.chat.id, message_id=msg_id,
                reply_markup=back_admin_kb(f"adm:pedit:{pid}"), parse_mode="HTML",
            )
            return
    elif field == "name":
        product.name = new_val
    elif field == "description":
        product.description = new_val or None
    elif field == "format_info":
        product.format_info = new_val or None
    elif field == "recommendations":
        product.recommendations = new_val or None

    await session.commit()
    await message.bot.edit_message_text(
        f"✅ Поле <b>{field}</b> обновлено.",
        chat_id=message.chat.id, message_id=msg_id,
        reply_markup=back_admin_kb(f"adm:pedit:{pid}"), parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════
# ТОВАРЫ: УДАЛЕНИЕ
# ═══════════════════════════════════════════════════

@router.callback_query(F.data.startswith("adm:prod:confirmdel:"))
async def prod_del_confirm(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    pid = int(callback.data.split(":")[3])
    product = (await session.execute(select(Product).where(Product.id == pid))).scalar_one_or_none()
    if not product:
        await answer_callback(callback, "❌ Не найден.")
        return
    await safe_edit(
        callback,
        f"❓ Удалить товар <b>«{product.name}»</b>?\n\nВсе аккаунты товара также будут удалены.",
        confirm_kb("prod", pid),
    )
    await answer_callback(callback)


@router.callback_query(F.data.startswith("confirm:prod:"))
async def prod_del_execute(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    pid = int(callback.data.split(":")[2])
    product = (await session.execute(select(Product).where(Product.id == pid))).scalar_one_or_none()
    if not product:
        return
    await session.execute(sa_delete(Account).where(Account.product_id == pid))
    await session.delete(product)
    await session.commit()
    await safe_edit(callback, f"✅ Товар «{product.name}» удалён.", back_admin_kb("adm:prod:list"))
    await answer_callback(callback)


@router.callback_query(F.data.startswith("reject:prod:"))
async def prod_del_cancel(callback: CallbackQuery):
    await safe_edit(callback, "❌ Удаление отменено.", back_admin_kb("adm:prod:list"))
    await answer_callback(callback)


# ═══════════════════════════════════════════════════
# АККАУНТЫ (СКЛАД)
# ═══════════════════════════════════════════════════

@router.callback_query(F.data == "adm:accounts")
async def accounts_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not _admin_check(callback.from_user.id):
        return
    await state.clear()
    prods = (await session.execute(select(Product).order_by(Product.name))).scalars().all()
    if not prods:
        await safe_edit(callback, "❌ Товаров нет. Сначала добавьте товар.", back_admin_kb("adm:products"))
        await answer_callback(callback)
        return
    await safe_edit(callback, "📊 <b>Управление складом</b>\n\nВыберите товар:", admin_accounts_menu_kb(prods))
    await answer_callback(callback)


@router.callback_query(F.data.startswith("adm:acc:prod:"))
async def accounts_product(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    pid = int(callback.data.split(":")[3])
    product = (await session.execute(select(Product).where(Product.id == pid))).scalar_one_or_none()
    if not product:
        await answer_callback(callback, "❌ Не найден.")
        return
    await safe_edit(
        callback,
        f"📦 <b>{product.name}</b>\n\n📊 На складе: {product.stock_count} шт.",
        admin_account_actions_kb(pid),
    )
    await answer_callback(callback)


@router.callback_query(F.data.startswith("adm:acc:add:"))
async def account_add_start(callback: CallbackQuery, state: FSMContext):
    if not _admin_check(callback.from_user.id):
        return
    pid = int(callback.data.split(":")[3])
    await state.update_data(
        _menu_msg_id=callback.message.message_id,
        _account_product_id=pid,
    )
    await state.set_state(AdminStates.waiting_add_account)
    await safe_edit(
        callback,
        "➕ <b>Добавление аккаунта</b>\n\nОтправьте данные аккаунта (текстом):",
        cancel_input_kb(f"adm:acc:prod:{pid}"),
    )
    await answer_callback(callback)


@router.message(AdminStates.waiting_add_account)
async def account_add_process(message: Message, state: FSMContext, session: AsyncSession):
    if not _admin_check(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    pid = data.get("_account_product_id")
    await state.clear()

    account_data = (message.text or "").strip()
    if not account_data:
        return

    session.add(Account(product_id=pid, account_data=account_data, is_sold=False))
    await session.execute(
        sa_update(Product).where(Product.id == pid).values(stock_count=Product.stock_count + 1)
    )
    await session.commit()

    await message.bot.edit_message_text(
        f"✅ Аккаунт добавлен.",
        chat_id=message.chat.id, message_id=msg_id,
        reply_markup=back_admin_kb(f"adm:acc:prod:{pid}"), parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("adm:acc:import:"))
async def account_import_start(callback: CallbackQuery, state: FSMContext):
    if not _admin_check(callback.from_user.id):
        return
    pid = int(callback.data.split(":")[3])
    await state.update_data(
        _menu_msg_id=callback.message.message_id,
        _import_product_id=pid,
    )
    await state.set_state(AdminStates.waiting_import_accounts_file)
    await safe_edit(
        callback,
        "📥 <b>Импорт аккаунтов</b>\n\nОтправьте файл (.txt / .csv) с аккаунтами.\n"
        "Каждая строка = один аккаунт.",
        cancel_input_kb(f"adm:acc:prod:{pid}"),
    )
    await answer_callback(callback)


@router.message(AdminStates.waiting_import_accounts_file)
async def account_import_process(message: Message, state: FSMContext, session: AsyncSession):
    if not _admin_check(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    pid = data.get("_import_product_id")
    await state.clear()

    if not message.document:
        await message.bot.edit_message_text(
            "❌ Отправьте файл (.txt / .csv).",
            chat_id=message.chat.id, message_id=msg_id,
            reply_markup=back_admin_kb(f"adm:acc:prod:{pid}"), parse_mode="HTML",
        )
        return

    try:
        file = await message.bot.download(message.document)
        content = file.read().decode("utf-8")

        from src.services.account_service import upload_accounts_from_file
        loaded, dupes = await upload_accounts_from_file(session, pid, content)
        await session.commit()

        result = (
            f"✅ <b>Импорт завершён</b>\n\n"
            f"📥 Загружено: {loaded}\n"
            f"♻️ Дубликатов: {dupes}"
        )
    except Exception as e:
        logger.error("Import error: %s", e)
        result = f"❌ Ошибка импорта: {e}"

    try:
        await message.bot.edit_message_text(
            result, chat_id=message.chat.id, message_id=msg_id,
            reply_markup=back_admin_kb(f"adm:acc:prod:{pid}"), parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("adm:acc:delete:"))
async def account_delete_menu(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    pid = int(callback.data.split(":")[3])
    accs = (await session.execute(
        select(Account).where(Account.product_id == pid, Account.is_sold == False).limit(20)
    )).scalars().all()

    if not accs:
        await safe_edit(callback, "❌ Нет доступных аккаунтов для удаления.", back_admin_kb(f"adm:acc:prod:{pid}"))
        await answer_callback(callback)
        return

    rows = [
        [InlineKeyboardButton(
            text=f"🗑️ {a.account_data[:30]}{'...' if len(a.account_data) > 30 else ''}",
            callback_data=f"adm:accdel:{a.id}:{pid}",
            style="danger",
        )]
        for a in accs
    ]
    rows.append([InlineKeyboardButton(text="🗑️ Удалить ВСЕ", callback_data=f"adm:accdelall:{pid}", style="danger")])
    rows.append([_back_btn(f"adm:acc:prod:{pid}")])
    await safe_edit(callback, "🗑️ <b>Выберите аккаунт:</b>", InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_callback(callback)


@router.callback_query(F.data.startswith("adm:accdel:"))
async def account_delete_one(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    parts = callback.data.split(":")
    acc_id = int(parts[2])
    pid = int(parts[3])

    acc = (await session.execute(select(Account).where(Account.id == acc_id))).scalar_one_or_none()
    if acc:
        await session.delete(acc)
        prod = (await session.execute(select(Product).where(Product.id == pid))).scalar_one_or_none()
        if prod and prod.stock_count > 0:
            prod.stock_count -= 1
        await session.commit()

    await safe_edit(callback, "✅ Аккаунт удалён.", back_admin_kb(f"adm:acc:prod:{pid}"))
    await answer_callback(callback)


@router.callback_query(F.data.startswith("adm:accdelall:"))
async def account_delete_all(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    pid = int(callback.data.split(":")[2])
    result = await session.execute(
        sa_delete(Account).where(Account.product_id == pid, Account.is_sold == False)
    )
    deleted = result.rowcount
    prod = (await session.execute(select(Product).where(Product.id == pid))).scalar_one_or_none()
    if prod:
        remaining = (await session.execute(
            select(func.count(Account.id)).where(Account.product_id == pid, Account.is_sold == False)
        )).scalar() or 0
        prod.stock_count = remaining
    await session.commit()

    await safe_edit(callback, f"✅ Удалено {deleted} аккаунтов.", back_admin_kb(f"adm:acc:prod:{pid}"))
    await answer_callback(callback)


# ═══════════════════════════════════════════════════
# ПОЛЬЗОВАТЕЛИ
# ═══════════════════════════════════════════════════

@router.callback_query(F.data == "adm:users")
async def users_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not _admin_check(callback.from_user.id):
        return
    await state.clear()
    users = (await session.execute(select(User).order_by(User.created_at.desc()))).scalars().all()
    await safe_edit(callback, f"👥 <b>Пользователи ({len(users)})</b>", admin_users_kb(users, 0))
    await answer_callback(callback)


@router.callback_query(F.data.startswith("adm:users:p"))
async def users_page(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    page = int(callback.data.split("p")[1])
    users = (await session.execute(select(User).order_by(User.created_at.desc()))).scalars().all()
    await safe_edit(callback, f"👥 <b>Пользователи ({len(users)})</b>", admin_users_kb(users, page))
    await answer_callback(callback)


@router.callback_query(F.data == "adm:users:search")
async def users_search(callback: CallbackQuery, state: FSMContext):
    if not _admin_check(callback.from_user.id):
        return
    await state.update_data(_menu_msg_id=callback.message.message_id)
    await state.set_state(AdminStates.waiting_user_id)
    await safe_edit(callback, "🔍 Введите Telegram ID или @username:", cancel_input_kb("adm:users"))
    await answer_callback(callback)


@router.message(AdminStates.waiting_user_id)
async def users_search_result(message: Message, state: FSMContext, session: AsyncSession):
    if not _admin_check(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    await state.clear()

    query = (message.text or "").strip().lstrip("@")
    user = None

    try:
        tid = int(query)
        user = (await session.execute(select(User).where(User.telegram_id == tid))).scalar_one_or_none()
    except ValueError:
        user = (await session.execute(select(User).where(User.username == query))).scalar_one_or_none()

    if not user:
        await message.bot.edit_message_text(
            "❌ Пользователь не найден.", chat_id=message.chat.id, message_id=msg_id,
            reply_markup=back_admin_kb("adm:users"), parse_mode="HTML",
        )
        return

    text = _user_detail_text(user)
    kb = admin_user_detail_kb(user, is_developer(message.from_user.id))
    await message.bot.edit_message_text(text, chat_id=message.chat.id, message_id=msg_id, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("adm:user:") & ~F.data.startswith("adm:user:block:") & ~F.data.startswith("adm:user:balance:") & ~F.data.startswith("adm:user:role:") & ~F.data.startswith("adm:users:"))
async def user_detail(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    try:
        tid = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        return
    user = (await session.execute(select(User).where(User.telegram_id == tid))).scalar_one_or_none()
    if not user:
        await safe_edit(callback, "❌ Пользователь не найден.", back_admin_kb("adm:users"))
        await answer_callback(callback)
        return

    text = _user_detail_text(user)
    kb = admin_user_detail_kb(user, is_developer(callback.from_user.id))
    await safe_edit(callback, text, kb)
    await answer_callback(callback)


def _user_detail_text(user) -> str:
    status = "🔒 Заблокирован" if user.is_blocked else "✅ Активен"
    return (
        f"👤 <b>Пользователь</b>\n\n"
        f"🆔 ID: <code>{user.telegram_id}</code>\n"
        f"👤 Имя: {user.first_name or '—'}\n"
        f"📛 Username: @{user.username or '—'}\n"
        f"💰 Баланс: {user.balance:.2f} ₽\n"
        f"👑 Роль: {user.role}\n"
        f"📊 Статус: {status}\n"
        f"🔗 Реферальный код: <code>{user.referral_code or '—'}</code>\n"
        f"📅 Регистрация: {user.created_at:%d.%m.%Y %H:%M}"
    )


@router.callback_query(F.data.startswith("adm:user:block:"))
async def user_block_toggle(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    uid = int(callback.data.split(":")[3])
    user = (await session.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if not user:
        return
    user.is_blocked = not user.is_blocked
    await session.commit()
    action = "заблокирован 🔒" if user.is_blocked else "разблокирован 🔓"
    await safe_edit(
        callback,
        f"✅ Пользователь {user.first_name or user.telegram_id} {action}.",
        back_admin_kb(f"adm:user:{user.telegram_id}"),
    )
    await answer_callback(callback)


@router.callback_query(F.data == "adm:users:bulk_block")
async def users_bulk_block(callback: CallbackQuery, state: FSMContext):
    if not _admin_check(callback.from_user.id):
        return
    await state.update_data(_menu_msg_id=callback.message.message_id)
    await state.set_state(AdminStates.waiting_bulk_block_users)
    await safe_edit(
        callback,
        "🔒 <b>Массовая блокировка</b>\n\n"
        "Введите Telegram ID через запятую:",
        cancel_input_kb("adm:users"),
    )
    await answer_callback(callback)


@router.message(AdminStates.waiting_bulk_block_users)
async def users_bulk_block_process(message: Message, state: FSMContext, session: AsyncSession):
    if not _admin_check(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    await state.clear()

    ids_raw = (message.text or "").strip().split(",")
    blocked = 0
    for raw in ids_raw:
        raw = raw.strip()
        if not raw.isdigit():
            continue
        tid = int(raw)
        user = (await session.execute(select(User).where(User.telegram_id == tid))).scalar_one_or_none()
        if user and not user.is_blocked:
            user.is_blocked = True
            blocked += 1
    await session.commit()
    await message.bot.edit_message_text(
        f"✅ Заблокировано: {blocked}",
        chat_id=message.chat.id, message_id=msg_id,
        reply_markup=back_admin_kb("adm:users"), parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("adm:user:balance:"))
async def user_balance_start(callback: CallbackQuery, state: FSMContext):
    if not _admin_check(callback.from_user.id):
        return
    uid = int(callback.data.split(":")[3])
    await state.update_data(
        _menu_msg_id=callback.message.message_id,
        _balance_user_id=uid,
    )
    await state.set_state(AdminStates.waiting_balance_amount)
    await safe_edit(callback, "💰 Введите сумму пополнения (₽):", cancel_input_kb("adm:users"))
    await answer_callback(callback)


@router.message(AdminStates.waiting_balance_amount)
async def user_balance_finish(message: Message, state: FSMContext, session: AsyncSession):
    if not _admin_check(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    uid = data.get("_balance_user_id")
    await state.clear()

    try:
        amount = float(message.text.replace(",", ".").strip())
    except (ValueError, TypeError, AttributeError):
        await message.bot.edit_message_text(
            "❌ Введите число.", chat_id=message.chat.id, message_id=msg_id,
            reply_markup=back_admin_kb("menu:admin"), parse_mode="HTML",
        )
        return

    user = (await session.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if not user:
        return

    user.balance += amount
    await session.commit()

    await message.bot.edit_message_text(
        f"✅ Баланс пользователя {user.first_name or user.telegram_id}: <b>{user.balance:.2f} ₽</b> ({'+' if amount >= 0 else ''}{amount:.2f})",
        chat_id=message.chat.id, message_id=msg_id,
        reply_markup=back_admin_kb("adm:users"), parse_mode="HTML",
    )

    try:
        from src.services.notifications import notify_balance_topup
        await notify_balance_topup(session, user, amount, message.bot)
    except Exception:
        pass


@router.callback_query(F.data.startswith("adm:user:role:"))
async def user_role_menu(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    if not is_developer(callback.from_user.id):
        await answer_callback(callback, "⛔ Только разработчик может менять роли.")
        return
    uid = int(callback.data.split(":")[3])
    user = (await session.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if not user:
        return
    await safe_edit(
        callback,
        f"👑 Текущая роль: <b>{user.role}</b>\n\nВыберите новую:",
        admin_role_kb(uid),
    )
    await answer_callback(callback)


@router.callback_query(F.data.startswith("adm:setrole:"))
async def user_set_role(callback: CallbackQuery, session: AsyncSession):
    if not is_developer(callback.from_user.id):
        return
    parts = callback.data.split(":")
    uid = int(parts[2])
    role = parts[3]
    user = (await session.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if not user:
        return
    user.role = role
    await session.commit()
    await safe_edit(
        callback,
        f"✅ Роль пользователя изменена на <b>{role}</b>.",
        back_admin_kb(f"adm:user:{user.telegram_id}"),
    )
    await answer_callback(callback)


# ═══════════════════════════════════════════════════
# СТАТИСТИКА
# ═══════════════════════════════════════════════════

@router.callback_query(F.data == "adm:stats")
async def admin_stats(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    total_users = (await session.execute(select(func.count(User.id)))).scalar() or 0
    total_orders = (await session.execute(select(func.count(Order.id)))).scalar() or 0
    total_revenue = (await session.execute(
        select(func.coalesce(func.sum(Order.total_amount), 0)).where(Order.status == "ВЫПОЛНЕНО")
    )).scalar() or 0
    total_products = (await session.execute(select(func.count(Product.id)))).scalar() or 0
    total_categories = (await session.execute(select(func.count(Category.id)))).scalar() or 0
    pending_orders = (await session.execute(
        select(func.count(Order.id)).where(Order.status == "ОЖИДАЕТ ОПЛАТЫ")
    )).scalar() or 0

    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"📦 Заказов всего: {total_orders}\n"
        f"⏳ Ожидают оплаты: {pending_orders}\n"
        f"💰 Выручка: {total_revenue:.2f} ₽\n"
        f"🛒 Товаров: {total_products}\n"
        f"📂 Категорий: {total_categories}"
    )
    await safe_edit(callback, text, back_admin_kb("menu:admin"))
    await answer_callback(callback)


# ═══════════════════════════════════════════════════
# ЛОГИ
# ═══════════════════════════════════════════════════

@router.callback_query(F.data == "adm:logs")
async def admin_logs(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    stmt = select(Log).where(Log.level == "ERROR").order_by(Log.created_at.desc()).limit(10)
    logs = (await session.execute(stmt)).scalars().all()

    if not logs:
        await safe_edit(callback, "📝 Ошибок нет. Всё работает! 🎉", back_admin_kb("menu:admin"))
        await answer_callback(callback)
        return

    text = "📝 <b>Последние ошибки:</b>\n\n"
    for log in logs:
        ts = log.created_at.strftime("%d.%m %H:%M") if log.created_at else "?"
        msg = (log.message or "")[:100]
        text += f"• [{ts}] {msg}\n"

    await safe_edit(callback, text, back_admin_kb("menu:admin"))
    await answer_callback(callback)


# ═══════════════════════════════════════════════════
# НАСТРОЙКИ
# ═══════════════════════════════════════════════════

@router.callback_query(F.data == "adm:settings")
async def settings_menu(callback: CallbackQuery, state: FSMContext):
    if not _admin_check(callback.from_user.id):
        return
    await state.clear()
    await safe_edit(callback, "⚙️ <b>Настройки</b>", admin_settings_kb())
    await answer_callback(callback)


@router.callback_query(F.data == "adm:set:edit")
async def settings_edit(callback: CallbackQuery):
    if not _admin_check(callback.from_user.id):
        return
    await safe_edit(callback, "✏️ Выберите параметр:", admin_settings_keys_kb())
    await answer_callback(callback)


@router.callback_query(F.data.startswith("adm:set:key:"))
async def settings_key_select(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    key = callback.data.split(":", 3)[3]
    setting = (await session.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    current = setting.value[:200] if setting and setting.value else "(не задано)"

    await state.update_data(
        _menu_msg_id=callback.message.message_id,
        _setting_key=key,
    )
    await state.set_state(AdminStates.waiting_setting_edit_value)
    await safe_edit(
        callback,
        f"✏️ <b>{key}</b>\n\nТекущее значение:\n<i>{current}</i>\n\nВведите новое значение:",
        cancel_input_kb("adm:settings"),
    )
    await answer_callback(callback)


@router.message(AdminStates.waiting_setting_edit_value)
async def settings_value_save(message: Message, state: FSMContext, session: AsyncSession):
    if not _admin_check(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    key = data.get("_setting_key")
    await state.clear()

    new_val = (message.text or "").strip()
    setting = (await session.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    if setting:
        setting.value = new_val
    else:
        session.add(Setting(key=key, value=new_val))
    await session.commit()

    await message.bot.edit_message_text(
        f"✅ Настройка <b>{key}</b> обновлена.",
        chat_id=message.chat.id, message_id=msg_id,
        reply_markup=back_admin_kb("adm:settings"), parse_mode="HTML",
    )


@router.callback_query(F.data == "adm:set:list")
async def settings_list(callback: CallbackQuery, session: AsyncSession):
    if not _admin_check(callback.from_user.id):
        return
    all_settings = (await session.execute(select(Setting).order_by(Setting.key))).scalars().all()
    if not all_settings:
        await safe_edit(callback, "⚙️ Настройки пусты.", back_admin_kb("adm:settings"))
        await answer_callback(callback)
        return

    text = "⚙️ <b>Все настройки:</b>\n\n"
    for s in all_settings:
        val = (s.value or "")[:80]
        text += f"• <b>{s.key}</b>: <i>{val}</i>\n"

    await safe_edit(callback, text, back_admin_kb("adm:settings"))
    await answer_callback(callback)
