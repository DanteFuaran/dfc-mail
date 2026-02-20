"""Модели базы данных"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from src.database.database import Base


class User(Base):
    """Пользователь"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    balance = Column(Float, default=0.0, nullable=False)
    is_blocked = Column(Boolean, default=False, nullable=False)
    referral_code = Column(String(50), unique=True, nullable=True, index=True)
    referred_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    role = Column(String(50), default="user", nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    orders = relationship("Order", back_populates="user")
    referrals = relationship("User", remote_side=[id], backref="referrer")


class Category(Base):
    """Категория товаров"""

    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)

    products = relationship("Product", back_populates="category")


class Product(Base):
    """Товар"""

    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    stock_count = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    format_info = Column(Text, nullable=True)
    recommendations = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    category = relationship("Category", back_populates="products")
    accounts = relationship("Account", back_populates="product")
    orders = relationship("Order", back_populates="product")
    notifications = relationship("StockNotification", back_populates="product")

    __table_args__ = (
        CheckConstraint("price >= 0", name="check_price_positive"),
        CheckConstraint("stock_count >= 0", name="check_stock_positive"),
    )


class Account(Base):
    """Аккаунт (склад)"""

    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    account_data = Column(Text, nullable=False)
    is_sold = Column(Boolean, default=False, nullable=False)
    sold_at = Column(DateTime, nullable=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    is_blocked = Column(Boolean, default=False, nullable=False)
    blocked_at = Column(DateTime, nullable=True)
    blocked_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)

    product = relationship("Product", back_populates="accounts")
    order = relationship("Order", back_populates="accounts")

    __table_args__ = (Index("idx_product_sold", "product_id", "is_sold"),)


class Order(Base):
    """Заказ"""

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    price_per_unit = Column(Float, nullable=False)
    discount = Column(Float, default=0.0, nullable=False)
    total_amount = Column(Float, nullable=False)
    status = Column(String(50), default="ОЖИДАЕТ ОПЛАТЫ", nullable=False)
    payment_method = Column(String(50), nullable=True)
    payment_id = Column(String(255), nullable=True)
    reserved_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    paid_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="orders")
    product = relationship("Product", back_populates="orders")
    accounts = relationship("Account", back_populates="order")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="check_quantity_positive"),
        CheckConstraint("total_amount >= 0", name="check_amount_positive"),
        Index("idx_user_status", "user_id", "status"),
        Index("idx_status", "status"),
    )


class StockNotification(Base):
    """Подписка на уведомление о поступлении товара"""

    __tablename__ = "stock_notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    is_notified = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)

    product = relationship("Product", back_populates="notifications")

    __table_args__ = (Index("idx_user_product", "user_id", "product_id"),)


class Payment(Base):
    """Платеж"""

    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, nullable=False)
    payment_method = Column(String(50), nullable=False)
    payment_id = Column(String(255), nullable=True)
    status = Column(String(50), default="PENDING", nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("amount > 0", name="check_payment_amount_positive"),
        Index("idx_payment_user_status", "user_id", "status"),
    )


class ReferralTransaction(Base):
    """Реферальная транзакция"""

    __tablename__ = "referral_transactions"

    id = Column(Integer, primary_key=True)
    referrer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    referred_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    amount = Column(Float, nullable=False)
    commission = Column(Float, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)


class Log(Base):
    """Лог ошибок"""

    __tablename__ = "logs"

    id = Column(Integer, primary_key=True)
    level = Column(String(20), nullable=False)
    message = Column(Text, nullable=False)
    user_id = Column(Integer, nullable=True)
    traceback = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)

    __table_args__ = (Index("idx_level_created", "level", "created_at"),)


class Setting(Base):
    """Настройки бота (тексты, контакты)"""

    __tablename__ = "settings"

    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)


class Refund(Base):
    """Возврат средств"""

    __tablename__ = "refunds"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, nullable=False)
    reason = Column(Text, nullable=True)
    status = Column(String(50), default="PENDING", nullable=False)
    processed_at = Column(DateTime, nullable=True)
    processed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("amount > 0", name="check_refund_amount_positive"),
        Index("idx_refund_status", "status"),
    )


class Promotion(Base):
    """Промоакции"""

    __tablename__ = "promotions"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    discount_type = Column(String(50), nullable=False)
    discount_value = Column(Float, nullable=False)
    min_quantity = Column(Integer, default=1, nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)

    __table_args__ = (CheckConstraint("discount_value > 0", name="check_discount_positive"),)


class Coupon(Base):
    """Промокоды"""

    __tablename__ = "coupons"

    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    discount_type = Column(String(50), nullable=False)
    discount_value = Column(Float, nullable=False)
    max_uses = Column(Integer, nullable=True)
    used_count = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    valid_from = Column(DateTime, nullable=False)
    valid_until = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)

    __table_args__ = (CheckConstraint("discount_value > 0", name="check_coupon_discount_positive"),)


class AuditLog(Base):
    """Журнал аудита"""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(String(100), nullable=False)
    entity_type = Column(String(50), nullable=True)
    entity_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_audit_user_created", "user_id", "created_at"),
        Index("idx_audit_action", "action"),
    )
