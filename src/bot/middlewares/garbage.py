"""GarbageMiddleware — удаляет текстовые сообщения пользователя для чистоты чата.

Все текстовые сообщения (кроме /start) удаляются ПОСЛЕ обработки хендлером.
Это создаёт эффект single-message UI: в чате видно только одно интерактивное сообщение.
"""
import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message

logger = logging.getLogger(__name__)


class GarbageMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        # Сначала вызываем хендлер (чтобы FSM-хендлеры обработали текст)
        result = await handler(event, data)

        # Затем удаляем сообщение пользователя (кроме /start)
        if isinstance(event, Message) and event.text:
            if event.text.strip().startswith("/start"):
                return result
            try:
                await event.delete()
            except Exception:
                pass  # Не критично, если не удалось удалить

        # Удаляем документы/фото тоже (загрузка файлов)
        if isinstance(event, Message) and (event.document or event.photo):
            try:
                await event.delete()
            except Exception:
                pass

        return result
