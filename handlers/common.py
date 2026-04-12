from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
import os
import aiosqlite
from database.models import Database
from keyboards.inline import (
    get_main_menu,
    get_about_channel_menu,
    get_subscription_menu,
    get_tariffs_menu,
    get_tariffs_text,
    get_back_to_main,
)
from keyboards.reply import get_start_keyboard
from utils.texts import (
    get_about_channel_text,
    get_requisites_text,
    get_subscription_status_text,
)
from config import DATABASE_PATH, CHANNEL_ID, WELCOME_PHOTO_PATH

router = Router()
db = Database(DATABASE_PATH)

# приветственный текст бота
WELCOME_TEXT = """Приветствую, друзья!

Терапевтическая рассылка от меня — это ваш личный проводник в мир глубинной психологии и реальных изменений.
Каждую неделю вы будете получать от меня послание на определенную тему.
Это не просто теория, а практический инструмент!

Мои письма - это ваш шанс наконец разобраться в себе, будь вы в активной зависимости, в ремиссии или просто хотите лучше понимать свою психику.
Присоединяйтесь к сообществу людей, которые меняют свою жизнь через глубокое самопознание 🤝"""


async def _send_welcome_photo_then_text(message: Message, has_sub: bool) -> None:
    """сначала фото приветствия, затем текст с главным меню"""
    import logging

    logger = logging.getLogger(__name__)
    try:
        if WELCOME_PHOTO_PATH.is_file():
            await message.answer_photo(FSInputFile(WELCOME_PHOTO_PATH))
        else:
            logger.warning("фото приветствия не найдено: %s", WELCOME_PHOTO_PATH)
    except Exception as e:
        logger.error("ошибка отправки фото приветствия: %s", e, exc_info=True)
    await message.answer(WELCOME_TEXT, reply_markup=get_main_menu(has_sub))


@router.message(CommandStart())
async def cmd_start(message: Message):
    """обработчик команды /start"""
    import logging
    logger = logging.getLogger(__name__)
    
    user = message.from_user
    
    # добавляем пользователя в БД
    await db.add_user(user.id, user.username, user.first_name)
    
    # проверяем параметры команды (для редиректа после оплаты)
    args = None
    if message.text and len(message.text.split()) > 1:
        args = message.text.split()[1]
    
    logger.info(f"Команда /start от пользователя {user.id} (@{user.username}), args={args}")
    
    if args == "payment_success":
        subscription = await db.get_user_subscription(user.id)
        logger.info(f"Редирект после успешной оплаты для пользователя {user.id}, подписка в БД: {subscription is not None}")
        
        if subscription:
            text = "✅ Оплата успешно обработана!\n\nПодписка активирована, рассылка придёт в этот чат по расписанию."
            has_sub = True
        else:
            text = "✅ Оплата получена!\n\nОбрабатываю платеж... Скоро придёт уведомление от бота."
            has_sub = False

        await message.answer(text, reply_markup=get_main_menu(has_sub))
        return
    elif args == "payment_fail":
        logger.info(f"Редирект после неудачной оплаты для пользователя {user.id}")
        text = "❌ Оплата не прошла. Попробуйте еще раз или обратитесь в поддержку."
        fail_sub = await db.get_user_subscription(user.id)
        await message.answer(text, reply_markup=get_main_menu(fail_sub is not None))
        return

    has_sub = await db.get_user_subscription(user.id) is not None
    await _send_welcome_photo_then_text(message, has_sub)


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    """обработчик команды /menu - возврат в главное меню"""
    has_sub = await db.get_user_subscription(message.from_user.id) is not None
    await message.answer(WELCOME_TEXT, reply_markup=get_main_menu(has_sub))


@router.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery):
    """обработчик возврата в главное меню"""
    import logging
    logger = logging.getLogger(__name__)
    
    await callback.answer()

    has_sub = await db.get_user_subscription(callback.from_user.id) is not None
    try:
        # редактируем текущее сообщение
        await callback.message.edit_text(WELCOME_TEXT, reply_markup=get_main_menu(has_sub))
    except Exception as e:
        logger.warning(f"Ошибка редактирования сообщения: {e}")
        # если не удалось отредактировать, отправляем новое
        await callback.message.answer(WELCOME_TEXT, reply_markup=get_main_menu(has_sub))


