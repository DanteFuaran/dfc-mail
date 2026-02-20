"""Информация, правила и поддержка — inline-only single-message UI.

Поддержка работает ВНУТРИ бота: пользователь пишет сообщение → оно пересылается
администраторам с inline-кнопкой «Ответить» → админ нажимает → пишет ответ → ответ
приходит пользователю в бота.
"""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.keyboards import info_kb, rules_kb, support_cancel_kb, support_kb, support_reply_kb
from src.bot.states import SupportStates
from src.bot.texts import FAQ_TEXT, RULES_TEXT, SUPPORT_TEXT, SUPPORT_WRITE_PROMPT
from src.bot.utils import answer_callback, safe_edit
from src.config import settings
from src.database.models import Setting, User

logger = logging.getLogger(__name__)
router = Router()


# ═══════════════════════════════════════════════
# FAQ / Информация
# ═══════════════════════════════════════════════

@router.callback_query(F.data == "menu:info")
async def show_info(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    # Проверяем кастомный FAQ в настройках
    stmt = select(Setting).where(Setting.key == "faq_text")
    result = await session.execute(stmt)
    setting = result.scalar_one_or_none()
    text = setting.value if setting and setting.value else FAQ_TEXT
    await safe_edit(callback, text, info_kb())
    await answer_callback(callback)


@router.callback_query(F.data == "menu:rules")
async def show_rules(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    stmt = select(Setting).where(Setting.key == "rules_text")
    result = await session.execute(stmt)
    setting = result.scalar_one_or_none()
    text = setting.value if setting and setting.value else RULES_TEXT
    await safe_edit(callback, text, rules_kb())
    await answer_callback(callback)


# ═══════════════════════════════════════════════
# Поддержка — пользователь → админ
# ═══════════════════════════════════════════════

@router.callback_query(F.data == "menu:support")
async def show_support(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit(callback, SUPPORT_TEXT, support_kb())
    await answer_callback(callback)


@router.callback_query(F.data == "support:write")
async def support_write(callback: CallbackQuery, state: FSMContext):
    await state.update_data(_menu_msg_id=callback.message.message_id)
    await state.set_state(SupportStates.waiting_message)
    await safe_edit(callback, SUPPORT_WRITE_PROMPT, support_cancel_kb())
    await answer_callback(callback)


@router.message(SupportStates.waiting_message)
async def process_support_message(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    await state.clear()

    user_text = (message.text or "").strip()
    if not user_text:
        try:
            await message.bot.edit_message_text(
                "❌ Пустое сообщение. Попробуйте снова.",
                chat_id=message.chat.id, message_id=msg_id,
                reply_markup=support_cancel_kb(), parse_mode="HTML",
            )
        except Exception:
            pass
        return

    user = message.from_user
    user_label = f"@{user.username}" if user.username else (user.first_name or str(user.id))

    notification = (
        f"💬 <b>Обращение в поддержку</b>\n\n"
        f"👤 От: {user_label} (ID: <code>{user.id}</code>)\n\n"
        f"📩 <i>{user_text}</i>"
    )

    sent_count = 0
    admin_ids = settings.admin_ids_list + settings.developer_ids_list
    unique_ids = list(set(admin_ids))
    for admin_id in unique_ids:
        try:
            await message.bot.send_message(
                admin_id, notification,
                reply_markup=support_reply_kb(user.id),
                parse_mode="HTML",
            )
            sent_count += 1
        except Exception as e:
            logger.warning("Cannot send support notification to %s: %s", admin_id, e)

    if sent_count > 0:
        result_text = "✅ <b>Сообщение отправлено!</b>\n\nАдминистратор ответит вам в этом чате."
    else:
        result_text = "❌ Не удалось отправить сообщение. Попробуйте позже."

    from src.bot.keyboards import noop_kb
    try:
        await message.bot.edit_message_text(
            result_text,
            chat_id=message.chat.id, message_id=msg_id,
            reply_markup=noop_kb(), parse_mode="HTML",
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════
# Поддержка — админ отвечает пользователю
# ═══════════════════════════════════════════════

@router.callback_query(F.data.startswith("support:reply:"))
async def support_admin_reply(callback: CallbackQuery, state: FSMContext):
    """Админ нажал 'Ответить' на обращение пользователя."""
    from src.bot.handlers.start import is_admin

    stmt_user_id = int(callback.data.split(":")[2])

    if not is_admin(callback.from_user.id):
        await answer_callback(callback, "⛔ Нет доступа.")
        return

    await state.update_data(
        _reply_to_user=stmt_user_id,
        _menu_msg_id=callback.message.message_id,
    )
    await state.set_state(SupportStates.waiting_reply)
    await safe_edit(
        callback,
        f"↩️ <b>Ответ пользователю</b> (ID: <code>{stmt_user_id}</code>)\n\n"
        "Напишите текст ответа:",
        support_cancel_kb(),
    )
    await answer_callback(callback)


@router.message(SupportStates.waiting_reply)
async def process_admin_reply(message: Message, state: FSMContext):
    data = await state.get_data()
    target_user_id = data.get("_reply_to_user")
    msg_id = data.get("_menu_msg_id")
    await state.clear()

    reply_text = (message.text or "").strip()
    if not reply_text or not target_user_id:
        return

    admin = message.from_user
    admin_label = f"@{admin.username}" if admin.username else (admin.first_name or "Админ")

    user_notification = (
        f"📩 <b>Ответ от поддержки</b>\n\n"
        f"💬 {reply_text}\n\n"
        f"<i>— {admin_label}</i>"
    )

    try:
        await message.bot.send_message(target_user_id, user_notification, parse_mode="HTML")
        result = f"✅ Ответ отправлен пользователю {target_user_id}."
    except Exception as e:
        logger.error("Cannot send reply to user %s: %s", target_user_id, e)
        result = f"❌ Не удалось отправить ответ пользователю {target_user_id}."

    from src.bot.keyboards import noop_kb
    try:
        await message.bot.edit_message_text(
            result,
            chat_id=message.chat.id, message_id=msg_id,
            reply_markup=noop_kb(), parse_mode="HTML",
        )
    except Exception:
        pass

