"""Inline-клавиатуры бота — единый интерактивный интерфейс"""
from typing import List, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.config import settings

# ═══════════════════════════════════════════════
# УТИЛИТЫ
# ═══════════════════════════════════════════════

_back = lambda cb="menu:main": InlineKeyboardButton(text="◀️ Назад", callback_data=cb)
_menu = lambda: InlineKeyboardButton(text="🏠 Меню", callback_data="menu:main")


def _row(*buttons: InlineKeyboardButton) -> list:
    return list(buttons)


# ═══════════════════════════════════════════════
# ГЛАВНОЕ МЕНЮ
# ═══════════════════════════════════════════════

def main_menu_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📂 Каталог", callback_data="menu:catalog")],
        [
            InlineKeyboardButton(text="💰 Баланс", callback_data="menu:balance"),
            InlineKeyboardButton(text="📦 Заказы", callback_data="menu:orders"),
        ],
        [
            InlineKeyboardButton(text="👥 Рефералы", callback_data="menu:referral"),
            InlineKeyboardButton(text="ℹ️ Информация", callback_data="menu:info"),
        ],
        [
            InlineKeyboardButton(text="💬 Поддержка", callback_data="menu:support"),
            InlineKeyboardButton(text="📜 Правила", callback_data="menu:rules"),
        ],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="⚙️ Панель управления", callback_data="menu:admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ═══════════════════════════════════════════════
# КАТАЛОГ
# ═══════════════════════════════════════════════

def categories_kb(categories: List) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=cat.name, callback_data=f"cat:{cat.id}")]
        for cat in categories
    ]
    rows.append([_back()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def products_kb(products: List, category_id: int) -> InlineKeyboardMarkup:
    rows = []
    for p in products:
        stock = f"✅ {p.stock_count}" if p.stock_count > 0 else "❌"
        rows.append([InlineKeyboardButton(
            text=f"{p.name} — {p.price:.2f}₽ {stock}",
            callback_data=f"prod:{p.id}",
        )])
    rows.append([_back("menu:catalog")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_detail_kb(product_id: int, has_stock: bool, category_id: int) -> InlineKeyboardMarkup:
    rows = []
    if has_stock:
        rows.append([InlineKeyboardButton(text="💳 Купить", callback_data=f"buy:{product_id}")])
    else:
        rows.append([InlineKeyboardButton(
            text="🔔 Уведомить о поступлении", callback_data=f"notify:{product_id}",
        )])
    rows.append([
        _back(f"cat:{category_id}"),
        _menu(),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quantity_cancel_kb(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"prod:{product_id}")],
    ])


# ═══════════════════════════════════════════════
# ОПЛАТА
# ═══════════════════════════════════════════════

def payment_methods_kb(order_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="💳 С баланса", callback_data=f"pay:balance:{order_id}")],
    ]
    if settings.YOOKASSA_SHOP_ID and settings.YOOKASSA_SECRET_KEY:
        rows.append([InlineKeyboardButton(text="💳 ЮКасса", callback_data=f"pay:yookassa:{order_id}")])
    if settings.ROBOKASSA_MERCHANT_LOGIN and settings.ROBOKASSA_PASSWORD_1:
        rows.append([InlineKeyboardButton(text="💳 Robokassa", callback_data=f"pay:robokassa:{order_id}")])
    if settings.LAVA_PROJECT_ID and settings.LAVA_SECRET_KEY:
        rows.append([InlineKeyboardButton(text="💳 Lava", callback_data=f"pay:lava:{order_id}")])
    if settings.HELEKET_API_KEY:
        rows.append([InlineKeyboardButton(text="💳 Heleket", callback_data=f"pay:heleket:{order_id}")])
    rows.append([InlineKeyboardButton(text="⭐ Telegram Stars", callback_data=f"pay:stars:{order_id}")])
    if settings.ENABLE_TEST_PAYMENT:
        rows.append([InlineKeyboardButton(text="🧪 Тестовая", callback_data=f"pay:test:{order_id}")])
    rows.append([InlineKeyboardButton(text="❌ Отменить заказ", callback_data=f"cancel:{order_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ═══════════════════════════════════════════════
# ЗАКАЗЫ
# ═══════════════════════════════════════════════

def orders_kb(orders: List) -> InlineKeyboardMarkup:
    emoji_map = {"ОЖИДАЕТ ОПЛАТЫ": "⏳", "ОПЛАЧЕНО": "✅", "ВЫПОЛНЕНО": "✔️", "ОТМЕНЕНО": "❌"}
    rows = [
        [InlineKeyboardButton(
            text=f"{emoji_map.get(o.status, '❓')} #{o.id} — {o.total_amount:.2f}₽",
            callback_data=f"order:{o.id}",
        )]
        for o in orders
    ]
    rows.append([_back()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_detail_kb(order_id: int, status: str) -> InlineKeyboardMarkup:
    rows = []
    if status == "ОЖИДАЕТ ОПЛАТЫ":
        rows.append([InlineKeyboardButton(text="💳 Оплатить", callback_data=f"pay_order:{order_id}")])
        rows.append([InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel:{order_id}")])
    elif status == "ВЫПОЛНЕНО":
        rows.append([InlineKeyboardButton(text="📥 Скачать", callback_data=f"download:{order_id}")])
    rows.append([_back("menu:orders")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ═══════════════════════════════════════════════
# БАЛАНС
# ═══════════════════════════════════════════════

def balance_topup_kb() -> InlineKeyboardMarkup:
    rows = []
    if settings.YOOKASSA_SHOP_ID and settings.YOOKASSA_SECRET_KEY:
        rows.append([InlineKeyboardButton(text="💳 ЮКасса", callback_data="topup:yookassa")])
    if settings.HELEKET_API_KEY:
        rows.append([InlineKeyboardButton(text="💳 Heleket", callback_data="topup:heleket")])
    if not rows:
        rows.append([InlineKeyboardButton(text="ℹ️ Через администратора", callback_data="topup:admin")])
    rows.append([_back()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def topup_amount_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu:balance")],
    ])


# ═══════════════════════════════════════════════
# РЕФЕРАЛЫ
# ═══════════════════════════════════════════════

def referral_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_back()],
    ])


# ═══════════════════════════════════════════════
# ПОДДЕРЖКА
# ═══════════════════════════════════════════════

def support_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Написать", callback_data="support:write")],
        [_back()],
    ])


def support_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu:support")],
    ])


def support_reply_kb(user_telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Ответить", callback_data=f"support:reply:{user_telegram_id}")],
    ])


# ═══════════════════════════════════════════════
# ИНФОРМАЦИЯ
# ═══════════════════════════════════════════════

def info_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_back()]])


