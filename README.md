# drmamashov-bot

Телеграм-бот для продажи подписки на закрытый канал: оплата и рекуррент через **Prodamus**, выдача доступа в канал, ручные админ-операции. Отдельно — **рассылка «недель»** из публичного Google Doc (текст по графику от момента активации подписки). Есть HTTP-приём webhook Prodamus (отдельный процесс в docker-compose).

## Стек

- **Python 3**, **aiogram 3**, SQLite (**aiosqlite**)
- **aiohttp** — Google Doc export, запросы к Prodamus
- **python-dotenv** — конфиг из `.env` в корне проекта
- **Docker / docker-compose** — типовой запуск (бот + webhook), том под БД

## Переменные окружения

См. полный перечень и плейсхолдеры в **`.env.example`**. Кратко по смыслу:

| Группа | Переменные |
|--------|------------|
| **Telegram** | `BOT_TOKEN`, `BOT_USERNAME`, `ADMIN_IDS`, `CHANNEL_ID`, `CHANNEL_INVITE_LINK`, `SUPPORT_TELEGRAM_USERNAME` |
| **БД** | `DATABASE_PATH` (в контейнере обычно `/app/data/bot.db`) |
| **Prodamus** | `PRODAMUS_API_KEY`, `PRODAMUS_SYS`, `PRODAMUS_WEBHOOK_SECRET`, `PRODAMUS_WEBHOOK_URL`, `PRODAMUS_PAYFORM_URL`, `PRODAMUS_PRODUCT_ID_MONTHLY`, `PRODAMUS_PRODUCT_ID_LIFETIME` |
| **Webhook-сервис** | `WEBHOOK_PORT` |
| **Версия / логи** | `APP_VERSION` |
| **Рассылка** | `NEWSLETTER_ENABLED`, `NEWSLETTER_GOOGLE_DOC_ID`, `NEWSLETTER_FIRST_SEND_DELAY_MINUTES`, `NEWSLETTER_WEEK_SPACING_DAYS`, `NEWSLETTER_CHECK_INTERVAL_SEC`, `NEWSLETTER_INCLUDE_TRIAL`, опционально `NEWSLETTER_TEST_*` для админ-теста |