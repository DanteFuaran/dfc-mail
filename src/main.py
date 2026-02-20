"""DFC Mail Bot — точка входа"""
import asyncio
import logging
import sys
import traceback

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent, FSInputFile

from src.config import settings
from src.database.database import async_session_maker, init_db
from src.bot.handlers import (  # noqa — роутеры регистрируются ниже
    start, catalog, orders, balance, referral, info, payment, admin, broadcast,
)
from src.bot.handlers.webhook import create_webhook_app
from src.utils.logger import logger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)


# ═══════════════════════════════════════════════
# ФОНОВЫЕ ЗАДАЧИ
# ═══════════════════════════════════════════════


async def cancel_expired_orders(bot: Bot) -> None:
    """Автоматическая отмена просроченных заказов (каждые 5 мин)."""
    from datetime import datetime

    from sqlalchemy import select, update

    from src.database.models import Account, Order, Product, User

    while True:
        try:
            async with async_session_maker() as session:
                now = datetime.now()
                stmt = select(Order).where(Order.status == "ОЖИДАЕТ ОПЛАТЫ", Order.reserved_until < now)
                result = await session.execute(stmt)
                expired_orders = result.scalars().all()

                for order in expired_orders:
                    stmt_acc = select(Account).where(Account.order_id == order.id)
                    result_acc = await session.execute(stmt_acc)
                    accounts = result_acc.scalars().all()

                    if accounts:
                        account_ids = [a.id for a in accounts]
                        await session.execute(
                            update(Account)
                            .where(Account.id.in_(account_ids))
                            .values(is_sold=False, sold_at=None, order_id=None)
                        )
                        await session.execute(
                            update(Product)
                            .where(Product.id == order.product_id)
                            .values(stock_count=Product.stock_count + order.quantity)
                        )

                    order.status = "ОТМЕНЕНО"
                    order.reserved_until = None

                    try:
                        stmt_user = select(User).where(User.id == order.user_id)
                        result_user = await session.execute(stmt_user)
                        user = result_user.scalar_one_or_none()
                        if user:
                            await bot.send_message(
                                user.telegram_id,
                                f"⏰ <b>Заказ отменен</b>\n\n"
                                f"Заказ #{order.id} был отменен из-за истечения времени ожидания оплаты "
                                f"({settings.ORDER_RESERVATION_MINUTES} минут).\n\n"
                                f"✅ Товар возвращен в каталог.\n\nВы можете создать новый заказ.",
                                parse_mode="HTML",
                            )
                    except Exception as e:
                        logger.error("Error notifying user about expired order: %s", e)

                if expired_orders:
                    await session.commit()
                    logger.info("Cancelled %d expired orders", len(expired_orders))
        except Exception as e:
            logger.error("Error in cancel_expired_orders: %s", e)
        await asyncio.sleep(300)


async def sync_roles_from_env(bot: Bot) -> None:
    """Синхронизация ролей пользователей из .env в БД."""
    from sqlalchemy import select

    from src.database.models import User

    async with async_session_maker() as session:
        all_admin_ids = set(settings.admin_ids_list + settings.developer_ids_list)
        for user_id in all_admin_ids:
            try:
                stmt = select(User).where(User.telegram_id == user_id)
                result = await session.execute(stmt)
                user = result.scalar_one_or_none()
                if user:
                    if user_id in settings.developer_ids_list:
                        if user.role != "developer":
                            user.role = "developer"
                            logger.info("Updated role to 'developer' for user %s", user_id)
                    elif user_id in settings.admin_ids_list:
                        if user.role != "admin":
                            user.role = "admin"
                            logger.info("Updated role to 'admin' for user %s", user_id)
                else:
                    logger.debug("User %s from .env not yet registered", user_id)
            except Exception as e:
                logger.error("Error syncing role for user %s: %s", user_id, e)
        await session.commit()


