import logging
import aiosqlite
from datetime import datetime
from typing import Optional
from aiogram import Router, Bot, F
from aiogram.types import Message, ContentType, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database.models import Database
from prodamus.webhook import ProdamusWebhookHandler
from prodamus.api import ProdamusAPI
from config import (
    DATABASE_PATH,
    ADMIN_IDS,
    TARIFFS,
    BOT_TOKEN,
    CHANNEL_ID,
    NEWSLETTER_ENABLED,
    NEWSLETTER_GOOGLE_DOC_ID,
    NEWSLETTER_FIRST_SEND_DELAY_MINUTES,
)

logger = logging.getLogger(__name__)

router = Router()
db = Database(DATABASE_PATH)

# FSM состояния для рассылки
class BroadcastStates(StatesGroup):
    waiting_for_content = State()

# FSM состояния для промокодов
class PromocodeAdminStates(StatesGroup):
    waiting_for_code = State()
    waiting_for_discount = State()
    waiting_for_delete_confirmation = State()

class AddUserStates(StatesGroup):
    """состояния для ручного добавления подписки пользователю"""
    waiting_for_user = State()
    waiting_for_tariff = State()

class UnsubscribeStates(StatesGroup):
    """состояния для отписки пользователя"""
    waiting_for_user = State()
    waiting_for_subscription_id = State()

class MigrateUserStates(StatesGroup):
    """состояния для миграции пользователя"""
    waiting_for_user = State()

class MigrateCheckStates(StatesGroup):
    """состояния для проверки статуса пользователя в канале"""
    waiting_for_user = State()


@router.message(Command("help"))
async def cmd_help(message: Message):
    """справка по командам бота (только для админа)"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    text = """📚 Команды администратора:

👥 Пользователи:
/users — все пользователи с подписками
/users_subs — только с активными подписками
/users_trial — пользователи с бесплатным периодом
/adduser — выдать подписку пользователю вручную

📊 Статистика и БД:
/stats — статистика бота
/db — все подписки в БД (для отладки)
/cleanup — очистка дубликатов подписок
/health — проверка состояния системы

📢 Рассылка:
/broadcast — рассылка сообщения всем пользователям
/newsletter_status — проверить парсинг Google Doc (недели)
/newsletter_test [user_id] — тест: все недели подряд с паузами (как прод), без сдвига очереди в БД

🔧 Прочее:
/unsubscribe — отписать пользователя (Prodamus + БД + канал)
/migrate_user — миграция пользователя
/migrate_check — проверить статус в канале
/cancel — отмена текущей операции"""
    
    await message.answer(text)


@router.message(Command("newsletter_status"))
async def cmd_newsletter_status(message: Message):
    """проверка: doc id, настройки, число недель в документе (админ)"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return

    from config import (
        NEWSLETTER_GOOGLE_DOC_ID,
        NEWSLETTER_ENABLED,
        NEWSLETTER_INCLUDE_TRIAL,
        NEWSLETTER_FIRST_SEND_DELAY_MINUTES,
        NEWSLETTER_WEEK_SPACING_DAYS,
        NEWSLETTER_CHECK_INTERVAL_SEC,
    )

    if not NEWSLETTER_GOOGLE_DOC_ID:
        await message.answer("NEWSLETTER_GOOGLE_DOC_ID пустой в .env")
        return

    try:
        from newsletter.google_doc import load_weeks

        weeks = await load_weeks(NEWSLETTER_GOOGLE_DOC_ID)
        keys = sorted(weeks.keys())
        preview_nums = ", ".join(str(k) for k in keys[:20])
        if len(keys) > 20:
            preview_nums += "…"
        await message.answer(
            f"📬 newsletter: enabled={NEWSLETTER_ENABLED}, trial={NEWSLETTER_INCLUDE_TRIAL}\n"
            f"старт через {NEWSLETTER_FIRST_SEND_DELAY_MINUTES} мин после подписки, шаг {NEWSLETTER_WEEK_SPACING_DAYS} дн.\n"
            f"тик каждые {NEWSLETTER_CHECK_INTERVAL_SEC} с\n"
            f"недель в документе: {len(keys)}\n"
            f"номера: {preview_nums or '—'}"
        )
    except Exception as e:
        logger.error("newsletter_status: %s", e, exc_info=True)
        await message.answer(f"❌ Ошибка загрузки документа: {e}")


@router.message(Command("newsletter_test"))
async def cmd_newsletter_test(message: Message, bot: Bot):
    """тест рассылки: все недели из doc, паузы из NEWSLETTER_TEST_*_SEC, проверка подписки перед каждой"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return

    from config import (
        NEWSLETTER_GOOGLE_DOC_ID,
        NEWSLETTER_TEST_FIRST_DELAY_SEC,
        NEWSLETTER_TEST_BETWEEN_WEEKS_SEC,
    )

    if not NEWSLETTER_GOOGLE_DOC_ID:
        await message.answer("NEWSLETTER_GOOGLE_DOC_ID пустой в .env")
        return

    parts = (message.text or "").split()
    target_user_id = message.from_user.id
    if len(parts) >= 2 and parts[1].isdigit():
        target_user_id = int(parts[1])

    await message.answer(
        f"🧪 Тест рассылки → user_id={target_user_id}\n"
        f"пауза до недели 1: {NEWSLETTER_TEST_FIRST_DELAY_SEC} с; между неделями: {NEWSLETTER_TEST_BETWEEN_WEEKS_SEC} с\n"
        f"(имитация продакшна; прогресс рассылки в БД не меняется)"
    )

    from newsletter.e2e_test import run_newsletter_e2e_test

    ok, report = await run_newsletter_e2e_test(bot, db, NEWSLETTER_GOOGLE_DOC_ID, target_user_id)
    await message.answer(("✅ " if ok else "❌ ") + report)


@router.message(Command("users"))
async def cmd_users(message: Message):
    """команда для просмотра всех пользователей с подписками (только для админа)"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    users = await db.get_all_users_with_subscriptions()
    
    if not users:
        await message.answer("📊 Пользователей пока нет.")
        return
    
    text = "📊 Список пользователей:\n\n"
    
    for user in users:
        user_info = f"👤 ID: {user['user_id']}"
        if user['username']:
            user_info += f" (@{user['username']})"
        if user['first_name']:
            user_info += f" - {user['first_name']}"
        
        if user['tariff_type']:
            tariff_name = TARIFFS.get(user['tariff_type'], {}).get('name', user['tariff_type'])
            status = "✅ Активна" if user['is_active'] else "❌ Неактивна"
            user_info += f"\n  📦 Подписка: {tariff_name} ({status})"
            
            if user['prodamus_subscription_id']:
                user_info += f"\n  🔑 Subscription ID: {user['prodamus_subscription_id']}"
            if user['prodamus_order_id']:
                user_info += f"\n  📝 Order ID: {user['prodamus_order_id']}"
            if user['start_date']:
                user_info += f"\n  📅 Начало: {user['start_date']}"
            if user['end_date']:
                user_info += f"\n  📅 Конец: {user['end_date']}"
            elif user['tariff_type'] == 'lifetime':
                user_info += f"\n  📅 Конец: Навсегда"
        else:
            user_info += "\n  📦 Подписка: нет"
        
        text += user_info + "\n\n"
    
    # телеграм ограничивает длину сообщения, разбиваем если нужно
    if len(text) > 4096:
        parts = [text[i:i+4096] for i in range(0, len(text), 4096)]
        for part in parts:
            await message.answer(part)
    else:
        await message.answer(text)


