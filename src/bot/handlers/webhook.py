"""HTTP-webhook для платёжных систем (YooKassa / Heleket)."""
import logging
from datetime import datetime

from aiohttp import web
from sqlalchemy import select

from src.database.database import async_session_maker
from src.database.models import Order, Payment, User
from src.services.payment import PaymentService

logger = logging.getLogger(__name__)


async def yookassa_webhook(request: web.Request) -> web.Response:
    """Обработка webhook от ЮKassa."""
    try:
        data = await request.json()
        event_type = data.get("event", "")
        payment_obj = data.get("object", {})
        payment_id = payment_obj.get("id")
        status = payment_obj.get("status")
        metadata = payment_obj.get("metadata", {})

        if event_type != "payment.succeeded" or status != "succeeded":
            return web.Response(status=200, text="OK")

        order_id = metadata.get("order_id")
        user_id = metadata.get("user_id")

        if not payment_id:
            return web.Response(status=200, text="OK")

        async with async_session_maker() as session:
            # Ищем платёж
            stmt_pay = select(Payment).where(Payment.payment_id == payment_id)
            payment = (await session.execute(stmt_pay)).scalar_one_or_none()
            if payment:
                payment.status = "COMPLETED"
                payment.completed_at = datetime.now()

            if order_id:
                order = (await session.execute(
                    select(Order).where(Order.id == int(order_id))
                )).scalar_one_or_none()
                if order and order.status == "ОЖИДАЕТ ОПЛАТЫ":
                    order.status = "ВЫПОЛНЕНО"
                    order.payment_method = "yookassa"
                    order.paid_at = datetime.now()
                    order.completed_at = datetime.now()
            elif user_id:
                # Пополнение баланса
                amount = float(payment_obj.get("amount", {}).get("value", 0))
                if amount > 0:
                    user = (await session.execute(
                        select(User).where(User.telegram_id == int(user_id))
                    )).scalar_one_or_none()
                    if user:
                        user.balance += amount

            await session.commit()

        return web.Response(status=200, text="OK")
    except Exception as e:
        logger.error("YooKassa webhook error: %s", e, exc_info=True)
        return web.Response(status=500, text="Error")


async def heleket_webhook(request: web.Request) -> web.Response:
    """Обработка webhook от Heleket."""
    try:
        data = await request.json()
        payment_id = data.get("payment_id")
        status = data.get("status")
        order_id = data.get("order_id")
        user_id = data.get("user_id")

        if status != "completed" or not payment_id:
            return web.Response(status=200, text="OK")

        async with async_session_maker() as session:
            stmt_pay = select(Payment).where(Payment.payment_id == payment_id)
            payment = (await session.execute(stmt_pay)).scalar_one_or_none()
            if payment:
                payment.status = "COMPLETED"
                payment.completed_at = datetime.now()

            if order_id and str(order_id) != "0":
                order = (await session.execute(
                    select(Order).where(Order.id == int(order_id))
                )).scalar_one_or_none()
                if order and order.status == "ОЖИДАЕТ ОПЛАТЫ":
                    order.status = "ВЫПОЛНЕНО"
                    order.payment_method = "heleket"
                    order.paid_at = datetime.now()
                    order.completed_at = datetime.now()
            elif user_id:
                amount = float(data.get("amount", 0))
                if amount > 0:
                    user = (await session.execute(
                        select(User).where(User.telegram_id == int(user_id))
                    )).scalar_one_or_none()
                    if user:
                        user.balance += amount

            await session.commit()

        return web.Response(status=200, text="OK")
    except Exception as e:
        logger.error("Heleket webhook error: %s", e, exc_info=True)
        return web.Response(status=500, text="Error")


def setup_webhook_routes(app: web.Application) -> None:
    """Регистрация маршрутов webhook."""
    app.router.add_post("/webhook/yookassa", yookassa_webhook)
    app.router.add_post("/webhook/heleket", heleket_webhook)
