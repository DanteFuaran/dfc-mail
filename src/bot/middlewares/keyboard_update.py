"""Middleware для автоматического обновления клавиатуры при изменении роли"""
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message
from sqlalchemy import select

from src.bot.keyboards import get_main_menu_keyboard
from src.config import settings
from src.database.models import User


class KeyboardUpdateMiddleware(BaseMiddleware):
    """Middleware для обновления клавиатуры при изменении роли пользователя."""

    def __init__(self) -> None:
        self._user_roles_cache: Dict[int, bool] = {}

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        if event.text and event.text.startswith("/start"):
            return await handler(event, data)

        user_id = event.from_user.id if event.from_user else None
        if not user_id:
            return await handler(event, data)

        session = data.get("session")
        if not session:
            return await handler(event, data)

        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            return await handler(event, data)

        is_admin = user_id in settings.admin_ids_list or user_id in settings.developer_ids_list
        if not is_admin and user.role in ("admin", "developer"):
            is_admin = True

        cached_is_admin = self._user_roles_cache.get(user_id)

        if cached_is_admin is None or cached_is_admin != is_admin:
            self._user_roles_cache[user_id] = is_admin
            if cached_is_admin is not None:
                try:
                    await event.answer(
                        "🔄 <b>Ваши права обновлены!</b>\n\nКлавиатура обновлена в соответствии с новыми правами.",
                        reply_markup=get_main_menu_keyboard(is_admin=is_admin),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

        return await handler(event, data)
