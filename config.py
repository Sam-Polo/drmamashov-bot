import os
from pathlib import Path
from dotenv import load_dotenv

# загружаем .env строго из корня проекта, независимо от cwd процесса
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")  # username бота (без @)

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

# тарифы (в рублях)
TARIFFS = {
    "monthly": {"price": 990, "duration_days": 30, "name": "1 месяц"},
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
PRODAMUS_PRODUCT_ID_LIFETIME = os.getenv("PRODAMUS_PRODUCT_ID_LIFETIME", "")