async def setup_support_chat(bot: Bot) -> None:
    """Настройка чата поддержки."""
    from sqlalchemy import select

    from src.database.models import Setting

    async with async_session_maker() as session:
        stmt = select(Setting).where(Setting.key == "support_chat_id")
        result = await session.execute(stmt)
        setting = result.scalar_one_or_none()

        support_chat_id = None
        if setting and setting.value:
            try:
                support_chat_id = int(setting.value)
            except ValueError:
                pass

        if not support_chat_id and settings.admin_ids_list:
            instruction_text = (
                "📋 <b>Настройка чата поддержки</b>\n\n"
                "Для настройки системы поддержки выполните следующие шаги:\n\n"
                "1. Создайте группу в Telegram (или используйте существующую)\n"
                "2. Добавьте бота в группу как администратора\n"
                "3. Отправьте любое сообщение в группу\n"
                "4. Бот автоматически сохранит ID группы"
            )
            for admin_id in settings.admin_ids_list:
                try:
                    await bot.send_message(admin_id, instruction_text, parse_mode="HTML")
                    logger.info("Sent support chat setup instruction to admin %s", admin_id)
                except Exception as e:
                    error_str = str(e).lower()
                    if any(w in error_str for w in ("unauthorized", "chat not found", "bot was blocked")):
                        logger.warning("Admin %s has not started conversation with bot", admin_id)
                    else:
                        logger.error("Failed to send instruction to admin %s: %s", admin_id, e)
        elif support_chat_id:
            try:
                chat = await bot.get_chat(support_chat_id)
                logger.info("Support chat configured: %s (ID: %s)", chat.title, support_chat_id)
            except Exception as e:
                logger.warning("Support chat ID %s is not accessible: %s", support_chat_id, e)
                if setting:
                    setting.value = ""
                    await session.commit()


# ═══════════════════════════════════════════════
# WEBHOOK СЕРВЕР
# ═══════════════════════════════════════════════


async def start_webhook_server(bot: Bot, dispatcher: Dispatcher = None):
    """Запуск HTTP/HTTPS сервера для webhook."""
    import ssl

    from aiohttp import web

    try:
        app = create_webhook_app(bot, dispatcher)
        runner = web.AppRunner(app)
        await runner.setup()

        use_https = settings.WEBHOOK_USE_HTTPS
        ssl_context = None

        if use_https:
            if not settings.WEBHOOK_SSL_CERT_PATH or not settings.WEBHOOK_SSL_KEY_PATH:
                logger.warning("HTTPS enabled but SSL certs not configured. Falling back to HTTP.")
                use_https = False
            else:
                try:
                    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                    ssl_context.load_cert_chain(settings.WEBHOOK_SSL_CERT_PATH, settings.WEBHOOK_SSL_KEY_PATH)
                    logger.info("SSL certificates loaded successfully")
                except Exception as e:
                    logger.error("Failed to load SSL certificates: %s. Falling back to HTTP.", e)
                    use_https = False
                    ssl_context = None

        if use_https and ssl_context:
            site = web.TCPSite(runner, "0.0.0.0", settings.WEBHOOK_PORT, ssl_context=ssl_context)
            protocol = "https"
        else:
            site = web.TCPSite(runner, "0.0.0.0", settings.WEBHOOK_PORT)
            protocol = "http"

        await site.start()
        logger.info("Webhook server started on port %s (%s)", settings.WEBHOOK_PORT, protocol.upper())
        return runner
    except Exception as e:
        logger.error("Failed to start webhook server: %s", e, exc_info=True)
        return None


# ═══════════════════════════════════════════════
# LIFECYCLE
# ═══════════════════════════════════════════════


async def on_startup(bot: Bot) -> None:
    """Действия при запуске бота."""
    logger.info("Bot starting up...")

    try:
        bot_info = await bot.get_me()
        logger.info("Bot token verified. Bot: @%s (ID: %s)", bot_info.username, bot_info.id)
    except Exception as e:
        if "unauthorized" in str(e).lower():
            logger.error("Bot token is invalid or expired!")
        raise

    await init_db()
    logger.info("Database initialized")

    await sync_roles_from_env(bot)
    logger.info("Roles synchronized from .env")

    await setup_support_chat(bot)
    logger.info("Support chat setup completed")

    asyncio.create_task(cancel_expired_orders(bot))
    logger.info("Expired orders cancellation task started")

    webhook_runner = await start_webhook_server(bot, None)
    if webhook_runner:
        bot._webhook_runner = webhook_runner

    if not settings.WEBHOOK_URL:
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("Polling mode: webhook deleted")
        except Exception as e:
            if "unauthorized" in str(e).lower():
                raise
            logger.warning("Could not delete webhook (non-critical): %s", e)