@router.message(Command("users_subs"))
async def cmd_users_subs(message: Message):
    """команда для просмотра пользователей только с активными подписками (только для админа)"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    users = await db.get_all_users_with_subscriptions()
    
    # фильтруем только пользователей с активными подписками
    users_with_subs = [user for user in users if user.get('tariff_type') and user.get('is_active')]
    
    if not users_with_subs:
        await message.answer("📊 Пользователей с активными подписками пока нет.")
        return
    
    text = f"📊 Пользователи с активными подписками (всего: {len(users_with_subs)}):\n\n"
    
    for user in users_with_subs:
        user_info = f"👤 ID: {user['user_id']}"
        if user['username']:
            user_info += f" (@{user['username']})"
        if user['first_name']:
            user_info += f" - {user['first_name']}"
        
        tariff_name = TARIFFS.get(user['tariff_type'], {}).get('name', user['tariff_type'])
        user_info += f"\n  📦 Подписка: {tariff_name} (✅ Активна)"
        
        if user['prodamus_subscription_id']:
            user_info += f"\n  🔑 Subscription ID: {user['prodamus_subscription_id']}"
        if user['prodamus_order_id']:
            user_info += f"\n  📝 Order ID: {user['prodamus_order_id']}"
        if user['start_date']:
            user_info += f"\n  📅 Начало: {user['start_date']}"
        if user['end_date']:
            user_info += f"\n  📅 Конец: {user['end_date']}"
        elif user['tariff_type'] == 'lifetime':
            user_info += f"\n  📅 Конец: Навсегда"
        
        text += user_info + "\n\n"
    
    # телеграм ограничивает длину сообщения, разбиваем если нужно
    if len(text) > 4096:
        parts = [text[i:i+4096] for i in range(0, len(text), 4096)]
        for part in parts:
            await message.answer(part)
    else:
        await message.answer(text)


@router.message(Command("db"))
async def cmd_db(message: Message):
    """команда для просмотра всех подписок в БД (включая неактивные) для отладки (только для админа)"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    subscriptions = await db.get_all_subscriptions()
    
    if not subscriptions:
        await message.answer("📊 Подписок в БД нет.")
        return
    
    text = f"📊 Все подписки в БД (всего: {len(subscriptions)}):\n\n"
    
    for sub in subscriptions:
        sub_info = f"👤 ID подписки: {sub['id']}"
        sub_info += f"\n   User ID: {sub['user_id']}"
        if sub['username']:
            sub_info += f" (@{sub['username']})"
        if sub['first_name']:
            sub_info += f" - {sub['first_name']}"
        
        tariff_name = TARIFFS.get(sub['tariff_type'], {}).get('name', sub['tariff_type']) if sub['tariff_type'] else "N/A"
        status = "✅ Активна" if sub['is_active'] else "❌ Неактивна"
        sub_info += f"\n  Тариф: {tariff_name} ({status})"
        
        if sub['prodamus_subscription_id']:
            sub_info += f"\n  Subscription ID: {sub['prodamus_subscription_id']}"
        if sub['prodamus_order_id']:
            sub_info += f"\n  Order ID: {sub['prodamus_order_id']}"
        if sub['start_date']:
            sub_info += f"\n  Начало: {sub['start_date']}"
        if sub['end_date']:
            sub_info += f"\n  Конец: {sub['end_date']}"
        sub_info += f"\n  Создана: {sub['created_at']}"
        
        text += sub_info + "\n\n"
    
    # телеграм ограничивает длину сообщения, разбиваем если нужно
    if len(text) > 4096:
        parts = [text[i:i+4096] for i in range(0, len(text), 4096)]
        for part in parts:
            await message.answer(part)
    else:
        await message.answer(text)