@router.message(Command("activate"))
async def cmd_activate(message: Message, bot: Bot):
    """команда для активации бесплатного периода для существующих участников канала"""
    from aiogram.enums import ChatMemberStatus
    import logging
    logger = logging.getLogger(__name__)
    
    user_id = message.from_user.id
    user = message.from_user
    
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    
    ACTIVATE_PASSWORD = "cloud"
    if not args or args[0].lower() != ACTIVATE_PASSWORD:
        await message.answer(
            "🔐 Для активации бесплатного периода требуется пароль.\n\n"
            f"Использование: /activate <пароль>\n\n"
            "Обратитесь к администратору для получения пароля."
        )
        return
    
    await db.add_user(user_id, user.username, user.first_name)
    
    existing = await db.get_user_subscription(user_id)
    if existing:
        is_trial = await db.is_trial_subscription(existing)
        if is_trial:
            await message.answer(
                "✅ У вас уже активирован бесплатный период!\n\n"
                "Используйте меню бота для управления."
            )
        else:
            await message.answer(
                "✅ У вас уже есть активная подписка!\n\n"
                "Используйте меню бота для управления подпиской."
            )
        return
    
    if not CHANNEL_ID:
        await message.answer(
            "❌ Ошибка конфигурации: CHANNEL_ID не установлен.\n"
            "Обратитесь к администратору."
        )
        return
    
    try:
        chat_member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        status = chat_member.status
        
        is_member = status in [
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR
        ]
        
        if not is_member:
            await message.answer(
                "❌ Вы не являетесь участником закрытого канала.\n\n"
                "Эта команда предназначена только для существующих участников, "
                "которые были добавлены до запуска нового бота.\n\n"
                "Если вы были участником ранее, убедитесь, что вы все еще в канале, "
                "или обратитесь к администратору."
            )
            return
        
        success = await db.create_free_period(
            user_id=user_id,
            duration_days=30
        )
        
        if success:
            await message.answer(
                "✅ Бесплатный период успешно активирован!\n\n"
                "Вы получили доступ на 30 дней для перехода на новый бот.\n\n"
                "⚠️ По окончании бесплатного периода необходимо оплатить подписку в боте.\n\n"
                "Теперь вы можете использовать все функции бота. "
                "Статус подписки — в разделе «Подписка»."
            )
            logger.info(f"✅ Активация бесплатного периода для пользователя {user_id} через /activate")
        else:
            await message.answer(
                "⚠️ Не удалось активировать бесплатный период.\n\n"
                "Возможно, у вас уже есть активная подписка или произошла ошибка.\n"
                "Обратитесь к администратору."
            )
    
    except Exception as e:
        logger.error(f"Ошибка при активации бесплатного периода для пользователя {user_id}: {e}", exc_info=True)
        await message.answer(
            "❌ Произошла ошибка при активации бесплатного периода.\n\n"
            "Обратитесь к администратору для ручной активации."
        )


@router.message(F.text == "Старт")
async def handle_start_button(message: Message):
    """обработчик кнопки 'Старт' из обычной клавиатуры"""
    import logging
    logger = logging.getLogger(__name__)
    
    user = message.from_user
    await db.add_user(user.id, user.username, user.first_name)

    has_sub = await db.get_user_subscription(user.id) is not None
    await _send_welcome_photo_then_text(message, has_sub)


@router.callback_query(F.data == "about_channel")
async def callback_about_channel(callback: CallbackQuery):
    """обработчик раздела 'О журнале'"""
    await callback.answer()
    text = get_about_channel_text()
    await callback.message.edit_text(text, reply_markup=get_about_channel_menu())


@router.callback_query(F.data == "requisites")
async def callback_requisites(callback: CallbackQuery):
    """обработчик раздела 'Реквизиты'"""
    await callback.answer()
    text = get_requisites_text()
    await callback.message.edit_text(text, reply_markup=get_back_to_main())


@router.callback_query(F.data == "subscription")
async def callback_subscription(callback: CallbackQuery, state: FSMContext):
    """обработчик раздела 'Подписка'"""
    import logging
    logger = logging.getLogger(__name__)

    # если пользователь нажал «Отмена» в шаге ввода телефона — убираем reply keyboard
    try:
        from handlers.payment import PaymentStates, _clear_phone_keyboard
        cur = await state.get_state()
        if cur == PaymentStates.waiting_for_phone.state:
            await _clear_phone_keyboard(callback.message, state)
    except Exception:
        pass
    await state.clear()
    
    await callback.answer()
    
    user = callback.from_user
    user_id = user.id
    
    # проверяем подарки (только если функционал включён)
    from config import GIFTS_ENABLED
    pending_gift = None
    if GIFTS_ENABLED:
        pending_gift = await db.get_pending_gift(user_id, user.username)
        if pending_gift:
            logger.info(f"Найден неактивированный подарок для пользователя {user_id}: {pending_gift}")
            from config import TARIFFS
            tariff_type = pending_gift["tariff_type"]
            tariff_info = TARIFFS.get(tariff_type)
            
            if tariff_info:
                try:
                    await db.create_subscription(
                        user_id=user_id,
                        tariff_type=tariff_type,
                        duration_days=tariff_info["duration_days"],
                        prodamus_subscription_id=None,
                        prodamus_order_id=None
                    )
                    
                    if not pending_gift.get("recipient_user_id") and user_id:
                        async with aiosqlite.connect(db.db_path) as db_conn:
                            await db_conn.execute("""
                                UPDATE gifts 
                                SET recipient_user_id = ?
                                WHERE id = ?
                            """, (user_id, pending_gift["id"]))
                            await db_conn.commit()
                    
                    await db.activate_gift(pending_gift["id"])
                    logger.info(f"Активирован подарок для пользователя {user_id}: тариф {tariff_type}")
                    
                    from config import CHANNEL_ID
                    if CHANNEL_ID:
                        try:
                            bot = callback.bot
                            await bot.unban_chat_member(
                                chat_id=CHANNEL_ID,
                                user_id=user_id,
                                only_if_banned=False
                            )
                        except Exception as e:
                            logger.error(f"Ошибка при добавлении пользователя в канал: {e}", exc_info=True)
                except Exception as e:
                    logger.error(f"Ошибка при активации подарка: {e}", exc_info=True)
    
    subscription = await db.get_user_subscription(user_id)
    has_subscription = subscription is not None
    text = get_subscription_status_text(subscription)
    if has_subscription:
        from utils.newsletter_user_hint import get_subscription_newsletter_footer

        text += await get_subscription_newsletter_footer(db, user_id)

    if not has_subscription:
        await callback.message.edit_text(get_tariffs_text(), reply_markup=get_tariffs_menu())
    else:
        await callback.message.edit_text(text, reply_markup=get_subscription_menu(has_subscription))
