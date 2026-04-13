import os
from pathlib import Path
from dotenv import load_dotenv

# загружаем .env строго из корня проекта, независимо от cwd процесса
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# приветственное фото для /start (лежит в media/, в Docker монтируется том ./media)
WELCOME_PHOTO_PATH = BASE_DIR / "media" / "photo_2026-02-13_11-31-01.jpg"

# токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")  # username бота (без @)
# аккаунт техподдержки (кнопка «задать вопрос», текст раздела), без @
SUPPORT_TELEGRAM_USERNAME = (
    os.getenv("SUPPORT_TELEGRAM_USERNAME", "mbuhtojarova").strip().lstrip("@")
)

# id администраторов (для админ-команд, через запятую)
ADMIN_IDS = [int(admin_id.strip()) for admin_id in os.getenv("ADMIN_IDS", "0").split(",") if admin_id.strip()]

# id или username канала (для выдачи ссылок)
# можно указать числовой ID (например -1001234567890) или username (@channel_name)
CHANNEL_ID = os.getenv("CHANNEL_ID", "")

# ссылка-приглашение на канал (для отправки пользователям)
CHANNEL_INVITE_LINK = os.getenv("CHANNEL_INVITE_LINK", "")

# путь к БД
# в Docker используем /app/data/bot.db, локально - bot.db
DATABASE_PATH = os.getenv("DATABASE_PATH", "bot.db")

# базовая цена 1 месяца для расчёта экономии
_MONTHLY_PRICE = 990

def _fmt(n: int) -> str:
    """форматирует число с пробелом как разделителем тысяч: 1990 → '1 990'"""
    return f"{n:,}".replace(",", "\u00a0")  # неразрывный пробел для читаемости

# тарифы (в рублях)
TARIFFS = {
    "monthly": {
        "price": _MONTHLY_PRICE,
        "duration_days": 30,
        "name": "1 месяц",
        "original_price": None,   # нет зачёркнутой цены
        "savings": None,
    },
    "quarterly": {
        "price": 1990,
        "duration_days": 90,
        "name": "3 месяца",
        "original_price": _MONTHLY_PRICE * 3,   # 2 970
        "savings": _MONTHLY_PRICE * 3 - 1990,   # 980
    },
    "half_year": {
        "price": 3990,
        "duration_days": 180,
        "name": "6 месяцев",
        "original_price": _MONTHLY_PRICE * 6,   # 5 940
        "savings": _MONTHLY_PRICE * 6 - 3990,   # 1 950
    },
    "annual": {
        "price": 4990,
        "duration_days": 365,
        "name": "12 месяцев",
        "original_price": _MONTHLY_PRICE * 12,  # 11 880
        "savings": _MONTHLY_PRICE * 12 - 4990,  # 6 890
    },
    "lifetime": {
        "price": 9990,
        "duration_days": None,  # бессрочно (end_date = NULL)
        "name": "Навсегда",
        "original_price": None,
        "savings": None,
    },
}

# функции, временно отключенные
GIFTS_ENABLED = False  # подарки подписки
PROMOCODES_ENABLED = False  # промокоды

# настройки Prodamus
PRODAMUS_API_KEY = os.getenv("PRODAMUS_API_KEY", "")
PRODAMUS_SYS = os.getenv("PRODAMUS_SYS", "")
PRODAMUS_WEBHOOK_SECRET = os.getenv("PRODAMUS_WEBHOOK_SECRET", "")
PRODAMUS_WEBHOOK_URL = os.getenv("PRODAMUS_WEBHOOK_URL", "")  # URL для webhook (нужно будет указать после деплоя)
PRODAMUS_PAYFORM_URL = os.getenv("PRODAMUS_PAYFORM_URL", "https://nugaeva.payform.ru/")  # URL платежной формы (по документации: https://название_поддомена.payform.ru/)

# Product ID для каждого тарифа (получить после создания подписок в ЛК Prodamus)
PRODAMUS_PRODUCT_ID_MONTHLY = os.getenv("PRODAMUS_PRODUCT_ID_MONTHLY", "")
PRODAMUS_PRODUCT_ID_QUARTERLY = os.getenv("PRODAMUS_PRODUCT_ID_QUARTERLY", "")
PRODAMUS_PRODUCT_ID_HALF_YEAR = os.getenv("PRODAMUS_PRODUCT_ID_HALF_YEAR", "")
PRODAMUS_PRODUCT_ID_ANNUAL = os.getenv("PRODAMUS_PRODUCT_ID_ANNUAL", "")
PRODAMUS_PRODUCT_ID_LIFETIME = os.getenv("PRODAMUS_PRODUCT_ID_LIFETIME", "")

# версия для логов (на сервере можно задать тег/хеш деплоя)
APP_VERSION = os.getenv("APP_VERSION", "dev")

# рассылка «недель» из Google Doc (export txt, документ «доступен всем по ссылке»)
NEWSLETTER_ENABLED = os.getenv("NEWSLETTER_ENABLED", "1").strip().lower() in ("1", "true", "yes")
NEWSLETTER_GOOGLE_DOC_ID = os.getenv("NEWSLETTER_GOOGLE_DOC_ID", "").strip()
# первая рассылка (неделя 1) не раньше чем через N минут после активации подписки (webhook / create_subscription)
NEWSLETTER_FIRST_SEND_DELAY_MINUTES = int(os.getenv("NEWSLETTER_FIRST_SEND_DELAY_MINUTES", "0"))
# интервал между «неделями» рассылки (календарные дни от якоря)
NEWSLETTER_WEEK_SPACING_DAYS = int(os.getenv("NEWSLETTER_WEEK_SPACING_DAYS", "7"))
# как часто проверять очередь рассылки (сек)
NEWSLETTER_CHECK_INTERVAL_SEC = int(os.getenv("NEWSLETTER_CHECK_INTERVAL_SEC", "60"))
NEWSLETTER_INCLUDE_TRIAL = os.getenv("NEWSLETTER_INCLUDE_TRIAL", "0").strip().lower() in ("1", "true", "yes")


def newsletter_recipient_tariff_types() -> tuple:
    """тарифы в subscriptions, при которых пользователь в очереди рассылки (все из TARIFFS + lifetime; trial опционально)"""
    types = set(TARIFFS.keys())
    types.add("lifetime")
    if NEWSLETTER_INCLUDE_TRIAL:
        types.add("trial")
    return tuple(sorted(types))


# админ-команда /newsletter_test: сжатая имитация задержек продакшна (сек)
NEWSLETTER_TEST_FIRST_DELAY_SEC = float(os.getenv("NEWSLETTER_TEST_FIRST_DELAY_SEC", "2"))
NEWSLETTER_TEST_BETWEEN_WEEKS_SEC = float(os.getenv("NEWSLETTER_TEST_BETWEEN_WEEKS_SEC", "5"))