@router.message(Command("cleanup"))
async def cmd_cleanup(message: Message):
    """команда для очистки дубликатов подписок (только для админа)"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    try:
        result = await db.cleanup_duplicate_subscriptions()
        await message.answer(
            f"✅ Очистка завершена!\n\n"
            f"🗑️ Удалено дубликатов: {result['deleted']}\n"
            f"✅ Оставлено подписок: {result['kept']}"
        )
    except Exception as e:
        logger.error(f"Ошибка при очистке дубликатов: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка при очистке: {e}")


@router.message(Command("health"))
async def cmd_health(message: Message, bot: Bot):
    """команда для проверки состояния системы (только для админа)"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    status = []
    
    # проверка БД
    try:
        users_count = await db.get_all_users_with_subscriptions()
        status.append("✅ БД: работает")
    except Exception as e:
        status.append(f"❌ БД: ошибка - {e}")
    
    # проверка API Prodamus
    try:
        from prodamus.api import ProdamusAPI
        api = ProdamusAPI()
        # пробуем простой запрос
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(
                api.payform_url,
                params={"sys": api.sys, "do": "link", "type": "json"},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status in [200, 400]:  # 400 тоже нормально (нет параметров)
                    status.append("✅ Prodamus API: доступен")
                else:
                    status.append(f"⚠️ Prodamus API: статус {response.status}")
    except Exception as e:
        status.append(f"❌ Prodamus API: ошибка - {str(e)[:50]}")
    
    # проверка канала
    try:
        from config import CHANNEL_ID
        if CHANNEL_ID:
            chat = await bot.get_chat(chat_id=CHANNEL_ID)
            status.append(f"✅ Канал: доступен ({chat.title if hasattr(chat, 'title') else 'OK'})")
        else:
            status.append("⚠️ Канал: CHANNEL_ID не установлен")
    except Exception as e:
        status.append(f"❌ Канал: ошибка - {str(e)[:50]}")
    
    # проверка бота
    try:
        me = await bot.get_me()
        status.append(f"✅ Бот: работает (@{me.username})")
    except Exception as e:
        status.append(f"❌ Бот: ошибка - {e}")
    
    text = "🏥 Состояние системы:\n\n" + "\n".join(status)
    await message.answer(text)


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """команда для просмотра статистики (только для админа)"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    try:
        stats = await db.get_statistics()
        
        text = "📊 Статистика:\n\n"
        text += f"👥 Всего пользователей: {stats['total_users']}\n"
        text += f"📦 Активных подписок: {stats['active_subscriptions']}\n\n"
        
        if stats['subscriptions_by_tariff']:
            text += "📋 По тарифам:\n"
            for tariff_type, count in stats['subscriptions_by_tariff'].items():
                tariff_name = TARIFFS.get(tariff_type, {}).get('name', tariff_type)
                text += f"  • {tariff_name}: {count}\n"
            text += "\n"
        
        text += f"💰 Выручка (активные подписки): {stats['revenue']}₽\n"
        text += f"⏰ Истекают в ближайшие 7 дней: {stats['expiring_soon']}"
        
        await message.answer(text)
    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка при получении статистики: {e}")


@router.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message, state: FSMContext):
    """команда для отписки пользователя (только для админа)"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    await state.set_state(UnsubscribeStates.waiting_for_user)
    await message.answer(
        "🚫 Отписка пользователя (Prodamus + БД + канал)\n\n"
        "Введите Telegram ID пользователя:\n\n"
        "Для отмены отправьте /cancel"
    )


@router.message(UnsubscribeStates.waiting_for_user)
async def process_unsubscribe_user(message: Message, state: FSMContext, bot: Bot):
    """обработка ввода user_id для отписки"""
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return
    
    text = (message.text or "").strip()
    
    # проверка на /cancel
    if text.lower() == "/cancel":
        await state.clear()
        await message.answer("✅ Операция отменена.")
        return
    
    if not text:
        await message.answer(
            "❌ Введите Telegram ID пользователя.\n\n"
            "Для отмены отправьте /cancel"
        )
        return
    
    try:
        user_id = int(text)
    except ValueError:
        await message.answer(
            "❌ ID должен быть числом.\n\n"
            "Для отмены отправьте /cancel"
        )
        return
    
    # проверяем подписку в БД
    subscription_data = await db.get_user_subscription(user_id)
    subscription = None
    
    if subscription_data:
        subscription = subscription_data.get("prodamus_subscription_id")
        customer_email = subscription_data.get("customer_email")
        customer_phone = subscription_data.get("customer_phone")
        if subscription:
            # есть subscription - сразу отписываем (используем email если есть)
            await _perform_unsubscribe(
                message,
                state,
                bot,
                user_id,
                subscription,
                subscription_data,
                None,
                customer_email,
                customer_phone
            )
            return
    
    # подписки нет в БД или нет subscription - запрашиваем вручную
    # (временный режим для тестирования)
    await state.update_data(unsubscribe_user_id=user_id, unsubscribe_data=subscription_data)
    await state.set_state(UnsubscribeStates.waiting_for_subscription_id)
    
    info = ""
    if subscription_data:
        email_info = f", Email: {subscription_data.get('customer_email')}" if subscription_data.get('customer_email') else ""
        info = f"\n\n📦 В БД есть подписка, но без subscription:\n  Order ID: {subscription_data.get('prodamus_order_id', 'N/A')}{email_info}"
    else:
        info = "\n\n⚠️ В БД нет подписки для этого пользователя."
    
    await message.answer(
        f"👤 User ID: {user_id}{info}\n\n"
        "Введите данные для отписки в одном из форматов:\n"
        "• <code>subscription</code>\n"
        "• <code>subscription:profile_id</code>\n"
        "• <code>subscription:email:user@example.com</code>\n"
        "• <code>subscription:phone:+79991234567</code>\n\n"
        "Пример: <code>2694662:email:test@mail.ru</code>\n"
        "Пример: <code>2694662:phone:+79991234567</code>\n"
        "(данные можно найти в ЛК Prodamus)\n\n"
        "Для отмены отправьте /cancel",
        parse_mode="HTML"
    )


@router.message(UnsubscribeStates.waiting_for_subscription_id)
async def process_unsubscribe_subscription_id(message: Message, state: FSMContext, bot: Bot):
    """обработка ввода subscription_id для отписки"""
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return
    
    text = (message.text or "").strip()
    
    # проверка на /cancel
    if text.lower() == "/cancel":
        await state.clear()
        await message.answer("✅ Операция отменена.")
        return
    
    if not text:
        await message.answer(
            "❌ Введите данные для отписки.\n\n"
            "Для отмены отправьте /cancel"
        )
        return
    
    # парсим формат: subscription или subscription:profile_id или subscription:email:xxx или subscription:phone:+7...
    subscription = None
    profile_id = None
    customer_email = None
    customer_phone = None
    
    if ":" in text:
        parts = text.split(":")
        subscription = parts[0].strip()
        
        if len(parts) >= 3 and parts[1].strip().lower() == "email":
            # формат subscription:email:xxx@yyy.com (email может содержать @ дальше без лишних :)
            customer_email = ":".join(parts[2:]).strip()
        elif len(parts) >= 3 and parts[1].strip().lower() == "phone":
            # формат subscription:phone:+79991234567
            customer_phone = ":".join(parts[2:]).strip()
        elif len(parts) >= 2:
            # формат subscription:profile_id
            try:
                profile_id = int(parts[1].strip())
            except ValueError:
                # может это email без ключевого слова?
                if "@" in parts[1]:
                    customer_email = parts[1].strip()
                else:
                    await message.answer(
                        "❌ Неверный формат. profile_id должен быть числом или используйте email.\n\n"
                        "Для отмены отправьте /cancel"
                    )
                    return
    else:
        subscription = text
    
    data = await state.get_data()
    user_id = data.get("unsubscribe_user_id")
    subscription_data = data.get("unsubscribe_data")
    
    await _perform_unsubscribe(
        message, state, bot, user_id, subscription, subscription_data,
        profile_id, customer_email, customer_phone
    )


async def _perform_unsubscribe(message: Message, state: FSMContext, bot: Bot, 
                               user_id: int, subscription: str, subscription_data: dict = None,
                               profile_id: int = None, customer_email: str = None, customer_phone: str = None):
    """выполнение отписки: Prodamus API + БД + канал"""
    await state.clear()
    
    results = []
    
    # 1. Отправляем запрос в Prodamus API (setActivity)
    prodamus_client = ProdamusAPI()
    prodamus_success = False
    
    # попытка: email (+ опционально телефон), при ошибке — только email
    if customer_email:
        try:
            success, error_msg = await prodamus_client.set_subscription_activity(
                subscription=subscription,
                customer_email=customer_email,
                customer_phone=customer_phone,
                active=False,
                as_manager=True
            )
            if not success and customer_phone:
                success, error_msg = await prodamus_client.set_subscription_activity(
                    subscription=subscription,
                    customer_email=customer_email,
                    customer_phone=None,
                    active=False,
                    as_manager=True
                )
            if success:
                prodamus_success = True
                results.append(f"✅ Prodamus: подписка деактивирована (email={customer_email})")
            else:
                results.append(f"❌ Prodamus (email): {error_msg}")
        except Exception as e:
            logger.error(f"Ошибка при отписке в Prodamus (email): {e}", exc_info=True)
            results.append(f"❌ Prodamus (email): ошибка - {e}")
    
    # только телефон
    if not prodamus_success and customer_phone and not customer_email:
        try:
            success, error_msg = await prodamus_client.set_subscription_activity(
                subscription=subscription,
                customer_phone=customer_phone,
                active=False,
                as_manager=True
            )
            if success:
                prodamus_success = True
                results.append("✅ Prodamus: подписка деактивирована (телефон)")
            else:
                results.append(f"❌ Prodamus (phone): {error_msg}")
        except Exception as e:
            logger.error(f"Ошибка при отписке в Prodamus (phone): {e}", exc_info=True)
            results.append(f"❌ Prodamus (phone): ошибка - {e}")
    
    # если есть profile_id
    if not prodamus_success and profile_id:
        try:
            success, error_msg = await prodamus_client.set_subscription_activity(
                subscription=subscription,
                profile_id=profile_id,
                active=False,
                as_manager=True
            )
            if success:
                prodamus_success = True
                results.append(f"✅ Prodamus: подписка деактивирована (profile_id={profile_id})")
            else:
                results.append(f"❌ Prodamus (profile): {error_msg}")
        except Exception as e:
            logger.error(f"Ошибка при отписке в Prodamus (profile): {e}", exc_info=True)
            results.append(f"❌ Prodamus (profile): ошибка - {e}")
    
    if not prodamus_success:
        results.append("❌ Prodamus: не удалось отписать (нужен email, phone или profile_id)")
    
    # 2. Деактивируем подписку в БД и канал только если Prodamus прошёл (или нечего было глушить)
    if subscription_data and prodamus_success:
        try:
            webhook_data = {
                "subscription_id": subscription,
                "subscription[id]": subscription,
                "order_num": subscription_data.get("prodamus_order_id"),
                "action_code": "cancel",
            }
            webhook_handler = ProdamusWebhookHandler(bot)
            await webhook_handler._handle_subscription_cancelled(user_id, webhook_data)
            results.append("✅ БД: подписка деактивирована")
        except Exception as e:
            logger.error(f"Ошибка при деактивации в БД: {e}", exc_info=True)
            results.append(f"❌ БД: ошибка - {e}")
    elif subscription_data and not prodamus_success:
        results.append("⚠️ БД и канал не тронуты — сначала нужно отписать в Prodamus.")
    elif not subscription_data and prodamus_success:
        try:
            if CHANNEL_ID:
                await bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
                results.append("✅ Канал: пользователь забанен")
        except Exception as e:
            logger.warning(f"Ошибка при бане в канале: {e}")
            results.append(f"⚠️ Канал: {e}")
    elif not subscription_data and not prodamus_success:
        results.append("⚠️ Нет записи в БД, Prodamus не отписан — канал не трогал.")
    
    await message.answer(
        f"🚫 Результат отписки пользователя {user_id}:\n\n"
        f"🔑 Subscription: {subscription}\n\n" +
        "\n".join(results)
    )


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    """команда для начала рассылки (только для админа)"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    await state.set_state(BroadcastStates.waiting_for_content)
    await message.answer(
        "📢 Режим рассылки активирован.\n\n"
        "Отправьте контент для рассылки (одно сообщение):\n"
        "• Текст\n"
        "• Фото\n"
        "• Видео\n"
        "• Кружок (video note)\n\n"
        "⚠️ Можно отправить только одно медиа за раз.\n"
        "Для отмены отправьте /cancel"
    )


@router.message(Command("cancel"))
async def cmd_cancel_admin(message: Message, state: FSMContext):
    """отмена текущей операции админа"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    current_state = await state.get_state()
    if current_state is None:
        return
    
    # список всех админских состояний
    admin_states = [
        BroadcastStates.waiting_for_content,
        UnsubscribeStates.waiting_for_user,
        UnsubscribeStates.waiting_for_subscription_id,
        MigrateUserStates.waiting_for_user,
        MigrateCheckStates.waiting_for_user,
        AddUserStates.waiting_for_user,
        AddUserStates.waiting_for_tariff,
        PromocodeAdminStates.waiting_for_code,
        PromocodeAdminStates.waiting_for_discount,
        PromocodeAdminStates.waiting_for_delete_confirmation,
    ]
    
    # проверяем, что текущее состояние - админское
    state_str = str(current_state)
    is_admin_state = any(str(s) == state_str for s in admin_states)
    
    if is_admin_state:
        await state.clear()
        await message.answer("✅ Операция отменена.")


@router.message(BroadcastStates.waiting_for_content)
async def process_broadcast_content(message: Message, state: FSMContext, bot: Bot):
    """обработка контента для рассылки"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    # проверка на альбом (несколько медиа) - запрещаем
    if message.media_group_id:
        await message.answer(
            "❌ Ошибка: нельзя отправлять несколько медиа одновременно (альбом).\n\n"
            "Отправьте только одно медиа: одно фото, одно видео или один кружок."
        )
        await state.clear()
        return
    
    # для тестирования - только один user_id
    TEST_USER_ID = 8495144404
    TEST_MODE = False  # после тестирования установить в False
    
    try:
        # получаем список пользователей
        if TEST_MODE:
            user_ids = [TEST_USER_ID]
            await message.answer(f"🧪 ТЕСТОВЫЙ РЕЖИМ: рассылка только на {TEST_USER_ID}")
        else:
            user_ids = await db.get_all_user_ids()
            await message.answer(f"📢 Начинаю рассылку на {len(user_ids)} пользователей...")
        
        if not user_ids:
            await message.answer("❌ Нет пользователей для рассылки.")
            await state.clear()
            return
        
        # счетчики для статистики
        success_count = 0
        error_count = 0
        
        # определяем тип контента и отправляем
        if message.content_type == ContentType.TEXT:
            # обычный текст
            text = message.text or message.caption or ""
            for user_id in user_ids:
                try:
                    await bot.send_message(chat_id=user_id, text=text)
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    logger.warning(f"Ошибка отправки текста пользователю {user_id}: {e}")
        
        elif message.content_type == ContentType.PHOTO:
            # фото с подписью или без
            photo = message.photo[-1]  # берем фото наибольшего размера
            caption = message.caption or None
            for user_id in user_ids:
                try:
                    await bot.send_photo(chat_id=user_id, photo=photo.file_id, caption=caption)
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    logger.warning(f"Ошибка отправки фото пользователю {user_id}: {e}")
        
        elif message.content_type == ContentType.VIDEO:
            # видео с подписью или без
            video = message.video
            caption = message.caption or None
            for user_id in user_ids:
                try:
                    await bot.send_video(chat_id=user_id, video=video.file_id, caption=caption)
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    logger.warning(f"Ошибка отправки видео пользователю {user_id}: {e}")
        
        elif message.content_type == ContentType.VIDEO_NOTE:
            # кружок (video note)
            video_note = message.video_note
            for user_id in user_ids:
                try:
                    await bot.send_video_note(chat_id=user_id, video_note=video_note.file_id)
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    logger.warning(f"Ошибка отправки кружка пользователю {user_id}: {e}")
        
        else:
            await message.answer(f"❌ Неподдерживаемый тип контента: {message.content_type}")
            await state.clear()
            return
        
        # отправляем статистику
        result_text = (
            f"✅ Рассылка завершена!\n\n"
            f"✅ Успешно: {success_count}\n"
            f"❌ Ошибок: {error_count}\n"
            f"📊 Всего: {len(user_ids)}"
        )
        await message.answer(result_text)
        await state.clear()
        
        logger.info(f"Рассылка завершена: успешно {success_count}, ошибок {error_count}")
        
    except Exception as e:
        logger.error(f"Ошибка при рассылке: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка при рассылке: {e}")
        await state.clear()


@router.message(Command("migrate_user"))
async def cmd_migrate_user(message: Message, state: FSMContext):
    """команда для миграции пользователя (только для админа)"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    await state.set_state(MigrateUserStates.waiting_for_user)
    await message.answer(
        "🔄 Миграция пользователя\n\n"
        "Введите Telegram ID пользователя:\n\n"
        "Для отмены отправьте /cancel"
    )


@router.message(MigrateUserStates.waiting_for_user)
async def process_migrate_user(message: Message, state: FSMContext, bot: Bot):
    """обработка ввода user_id для миграции"""
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return
    
    text = (message.text or "").strip()
    if not text:
        await message.answer(
            "❌ Введите Telegram ID пользователя.\n\n"
            "Для отмены отправьте /cancel"
        )
        return
    
    try:
        user_id = int(text)
    except ValueError:
        await message.answer(
            "❌ ID должен быть числом.\n\n"
            "Для отмены отправьте /cancel"
        )
        return
    
    # проверяем, есть ли уже подписка
    existing = await db.get_user_subscription(user_id)
    if existing:
        await state.clear()
        await message.answer(
            f"⚠️ У пользователя {user_id} уже есть активная подписка:\n"
            f"  Тариф: {existing.get('tariff_type', 'N/A')}\n"
            f"  Статус: {'✅ Активна' if existing.get('is_active') else '❌ Неактивна'}"
        )
        return
    
    # проверяем, что пользователь существует в Telegram
    try:
        chat_member = await bot.get_chat_member(chat_id=user_id, user_id=user_id)
        username = chat_member.user.username or "N/A"
        first_name = chat_member.user.first_name or "N/A"
    except Exception as e:
        logger.warning(f"Не удалось получить информацию о пользователе {user_id}: {e}")
        username = None
        first_name = None
    
    # добавляем пользователя в БД
    await db.add_user(user_id, username, first_name)
    
    # создаем миграционную подписку (месячный тариф)
    success = await db.create_migration_subscription(
        user_id=user_id,
        tariff_type="monthly",
        duration_days=30
    )
    
    await state.clear()
    
    if success:
        await message.answer(
            f"✅ Пользователь {user_id} успешно мигрирован!\n"
            f"  👤 Username: @{username if username else 'N/A'}\n"
            f"  📦 Подписка: 1 месяц (30 дней)\n"
            f"  📅 Начало: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"Пользователь может написать /activate в боте для активации."
        )
        logger.info(f"✅ Миграция пользователя {user_id} выполнена админом {message.from_user.id}")
    else:
        await message.answer(f"❌ Не удалось создать подписку для пользователя {user_id}")


@router.message(Command("migrate_check"))
async def cmd_migrate_check(message: Message, state: FSMContext):
    """команда для проверки статуса пользователя в канале (только для админа)"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    from config import CHANNEL_ID
    
    if not CHANNEL_ID:
        await message.answer("❌ CHANNEL_ID не установлен в конфиге")
        return
    
    await state.set_state(MigrateCheckStates.waiting_for_user)
    await message.answer(
        "🔍 Проверка статуса пользователя в канале\n\n"
        "Введите Telegram ID пользователя:\n\n"
        "Для отмены отправьте /cancel"
    )


@router.message(MigrateCheckStates.waiting_for_user)
async def process_migrate_check(message: Message, state: FSMContext, bot: Bot):
    """обработка ввода user_id для проверки статуса"""
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return
    
    from config import CHANNEL_ID
    
    text = (message.text or "").strip()
    if not text:
        await message.answer(
            "❌ Введите Telegram ID пользователя.\n\n"
            "Для отмены отправьте /cancel"
        )
        return
    
    try:
        user_id = int(text)
    except ValueError:
        await message.answer(
            "❌ ID должен быть числом.\n\n"
            "Для отмены отправьте /cancel"
        )
        return
    
    await state.clear()
    
    # проверяем статус пользователя в канале
    try:
        from aiogram.enums import ChatMemberStatus
        chat_member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        status = chat_member.status
        
        status_text = {
            ChatMemberStatus.MEMBER: "✅ Участник",
            ChatMemberStatus.ADMINISTRATOR: "✅ Администратор",
            ChatMemberStatus.CREATOR: "✅ Создатель",
            ChatMemberStatus.LEFT: "❌ Не участник (покинул)",
            ChatMemberStatus.KICKED: "❌ Забанен",
            ChatMemberStatus.RESTRICTED: "⚠️ Ограничен",
        }.get(status, f"❓ Неизвестный статус: {status}")
        
        # проверяем подписку в БД
        subscription = await db.get_user_subscription(user_id)
        subscription_text = "✅ Есть активная подписка" if subscription else "❌ Нет активной подписки"
        
        await message.answer(
            f"📊 Информация о пользователе {user_id}:\n\n"
            f"📢 Статус в канале: {status_text}\n"
            f"📦 Подписка в БД: {subscription_text}"
        )
    except Exception as e:
        logger.error(f"Ошибка при проверке пользователя {user_id}: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка при проверке: {e}")


@router.message(Command("adduser"))
async def cmd_adduser(message: Message, state: FSMContext):
    """команда для ручного добавления подписки пользователю (только для админа)"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ у вас нет доступа к этой команде.")
        return
    
    await state.set_state(AddUserStates.waiting_for_user)
    await message.answer(
        "👤 Введите Telegram ID или @username пользователя, которому нужно выдать подписку.\n\n"
        "Примеры:\n"
        "• 123456789\n"
        "• @username\n\n"
        "Для отмены отправьте /cancel"
    )


