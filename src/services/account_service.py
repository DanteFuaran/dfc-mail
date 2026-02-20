"""Сервис выдачи аккаунтов"""
import csv
import io
import logging
from datetime import datetime
from io import BytesIO
from typing import List

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Account, Product

logger = logging.getLogger(__name__)


async def reserve_accounts(
    session: AsyncSession,
    product_id: int,
    quantity: int,
    order_id: int = None,
) -> List[Account]:
    """Резервирование аккаунтов с SELECT FOR UPDATE."""
    stmt = (
        select(Account)
        .where(Account.product_id == product_id, Account.is_sold == False)
        .limit(quantity)
        .with_for_update()
    )
    result = await session.execute(stmt)
    accounts = result.scalars().all()

    if len(accounts) < quantity:
        raise ValueError(
            f"Недостаточно товара на складе. Доступно: {len(accounts)}, требуется: {quantity}"
        )

    stmt_product = select(Product).where(Product.id == product_id).with_for_update()
    result_product = await session.execute(stmt_product)
    product = result_product.scalar_one_or_none()

    if not product:
        raise ValueError(f"Товар с ID {product_id} не найден")
    if product.stock_count < quantity:
        raise ValueError(
            f"Недостаточно товара на складе. Доступно: {product.stock_count}, требуется: {quantity}"
        )

    account_ids = [acc.id for acc in accounts]
    update_values = {"is_sold": True, "sold_at": datetime.now()}
    if order_id:
        update_values["order_id"] = order_id

    await session.execute(update(Account).where(Account.id.in_(account_ids)).values(**update_values))
    await session.execute(
        update(Product).where(Product.id == product_id).values(stock_count=Product.stock_count - quantity)
    )

    return accounts


async def get_accounts_for_order(session: AsyncSession, order_id: int) -> List[Account]:
    """Получить аккаунты для заказа."""
    stmt = select(Account).where(Account.order_id == order_id)
    result = await session.execute(stmt)
    return result.scalars().all()


async def create_accounts_file(accounts: List[Account]) -> BytesIO:
    """Создать текстовый файл с аккаунтами."""
    file_content = "\n".join([acc.account_data for acc in accounts])
    file_obj = BytesIO(file_content.encode("utf-8"))
    file_obj.name = f"accounts_{datetime.now():%Y%m%d_%H%M%S}.txt"
    return file_obj


async def upload_accounts_from_file(
    session: AsyncSession,
    product_id: int,
    file_content: str,
) -> tuple[int, int]:
    """Загрузить аккаунты из файла (TXT / CSV). Возвращает (загружено, дубликатов)."""
    text = file_content.strip()
    lines: list[str] = []

    try:
        if not text:
            return 0, 0
        sample = text[:1024]
        dialect = csv.Sniffer().sniff(sample, delimiters=";,|\t,")
        reader = csv.reader(io.StringIO(text), dialect)
        for row in reader:
            cols = [col.strip() for col in row if col and col.strip()]
            if not cols:
                continue
            lines.append(":".join(cols) if len(cols) > 1 else cols[0])
    except Exception:
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    stmt = select(Account.account_data).where(Account.product_id == product_id)
    result = await session.execute(stmt)
    existing_accounts = set(result.scalars().all())

    unique_accounts: set[str] = set()
    duplicates = 0
    loaded = 0

    for normalized in lines:
        if normalized in unique_accounts or normalized in existing_accounts:
            duplicates += 1
            continue
        unique_accounts.add(normalized)
        session.add(Account(product_id=product_id, account_data=normalized, is_sold=False))
        loaded += 1

    await session.execute(
        update(Product).where(Product.id == product_id).values(stock_count=Product.stock_count + loaded)
    )

    return loaded, duplicates