def rules_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_back()]])


# ═══════════════════════════════════════════════
# АДМИН-ПАНЕЛЬ
# ═══════════════════════════════════════════════

def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Заказы", callback_data="adm:orders")],
        [InlineKeyboardButton(text="📂 Каталог", callback_data="adm:catalog")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="adm:users")],
        [InlineKeyboardButton(text="💰 Пополнить свой баланс", callback_data="adm:topup_self")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats")],
        [InlineKeyboardButton(text="📝 Логи ошибок", callback_data="adm:logs")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="adm:broadcast")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="adm:settings")],
        [_back()],
    ])


def admin_orders_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Все заказы", callback_data="adm:orders:all")],
        [InlineKeyboardButton(text="🔍 Поиск по ID", callback_data="adm:orders:search")],
        [InlineKeyboardButton(text="📅 По дате", callback_data="adm:orders:date")],
        [InlineKeyboardButton(text="📊 По статусу", callback_data="adm:orders:status")],
        [InlineKeyboardButton(text="👤 По пользователю", callback_data="adm:orders:user")],
        [_back("menu:admin")],
    ])


def admin_catalog_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить категорию", callback_data="adm:cat:add")],
        [InlineKeyboardButton(text="🗑️ Удалить категорию", callback_data="adm:cat:del")],
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="adm:prod:add")],
        [InlineKeyboardButton(text="✏️ Редактировать товар", callback_data="adm:prod:edit")],
        [InlineKeyboardButton(text="🗑️ Удалить товар", callback_data="adm:prod:del")],
        [InlineKeyboardButton(text="📦 Управление аккаунтами", callback_data="adm:accounts")],
        [_back("menu:admin")],
    ])


