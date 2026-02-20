"""Конфигурация DFC Mail Bot"""
from typing import List
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    """Настройки приложения"""

    # Telegram
    BOT_TOKEN: str
    BOT_NAME: str = ""

    # Database (PostgreSQL, async)
    DATABASE_HOST: str = "dfc-mail-db"
    DATABASE_PORT: int = 5432
    DATABASE_NAME: str = "dfc-mail"
    DATABASE_USER: str = "dfc-mail"
    DATABASE_PASSWORD: str = ""

    # Admins
    ADMIN_IDS: str = ""
    DEVELOPER_IDS: str = ""

    # Payment Systems
    YOOKASSA_SHOP_ID: str = ""
    YOOKASSA_SECRET_KEY: str = ""
    ROBOKASSA_MERCHANT_LOGIN: str = ""
    ROBOKASSA_PASSWORD_1: str = ""
    ROBOKASSA_PASSWORD_2: str = ""
    LAVA_PROJECT_ID: str = ""
    LAVA_SECRET_KEY: str = ""
    HELEKET_API_KEY: str = ""

    # Support
    SUPPORT_CHAT: str = ""
    NOTIFICATIONS_CHAT_ID: str = ""

    # Webhook
    WEBHOOK_URL: str = ""
    WEBHOOK_PORT: int = 8443
    WEBHOOK_SSL_CERT_PATH: str = ""
    WEBHOOK_SSL_KEY_PATH: str = ""
    WEBHOOK_USE_HTTPS: bool = False

    # Settings
    REFERRAL_COMMISSION: int = 10
    ORDER_RESERVATION_MINUTES: int = 15
    BROADCAST_THROTTLE: int = 25
    ENABLE_TEST_PAYMENT: bool = False

    @property
    def DATABASE_URL(self) -> str:
        """Async PostgreSQL URL"""
        return (
            f"postgresql+asyncpg://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
        )

    @property
    def admin_ids_list(self) -> List[int]:
        if not self.ADMIN_IDS:
            return []
        return [int(uid.strip()) for uid in self.ADMIN_IDS.split(",") if uid.strip().isdigit()]

    @property
    def developer_ids_list(self) -> List[int]:
        if not self.DEVELOPER_IDS:
            return []
        return [int(uid.strip()) for uid in self.DEVELOPER_IDS.split(",") if uid.strip().isdigit()]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


settings = Settings()
