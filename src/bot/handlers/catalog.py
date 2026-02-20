"""Каталог — inline-only single-message UI"""
import logging
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.keyboards import (
    categories_kb, payment_methods_kb, product_detail_kb,
    products_kb, quantity_cancel_kb,
)
from src.bot.states import OrderStates
from src.bot.texts import product_detail_text
from src.bot.utils import answer_callback, safe_edit
from src.config import settings
from src.database.models import (
    Account, Category, Order, Product, StockNotification, User,
)
from src.services.account_service import reserve_accounts
from src.services.discount import calculate_total_price

logger = logging.getLogger(__name__)
router = Router()


# ═══════════════════════════════════════════════
# Каталог → Категории
# ═══════════════════════════════════════════════

@router.callback_query(F.data == "menu:catalog")
async def show_catalog(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    stmt = select(Category).where(Category.is_active == True)
    result = await session.execute(stmt)
    categories = result.scalars().all()
    if not categories:
        await safe_edit(callback, "📂 <b>Каталог</b>\n\nКаталог пуст.", categories_kb([]))
    else:
        await safe_edit(callback, "📂 <b>Каталог</b>\n\nВыберите категорию:", categories_kb(categories))
    await answer_callback(callback)


# ═══════════════════════════════════════════════
# Категория → Товары
# ═══════════════════════════════════════════════

@router.callback_query(F.data.startswith("cat:"))
async def show_products(callback: CallbackQuery, session: AsyncSession):
    cat_id = int(callback.data.split(":")[1])
    stmt = select(Product).where(Product.category_id == cat_id, Product.is_active == True)
    result = await session.execute(stmt)
    products = result.scalars().all()
    if not products:
        await answer_callback(callback, "В категории пока нет товаров")
        return
    stmt_cat = select(Category).where(Category.id == cat_id)
    cat = (await session.execute(stmt_cat)).scalar_one_or_none()
    cat_name = cat.name if cat else "Товары"
    await safe_edit(callback, f"🛒 <b>{cat_name}</b>\n\nВыберите товар:", products_kb(products, cat_id))
    await answer_callback(callback)


# ═══════════════════════════════════════════════
# Товар → Детали
# ═══════════════════════════════════════════════

@router.callback_query(F.data.startswith("prod:"))
async def show_product(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    prod_id = int(callback.data.split(":")[1])
    stmt = select(Product).where(Product.id == prod_id)
    product = (await session.execute(stmt)).scalar_one_or_none()
    if not product:
        await answer_callback(callback, "Товар не найден")
        return
    await safe_edit(
        callback,
        product_detail_text(product),
        product_detail_kb(prod_id, product.stock_count > 0, product.category_id),
    )
    await answer_callback(callback)


# ═══════════════════════════════════════════════
# Купить → Ввод количества
# ═══════════════════════════════════════════════

@router.callback_query(F.data.startswith("buy:"))
async def start_buy(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    prod_id = int(callback.data.split(":")[1])
    stmt = select(Product).where(Product.id == prod_id)
    product = (await session.execute(stmt)).scalar_one_or_none()
    if not product or product.stock_count == 0:
        await answer_callback(callback, "Товар недоступен")
        return

    # Проверка лимита заказов
    user_id = callback.from_user.id
    stmt_u = select(User).where(User.telegram_id == user_id)
    user = (await session.execute(stmt_u)).scalar_one_or_none()
    if user:
        stmt_o = select(Order).where(Order.user_id == user.id, Order.status == "ОЖИДАЕТ ОПЛАТЫ")
        pending = (await session.execute(stmt_o)).scalars().all()
        if len(pending) >= 3:
            await answer_callback(callback, "Слишком много неоплаченных заказов (макс. 3)")
            return

    await state.update_data(
        product_id=prod_id,
        max_quantity=product.stock_count,
        _menu_msg_id=callback.message.message_id,
    )
    await state.set_state(OrderStates.waiting_quantity)
    await safe_edit(
        callback,
        f"📦 <b>{product.name}</b>\n\n"
        f"💰 Цена: {product.price:.2f} ₽/шт.\n"
        f"📊 Доступно: {product.stock_count} шт.\n\n"
        f"✏️ <b>Введите количество:</b>",
        quantity_cancel_kb(prod_id),
    )
    await answer_callback(callback)


@router.message(OrderStates.waiting_quantity)
async def process_quantity(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    prod_id = data.get("product_id")
    max_qty = data.get("max_quantity", 0)

    try:
        quantity = int(message.text)
    except (ValueError, TypeError):
        await message.bot.edit_message_text(
            "❌ Введите <b>число</b>:",
            chat_id=message.chat.id,
            message_id=msg_id,
            reply_markup=quantity_cancel_kb(prod_id),
            parse_mode="HTML",
        )
        return

    if quantity <= 0:
        await message.bot.edit_message_text(
            "❌ Количество должно быть больше нуля:",
            chat_id=message.chat.id,
            message_id=msg_id,
            reply_markup=quantity_cancel_kb(prod_id),
            parse_mode="HTML",
        )
        return

    if quantity > max_qty:
        await message.bot.edit_message_text(
            f"❌ Доступно только <b>{max_qty}</b> шт.:",
            chat_id=message.chat.id,
            message_id=msg_id,
            reply_markup=quantity_cancel_kb(prod_id),
            parse_mode="HTML",
        )
        return

    stmt = select(Product).where(Product.id == prod_id)
    product = (await session.execute(stmt)).scalar_one_or_none()
    if not product:
        await state.clear()
        return

    stmt_u = select(User).where(User.telegram_id == message.from_user.id)
    user = (await session.execute(stmt_u)).scalar_one_or_none()
    if not user:
        await state.clear()
        return

    discount_percent, total_amount = calculate_total_price(product.price, quantity)

    try:
        reserved = await reserve_accounts(session, prod_id, quantity, None)
    except ValueError as e:
        await message.bot.edit_message_text(
            f"❌ {e}",
            chat_id=message.chat.id, message_id=msg_id,
            reply_markup=quantity_cancel_kb(prod_id), parse_mode="HTML",
        )
        await state.clear()
        return

    order = Order(
        user_id=user.id,
        product_id=prod_id,
        quantity=quantity,
        price_per_unit=product.price,
        discount=discount_percent,
        total_amount=total_amount,
        status="ОЖИДАЕТ ОПЛАТЫ",
        reserved_until=datetime.now() + timedelta(minutes=settings.ORDER_RESERVATION_MINUTES),
    )
    session.add(order)
    await session.flush()

    account_ids = [a.id for a in reserved]
    await session.execute(
        update(Account).where(Account.id.in_(account_ids)).values(order_id=order.id)
    )
    await session.commit()
    await session.refresh(order)

    try:
        from src.services.notifications import notify_new_order
        await notify_new_order(session, order, message.bot)
    except Exception as e:
        logger.error("Order notification error: %s", e)

    await state.clear()

    text = (
        f"📦 <b>Заказ #{order.id}</b>\n\n"
        f"Товар: {product.name}\n"
        f"Количество: {quantity} шт.\n"
        f"Цена: {product.price:.2f} ₽/шт.\n"
    )
    if discount_percent > 0:
        text += f"Скидка: {discount_percent}%\n"
    text += f"💰 <b>Итого: {total_amount:.2f} ₽</b>\n\nВыберите способ оплаты:"

    await message.bot.edit_message_text(
        text,
        chat_id=message.chat.id, message_id=msg_id,
        reply_markup=payment_methods_kb(order.id), parse_mode="HTML",
    )


# ═══════════════════════════════════════════════
# Уведомление о поступлении
# ═══════════════════════════════════════════════

@router.callback_query(F.data.startswith("notify:"))
async def subscribe_notify(callback: CallbackQuery, session: AsyncSession):
    prod_id = int(callback.data.split(":")[1])
    stmt_u = select(User).where(User.telegram_id == callback.from_user.id)
    user = (await session.execute(stmt_u)).scalar_one_or_none()
    if not user:
        await answer_callback(callback, "Пользователь не найден")
        return
    stmt = select(StockNotification).where(
        StockNotification.user_id == user.id,
        StockNotification.product_id == prod_id,
        StockNotification.is_notified == False,
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing:
        await answer_callback(callback, "Вы уже подписаны")
        return
    session.add(StockNotification(user_id=user.id, product_id=prod_id))
    await session.commit()
    await answer_callback(callback, "✅ Уведомим о поступлении")
