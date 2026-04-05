from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove


def get_start_keyboard():
    """обычная клавиатура с кнопкой 'Старт' (единственное исключение из inline-правила)"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Старт")]],
        resize_keyboard=True
    )
    return keyboard


def get_phone_request_keyboard():
    """reply-клавиатура с кнопкой шера контакта при запросе телефона"""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