@router.message(AddUserStates.waiting_for_user)
async def process_adduser_user(message: Message, state: FSMContext, bot: Bot):
    """обработка ввода пользователя для команды /adduser"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    text = (message.text or "").strip()
    if not text:
        await message.answer(
            "❌ Введите Telegram ID или @username пользователя.\n\n"
            "Для отмены отправьте /cancel"
        )
        return
    
    user_id: Optional[int] = None
    username: Optional[str] = None
    first_name: Optional[str] = None
    
    if text.startswith("@"):
        # поиск по username
        username = text[1:].strip()
        if not username:
            await message.answer("❌ неверный username. попробуйте ещё раз или отправьте /cancel.")
            return
        
        user_row = await db.get_user_by_username(username)
        if not user_row:
            await message.answer(
                "❌ пользователь с таким username не найден в базе.\n\n"
                "скорее всего, он ещё не писал боту.\n"
                "либо попросите его написать боту, либо введите его числовой id."
            )
            return
        
        user_id = user_row.get("user_id")
        username = user_row.get("username") or username
        first_name = user_row.get("first_name")
    else:
        # попытка распарсить числовой id
        try:
            user_id = int(text)
        except ValueError:
            await message.answer(
                "❌ Неверный формат.\n\n"
                "Введите username (например: @username) или числовой ID пользователя.\n\n"
                "Для отмены отправьте /cancel"
            )
            return
        
        # пробуем подтянуть данные о пользователе из telegram
        try:
            chat_member = await bot.get_chat_member(chat_id=user_id, user_id=user_id)
            username = chat_member.user.username
            first_name = chat_member.user.first_name
        except Exception as e:
            logger.warning(f"не удалось получить данные о пользователе {user_id}: {e}")
            # оставляем username и first_name пустыми
    
    if not user_id:
        await message.answer("❌ не удалось определить пользователя. попробуйте ещё раз или отправьте /cancel.")
        return
    
    # сохраняем/обновляем пользователя в таблице users
    await db.add_user(user_id, username, first_name)
    
    await state.update_data(target_user_id=user_id)
    await state.set_state(AddUserStates.waiting_for_tariff)
    
    # формируем клавиатуру с тарифами
    buttons = []
    for tariff_key, tariff in TARIFFS.items():
        buttons.append([
            InlineKeyboardButton(
                text=tariff["name"],
                callback_data=f"adduser_tariff:{tariff_key}"
            )
        ])
    buttons.append([
        InlineKeyboardButton(
            text="❌ Отмена",
            callback_data="adduser_cancel"
        )
    ])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    user_label = f"id {user_id}"
    if username:
        user_label += f" (@{username})"
    
    await message.answer(
        f"👤 пользователь: {user_label}\n\n"
        f"выберите тариф, который нужно назначить.",
        reply_markup=keyboard
    )


@router.callback_query(F.data.startswith("adduser_tariff:"))
async def callback_adduser_tariff(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """выбор тарифа для команды /adduser"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ нет доступа", show_alert=True)
        return
    
    data = await state.get_data()
    target_user_id = data.get("target_user_id")
    if not target_user_id:
        await callback.answer("❌ пользователь не найден в состоянии. начните заново с /adduser.", show_alert=True)
        await state.clear()
        return
    
    tariff_type = callback.data.split(":", 1)[1]
    if tariff_type not in TARIFFS:
        await callback.answer("❌ неверный тариф", show_alert=True)
        return
    
    tariff_info = TARIFFS[tariff_type]
    duration_days = tariff_info["duration_days"]
    
    try:
        # создаем подписку без привязки к prodamus
        await db.create_subscription(
            target_user_id,
            tariff_type,
            duration_days,
            prodamus_subscription_id=None,
            prodamus_order_id=None
        )
        # якорь рассылки уже выставлен в create_subscription (неделя 1 + задержка)
        if NEWSLETTER_ENABLED and NEWSLETTER_GOOGLE_DOC_ID:
            logger.info(
                "adduser: очередь рассылки для user_id=%s сброшена (как при новой подписке)",
                target_user_id,
            )
        
        # добавляем пользователя в канал / разбаниваем
        if CHANNEL_ID:
            try:
                await bot.unban_chat_member(
                    chat_id=CHANNEL_ID,
                    user_id=target_user_id,
                    only_if_banned=False
                )
            except Exception as e:
                logger.warning(f"ошибка при добавлении пользователя {target_user_id} в канал: {e}")
        
        await state.clear()
        await callback.answer("✅ Подписка выдана", show_alert=True)
        
        duration_text = "без ограничений" if duration_days is None else f"{duration_days} дней"
        text = (
            f"✅ Подписка успешно выдана.\n\n"
            f"👤 Пользователь: {target_user_id}\n"
            f"📦 Тариф: {tariff_info['name']}\n"
            f"⏰ Срок действия: {duration_text}"
        )
        try:
            await callback.message.edit_text(text)
        except Exception:
            await callback.message.answer(text)
        
        # уведомляем пользователя о выданной подписке (если возможно)
        try:
            delay = NEWSLETTER_FIRST_SEND_DELAY_MINUTES
            if NEWSLETTER_ENABLED and NEWSLETTER_GOOGLE_DOC_ID:
                user_notice = (
                    f"✅ Вам открыт доступ.\n\n"
                    f"Тариф: {tariff_info['name']}\n\n"
                    f"📬 Запущена рассылка материалов по неделям: первое сообщение в этот чат "
                    f"придёт примерно через {delay} мин., далее по расписанию.\n\n"
                    f"Закрытый канал — по приглашению от бота (отдельным сообщением), если оно ещё не приходило."
                )
            else:
                user_notice = (
                    f"✅ Вам открыт доступ.\n\n"
                    f"Тариф: {tariff_info['name']}\n\n"
                    f"Следите за сообщениями от бота: уведомления о канале и сервисные сообщения."
                )
            await bot.send_message(chat_id=target_user_id, text=user_notice)
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление пользователю {target_user_id}: {e}")
    except Exception as e:
        logger.error(f"Ошибка при ручной выдаче подписки пользователю {target_user_id}: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при выдаче подписки", show_alert=True)


