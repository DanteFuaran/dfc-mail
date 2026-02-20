"""Утилиты бота — single-message UI"""
import logging
from typing import Optional, Union

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)


async def safe_edit(
    target: Union[CallbackQuery, Message],
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    *,
    bot: Optional[Bot] = None,
    chat_id: Optional[int] = None,
    message_id: Optional[int] = None,
    parse_mode: str = "HTML",
) -> Optional[Message]:
    """
    Безопасное редактирование сообщения.
    Если target — CallbackQuery, редактирует callback.message.
    Если target — Message, нужны bot, chat_id, message_id.
    Если сообщение не изменилось — тихо игнорирует.
    Если редактирование невозможно — отправляет новое.
    """
    try:
        if isinstance(target, CallbackQuery):
            msg = target.message
            try:
                result = await msg.edit_text(
                    text, reply_markup=reply_markup, parse_mode=parse_mode,
                )
                return result
            except Exception as e:
                err = str(e).lower()
                if "message is not modified" in err:
                    return msg
                if any(w in err for w in ("message to edit not found", "message can't be edited")):
                    return await msg.answer(
                        text, reply_markup=reply_markup, parse_mode=parse_mode,
                    )
                raise
        else:
            _bot = bot or target.bot
            _chat = chat_id or target.chat.id
            _msg_id = message_id
            if not _msg_id:
                raise ValueError("message_id required for Message target")
            try:
                return await _bot.edit_message_text(
                    text,
                    chat_id=_chat,
                    message_id=_msg_id,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
            except Exception as e:
                err = str(e).lower()
                if "message is not modified" in err:
                    return None
                if any(w in err for w in ("message to edit not found", "message can't be edited")):
                    return await _bot.send_message(
                        _chat, text, reply_markup=reply_markup, parse_mode=parse_mode,
                    )
                raise
    except Exception as e:
        err = str(e).lower()
        if any(w in err for w in ("timeout", "semaphore", "connection", "network")):
            logger.warning("Network error in safe_edit: %s", e)
            return None
        logger.error("safe_edit error: %s", e, exc_info=True)
        return None


async def answer_callback(callback: CallbackQuery, text: str = ""):
    """Безопасный answer callback."""
    try:
        await callback.answer(text)
    except Exception:
        pass


async def delete_message_safe(message: Message) -> None:
    """Удалить сообщение без ошибок."""
    try:
        await message.delete()
    except Exception:
        pass


async def send_menu(
    bot: Bot,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    parse_mode: str = "HTML",
) -> Optional[Message]:
    """Отправить новое сообщение-меню."""
    try:
        return await bot.send_message(
            chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode,
        )
    except Exception as e:
        logger.error("send_menu error: %s", e)
        return None