def admin_users_kb(users: List, page: int = 0, per_page: int = 10) -> InlineKeyboardMarkup:
    start = page * per_page
    end = start + per_page
    page_users = users[start:end]

    rows = [
        [InlineKeyboardButton(
            text=f"{'🔒 ' if u.is_blocked else ''}{u.first_name or 'N/A'} (@{u.username or 'N/A'}) — {u.role}",
            callback_data=f"adm:user:{u.telegram_id}",
        )]
        for u in page_users
    ]

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm:users:p{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{max(1, (len(users) + per_page - 1) // per_page)}", callback_data="noop"))
    if end < len(users):
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm:users:p{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append([
        InlineKeyboardButton(text="🔍 Поиск", callback_data="adm:users:search"),
        InlineKeyboardButton(text="🔒 Масс. блок", callback_data="adm:users:bulk_block"),
    ])
    rows.append([_back("menu:admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_user_detail_kb(user, is_developer: bool = False) -> InlineKeyboardMarkup:
    block_text = "🔓 Разблокировать" if user.is_blocked else "🔒 Заблокировать"
    rows = [
        [InlineKeyboardButton(text=block_text, callback_data=f"adm:user:block:{user.id}")],
        [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data=f"adm:user:balance:{user.id}")],
    ]
    if is_developer:
        rows.append([InlineKeyboardButton(text="👑 Роль", callback_data=f"adm:user:role:{user.id}")])
    rows.append([_back("adm:users")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data="adm:set:edit")],
        [InlineKeyboardButton(text="📋 Список настроек", callback_data="adm:set:list")],
        [_back("menu:admin")],
    ])


def admin_settings_keys_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Приветствие", callback_data="adm:set:key:welcome_text")],
        [InlineKeyboardButton(text="Контакт поддержки", callback_data="adm:set:key:support_chat")],
        [InlineKeyboardButton(text="FAQ", callback_data="adm:set:key:faq_text")],
        [InlineKeyboardButton(text="Правила", callback_data="adm:set:key:rules_text")],
        [_back("adm:settings")],
    ])


def admin_broadcast_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Массовая", callback_data="adm:bcast:mass")],
        [InlineKeyboardButton(text="👤 Индивидуальная", callback_data="adm:bcast:individual")],
        [_back("menu:admin")],
    ])


def admin_order_status_filter_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Ожидает оплаты", callback_data="adm:orders:fs:ОЖИДАЕТ ОПЛАТЫ")],
        [InlineKeyboardButton(text="✅ Оплачено", callback_data="adm:orders:fs:ОПЛАЧЕНО")],
        [InlineKeyboardButton(text="✔️ Выполнено", callback_data="adm:orders:fs:ВЫПОЛНЕНО")],
        [InlineKeyboardButton(text="❌ Отменено", callback_data="adm:orders:fs:ОТМЕНЕНО")],
        [_back("adm:orders")],
    ])


def admin_accounts_menu_kb(products: List) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"{p.name} ({p.stock_count} шт.)",
            callback_data=f"adm:acc:prod:{p.id}",
        )]
        for p in products
    ]
    rows.append([_back("adm:catalog")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_account_actions_kb(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить один", callback_data=f"adm:acc:add:{product_id}")],
        [InlineKeyboardButton(text="📥 Импорт файлом", callback_data=f"adm:acc:import:{product_id}")],
        [InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"adm:acc:delete:{product_id}")],
        [_back("adm:accounts")],
    ])


def admin_role_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 User", callback_data=f"adm:setrole:{user_id}:user")],
        [InlineKeyboardButton(text="🛡️ Admin", callback_data=f"adm:setrole:{user_id}:admin")],
        [InlineKeyboardButton(text="👑 Developer", callback_data=f"adm:setrole:{user_id}:developer")],
        [_back(f"adm:user:{user_id}")],
    ])


def back_admin_kb(target: str = "menu:admin") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_back(target)]])


def cancel_input_kb(target: str = "menu:admin") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=target)],
    ])


def confirm_kb(action: str, item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data=f"confirm:{action}:{item_id}"),
            InlineKeyboardButton(text="❌ Нет", callback_data=f"reject:{action}:{item_id}"),
        ],
    ])


def noop_kb() -> InlineKeyboardMarkup:
    """Пустая клавиатура с кнопкой назад"""
    return InlineKeyboardMarkup(inline_keyboard=[[_back()]])
