"""Обработка оплаты заказа — inline-only single-message UI"""
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery, LabeledPrice, PreCheckoutQuery
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.keyboards import noop_kb, payment_methods_kb
from src.bot.texts import order_text
from src.bot.utils import answer_callback, safe_edit
from src.database.models import Account, Order, Payment, Product, ReferralTransaction, User
from src.services.account_service import get_accounts_for_order, reserve_accounts
from src.services.payment import PaymentService

logger = logging.getLogger(__name__)
router = Router()


async def _complete_order(session: AsyncSession, order: Order, payment_method: str, bot) -> str:
    """Завершить заказ: зачислить аккаунты, начислить реферальный бонус."""
    order.status = "ВЫПОЛНЕНО"
    order.payment_method = payment_method
    order.paid_at = datetime.now()
    order.completed_at = datetime.now()

    # Реферальный бонус
    stmt_user = select(User).where(User.id == order.user_id)
    user = (await session.execute(stmt_user)).scalar_one_or_none()
    if user and user.referred_by:
        from src.config import settings as cfg
        commission_rate = cfg.REFERRAL_COMMISSION / 100
        commission = order.total_amount * commission_rate
        if commission > 0:
            stmt_ref = select(User).where(User.id == user.referred_by)
            referrer = (await session.execute(stmt_ref)).scalar_one_or_none()
            if referrer:
                referrer.balance += commission
                session.add(ReferralTransaction(
                    referrer_id=referrer.id,
                    referred_id=user.id,
                    order_id=order.id,
                    amount=order.total_amount,
                    commission=commission,
                ))

    await session.commit()

    # Уведомляем админов
    try:
        from src.services.notifications import notify_admins_about_purchase
        await notify_admins_about_purchase(session, order, bot)
    except Exception as e:
        logger.error("Notification error: %s", e)

    return "✅ Заказ оплачен и выполнен!"


