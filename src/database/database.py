"""Подключение к базе данных"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from src.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_size=20,
    max_overflow=10,
    pool_recycle=3600,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


async def init_db() -> None:
    """Инициализация базы данных — создание всех таблиц."""
    from src.database import models  # noqa: F401

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, checkfirst=True)
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error("Database initialization error: %s", e)
        raise


async def get_session() -> AsyncSession:
    """Получить сессию БД (для dependency injection)."""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
