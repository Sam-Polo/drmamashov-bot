import asyncio
import logging
from datetime import datetime
import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN, DATABASE_PATH, CHANNEL_ID
from database.models import Database
from prodamus.webhook import ProdamusWebhookHandler
from handlers import common, admin, payment, channel

# настройка логирования с форматированием
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


async def check_trial_subscriptions_notifications(bot: Bot, db: Database):
    """ежедневная проверка trial подписок, истекающих завтра (для уведомлений)"""
    while True:
        try:
            # ждем 24 часа
            await asyncio.sleep(24 * 60 * 60)  # 24 часа в секундах
            
            logger.info("🔔 Проверка trial подписок, истекающих завтра...")
            expiring_tomorrow = await db.get_trial_subscriptions_expiring_tomorrow()
            
            if not expiring_tomorrow:
                logger.info("✅ Trial подписок, истекающих завтра, не найдено")
                continue
            
            logger.info(f"📢 Найдено {len(expiring_tomorrow)} trial подписок, истекающих завтра")
            
            for subscription in expiring_tomorrow:
                user_id = subscription["user_id"]
                logger.info(f"📢 Отправка уведомления пользователю {user_id} о скором окончании trial")
                
                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text="⏰ Ваш бесплатный период заканчивается завтра!\n\n"
                             "Чтобы продолжить пользоваться каналом, необходимо подключить подписку.\n\n"
                             "Перейдите в главное меню → раздел 'Подписка' для оформления подписки."
                    )
                    logger.info(f"✅ Уведомление отправлено пользователю {user_id}")
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления пользователю {user_id}: {e}", exc_info=True)
            
            logger.info(f"✅ Проверка уведомлений завершена, обработано {len(expiring_tomorrow)} подписок")
            
        except Exception as e:
            logger.error(f"Ошибка при проверке уведомлений trial подписок: {e}", exc_info=True)
            # при ошибке ждем час перед следующей попыткой
            await asyncio.sleep(3600)


async def check_expired_subscriptions(bot: Bot, db: Database):
    """периодическая проверка истекших подписок (раз в день)"""
    while True:
        try:
            # ждем 24 часа (проверяем каждый день)
            await asyncio.sleep(24 * 60 * 60)  # 24 часа в секундах
            
            logger.info("🔍 Начинаю проверку истекших подписок...")
            
            # сначала обрабатываем истекшие trial подписки
            expired_trials = await db.get_expired_trial_subscriptions()
            if expired_trials:
                logger.info(f"⏰ Найдено {len(expired_trials)} истекших trial подписок")
                
                for subscription in expired_trials:
                    user_id = subscription["user_id"]
                    logger.info(f"⏰ Обработка истекшей trial подписки для user_id={user_id}")
                    
                    # деактивируем подписку
                    await db.deactivate_subscription(user_id)
                    
                    # удаляем пользователя из канала
                    try:
                        if CHANNEL_ID:
                            await bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
                            logger.info(f"✅ Пользователь {user_id} удален из канала (trial истек)")
                    except Exception as e:
                        logger.error(f"Ошибка при удалении пользователя {user_id} из канала: {e}", exc_info=True)
                    
                    # отправляем уведомление
                    try:
                        await bot.send_message(
                            chat_id=user_id,
                            text="⏰ Ваш бесплатный период закончился. Доступ к каналу прекращен.\n\n"
                                 "Для продолжения использования канала необходимо оформить подписку.\n\n"
                                 "Перейдите в главное меню → раздел 'Подписка' для оформления подписки."
                        )
                    except Exception as e:
                        logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}", exc_info=True)
            
            # затем обрабатываем остальные истекшие подписки
            expired = await db.get_expired_subscriptions()
            
            if not expired:
                logger.info("✅ Истекших подписок не найдено")
                continue
            
            logger.info(f"⏰ Найдено {len(expired)} истекших подписок")
            
            webhook_handler = ProdamusWebhookHandler(bot)
            
            for subscription in expired:
                user_id = subscription["user_id"]
                # пропускаем trial, они уже обработаны выше
                if subscription.get("tariff_type") == "trial":
                    continue
                    
                logger.info(f"⏰ Обработка истекшей подписки для user_id={user_id}")
                
                # деактивируем подписку
                await db.deactivate_subscription(user_id)
                
                # удаляем пользователя из канала
                try:
                    if CHANNEL_ID:
                        await bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
                        logger.info(f"✅ Пользователь {user_id} удален из канала")
                except Exception as e:
                    logger.error(f"Ошибка при удалении пользователя {user_id} из канала: {e}", exc_info=True)
                
                # отправляем уведомление
                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text="⏰ Срок вашей подписки истек. Доступ к каналу прекращен.\n\n"
                             "Вы можете продлить подписку в разделе 'Подписка'."
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}", exc_info=True)
            
            total_processed = len(expired_trials) + len([s for s in expired if s.get("tariff_type") != "trial"])
            logger.info(f"✅ Проверка завершена, обработано {total_processed} подписок")
            
        except Exception as e:
            logger.error(f"Ошибка при проверке истекших подписок: {e}", exc_info=True)
            # при ошибке ждем час перед следующей попыткой
            await asyncio.sleep(3600)