async def on_shutdown(bot: Bot) -> None:
    """Действия при остановке бота."""
    logger.info("Bot shutting down...")
    if hasattr(bot, "_webhook_runner"):
        try:
            await bot._webhook_runner.cleanup()
            logger.info("Webhook server stopped")
        except Exception as e:
            logger.warning("Error stopping webhook server: %s", e)
    try:
        await bot.delete_webhook()
    except Exception as e:
        logger.warning("Error deleting webhook on shutdown: %s", e)
    finally:
        try:
            await bot.session.close()
        except Exception as e:
            logger.warning("Error closing bot session: %s", e)


# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════


async def main() -> None:
    if not settings.BOT_TOKEN:
        logger.error("BOT_TOKEN not set in environment variables!")
        sys.exit(1)

    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Регистрация роутеров (порядок важен!)
    dp.include_router(start.router)
    dp.include_router(admin.router)
    dp.include_router(broadcast.router)
    dp.include_router(catalog.router)
    dp.include_router(orders.router)
    dp.include_router(balance.router)
    dp.include_router(referral.router)
    dp.include_router(payment.router)
    dp.include_router(info.router)  # должен быть последним

    # Регистрация middleware
    from src.bot.middlewares import (
        BlockedUserMiddleware,
        DatabaseMiddleware,
        ErrorHandlerMiddleware,
        KeyboardUpdateMiddleware,
    )

    dp.message.middleware(DatabaseMiddleware())
    dp.callback_query.middleware(DatabaseMiddleware())
    dp.message.middleware(BlockedUserMiddleware())
    dp.callback_query.middleware(BlockedUserMiddleware())
    dp.message.middleware(KeyboardUpdateMiddleware())
    dp.update.outer_middleware(ErrorHandlerMiddleware())

    @dp.errors()
    async def error_handler(event, data):
        if isinstance(event, ErrorEvent):
            exception = event.exception
            update = event.update
        elif hasattr(event, "exception"):
            exception = event.exception
            update = getattr(event, "update", None)
        else:
            exception = event
            update = None

        error_str = str(exception).lower()
        if any(p in error_str for p in ("timeout", "semaphore", "connection", "network")):
            logger.warning("Network error (non-critical): %s", exception)
            return
        if "message is not modified" in error_str:
            return

        logger.error("Error handler called: %s: %s", type(exception).__name__, exception, exc_info=exception)

        try:
            from src.utils.logger import log_error_to_db

            async with async_session_maker() as session:
                user_id = None
                if not update and data:
                    update = data.get("update")
                if update:
                    if update.message and update.message.from_user:
                        user_id = update.message.from_user.id
                    elif update.callback_query and update.callback_query.from_user:
                        user_id = update.callback_query.from_user.id
                tb_str = "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))
                await log_error_to_db(session, "ERROR", str(exception), user_id=user_id, traceback=tb_str)
        except Exception as e:
            logger.error("Error logging to DB: %s", e)

    # Запуск бота
    if settings.WEBHOOK_URL:
        logger.info("Starting bot in WEBHOOK mode")
        try:
            await on_startup(bot)
            if hasattr(bot, "_webhook_runner"):
                await bot._webhook_runner.cleanup()
            webhook_runner = await start_webhook_server(bot, dp)
            if webhook_runner:
                bot._webhook_runner = webhook_runner
            try:
                await bot.set_webhook(
                    url=settings.WEBHOOK_URL,
                    certificate=FSInputFile(settings.WEBHOOK_SSL_CERT_PATH) if settings.WEBHOOK_SSL_CERT_PATH else None,
                    allowed_updates=dp.resolve_used_update_types(),
                )
                logger.info("Webhook set to %s", settings.WEBHOOK_URL)
            except Exception as e:
                logger.error("Failed to set webhook: %s", e)
                raise
            logger.info("Bot is running in webhook mode. Press Ctrl+C to stop.")
            try:
                await asyncio.Event().wait()
            except KeyboardInterrupt:
                logger.info("Received shutdown signal")
            finally:
                await on_shutdown(bot)
        except Exception as e:
            logger.error("Error in webhook mode: %s", e, exc_info=True)
            await on_shutdown(bot)
            raise
    else:
        logger.info("Starting bot in POLLING mode")
        await on_startup(bot)
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        finally:
            await on_shutdown(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error("Fatal error: %s", e)
        sys.exit(1)
