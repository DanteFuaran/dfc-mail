"""Middleware для обработки ошибок"""
import logging
import traceback
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Update

logger = logging.getLogger(__name__)


class ErrorHandlerMiddleware(BaseMiddleware):
    """Middleware для обработки ошибок."""

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception as exception:
            error_str = str(exception).lower()

            if "message is not modified" in error_str:
                return None

            if any(
                phrase in error_str
                for phrase in ("timeout", "semaphore", "connection", "network")
            ):
                logger.warning("Network error in handler (non-critical): %s", exception)
                return None

            logger.error("Error in handler: %s", exception, exc_info=exception)

            try:
                from src.database.database import async_session_maker
                from src.utils.logger import log_error_to_db

                async with async_session_maker() as session:
                    user_id = None
                    update = None

                    if isinstance(event, Update):
                        update = event
                    elif hasattr(event, "update"):
                        update = event.update

                    if update and isinstance(update, Update):
                        if update.message and update.message.from_user:
                            user_id = update.message.from_user.id
                        elif update.callback_query and update.callback_query.from_user:
                            user_id = update.callback_query.from_user.id

                    tb_str = "".join(
                        traceback.format_exception(type(exception), exception, exception.__traceback__)
                    )
                    await log_error_to_db(session, "ERROR", str(exception), user_id=user_id, traceback=tb_str)
            except Exception as e:
                logger.error("Error logging to DB: %s", e)

            raise
