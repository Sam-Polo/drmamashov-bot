from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def get_start_keyboard():
    """обычная клавиатура с кнопкой 'Старт' (единственное исключение из inline-правила)"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Старт")]],
        resize_keyboard=True
    )
    return keyboard