@router.callback_query(F.data.startswith("pay:"))
async def process_payment(callback: CallbackQuery, session: AsyncSession):
    parts = callback.data.split(":")
    if len(parts) < 3:
        await answer_callback(callback, "❌ Ошибка")
        return

    method = parts[1]
    try:
        order_id = int(parts[2])
    except ValueError:
        await answer_callback(callback, "❌ Ошибка")
        return

    stmt = select(Order).where(Order.id == order_id)
    order = (await session.execute(stmt)).scalar_one_or_none()
    if not order:
        await safe_edit(callback, "❌ Заказ не найден.", noop_kb())
        await answer_callback(callback)
        return

    stmt_user = select(User).where(User.telegram_id == callback.from_user.id)
    user = (await session.execute(stmt_user)).scalar_one_or_none()
    if not user or order.user_id != user.id:
        await answer_callback(callback, "⛔ Нет доступа.")
        return

    if order.status != "ОЖИДАЕТ ОПЛАТЫ":
        await safe_edit(callback, f"ℹ️ Заказ уже {order.status.lower()}.", noop_kb())
        await answer_callback(callback)
        return

    # ── Оплата с баланса ──
    if method == "balance":
        if user.balance < order.total_amount:
            await safe_edit(
                callback,
                f"❌ Недостаточно средств.\n\n"
                f"💰 Баланс: {user.balance:.2f} ₽\n"
                f"💳 Нужно: {order.total_amount:.2f} ₽",
                payment_methods_kb(order.id),
            )
            await answer_callback(callback)
            return

        user.balance -= order.total_amount
        result_msg = await _complete_order(session, order, "balance", callback.bot)
        await safe_edit(callback, f"{result_msg}\n\n{order_text(order)}", noop_kb())
        await answer_callback(callback)
        return

    # ── Тестовая оплата ──
    if method == "test":
        from src.config import settings as cfg
        if not cfg.ENABLE_TEST_PAYMENT:
            await answer_callback(callback, "🧪 Тестовая оплата отключена.")
            return

        result_msg = await _complete_order(session, order, "test", callback.bot)
        await safe_edit(callback, f"{result_msg}\n\n{order_text(order)}", noop_kb())
        await answer_callback(callback)
        return

    # ── Telegram Stars ──
    if method == "stars":
        stars_amount = max(1, int(order.total_amount))
        try:
            await callback.message.answer_invoice(
                title=f"Заказ #{order.id}",
                description=f"Оплата заказа на {order.total_amount:.2f} ₽",
                payload=f"order_{order.id}",
                currency="XTR",
                prices=[LabeledPrice(label="Оплата", amount=stars_amount)],
            )
            await safe_edit(callback, "⭐ Счёт на оплату Stars отправлен ниже.", noop_kb())
        except Exception as e:
            logger.error("Stars invoice error: %s", e)
            await safe_edit(callback, "❌ Ошибка создания счёта Stars.", payment_methods_kb(order.id))
        await answer_callback(callback)
        return

    # ── YooKassa / Heleket / Robokassa / Lava ──
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    payment_url = None
    payment_id = None

    if method == "yookassa":
        result = await PaymentService.create_yookassa_payment(order.total_amount, order.id, user.telegram_id)
        if result:
            payment_url = result.get("payment_url")
            payment_id = result.get("payment_id")
    elif method == "heleket":
        result = await PaymentService.create_heleket_payment(order.total_amount, order.id, user.telegram_id)
        if result:
            payment_url = result.get("payment_url")
            payment_id = result.get("payment_id")
    else:
        await safe_edit(callback, f"❌ Метод оплаты «{method}» не поддерживается.", payment_methods_kb(order.id))
        await answer_callback(callback)
        return

    if payment_url:
        if payment_id:
            order.payment_id = payment_id
            order.payment_method = method
            payment = Payment(
                user_id=user.id, amount=order.total_amount,
                payment_method=method, payment_id=payment_id,
                order_id=order.id, status="PENDING",
            )
            session.add(payment)
            await session.commit()

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=payment_url)],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:orders")],
        ])
        await safe_edit(
            callback,
            f"💳 <b>Оплата заказа #{order.id}</b>\n\n"
            f"💰 Сумма: {order.total_amount:.2f} ₽\n\n"
            "Нажмите кнопку для перехода к оплате:",
            kb,
        )
    else:
        await safe_edit(callback, "❌ Ошибка создания платежа. Попробуйте позже.", payment_methods_kb(order.id))

    await answer_callback(callback)


# ═══════════════════════════════════════════════
# Telegram Stars — pre_checkout & successful_payment
# ═══════════════════════════════════════════════

@router.pre_checkout_query()
async def stars_pre_checkout(query: PreCheckoutQuery, session: AsyncSession):
    payload = query.invoice_payload or ""
    if payload.startswith("order_"):
        try:
            order_id = int(payload.split("_")[1])
            stmt = select(Order).where(Order.id == order_id, Order.status == "ОЖИДАЕТ ОПЛАТЫ")
            order = (await session.execute(stmt)).scalar_one_or_none()
            if order:
                await query.answer(ok=True)
                return
        except Exception:
            pass
    await query.answer(ok=False, error_message="Заказ не найден или уже оплачен.")


@router.message(F.successful_payment)
async def stars_successful_payment(message, session: AsyncSession):
    payload = message.successful_payment.invoice_payload or ""
    if not payload.startswith("order_"):
        return

    try:
        order_id = int(payload.split("_")[1])
    except (IndexError, ValueError):
        return

    stmt = select(Order).where(Order.id == order_id)
    order = (await session.execute(stmt)).scalar_one_or_none()
    if not order or order.status != "ОЖИДАЕТ ОПЛАТЫ":
        return

    result_msg = await _complete_order(session, order, "stars", message.bot)

    from src.bot.keyboards import main_menu_kb
    from src.bot.handlers.start import is_admin

    await message.answer(
        f"{result_msg}\n\n{order_text(order)}",
        reply_markup=main_menu_kb(is_admin(message.from_user.id)),
        parse_mode="HTML",
    )
