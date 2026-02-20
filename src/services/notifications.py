"""Сервис уведомлений"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database.models import Product, User

logger = logging.getLogger(__name__)


async def send_notification_to_chat(bot, message: str, parse_mode: str = "HTML") -> None:
    """Отправить уведомление в канал/чат поддержки."""
    try:
        chat_id = settings.NOTIFICATIONS_CHAT_ID
        if not chat_id:
            for admin_id in settings.admin_ids_list:
                try:
                    await bot.send_message(admin_id, message, parse_mode=parse_mode)
                except Exception as e:
                    logger.error("Error sending notification to admin %s: %s", admin_id, e)
            return

        try:
            target = int(chat_id) if chat_id.lstrip("-").isdigit() else chat_id
            await bot.send_message(target, message, parse_mode=parse_mode)
        except Exception as e:
            logger.error("Error sending notification to chat %s: %s", chat_id, e)
            for admin_id in settings.admin_ids_list:
                try:
                    await bot.send_message(admin_id, message, parse_mode=parse_mode)
                except Exception:
                    pass
    except Exception as e:
        logger.error("Error in send_notification_to_chat: %s", e)


async def notify_stock_available(session: AsyncSession, product_id: int, bot, check_stock_was_zero: bool = False) -> None:
    """Уведомить пользователей о поступлении товара."""
    from src.database.models import Account, StockNotification

    try:
        stmt_product = select(Product).where(Product.id == product_id)
        result_product = await session.execute(stmt_product)
        product = result_product.scalar_one_or_none()
        if not product:
            return

        if check_stock_was_zero:
            from sqlalchemy import func, update

            stmt_count = select(func.count(Account.id)).where(
                Account.product_id == product_id, Account.is_sold == False
            )
            result_count = await session.execute(stmt_count)
            actual = result_count.scalar() or 0

            if product.stock_count != actual:
                await session.execute(
                    update(Product).where(Product.id == product_id).values(stock_count=actual)
                )
                await session.commit()
                result_product = await session.execute(stmt_product)
                product = result_product.scalar_one_or_none()

            if product.stock_count <= 0:
                return

        stmt = select(StockNotification).where(
            StockNotification.product_id == product_id, StockNotification.is_notified == False
        )
        result = await session.execute(stmt)
        notifications = result.scalars().all()
        if not notifications:
            return

        for notification in notifications:
            try:
                stmt_user = select(User).where(User.id == notification.user_id)
                result_user = await session.execute(stmt_user)
                user = result_user.scalar_one_or_none()
                if user and not user.is_blocked:
                    await bot.send_message(
                        user.telegram_id,
                        f"🔔 <b>Товар поступил в продажу!</b>\n\n"
                        f"📦 {product.name}\n"
                        f"💰 Цена: {product.price:.2f} ₽\n"
                        f"📊 В наличии: {product.stock_count} шт.\n\n"
                        f"Используйте меню 'Каталог' для покупки.",
                        parse_mode="HTML",
                    )
                    notification.is_notified = True
            except Exception as e:
                logger.error("Error notifying user %s: %s", notification.user_id, e)

        await session.commit()
    except Exception as e:
        logger.error("Error in notify_stock_available: %s", e)


async def notify_admins_about_purchase(session: AsyncSession, order, bot) -> None:
    """Уведомить администраторов о покупке."""
    try:
        stmt_user = select(User).where(User.id == order.user_id)
        result_user = await session.execute(stmt_user)
        user = result_user.scalar_one_or_none()

        stmt_product = select(Product).where(Product.id == order.product_id)
        result_product = await session.execute(stmt_product)
        product = result_product.scalar_one_or_none()

        if not user or not product:
            return

        text = (
            f"🛒 <b>Новая покупка</b>\n\n"
            f"👤 Пользователь: @{user.username or user.first_name or 'Без имени'} "
            f"(ID: {user.telegram_id})\n"
            f"📦 Товар: {product.name}\n"
            f"📊 Количество: {order.quantity} шт.\n"
            f"💰 Сумма: {order.total_amount:.2f} ₽\n"
            f"💳 Способ оплаты: {order.payment_method or 'Не указан'}\n"
            f"📋 Остаток на складе: {product.stock_count} шт.\n"
            f"🆔 Заказ: #{order.id}\n"
        )
        await send_notification_to_chat(bot, text)
    except Exception as e:
        logger.error("Error in notify_admins_about_purchase: %s", e)


async def notify_user_registration(session: AsyncSession, user: User, bot) -> None:
    """Уведомить о регистрации нового пользователя."""
    try:
        text = (
            f"👤 <b>Новая регистрация</b>\n\n"
            f"👤 Пользователь: @{user.username or user.first_name or 'Без имени'} "
            f"(ID: {user.telegram_id})\n"
            f"📅 Дата: {user.created_at:%d.%m.%Y %H:%M}\n"
            f"🔗 Реферальный код: {user.referral_code or 'Нет'}\n"
        )

        if user.referred_by:
            stmt_ref = select(User).where(User.id == user.referred_by)
            result_ref = await session.execute(stmt_ref)
            referrer = result_ref.scalar_one_or_none()
            if referrer:
                text += (
                    f"👥 Приглашен пользователем: @{referrer.username or referrer.first_name or 'N/A'} "
                    f"(ID: {referrer.telegram_id})\n"
                )

        await send_notification_to_chat(bot, text)
    except Exception as e:
        logger.error("Error in notify_user_registration: %s", e)


async def notify_balance_topup(session: AsyncSession, user: User, amount: float, bot) -> None:
    """Уведомить о пополнении баланса."""
    try:
        text = (
            f"💰 <b>Пополнение баланса</b>\n\n"
            f"👤 Пользователь: @{user.username or user.first_name or 'Без имени'} "
            f"(ID: {user.telegram_id})\n"
            f"💵 Сумма: {amount:.2f} ₽\n"
            f"💳 Новый баланс: {user.balance:.2f} ₽\n"
        )
        await send_notification_to_chat(bot, text)
    except Exception as e:
        logger.error("Error in notify_balance_topup: %s", e)


async def notify_new_order(session: AsyncSession, order, bot) -> None:
    """Уведомить о создании нового заказа."""
    try:
        stmt_user = select(User).where(User.id == order.user_id)
        result_user = await session.execute(stmt_user)
        user = result_user.scalar_one_or_none()

        stmt_product = select(Product).where(Product.id == order.product_id)
        result_product = await session.execute(stmt_product)
        product = result_product.scalar_one_or_none()

        if not user or not product:
            return

        text = (
            f"📦 <b>Новый заказ</b>\n\n"
            f"👤 Пользователь: @{user.username or user.first_name or 'Без имени'} "
            f"(ID: {user.telegram_id})\n"
            f"📦 Товар: {product.name}\n"
            f"📊 Количество: {order.quantity} шт.\n"
            f"💰 Сумма: {order.total_amount:.2f} ₽\n"
            f"⏳ Статус: {order.status}\n"
            f"🆔 Заказ: #{order.id}\n"
        )
        await send_notification_to_chat(bot, text)
    except Exception as e:
        logger.error("Error in notify_new_order: %s", e)
