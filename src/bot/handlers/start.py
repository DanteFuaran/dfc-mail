"""Обработчик /start и главного меню — single-message UI"""
import logging
import secrets
import string

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.keyboards import main_menu_kb
from src.bot.texts import welcome_text
from src.bot.utils import answer_callback, safe_edit
from src.config import settings
from src.database.models import Setting, User

logger = logging.getLogger(__name__)
router = Router()


def _generate_referral_code() -> str:
    return "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(10))


def is_admin(user_id: int, user=None) -> bool:
    if user_id in settings.admin_ids_list or user_id in settings.developer_ids_list:
        return True
    return user is not None and user.role in ("admin", "developer")


def is_developer(user_id: int, user=None) -> bool:
    if user_id in settings.developer_ids_list:
        return True
    return user is not None and user.role == "developer"


async def get_or_create_user(session: AsyncSession, tg_user, text: str = "", bot=None) -> tuple:
    user_id = tg_user.id
    stmt = select(User).where(User.telegram_id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user:
        user.username = tg_user.username
        user.first_name = tg_user.first_name
        if user_id in settings.developer_ids_list and user.role != "developer":
            user.role = "developer"
        elif user_id in settings.admin_ids_list and user.role != "admin":
            user.role = "admin"
        await session.commit()
        return user, False

    referral_code_param = None
    if text and len(text.split()) > 1:
        referral_code_param = text.split()[1]

    referred_by = None
    if referral_code_param:
        stmt_ref = select(User).where(User.referral_code == referral_code_param)
        result_ref = await session.execute(stmt_ref)
        referrer = result_ref.scalar_one_or_none()
        if referrer:
            referred_by = referrer.id

    user_code = _generate_referral_code()
    while True:
        stmt_check = select(User).where(User.referral_code == user_code)
        result_check = await session.execute(stmt_check)
        if result_check.scalar_one_or_none() is None:
            break
        user_code = _generate_referral_code()

    user_role = "user"
    if user_id in settings.developer_ids_list:
        user_role = "developer"
    elif user_id in settings.admin_ids_list:
        user_role = "admin"

    user = User(
        telegram_id=user_id,
        username=tg_user.username,
        first_name=tg_user.first_name,
        referral_code=user_code,
        referred_by=referred_by,
        role=user_role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    try:
        from src.services.notifications import notify_user_registration
        if bot:
            await notify_user_registration(session, user, bot)
    except Exception as e:
        logger.error("Registration notification error: %s", e)

    return user, True


async def get_welcome(session: AsyncSession, is_new: bool, name: str = "") -> str:
    stmt = select(Setting).where(Setting.key == "welcome_text")
    result = await session.execute(stmt)
    setting = result.scalar_one_or_none()
    text = setting.value if setting and setting.value else welcome_text(name)

    if is_new:
        from src.bot.texts import RULES_TEXT
        stmt_r = select(Setting).where(Setting.key == "rules_text")
        result_r = await session.execute(stmt_r)
        rules_s = result_r.scalar_one_or_none()
        rules = rules_s.value if rules_s and rules_s.value else RULES_TEXT
        text = f"{text}\n\n✅ <b>Вы успешно зарегистрированы!</b>\n\n{rules}"
    return text


# ═══════════════════════════════════════════════
# /start
# ═══════════════════════════════════════════════

@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext):
    await state.clear()
    user, is_new = await get_or_create_user(session, message.from_user, message.text or "", bot=message.bot)
    text = await get_welcome(session, is_new, message.from_user.first_name or "")
    try:
        await message.delete()
    except Exception:
        pass
    await message.answer(text, reply_markup=main_menu_kb(is_admin(message.from_user.id, user)), parse_mode="HTML")


# ═══════════════════════════════════════════════
# Возврат в главное меню
# ═══════════════════════════════════════════════

@router.callback_query(F.data == "menu:main")
async def back_to_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    stmt = select(User).where(User.telegram_id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    text = await get_welcome(session, False, callback.from_user.first_name or "")
    await safe_edit(callback, text, main_menu_kb(is_admin(user_id, user)))
    await answer_callback(callback)


@router.callback_query(F.data == "noop")
async def noop_handler(callback: CallbackQuery):
    await answer_callback(callback)