@router.callback_query(F.data == "adduser_cancel")
async def callback_adduser_cancel(callback: CallbackQuery, state: FSMContext):
    """отмена операции /adduser"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer()
        return
    
    await state.clear()
    try:
        await callback.message.edit_text("❌ операция добавления пользователя отменена.")
    except Exception:
        await callback.message.answer("❌ операция добавления пользователя отменена.")
    await callback.answer()


@router.message(Command("users_trial"))
async def cmd_users_trial(message: Message):
    """команда для просмотра пользователей с бесплатным периодом (trial) (только для админа)"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    try:
        # получаем все активные trial подписки
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT 
                    s.user_id,
                    u.username,
                    u.first_name,
                    s.start_date,
                    s.end_date,
                    s.created_at
                FROM subscriptions s
                LEFT JOIN users u ON s.user_id = u.user_id
                WHERE s.is_active = 1 
                AND s.tariff_type = 'trial'
                ORDER BY s.end_date ASC
            """) as cursor:
                rows = await cursor.fetchall()
                trial_subscriptions = [dict(row) for row in rows]
        
        if not trial_subscriptions:
            await message.answer("📊 Пользователей с бесплатным периодом (trial) нет.")
            return
        
        # группируем по статусу (активные, истекающие скоро, истекшие)
        from datetime import datetime
        now = datetime.now()
        
        active = []
        expiring_soon = []  # истекают в ближайшие 7 дней
        expired = []
        
        for sub in trial_subscriptions:
            if sub['end_date']:
                end_date = datetime.fromisoformat(sub['end_date']) if isinstance(sub['end_date'], str) else sub['end_date']
                days_left = (end_date - now).days
                
                if days_left < 0:
                    expired.append((sub, days_left))
                elif days_left <= 7:
                    expiring_soon.append((sub, days_left))
                else:
                    active.append((sub, days_left))
            else:
                active.append((sub, None))
        
        # формируем отчет
        text = f"📊 Пользователи с бесплатным периодом (trial):\n\n"
        text += f"Всего: {len(trial_subscriptions)}\n"
        text += f"✅ Активных: {len(active)}\n"
        text += f"⚠️ Истекают в ближайшие 7 дней: {len(expiring_soon)}\n"
        text += f"❌ Истекших: {len(expired)}\n\n"
        
        # показываем истекающие скоро
        if expiring_soon:
            text += f"⚠️ Истекают в ближайшие 7 дней ({len(expiring_soon)}):\n\n"
            for sub, days_left in sorted(expiring_soon, key=lambda x: x[1] if x[1] else 999):
                user_info = f"👤 ID: {sub['user_id']}"
                if sub['username']:
                    user_info += f" (@{sub['username']})"
                if sub['first_name']:
                    user_info += f" - {sub['first_name']}"
                
                if sub['end_date']:
                    end_date = datetime.fromisoformat(sub['end_date']) if isinstance(sub['end_date'], str) else sub['end_date']
                    user_info += f"\n  📅 Окончание: {end_date.strftime('%d.%m.%Y')} (через {abs(days_left)} дн.)"
                
                text += user_info + "\n\n"
        
        # показываем активные (первые 20)
        if active:
            text += f"✅ Активные ({len(active)}):\n\n"
            for i, (sub, days_left) in enumerate(active[:20], 1):
                user_info = f"{i}. ID: {sub['user_id']}"
                if sub['username']:
                    user_info += f" (@{sub['username']})"
                if sub['first_name']:
                    user_info += f" - {sub['first_name']}"
                
                if sub['end_date']:
                    end_date = datetime.fromisoformat(sub['end_date']) if isinstance(sub['end_date'], str) else sub['end_date']
                    if days_left:
                        user_info += f" | До {end_date.strftime('%d.%m.%Y')} ({days_left} дн.)"
                    else:
                        user_info += f" | До {end_date.strftime('%d.%m.%Y')}"
                else:
                    user_info += " | Без срока"
                
                text += user_info + "\n"
            
            if len(active) > 20:
                text += f"\n... и еще {len(active) - 20} активных\n"
        
        # показываем истекшие (первые 10)
        if expired:
            text += f"\n❌ Истекшие ({len(expired)}):\n\n"
            for i, (sub, days_left) in enumerate(sorted(expired, key=lambda x: x[1] if x[1] else 0)[:10], 1):
                user_info = f"{i}. ID: {sub['user_id']}"
                if sub['username']:
                    user_info += f" (@{sub['username']})"
                if sub['first_name']:
                    user_info += f" - {sub['first_name']}"
                
                if sub['end_date']:
                    end_date = datetime.fromisoformat(sub['end_date']) if isinstance(sub['end_date'], str) else sub['end_date']
                    user_info += f" | Истек {end_date.strftime('%d.%m.%Y')} ({abs(days_left)} дн. назад)"
                
                text += user_info + "\n"
            
            if len(expired) > 10:
                text += f"\n... и еще {len(expired) - 10} истекших\n"
        
        # разбиваем на части если слишком длинное
        if len(text) > 4096:
            parts = [text[i:i+4096] for i in range(0, len(text), 4096)]
            for part in parts:
                await message.answer(part)
        else:
            await message.answer(text)
        
    except Exception as e:
        logger.error(f"Ошибка при получении списка trial подписок: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка при получении списка: {e}")


@router.message(Command("promo_add"))
async def cmd_promo_add(message: Message, state: FSMContext):
    """команда для добавления промокода (только для админа)"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    await state.set_state(PromocodeAdminStates.waiting_for_code)
    await message.answer(
        "🎟️ Создание нового промокода\n\n"
        "Введите название промокода (буквы, цифры, дефис и подчеркивание, включая русские буквы):\n\n"
        "Для отмены отправьте /cancel"
    )


