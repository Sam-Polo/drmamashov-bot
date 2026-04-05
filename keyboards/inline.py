from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import TARIFFS, SUPPORT_TELEGRAM_USERNAME, _fmt


def get_main_menu(has_active_subscription: bool = False):
    """главное меню с разделами; отписка — только при активной подписке"""
    rows = [
        [InlineKeyboardButton(text="💳 Подписаться", callback_data="subscription")],
        [InlineKeyboardButton(text="📖 О рассылке", callback_data="about_channel")],
    ]
    if has_active_subscription:
        rows.append([InlineKeyboardButton(text="❌ Отписаться", callback_data="unsubscribe")])
    rows.append([
        InlineKeyboardButton(
            text="❓ Задать вопрос",
            url=f"https://t.me/{SUPPORT_TELEGRAM_USERNAME}",
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
        buttons.append([InlineKeyboardButton(text="❌ Отписаться", callback_data="unsubscribe")])
    
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard


def get_tariffs_text() -> str:
    """HTML-текст над кнопками тарифов: зачёркнутая полная цена + экономия"""
    lines = ["<b>Выберите тариф:</b>\n"]
    for key, t in TARIFFS.items():
        orig = t.get("original_price")
        savings = t.get("savings")
        price_fmt = _fmt(t["price"])
        name = t["name"]
        if orig and savings:
            orig_fmt = _fmt(orig)
            save_fmt = _fmt(savings)
            lines.append(
                f"• <b>{_fmt(t['price'])} ₽</b> / {name} — "
                f"<s>{orig_fmt} ₽</s>  экономия {save_fmt} ₽"
            )
        else:
            lines.append(f"• <b>{price_fmt} ₽</b> / {name}")
    return "\n".join(lines)


def get_tariffs_menu():
    """кнопки выбора тарифа; текст для сообщения — get_tariffs_text()"""
    buttons = []

    for key, t in TARIFFS.items():
        price_fmt = _fmt(t["price"])
        name = t["name"]
        buttons.append([
            InlineKeyboardButton(
                text=f"{price_fmt} ₽ / {name}",
                callback_data=f"tariff_{key}",
            )
        ])

    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_back_to_main():
    """кнопка возврата в главное меню"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu")],
    ])
    return keyboard
