"""Заказы — inline-only single-message UI"""
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.keyboards import order_detail_kb, orders_kb, payment_methods_kb
from src.bot.texts import order_text
from src.bot.utils import answer_callback, safe_edit
from src.database.models import Account, Order, Product, User
from src.services.account_service import create_accounts_file, get_accounts_for_order

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "menu:orders")
async def show_orders(callback: CallbackQuery, session: AsyncSession):
    stmt_u = select(User).where(User.telegram_id == callback.from_user.id)
    user = (await session.execute(stmt_u)).scalar_one_or_none()
    if not user:
        await answer_callback(callback, "Пользователь не найден")
        return

    stmt = select(Order).where(Order.user_id == user.id).order_by(Order.created_at.desc()).limit(20)
    result = await session.execute(stmt)
    user_orders = result.scalars().all()

    if not user_orders:
        await safe_edit(callback, "📦 <b>Мои заказы</b>\n\nУ вас пока нет заказов.", orders_kb([]))
    else:
        await safe_edit(callback, "📦 <b>Мои заказы</b>\n\nВыберите заказ:", orders_kb(user_orders))
    await answer_callback(callback)


@router.callback_query(F.data.startswith("order:"))
async def show_order_detail(callback: CallbackQuery, session: AsyncSession):
    order_id = int(callback.data.split(":")[1])
    stmt = select(Order).where(Order.id == order_id)
    order = (await session.execute(stmt)).scalar_one_or_none()
    if not order:
        await answer_callback(callback, "Заказ не найден")
        return

    # Добавляем название товара
    stmt_p = select(Product).where(Product.id == order.product_id)
    product = (await session.execute(stmt_p)).scalar_one_or_none()
    prod_name = product.name if product else "—"

    text = order_text(order) + f"\n🏷️ Товар: {prod_name}"
    await safe_edit(callback, text, order_detail_kb(order_id, order.status))
    await answer_callback(callback)


@router.callback_query(F.data.startswith("pay_order:"))
async def pay_order(callback: CallbackQuery, session: AsyncSession):
    order_id = int(callback.data.split(":")[1])
    stmt = select(Order).where(Order.id == order_id)
    order = (await session.execute(stmt)).scalar_one_or_none()
    if not order or order.status != "ОЖИДАЕТ ОПЛАТЫ":
        await answer_callback(callback, "Заказ недоступен для оплаты")
        return

    stmt_p = select(Product).where(Product.id == order.product_id)
    product = (await session.execute(stmt_p)).scalar_one_or_none()
    prod_name = product.name if product else "—"

    text = (
        f"📦 <b>Заказ #{order.id}</b>\n\n"
        f"Товар: {prod_name}\n"
        f"Количество: {order.quantity} шт.\n"
        f"💰 <b>Итого: {order.total_amount:.2f} ₽</b>\n\n"
        f"Выберите способ оплаты:"
    )
    await safe_edit(callback, text, payment_methods_kb(order_id))
    await answer_callback(callback)


@router.callback_query(F.data.startswith("cancel:"))
async def cancel_order(callback: CallbackQuery, session: AsyncSession):
    order_id = int(callback.data.split(":")[1])
    stmt = select(Order).where(Order.id == order_id)
    order = (await session.execute(stmt)).scalar_one_or_none()
    if not order:
        await answer_callback(callback, "Заказ не найден")
        return
    if order.status != "ОЖИДАЕТ ОПЛАТЫ":
        await answer_callback(callback, "Этот заказ нельзя отменить")
        return

    # Возврат аккаунтов
    stmt_acc = select(Account).where(Account.order_id == order.id)
    accounts = (await session.execute(stmt_acc)).scalars().all()
    if accounts:
        acc_ids = [a.id for a in accounts]
        await session.execute(
            update(Account).where(Account.id.in_(acc_ids)).values(is_sold=False, sold_at=None, order_id=None)
        )
        await session.execute(
            update(Product).where(Product.id == order.product_id).values(
                stock_count=Product.stock_count + order.quantity
            )
        )

    order.status = "ОТМЕНЕНО"
    order.reserved_until = None
    await session.commit()

    from src.bot.keyboards import noop_kb
    await safe_edit(
        callback,
        f"❌ <b>Заказ #{order_id} отменён</b>\n\nТовар возвращён в каталог.",
        noop_kb(),
    )
    await answer_callback(callback)


@router.callback_query(F.data.startswith("download:"))
async def download_order(callback: CallbackQuery, session: AsyncSession):
    order_id = int(callback.data.split(":")[1])
    stmt = select(Order).where(Order.id == order_id)
    order = (await session.execute(stmt)).scalar_one_or_none()
    if not order or order.status != "ВЫПОЛНЕНО":
        await answer_callback(callback, "Заказ не доступен для скачивания")
        return

    accounts = await get_accounts_for_order(session, order_id)
    if not accounts:
        await answer_callback(callback, "Нет данных для скачивания")
        return

    from aiogram.types import BufferedInputFile

    file_obj = await create_accounts_file(accounts)
    file_bytes = file_obj.read()
    file_obj.seek(0)

    doc = BufferedInputFile(file_bytes, filename=file_obj.name)
    await callback.message.answer_document(doc, caption=f"📥 Данные к заказу #{order_id}")
    await answer_callback(callback)
