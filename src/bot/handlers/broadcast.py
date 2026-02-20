"""Рассылка (массовая и индивидуальная) — inline-only single-message UI"""
import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.keyboards import admin_broadcast_kb, cancel_input_kb, noop_kb
from src.bot.states import BroadcastStates
from src.bot.utils import answer_callback, safe_edit
from src.config import settings
from src.database.models import User

logger = logging.getLogger(__name__)
router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids_list or user_id in settings.developer_ids_list


# ═══════════════════════════════════════════════
# Меню рассылки
# ═══════════════════════════════════════════════

@router.callback_query(F.data == "adm:broadcast")
async def broadcast_menu(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        await answer_callback(callback, "⛔ Нет доступа.")
        return
    await state.clear()
    await safe_edit(
        callback,
        "📢 <b>Рассылка</b>\n\nВыберите тип рассылки:",
        admin_broadcast_kb(),
    )
    await answer_callback(callback)


# ═══════════════════════════════════════════════
# Массовая рассылка
# ═══════════════════════════════════════════════

@router.callback_query(F.data == "adm:bcast:mass")
async def mass_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        await answer_callback(callback, "⛔ Нет доступа.")
        return
    await state.update_data(_menu_msg_id=callback.message.message_id)
    await state.set_state(BroadcastStates.waiting_message)
    await safe_edit(
        callback,
        "📢 <b>Массовая рассылка</b>\n\nВведите текст сообщения для всех пользователей:",
        cancel_input_kb("adm:broadcast"),
    )
    await answer_callback(callback)


@router.message(BroadcastStates.waiting_message)
async def mass_broadcast_process(message: Message, state: FSMContext, session: AsyncSession):
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    await state.clear()

    text = (message.text or "").strip()
    if not text:
        try:
            await message.bot.edit_message_text(
                "❌ Пустое сообщение.",
                chat_id=message.chat.id, message_id=msg_id,
                reply_markup=cancel_input_kb("adm:broadcast"), parse_mode="HTML",
            )
        except Exception:
            pass
        return

    # Отправляем статус
    try:
        await message.bot.edit_message_text(
            "📤 Отправка...",
            chat_id=message.chat.id, message_id=msg_id,
            parse_mode="HTML",
        )
    except Exception:
        pass

    stmt = select(User).where(User.is_blocked == False)
    result = await session.execute(stmt)
    users = result.scalars().all()

    sent, failed = 0, 0
    throttle = settings.BROADCAST_THROTTLE or 25

    for i, user in enumerate(users):
        try:
            await message.bot.send_message(user.telegram_id, text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
        if (i + 1) % throttle == 0:
            await asyncio.sleep(1)

    result_text = (
        f"📢 <b>Рассылка завершена</b>\n\n"
        f"✅ Отправлено: {sent}\n"
        f"❌ Ошибки: {failed}\n"
        f"📊 Всего: {len(users)}"
    )
    try:
        await message.bot.edit_message_text(
            result_text,
            chat_id=message.chat.id, message_id=msg_id,
            reply_markup=noop_kb(), parse_mode="HTML",
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════
# Индивидуальная рассылка
# ═══════════════════════════════════════════════

@router.callback_query(F.data == "adm:bcast:individual")
async def individual_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        await answer_callback(callback, "⛔ Нет доступа.")
        return
    await state.update_data(_menu_msg_id=callback.message.message_id)
    await state.set_state(BroadcastStates.waiting_user_id)
    await safe_edit(
        callback,
        "👤 <b>Индивидуальная рассылка</b>\n\nВведите Telegram ID пользователя:",
        cancel_input_kb("adm:broadcast"),
    )
    await answer_callback(callback)


@router.message(BroadcastStates.waiting_user_id)
async def individual_broadcast_user_id(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")

    try:
        target_id = int(message.text.strip())
    except (ValueError, TypeError, AttributeError):
        try:
            await message.bot.edit_message_text(
                "❌ Введите числовой Telegram ID:",
                chat_id=message.chat.id, message_id=msg_id,
                reply_markup=cancel_input_kb("adm:broadcast"), parse_mode="HTML",
            )
        except Exception:
            pass
        return

    await state.update_data(_target_user_id=target_id)
    await state.set_state(BroadcastStates.waiting_individual_message)

    try:
        await message.bot.edit_message_text(
            f"📝 Введите сообщение для пользователя <code>{target_id}</code>:",
            chat_id=message.chat.id, message_id=msg_id,
            reply_markup=cancel_input_kb("adm:broadcast"), parse_mode="HTML",
        )
    except Exception:
        pass


@router.message(BroadcastStates.waiting_individual_message)
async def individual_broadcast_send(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    msg_id = data.get("_menu_msg_id")
    target_id = data.get("_target_user_id")
    await state.clear()

    text = (message.text or "").strip()
    if not text or not target_id:
        return

    try:
        await message.bot.send_message(target_id, text, parse_mode="HTML")
        result = f"✅ Сообщение отправлено пользователю <code>{target_id}</code>."
    except Exception as e:
        logger.error("Individual broadcast error to %s: %s", target_id, e)
        result = f"❌ Не удалось отправить сообщение пользователю <code>{target_id}</code>."

    try:
        await message.bot.edit_message_text(
            result,
            chat_id=message.chat.id, message_id=msg_id,
            reply_markup=noop_kb(), parse_mode="HTML",
        )
    except Exception:
        pass