@router.message(PromocodeAdminStates.waiting_for_code)
async def process_promo_code(message: Message, state: FSMContext):
    """обработка введенного названия промокода"""
    code = message.text.strip()
    
    # проверка формата промокода (буквы, цифры, дефис, подчеркивание, включая русские буквы)
    import re
    if not re.match(r'^[A-ZА-ЯЁa-zа-яё0-9_-]+$', code, re.UNICODE):
        await message.answer(
            "❌ Неверный формат промокода!\n\n"
            "Промокод должен содержать только:\n"
            "• Буквы (A-Z, А-Я, включая Ё)\n"
            "• Цифры (0-9)\n"
            "• Дефис (-)\n"
            "• Подчеркивание (_)\n\n"
            "Попробуйте еще раз или отправьте /cancel для отмены."
        )
        return
    
    # приводим к верхнему регистру (для латиницы), русские буквы остаются как есть
    code = code.upper()
    
    # проверка на существование промокода
    existing = await db.get_promocode(code)
    if existing:
        await message.answer(
            f"❌ Промокод {code} уже существует!\n\n"
            "Введите другое название или отправьте /cancel для отмены."
        )
        return
    
    # сохраняем код и переходим к следующему шагу
    await state.update_data(code=code)
    await state.set_state(PromocodeAdminStates.waiting_for_discount)
    await message.answer(
        f"✅ Промокод: {code}\n\n"
        "Введите сумму скидки в рублях (например, 100):\n\n"
        "Для отмены отправьте /cancel"
    )