async def warm_up_prodamus():
    """периодический warm-up запроса к prodamus"""
    from prodamus.api import ProdamusAPI
    while True:
        try:
            api = ProdamusAPI()
            params = {"sys": api.sys, "do": "link", "type": "json"}
            logger.info("🔥 warm-up prodamus: отправляю ping")
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    api.payform_url,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    await response.text()
            logger.info("✅ warm-up prodamus: ping успешно обработан")
        except Exception as e:
            logger.warning(f"⚠️ warm-up prodamus: ошибка пинга ({e})")
        finally:
            await asyncio.sleep(300)


async def newsletter_scheduler_loop(bot: Bot, db: Database):
    """периодически: у кого наступила очередная «неделя» с якоря подписки — отправить выпуск"""
    from config import (
        NEWSLETTER_ENABLED,
        NEWSLETTER_GOOGLE_DOC_ID,
        NEWSLETTER_CHECK_INTERVAL_SEC,
    )

    if not NEWSLETTER_ENABLED or not NEWSLETTER_GOOGLE_DOC_ID:
        logger.info("newsletter: выключена (NEWSLETTER_ENABLED или пустой NEWSLETTER_GOOGLE_DOC_ID)")
        return

    from newsletter.weekly_job import run_newsletter_tick

    while True:
        try:
            await asyncio.sleep(max(15, NEWSLETTER_CHECK_INTERVAL_SEC))
            await run_newsletter_tick(bot, db, NEWSLETTER_GOOGLE_DOC_ID)
        except Exception as e:
            logger.error("newsletter_scheduler_loop: %s", e, exc_info=True)


async def main():
    """главная функция запуска бота"""
    # инициализация бота
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # регистрация роутеров
    dp.include_router(channel.router)  # должен быть первым для обработки событий канала
    dp.include_router(common.router)
    dp.include_router(admin.router)
    dp.include_router(payment.router)
    
    # заметный маркер начала запуска
    logger.info("=" * 80)
    logger.info("=" * 80)
    logger.info("🤖 ЗАПУСК TELEGRAM БОТА")
    logger.info("=" * 80)
    logger.info("=" * 80)
    
    # инициализация БД
    db = Database(DATABASE_PATH)
    await db.init()
    logger.info("✅ База данных инициализирована")
    
    # запускаем периодический warm-up prodamus
    asyncio.create_task(warm_up_prodamus())
    logger.info("✅ Запущен периодический warm-up prodamus каждые 5 минут")
    
    # запускаем фоновую задачу для проверки уведомлений о trial подписках
    asyncio.create_task(check_trial_subscriptions_notifications(bot, db))
    logger.info("✅ Запущена ежедневная проверка уведомлений о trial подписках")
    
    # запускаем фоновую задачу для проверки истекших подписок
    asyncio.create_task(check_expired_subscriptions(bot, db))
    logger.info("✅ Запущена ежедневная проверка истекших подписок")

    asyncio.create_task(newsletter_scheduler_loop(bot, db))
    logger.info("✅ Запущен планировщик newsletter (якорь от подписки → Google Doc)")
    
    # устанавливаем команды меню бота
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню")
    ])
    logger.info("✅ Команды меню установлены")
    
    # запуск бота
    logger.info("✅ Бот запущен и готов к работе")
    logger.info("=" * 80)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

