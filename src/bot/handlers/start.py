"""Обработчик команды /start"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.database.models import User, Setting
from src.database.database import get_session
from src.bot.keyboards import get_main_menu_keyboard
from src.bot.texts import WELCOME_MESSAGE
from src.config import settings
import secrets
import string
import logging

logger = logging.getLogger(__name__)

router = Router()


def generate_referral_code() -> str:
    """Генерация реферального кода."""
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(10))


async def _get_or_create_user(session: AsyncSession, message: Message) -> tuple:
    """Получить или создать пользователя. Возвращает (user, is_new)."""
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    stmt = select(User).where(User.telegram_id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user:
        # Обновляем данные
        user.username = username
        user.first_name = first_name
        # Синхронизируем роль с .env
        if user_id in settings.developer_ids_list and user.role != "developer":
            user.role = "developer"
        elif user_id in settings.admin_ids_list and user.role != "admin":
            user.role = "admin"
        await session.commit()
        return user, False

    # Создаём нового пользователя
    referral_code = None
    if len(message.text.split()) > 1:
        referral_code = message.text.split()[1]

    referred_by = None
    if referral_code:
        stmt_ref = select(User).where(User.referral_code == referral_code)
        result_ref = await session.execute(stmt_ref)
        referrer = result_ref.scalar_one_or_none()
        if referrer:
            referred_by = referrer.id

    user_code = generate_referral_code()
    while True:
        stmt_check = select(User).where(User.referral_code == user_code)
        result_check = await session.execute(stmt_check)
        if result_check.scalar_one_or_none() is None:
            break
        user_code = generate_referral_code()

    user_role = "user"
    if user_id in settings.developer_ids_list:
        user_role = "developer"
    elif user_id in settings.admin_ids_list:
        user_role = "admin"

    user = User(
        telegram_id=user_id,
        username=username,
        first_name=first_name,
        referral_code=user_code,
        referred_by=referred_by,
        role=user_role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    # Уведомляем администраторов
    try:
        from src.services.notifications import notify_user_registration
        await notify_user_registration(session, user, message.bot)
    except Exception as e:
        logger.error("Error notifying about registration: %s", e)

    return user, True


def _is_admin(user_id: int, user) -> bool:
    """Проверка прав администратора (гибридная: .env + БД)."""
    if user_id in settings.admin_ids_list or user_id in settings.developer_ids_list:
        return True
    return user and user.role in ("admin", "developer")


async def _get_welcome_text(session: AsyncSession, is_new: bool) -> str:
    """Получить текст приветствия."""
    stmt = select(Setting).where(Setting.key == "welcome_text")
    result = await session.execute(stmt)
    setting = result.scalar_one_or_none()
    welcome = setting.value if setting and setting.value else WELCOME_MESSAGE

    if is_new:
        from src.bot.texts import RULES_TEXT
        stmt_rules = select(Setting).where(Setting.key == "rules_text")
        result_rules = await session.execute(stmt_rules)
        rules_setting = result_rules.scalar_one_or_none()
        rules = rules_setting.value if rules_setting and rules_setting.value else RULES_TEXT
        welcome = f"{welcome}\n\n✅ Вы успешно зарегистрированы!\n\n{rules}"

    return welcome


# ═══════════════════════════════════════════════
# /start в ЛИЧНЫХ СООБЩЕНИЯХ
# ═══════════════════════════════════════════════

@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start_private(message: Message, session: AsyncSession):
    """Обработка /start в личных сообщениях — полное меню."""
    user, is_new = await _get_or_create_user(session, message)
    welcome = await _get_welcome_text(session, is_new)
    is_adm = _is_admin(message.from_user.id, user)

    await message.answer(
        welcome,
        reply_markup=get_main_menu_keyboard(is_admin=is_adm),
    )


# ═══════════════════════════════════════════════
# /start в ГРУППАХ — inline-кнопка «Открыть бота»
# ═══════════════════════════════════════════════

@router.message(CommandStart(), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def cmd_start_group(message: Message, session: AsyncSession):
    """Обработка /start в группах — кнопка перехода в ЛС + авто-сохранение чата поддержки."""
    user, _ = await _get_or_create_user(session, message)
    bot_info = await message.bot.get_me()

    # Авто-сохраняем ID группы как чат поддержки (если ещё не установлен)
    chat_id = message.chat.id
    stmt = select(Setting).where(Setting.key == "support_chat_id")
    result = await session.execute(stmt)
    setting = result.scalar_one_or_none()
    if not setting:
        session.add(Setting(key="support_chat_id", value=str(chat_id)))
        await session.commit()
        logger.info("Support chat auto-saved: %s (%s)", message.chat.title, chat_id)
    elif not setting.value:
        setting.value = str(chat_id)
        await session.commit()
        logger.info("Support chat auto-saved: %s (%s)", message.chat.title, chat_id)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Открыть бота", url=f"https://t.me/{bot_info.username}?start=group")]
    ])

    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "Для покупки товаров нажмите кнопку ниже — бот работает в личных сообщениях.",
        reply_markup=keyboard,
    )


# ═══════════════════════════════════════════════
# ВОЗВРАТ В МЕНЮ
# ═══════════════════════════════════════════════

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Возврат в главное меню."""
    await state.clear()
    user_id = callback.from_user.id

    stmt = select(User).where(User.telegram_id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    is_adm = _is_admin(user_id, user)

    welcome = await _get_welcome_text(session, False)

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.message.answer(
        welcome,
        reply_markup=get_main_menu_keyboard(is_admin=is_adm),
    )
    await callback.answer()
