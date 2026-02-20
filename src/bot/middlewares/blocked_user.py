"""Middleware для проверки блокировки пользователя"""
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from src.bot.texts import (
    MENU_ADMIN,
    MENU_BALANCE,
    MENU_BROADCAST,
    MENU_CATALOG,
    MENU_INFO,
    MENU_ORDERS,
    MENU_REFERRAL,
    MENU_RULES,
    MENU_SUPPORT,
)
from src.config import settings
from src.database.models import User


class BlockedUserMiddleware(BaseMiddleware):
    """Middleware для проверки блокировки пользователя."""

    ADMIN_PREFIXES = ("admin_", "broadcast_")
    MENU_BUTTONS = (
        MENU_CATALOG, MENU_BALANCE, MENU_ORDERS, MENU_REFERRAL,
        MENU_SUPPORT, MENU_INFO, MENU_RULES, MENU_ADMIN, MENU_BROADCAST,
    )

    def _is_support_related(self, event: Any) -> bool:
        if isinstance(event, Message):
            if event.text == MENU_SUPPORT:
                return True
            if event.text and not event.text.startswith("/") and event.text not in self.MENU_BUTTONS:
                return True
            if event.photo or event.document or event.video or event.voice or event.audio:
                return True
        return False

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        user_id = None
        is_callback = False
        callback_data = None

        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id
            is_callback = True
            callback_data = event.data

        if not user_id:
            return await handler(event, data)

        if callback_data and any(callback_data.startswith(p) for p in self.ADMIN_PREFIXES):
            return await handler(event, data)

        if user_id in settings.admin_ids_list or user_id in settings.developer_ids_list:
            return await handler(event, data)

        session = data.get("session")
        if session:
            stmt = select(User).where(User.telegram_id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if user and user.is_blocked:
                if self._is_support_related(event):
                    return await handler(event, data)

                blocked_message = (
                    "❌ <b>Вы заблокированы</b>\n\n"
                    "Ваш доступ к боту ограничен администратором.\n"
                    "Если вы считаете, что это ошибка, обратитесь в поддержку."
                )
                if is_callback:
                    try:
                        await event.message.edit_text(blocked_message, parse_mode="HTML")
                    except Exception:
                        await event.answer("Вы заблокированы", show_alert=True)
                    return
                else:
                    await event.answer(blocked_message, parse_mode="HTML")
                    return

        return await handler(event, data)
