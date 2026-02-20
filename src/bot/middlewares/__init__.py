"""Middlewares для бота"""
from src.bot.middlewares.blocked_user import BlockedUserMiddleware
from src.bot.middlewares.database import DatabaseMiddleware
from src.bot.middlewares.error_handler import ErrorHandlerMiddleware
from src.bot.middlewares.keyboard_update import KeyboardUpdateMiddleware

__all__ = [
    "DatabaseMiddleware",
    "BlockedUserMiddleware",
    "ErrorHandlerMiddleware",
    "KeyboardUpdateMiddleware",
]