@router.message(PromocodeAdminStates.waiting_for_discount)
async def process_promo_discount(message: Message, state: FSMContext):
    """обработка введенной суммы скидки"""
    try:
        discount = int(message.text.strip())
        if discount < 1:
            raise ValueError()
    except ValueError:
        await message.answer(
            "❌ Неверный формат!\n\n"
            "Введите положительное число (сумма скидки в рублях).\n\n"
            "Попробуйте еще раз или отправьте /cancel для отмены."
        )
        return
    
    # получаем данные из состояния
    data = await state.get_data()
    code = data.get("code")
    
    if not code:
        logger.error(f"Ошибка: код промокода не найден в состоянии")
        await message.answer("❌ Ошибка: неполные данные. Попробуйте создать промокод заново.")
        await state.clear()
        return
    
    logger.info(f"Создание промокода: code={code}, discount_amount={discount}")
    
    # проверяем, есть ли уже активный промокод с таким кодом
    existing = await db.get_promocode(code)
    if existing and existing.get('is_active'):
        await message.answer(
            f"❌ Промокод {code} уже существует и активен!\n\n"
            f"💰 Текущая скидка: {existing.get('discount_amount')}₽\n\n"
            "Используйте /promo_delete для удаления или создайте промокод с другим названием."
        )
        await state.clear()
        return
    
    # создаем промокод
    try:
        success = await db.add_promocode(code, discount)
        
        if success:
            await message.answer(
                f"✅ Промокод успешно создан!\n\n"
                f"🎟️ Код: {code}\n"
                f"💰 Сумма скидки: {discount}₽\n"
                f"📅 Скидка применяется только на первый месяц"
            )
        else:
            logger.error(f"Не удалось создать промокод {code}. Метод add_promocode вернул False")
            await message.answer(
                f"❌ Ошибка при создании промокода.\n"
                f"Возможно, промокод {code} уже существует.\n\n"
                f"Проверьте список промокодов командой /promo"
            )
    except Exception as e:
        logger.error(f"Исключение при создании промокода {code}: {e}", exc_info=True)
        await message.answer(
            f"❌ Ошибка при создании промокода: {str(e)}\n\n"
            f"Проверьте логи для деталей."
        )
    
    await state.clear()


