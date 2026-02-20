"""DFC Mail Bot — точка входа.

Single-message interactive UI с inline-кнопками.
"""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from src.config import settings
from src.database.database import init_db

# Импорт модуля логирования (настраивает logging при импорте)
import src.utils.logger  # noqa: F401

logger = logging.getLogger(__name__)


def _register_routers(dp: Dispatcher) -> None:
    """Подключить все роутеры."""
    from src.bot.handlers.start import router as start_router
    from src.bot.handlers.catalog import router as catalog_router
    from src.bot.handlers.orders import router as orders_router
    from src.bot.handlers.balance import router as balance_router
    from src.bot.handlers.referral import router as referral_router
    from src.bot.handlers.info import router as info_router
    from src.bot.handlers.payment import router as payment_router
    from src.bot.handlers.broadcast import router as broadcast_router
    from src.bot.handlers.admin import router as admin_router

    dp.include_routers(
        start_router,
        catalog_router,
        orders_router,
        balance_router,
        referral_router,
        info_router,
        payment_router,
        broadcast_router,
        admin_router,
    )


def _register_middlewares(dp: Dispatcher) -> None:
    """Подключить все middleware."""
    from src.bot.middlewares.database import DatabaseMiddleware
    from src.bot.middlewares.error_handler import ErrorHandlerMiddleware
    from src.bot.middlewares.blocked_user import BlockedUserMiddleware
    from src.bot.middlewares.garbage import GarbageMiddleware

    # --- Middleware на update (самый ранний) ---
    dp.update.outer_middleware(ErrorHandlerMiddleware())

    # --- Middleware на message ---
    dp.message.outer_middleware(DatabaseMiddleware())
    dp.message.outer_middleware(BlockedUserMiddleware())
    dp.message.middleware(GarbageMiddleware())      # inner — ПОСЛЕ фильтров

    # --- Middleware на callback_query ---
    dp.callback_query.outer_middleware(DatabaseMiddleware())
    dp.callback_query.outer_middleware(BlockedUserMiddleware())

    # --- Middleware на pre_checkout_query ---
    dp.pre_checkout_query.outer_middleware(DatabaseMiddleware())


async def _on_startup(bot: Bot) -> None:
    """Действия при запуске."""
    logger.info("Инициализация базы данных...")
    await init_db()
    me = await bot.get_me()
    logger.info("Бот запущен: @%s (ID: %s)", me.username, me.id)


async def _on_shutdown(bot: Bot) -> None:
    """Действия при остановке."""
    logger.info("Бот остановлен.")


async def main() -> None:
    """Главная функция запуска."""
    logger.info("DFC Mail Bot — запуск...")

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    dp.startup.register(_on_startup)
    dp.shutdown.register(_on_shutdown)

    _register_middlewares(dp)
    _register_routers(dp)

    # Режим запуска: webhook или polling
    if settings.WEBHOOK_URL:
        from aiohttp import web
        from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

        await bot.set_webhook(settings.WEBHOOK_URL)

        app = web.Application()
        SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook/bot")

        # Подключаем маршруты платёжных webhook
        from src.bot.handlers.webhook import setup_webhook_routes
        setup_webhook_routes(app)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", settings.WEBHOOK_PORT)
        logger.info("Webhook-сервер на порту %s", settings.WEBHOOK_PORT)
        await site.start()

        # Бесконечный цикл для поддержания сервера
        try:
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()
            await bot.delete_webhook()
    else:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Режим polling")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
