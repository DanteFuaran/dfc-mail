"""Реферальная программа — inline-only single-message UI"""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.keyboards import referral_kb
from src.bot.texts import referral_text
from src.bot.utils import answer_callback, safe_edit
from src.database.models import ReferralTransaction, User

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "menu:referral")
async def show_referral(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()

    stmt = select(User).where(User.telegram_id == callback.from_user.id)
    user = (await session.execute(stmt)).scalar_one_or_none()

    if not user or not user.referral_code:
        await safe_edit(callback, "❌ Реферальная программа недоступна.", referral_kb())
        await answer_callback(callback)
        return

    # Количество рефералов
    stmt_count = select(func.count(User.id)).where(User.referred_by == user.id)
    count = (await session.execute(stmt_count)).scalar() or 0

    # Сумма заработка
    stmt_earn = select(func.coalesce(func.sum(ReferralTransaction.commission), 0.0)).where(
        ReferralTransaction.referrer_id == user.id,
    )
    earnings = float((await session.execute(stmt_earn)).scalar() or 0.0)

    await safe_edit(callback, referral_text(user.referral_code, count, earnings), referral_kb())
    await answer_callback(callback)
