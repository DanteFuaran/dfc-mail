"""Баланс и пополнение — inline-only single-message UI"""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.keyboards import balance_topup_kb, noop_kb, topup_amount_cancel_kb
from src.bot.states import TopupStates
from src.bot.texts import balance_text
from src.bot.utils import answer_callback, safe_edit
from src.database.models import Payment, User
from src.services.payment import PaymentService

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "menu:balance")
async def show_balance(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    stmt = select(User).where(User.telegram_id == callback.from_user.id)
    user = (await session.execute(stmt)).scalar_one_or_none()
    bal = user.balance if user else 0.0
    await safe_edit(callback, balance_text(bal), balance_topup_kb())
    await answer_callback(callback)


@router.callback_query(F.data.startswith("topup:"))
async def topup_method(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    method = callback.data.split(":")[1]

    if method == "admin":
        await safe_edit(
            callback,
            "ℹ️ Для пополнения обратитесь к администратору через раздел «Поддержка».",
            noop_kb(),
        )
        await answer_callback(callback)
        return

    await state.update_data(
        topup_method=method,
        _menu_msg_id=callback.message.message_id,
    )
    await state.set_state(TopupStates.waiting_amount)
    await safe_edit(
        callback,
        f"💰 <b>Пополнение ({method.upper()})</b>\n\n✏️ Введите сумму в рублях:",
        topup_amount_cancel_kb(),
    )
    await answer_callback(callback)


@router.message(TopupStates.waiting_amount)
async def process_topup_amount(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    method = data.get("topup_method", "")

    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        try:
            await message.bot.edit_message_text(
                "❌ Введите <b>положительное число</b>:",
                chat_id=message.chat.id, message_id=msg_id,
                reply_markup=topup_amount_cancel_kb(), parse_mode="HTML",
            )
        except Exception:
            pass
        return

    await state.clear()

    stmt = select(User).where(User.telegram_id == message.from_user.id)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if not user:
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    if method == "yookassa":
        result = await PaymentService.create_yookassa_payment(amount, None, user.telegram_id)
        if result and result.get("payment_url"):
            payment = Payment(
                user_id=user.id, amount=amount,
                payment_method="yookassa", payment_id=result["payment_id"],
                status="PENDING",
            )
            session.add(payment)
            await session.commit()
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Оплатить", url=result["payment_url"])],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:balance")],
            ])
            await message.bot.edit_message_text(
                f"💰 <b>Пополнение на {amount:.2f} ₽</b>\n\nНажмите кнопку для оплаты:",
                chat_id=message.chat.id, message_id=msg_id,
                reply_markup=kb, parse_mode="HTML",
            )
        else:
            await message.bot.edit_message_text(
                "❌ Ошибка создания платежа. Попробуйте позже.",
                chat_id=message.chat.id, message_id=msg_id,
                reply_markup=noop_kb(), parse_mode="HTML",
            )

    elif method == "heleket":
        result = await PaymentService.create_heleket_payment(amount, None, user.telegram_id)
        if result and result.get("payment_url"):
            payment = Payment(
                user_id=user.id, amount=amount,
                payment_method="heleket", payment_id=result["payment_id"],
                status="PENDING",
            )
            session.add(payment)
            await session.commit()
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Оплатить", url=result["payment_url"])],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:balance")],
            ])
            await message.bot.edit_message_text(
                f"💰 <b>Пополнение на {amount:.2f} ₽</b>\n\nНажмите кнопку для оплаты:",
                chat_id=message.chat.id, message_id=msg_id,
                reply_markup=kb, parse_mode="HTML",
            )
        else:
            await message.bot.edit_message_text(
                "❌ Ошибка создания платежа. Попробуйте позже.",
                chat_id=message.chat.id, message_id=msg_id,
                reply_markup=noop_kb(), parse_mode="HTML",
            )
    else:
        await message.bot.edit_message_text(
            "❌ Неизвестный метод оплаты.",
            chat_id=message.chat.id, message_id=msg_id,
            reply_markup=noop_kb(), parse_mode="HTML",
        )
