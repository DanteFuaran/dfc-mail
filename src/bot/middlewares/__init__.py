"""Middleware бота"""
from src.bot.middlewares.blocked_user import BlockedUserMiddleware
from src.bot.middlewares.database import DatabaseMiddleware
from src.bot.middlewares.error_handler import ErrorHandlerMiddleware
from src.bot.middlewares.garbage import GarbageMiddleware

__all__ = [
    "BlockedUserMiddleware",
    "DatabaseMiddleware",
    "ErrorHandlerMiddleware",
    "GarbageMiddleware",
]
