"""FSM-состояния бота"""
from aiogram.fsm.state import State, StatesGroup


class OrderStates(StatesGroup):
    waiting_quantity = State()


class TopupStates(StatesGroup):
    waiting_amount = State()
    waiting_method = State()


class SupportStates(StatesGroup):
    waiting_message = State()
    waiting_reply = State()


class BroadcastStates(StatesGroup):
    waiting_message = State()
    waiting_user_id = State()
    waiting_individual_message = State()


class AdminStates(StatesGroup):
    # Категории
    waiting_category_name = State()
    # Товары — добавление
    waiting_product_name = State()
    waiting_product_price = State()
    waiting_product_description = State()
    waiting_product_format = State()
    waiting_product_recommendations = State()
    waiting_product_category = State()
    # Товары — редактирование
    waiting_edit_product_search = State()
    waiting_edit_product_id = State()
    waiting_edit_product_value = State()
    # Товары — удаление
    waiting_delete_product_name = State()
    # Аккаунты
    waiting_upload_file = State()
    waiting_add_account = State()
    waiting_import_accounts_file = State()
    # Заказы
    waiting_order_id = State()
    waiting_order_date_from = State()
    waiting_order_date_to = State()
    # Пользователи
    waiting_user_id = State()
    waiting_balance_amount = State()
    waiting_bulk_block_users = State()
    # Настройки
    waiting_setting_edit_value = State()
