"""Middleware для проверки блокировки пользователя (inline-only)"""
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from src.config import settings
from src.database.models import User


class BlockedUserMiddleware(BaseMiddleware):
    """Middleware для проверки блокировки пользователя."""

    ADMIN_PREFIXES = ("adm:", "menu:admin", "support:reply:")

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

        # Админы / разработчики — всегда пропускаем
        if user_id in settings.admin_ids_list or user_id in settings.developer_ids_list:
            return await handler(event, data)

        # Админские callback — пропускаем (проверка роли внутри хендлеров)
        if callback_data and any(callback_data.startswith(p) for p in self.ADMIN_PREFIXES):
            return await handler(event, data)

        session = data.get("session")
        if session:
            stmt = select(User).where(User.telegram_id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if user and user.is_blocked:
                # Поддержку разрешаем даже заблокированным
                if is_callback and callback_data and callback_data.startswith("support:"):
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
                    try:
                        await event.answer(blocked_message, parse_mode="HTML")
                    except Exception:
                        pass
                    return

        return await handler(event, data)
