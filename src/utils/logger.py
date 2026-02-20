"""Логирование"""
import logging
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = Path("/opt/dfc-mail/logs") if Path("/opt/dfc-mail").exists() else Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"bot_{datetime.now():%Y%m%d}.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger("dfc-mail")


async def log_error_to_db(
    session,
    level: str,
    message: str,
    user_id: int = None,
    traceback: str = None,
) -> None:
    """Записать ошибку в БД."""
    try:
        from src.database.models import Log

        log_entry = Log(level=level, message=message, user_id=user_id, traceback=traceback)
        session.add(log_entry)
        await session.commit()
    except Exception as e:
        logger.error("Failed to log to database: %s", e)
