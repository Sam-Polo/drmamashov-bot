from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import TARIFFS


def get_main_menu():
    """главное меню с разделами"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Подписаться", callback_data="subscription")],
        [InlineKeyboardButton(text="📖 О рассылке", callback_data="about_channel")],
        # [InlineKeyboardButton(text="🎁 Подарить подписку", callback_data="gift_select_tariff")],  # временно скрыто
        [InlineKeyboardButton(text="❓ Задать вопрос", url="https://t.me/nugaevahelps")],
    ])
    return keyboard


def get_about_channel_menu():
    """меню раздела 'О журнале'"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Реквизиты", callback_data="requisites")],
        [InlineKeyboardButton(text="📄 Оферта", url="https://docs.google.com/document/d/1-Q434Dv0oaDiJSbeu3gUUihBy-s4hVBwShW-TbEneUk/edit?usp=drivesdk")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")],
    ])
    return keyboard


def get_subscription_menu(has_active_subscription: bool):
    """меню раздела 'Подписка'"""
    buttons = []
    
    if has_active_subscription:
        buttons.append([InlineKeyboardButton(text="🔗 Получить ссылку", callback_data="get_channel_link")])
        buttons.append([InlineKeyboardButton(text="❌ Отписаться", callback_data="unsubscribe")])
    
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard


def get_tariffs_menu():
    """меню выбора тарифа"""
    buttons = []
    
    # только два тарифа: monthly и lifetime
    if 'monthly' in TARIFFS:
        buttons.append([
            InlineKeyboardButton(
                text=f"{TARIFFS['monthly']['name']} - {TARIFFS['monthly']['price']}₽",
                callback_data="tariff_monthly"
            )
        ])
    
    if 'lifetime' in TARIFFS:
        buttons.append([
            InlineKeyboardButton(
                text=f"{TARIFFS['lifetime']['name']} - {TARIFFS['lifetime']['price']}₽",
                callback_data="tariff_lifetime"
            )
    ])
    
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard


def get_back_to_main():
    """кнопка возврата в главное меню"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu")],
    ])
    return keyboard