@router.message(Command("promo_delete"))
async def cmd_promo_delete(message: Message, state: FSMContext):
    """команда для удаления промокода (только для админа)"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    await state.set_state(PromocodeAdminStates.waiting_for_delete_confirmation)
    await message.answer(
        "🗑️ Удаление промокода\n\n"
        "Введите название промокода для удаления:\n\n"
        "Для отмены отправьте /cancel"
    )


@router.message(PromocodeAdminStates.waiting_for_delete_confirmation)
async def process_promo_delete(message: Message, state: FSMContext):
    """обработка удаления промокода"""
    code = message.text.strip()
    
    # проверка формата промокода
    import re
    if not re.match(r'^[A-ZА-ЯЁa-zа-яё0-9_-]+$', code, re.UNICODE):
        await message.answer(
            "❌ Неверный формат промокода!\n\n"
            "Введите корректное название промокода или отправьте /cancel для отмены."
        )
        return
    
    # приводим к верхнему регистру (для латиницы), русские буквы остаются как есть
    code = code.upper()
    
    # проверяем существование промокода
    promo = await db.get_promocode(code)
    if not promo:
        await message.answer(
            f"❌ Промокод {code} не найден!\n\n"
            "Введите другое название или отправьте /cancel для отмены."
        )
        return
    
    # показываем информацию о промокоде и запрашиваем подтверждение
    text = (
        f"⚠️ Вы точно хотите удалить промокод {code}?\n\n"
        f"💰 Сумма скидки: {promo['discount_amount']}₽\n"
        f"📅 Скидка применяется только на первый месяц"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"promo_delete_confirm_{code}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="promo_delete_cancel")],
    ])
    
    await message.answer(text, reply_markup=keyboard)
    await state.clear()


@router.callback_query(F.data.startswith("promo_delete_confirm_"))
async def callback_promo_delete_confirm(callback: CallbackQuery):
    """подтверждение удаления промокода"""
    code = callback.data.replace("promo_delete_confirm_", "")
    
    await callback.answer()
    
    # удаляем промокод
    success = await db.delete_promocode(code)
    
    if success:
        await callback.message.edit_text(f"✅ Промокод {code} успешно удален.")
    else:
        await callback.message.edit_text(f"❌ Ошибка при удалении промокода {code}.")


@router.callback_query(F.data == "promo_delete_cancel")
async def callback_promo_delete_cancel(callback: CallbackQuery):
    """отмена удаления промокода"""
    await callback.answer("❌ Удаление отменено")
    await callback.message.edit_text("❌ Удаление промокода отменено.")


@router.message(Command("promo"))
async def cmd_promo_list(message: Message):
    """команда для просмотра списка промокодов (только для админа)"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    try:
        promocodes = await db.get_all_promocodes()
        
        if not promocodes:
            await message.answer("📋 Действующих промокодов нет.")
            return
        
        text = f"📋 Список действующих промокодов ({len(promocodes)}):\n\n"
        
        for i, promo in enumerate(promocodes, 1):
            text += (
                f"{i}. 🎟️ {promo['code']}\n"
                f"   Сумма скидки: {promo['discount_amount']}₽\n"
                f"   Скидка применяется только на первый месяц\n"
                f"   Создан: {promo['created_at']}\n\n"
            )
        
        # разбиваем на части если слишком длинное
        if len(text) > 4096:
            parts = [text[i:i+4096] for i in range(0, len(text), 4096)]
            for part in parts:
                await message.answer(part)
        else:
            await message.answer(text)
            
    except Exception as e:
        logger.error(f"Ошибка при получении списка промокодов: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка при получении списка: {e}")


@router.message(Command("test_gift"))
async def cmd_test_gift(message: Message, bot: Bot):
    """тестовая команда для подарка подписки (только для админа)
    
    Использование: /test_gift @username
    """
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    # парсим аргументы команды
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    
    if not args:
        await message.answer(
            "❌ Укажите username получателя:\n"
            "  /test_gift @username\n\n"
            "Пример: /test_gift @testuser"
        )
        return
    
    test_username = args[0].lstrip('@')
    tariff_type = "monthly"
    tariff_info = TARIFFS[tariff_type]
    
    try:
        # сохраняем подарок по username (без получения user_id)
        # подписка будет активирована когда пользователь зайдет в бота
        success = await db.create_gift(
            tariff_type=tariff_type,
            giver_user_id=None,  # тестовая команда
            recipient_username=test_username
        )
        
        if success:
            logger.info(f"Тестовый подарок подписки создан: пользователю @{test_username} подарена {tariff_type} подписка")
            
            await message.answer(
                f"✅ Тестовая подписка успешно подарена!\n\n"
                f"🎁 Получатель: @{test_username}\n"
                f"📦 Тариф: {tariff_info['name']}\n"
                f"📅 Срок действия: {tariff_info['duration_days']} дней\n\n"
                f"Подписка будет активирована автоматически, когда получатель зайдет в бота."
            )
        else:
            await message.answer("❌ Ошибка при создании подарка.")
    except Exception as e:
        logger.error(f"Ошибка при тестовом подарке подписки: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("gifts_clear"))
async def cmd_gifts_clear(message: Message):
    """команда для очистки всех подарков (только для админа)"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    try:
        count = await db.clear_all_gifts()
        await message.answer(
            f"✅ Таблица подарков очищена!\n\n"
            f"Удалено записей: {count}"
        )
    except Exception as e:
        logger.error(f"Ошибка при очистке таблицы подарков: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка при очистке: {e}")

