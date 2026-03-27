import logging
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database.models import Database
from prodamus.api import ProdamusAPI
from keyboards.inline import get_back_to_main, get_main_menu
from config import DATABASE_PATH, TARIFFS, CHANNEL_ID, GIFTS_ENABLED, PROMOCODES_ENABLED

logger = logging.getLogger(__name__)

router = Router()
db = Database(DATABASE_PATH)
prodamus_api = ProdamusAPI()

# приветственный текст для возврата в меню
WELCOME_TEXT = """Привет, рада тебя видеть!

Приглашаю в мужской журнал: ты можешь смотреть больше моих фотографий каждый день и читать статьи от специалистов по психологии для мужчин.

Здесь же будут зарядки, которые подходят мужчинам и женщинам. Подключайся к нашему журналу, это просто и совсем недорого =)"""


class PromocodeStates(StatesGroup):
    waiting_for_promocode = State()


class GiftSubscriptionStates(StatesGroup):
    waiting_for_recipient = State()


class PaymentStates(StatesGroup):
    waiting_for_email = State()
    waiting_for_phone = State()


def _normalize_phone(raw_phone: str) -> str | None:
    """проверяет номер строго в формате +79991234567"""
    if not raw_phone:
        return None
    cleaned = raw_phone.strip()
    if len(cleaned) == 12 and cleaned.startswith("+7") and cleaned[2:].isdigit():
        return cleaned
    return None


async def _safe_delete_user_message(message: Message):
    """удаляет сообщение пользователя, если возможно"""
    try:
        await message.delete()
    except Exception:
        # сообщение может быть уже удалено или недоступно к удалению
        pass


async def _render_payment_menu(
    message: Message,
    state: FSMContext,
    text: str,
    reply_markup: InlineKeyboardMarkup
) -> None:
    """обновляет одно меню оплаты, при необходимости создает новое"""
    state_data = await state.get_data()
    menu_message_id = state_data.get("payment_menu_message_id")
    chat_id = message.chat.id

    if menu_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=chat_id,
                message_id=menu_message_id,
                text=text,
                reply_markup=reply_markup
            )
            return
        except Exception:
            # если старое меню недоступно, создаем новое и перезаписываем id
            pass

    sent = await message.answer(text, reply_markup=reply_markup)
    await state.update_data(payment_menu_message_id=sent.message_id)


@router.callback_query(F.data.startswith("tariff_"))
async def callback_tariff_selected(callback: CallbackQuery, state: FSMContext):
    """обработчик выбранного тарифа - запрос email перед оплатой"""
    tariff_type = callback.data.replace("tariff_", "")
    
    if tariff_type not in TARIFFS:
        await callback.answer("❌ Неверный тариф", show_alert=True)
        return
    
    tariff_info = TARIFFS[tariff_type]
    
    await callback.answer()
    await state.update_data(
        tariff_type=tariff_type,
        payment_menu_message_id=callback.message.message_id
    )
    await state.set_state(PaymentStates.waiting_for_email)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="subscription")]
    ])
    
    await callback.message.edit_text(
        f"📧 Введите ваш email для оформления подписки:\n\n"
        f"Тариф: {tariff_info['name']} — {tariff_info['price']}₽\n\n"
        f"Email нужен для управления подпиской и получения чеков.",
        reply_markup=keyboard
    )


@router.message(PaymentStates.waiting_for_email)
async def process_email_for_payment(message: Message, state: FSMContext):
    """обработка введённого email и переход к вводу телефона"""
    import re
    
    email = (message.text or "").strip().lower()
    
    # простая валидация email
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_regex, email):
        await _safe_delete_user_message(message)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="subscription")]
        ])
        await _render_payment_menu(
            message,
            state,
            "❌ Неверный формат email. Попробуйте ещё раз:\n\n"
            "Пример: example@mail.ru",
            reply_markup=keyboard
        )
        return
    
    data = await state.get_data()
    tariff_type = data.get("tariff_type")
    
    if not tariff_type or tariff_type not in TARIFFS:
        await _safe_delete_user_message(message)
        await state.clear()
        await message.answer("❌ Ошибка: тариф не найден. Попробуйте снова.")
        return
    
    await _safe_delete_user_message(message)
    await state.update_data(customer_email=email)
    await state.set_state(PaymentStates.waiting_for_phone)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="subscription")]
    ])
    await _render_payment_menu(
        message,
        state,
        "📱 Теперь введите номер телефона строго в формате +79991234567.\n\n"
        "Пример: +79991234567\n\n"
        "Телефон нужен для привязки клиента в платежной системе.",
        reply_markup=keyboard
    )


@router.message(PaymentStates.waiting_for_phone)
async def process_phone_for_payment(message: Message, state: FSMContext):
    """обработка введённого телефона и создание ссылки на оплату"""
    phone = _normalize_phone(message.text or "")
    if not phone:
        await _safe_delete_user_message(message)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="subscription")]
        ])
        await _render_payment_menu(
            message,
            state,
            "❌ Неверный формат телефона. Нужен строго формат +79991234567.\n\n"
            "Пример: +79991234567",
            reply_markup=keyboard
        )
        return

    data = await state.get_data()
    tariff_type = data.get("tariff_type")
    email = data.get("customer_email")

    if not tariff_type or tariff_type not in TARIFFS or not email:
        await _safe_delete_user_message(message)
        await state.clear()
        await message.answer("❌ Ошибка: данные оплаты потеряны. Попробуйте снова.")
        return

    await _safe_delete_user_message(message)
    user_id = message.from_user.id
    tariff_info = TARIFFS[tariff_type]

    # показываем статус в одном и том же сообщении-меню
    loading_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="subscription")]
    ])
    await _render_payment_menu(message, state, "⏳ Создаю ссылку на оплату...", loading_keyboard)

    # создаем ссылку на оплату с email и телефоном
    payment_url = await prodamus_api.create_payment_link(
        user_id=user_id,
        tariff_type=tariff_type,
        tariff_price=tariff_info["price"],
        tariff_name=tariff_info["name"],
        duration_days=tariff_info["duration_days"],
        customer_email=email,
        customer_phone=phone
    )

    if not payment_url:
        text = "❌ Ошибка создания ссылки на оплату.\n\nПопробуйте ещё раз или обратитесь в поддержку."
        await _render_payment_menu(message, state, text, get_back_to_main())
        await state.clear()
        return

    text = f"""💳 Оплата подписки "{tariff_info['name']}"

📧 Email: {email}
📱 Телефон: {phone}
💰 Сумма: {tariff_info['price']}₽

Нажмите на кнопку ниже, чтобы перейти к оплате."""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Перейти к оплату", url=payment_url)],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="subscription")],
    ])
    
    await _render_payment_menu(message, state, text, keyboard)
    await state.clear()


@router.callback_query(F.data.startswith("promo_"))
async def callback_apply_promocode(callback: CallbackQuery, state: FSMContext):
    """обработчик кнопки 'применить промокод'"""
    if not PROMOCODES_ENABLED:
        await callback.answer("🚫 Промокоды временно недоступны", show_alert=True)
        return
    
    tariff_type = callback.data.replace("promo_", "")
    
    if tariff_type not in TARIFFS:
        await callback.answer("❌ Неверный тариф", show_alert=True)
        return
    
    await callback.answer()
    await state.update_data(tariff_type=tariff_type)
    await state.set_state(PromocodeStates.waiting_for_promocode)
    
    text = "🎟️ Введите промокод:\n\n(Для отмены отправьте /cancel)"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel_promo_{tariff_type}")],
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("cancel_promo_"))
async def callback_cancel_promocode(callback: CallbackQuery, state: FSMContext):
    """отмена ввода промокода"""
    tariff_type = callback.data.replace("cancel_promo_", "")
    
    await callback.answer()
    await state.clear()
    
    if tariff_type not in TARIFFS:
        await callback.message.edit_text("❌ Ошибка: неверный тариф.", reply_markup=get_back_to_main())
        return
    
    tariff_info = TARIFFS[tariff_type]
    user_id = callback.from_user.id
    
    await callback.message.edit_text("⏳ Создаю ссылку на оплату...")
    
    payment_url = await prodamus_api.create_payment_link(
        user_id=user_id,
        tariff_type=tariff_type,
        tariff_price=tariff_info["price"],
        tariff_name=tariff_info["name"],
        duration_days=tariff_info["duration_days"]
    )
    
    if not payment_url:
        text = "❌ Ошибка создания ссылки на оплату.\n\nПопробуйте ещё раз или обратитесь в поддержку."
        await callback.message.edit_text(text, reply_markup=get_back_to_main())
        return
    
    text = f"""💳 Оплата подписки "{tariff_info['name']}"

💰 Сумма: {tariff_info['price']}₽

Нажмите на кнопку ниже, чтобы перейти к оплате."""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_url)],
        # [InlineKeyboardButton(text="🎟️ Применить промокод", callback_data=f"promo_{tariff_type}")],  # временно скрыто
        [InlineKeyboardButton(text="◀️ Назад", callback_data="subscription")],
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data == "gift_select_tariff")
async def callback_gift_select_tariff(callback: CallbackQuery, state: FSMContext):
    """обработчик кнопки 'подарить подписку' - показывает выбор тарифа"""
    if not GIFTS_ENABLED:
        await callback.answer("🚫 Подарки временно недоступны", show_alert=True)
        return
    
    await callback.answer()
    await state.update_data(gift_return_to="main_menu")
    
    text = "🎁 Подарить подписку\n\nВыберите тариф для подарка:"
    
    tariff_buttons = []
    if 'monthly' in TARIFFS:
        tariff_buttons.append([
            InlineKeyboardButton(
                text=f"{TARIFFS['monthly']['name']} - {TARIFFS['monthly']['price']}₽",
                callback_data="gift_monthly"
            )
        ])
    if 'lifetime' in TARIFFS:
        tariff_buttons.append([
            InlineKeyboardButton(
                text=f"{TARIFFS['lifetime']['name']} - {TARIFFS['lifetime']['price']}₽",
                callback_data="gift_lifetime"
            )
    ])
    tariff_buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="gift_back")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=tariff_buttons)
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data.in_(["gift_monthly", "gift_lifetime"]))
async def callback_gift_subscription(callback: CallbackQuery, state: FSMContext):
    """обработчик выбранного тарифа для подарка"""
    tariff_type = callback.data.replace("gift_", "")
    
    if tariff_type not in TARIFFS:
        await callback.answer("❌ Неверный тариф", show_alert=True)
        return
    
    await callback.answer()
    await state.update_data(tariff_type=tariff_type, gift_return_to="main_menu")
    await state.set_state(GiftSubscriptionStates.waiting_for_recipient)
    
    text = "🎁 Подарить подписку\n\nВведите username (например: @username) или ID пользователя, которому хотите подарить подписку:\n\n(Для отмены отправьте /cancel)"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel_gift_{tariff_type}")],
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data == "gift_back")
async def callback_gift_back(callback: CallbackQuery, state: FSMContext):
    """обработчик кнопки 'назад' в процессе подарка - возврат в главное меню"""
    await callback.answer()
    await state.clear()
    
    await callback.message.edit_text(WELCOME_TEXT, reply_markup=get_main_menu())


@router.callback_query(F.data.startswith("cancel_gift_"))
async def callback_cancel_gift(callback: CallbackQuery, state: FSMContext):
    """отмена ввода получателя подарка - возврат в главное меню"""
    await callback.answer()
    await state.clear()
    
    await callback.message.edit_text(WELCOME_TEXT, reply_markup=get_main_menu())


@router.message(GiftSubscriptionStates.waiting_for_recipient)
async def process_gift_recipient(message: Message, state: FSMContext, bot: Bot):
    """обработка введенного username/id получателя подарка"""
    if not GIFTS_ENABLED:
        await message.answer("🚫 Подарки временно недоступны")
        await state.clear()
        return
    
    recipient_input = message.text.strip()
    
    data = await state.get_data()
    tariff_type = data.get("tariff_type")
    
    if tariff_type not in TARIFFS:
        await message.answer("❌ Ошибка: неверный тариф. Начните заново.")
        await state.clear()
        return
    
    tariff_info = TARIFFS[tariff_type]
    
    recipient_user_id = None
    recipient_username = None
    
    if recipient_input.startswith("@"):
        recipient_username = recipient_input[1:]
    else:
        try:
            recipient_user_id = int(recipient_input)
        except ValueError:
            await message.answer(
                "❌ Неверный формат!\n\n"
                "Введите username (например: @username) или числовой ID пользователя.\n\n"
                "Для отмены отправьте /cancel"
            )
            return
    
    if recipient_user_id and recipient_user_id == message.from_user.id:
        await message.answer("❌ Нельзя подарить подписку самому себе! 😄\n\nВведите другого получателя или отправьте /cancel для отмены.")
        return
    
    if recipient_username and message.from_user.username and recipient_username.lower() == message.from_user.username.lower():
        await message.answer("❌ Нельзя подарить подписку самому себе! 😄\n\nВведите другого получателя или отправьте /cancel для отмены.")
        return
    
    giver_user_id = message.from_user.id
    
    import time
    order_id = f"tg_{giver_user_id}_gift_{tariff_type}_{int(time.time())}"
    
    await message.answer("⏳ Создаю ссылку на оплату подарка...")
    
    payment_url = await prodamus_api.create_payment_link(
        user_id=giver_user_id,
        tariff_type=tariff_type,
        tariff_price=tariff_info["price"],
        tariff_name=tariff_info["name"],
        duration_days=tariff_info["duration_days"],
        order_id_override=order_id
    )
    
    if not payment_url:
        await message.answer("❌ Ошибка создания ссылки на оплату.\n\nПопробуйте ещё раз или обратитесь в поддержку.")
        await state.clear()
        return
    
    try:
        success = await db.save_order_gift(
            order_id=order_id,
            recipient_user_id=recipient_user_id,
            recipient_username=recipient_username,
            giver_user_id=giver_user_id,
            tariff_type=tariff_type
        )
        
        if success:
            recipient_info = f"@{recipient_username}" if recipient_username else (f"ID {recipient_user_id}" if recipient_user_id else "неизвестно")
            logger.info(f"Подарок подписки создан: пользователь {giver_user_id} дарит {tariff_type} подписку получателю {recipient_info}, order_id={order_id}")
            
            text = f"""🎁 Подарок подписки

Получатель: {recipient_info}
📦 Тариф: {tariff_info['name']}
💰 Сумма: {tariff_info['price']}₽

После оплаты подписка будет автоматически активирована для получателя."""
            
            data = await state.get_data()
            return_to = data.get("gift_return_to", "main_menu")
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_url)],
                [InlineKeyboardButton(text="◀️ Назад", callback_data=return_to)],
            ])
            
            await message.answer(text, reply_markup=keyboard)
        else:
            await message.answer("❌ Ошибка при создании подарка. Попробуйте еще раз или обратитесь в поддержку.")
    except Exception as e:
        logger.error(f"Ошибка при создании подарка: {e}", exc_info=True)
        await message.answer("❌ Ошибка при создании подарка. Попробуйте еще раз или обратитесь в поддержку.")
    
    await state.clear()


@router.message(PromocodeStates.waiting_for_promocode)
async def process_promocode(message: Message, state: FSMContext):
    """обработка введенного промокода"""
    if not PROMOCODES_ENABLED:
        await message.answer("🚫 Промокоды временно недоступны")
        await state.clear()
        return
    
    promocode = message.text.strip()
    
    import re
    if not re.match(r'^[A-ZА-ЯЁa-zа-яё0-9_-]+$', promocode, re.UNICODE):
        await message.answer(
            "❌ Неверный формат промокода!\n\n"
            "Промокод должен содержать только буквы, цифры, дефис и подчеркивание.\n\n"
            "Попробуйте ввести другой промокод или отправьте /cancel для отмены."
        )
        return
    
    promocode = promocode.upper()
    
    promo = await db.get_promocode(promocode)
    
    if not promo:
        await message.answer("❌ Промокод не найден или недействителен.\n\nПопробуйте ввести другой промокод или отправьте /cancel для отмены.")
        return
    
    data = await state.get_data()
    tariff_type = data.get("tariff_type")
    
    if tariff_type not in TARIFFS:
        await message.answer("❌ Ошибка: неверный тариф. Начните заново.")
        await state.clear()
        return
    
    tariff_info = TARIFFS[tariff_type]
    user_id = message.from_user.id
    
    discount_amount = promo["discount_amount"]
    
    await message.answer("⏳ Создаю ссылку на оплату с промокодом...")
    
    payment_url = await prodamus_api.create_payment_link(
        user_id=user_id,
        tariff_type=tariff_type,
        tariff_price=tariff_info["price"],
        tariff_name=tariff_info["name"],
        duration_days=tariff_info["duration_days"],
        promocode=promocode,
        discount_amount=discount_amount
    )
    
    if not payment_url:
        await message.answer("❌ Ошибка создания ссылки на оплату.\n\nПопробуйте ещё раз или обратитесь в поддержку.")
        await state.clear()
        return
    
    original_price = tariff_info["price"]
    final_price = max(0, original_price - discount_amount)
    
    text = f"""💳 Оплата подписки "{tariff_info['name']}"

🎟️ Промокод: {promocode}
💵 Скидка: {discount_amount}₽
Цена: {original_price}₽ → {final_price}₽
Скидка применяется только на первый месяц

Нажмите на кнопку ниже, чтобы перейти к оплате."""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_url)],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="subscription")],
    ])
    
    await message.answer(text, reply_markup=keyboard)
    await state.clear()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """отмена текущей операции"""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("❌ Нет активных операций для отмены.")
        return
    
    await state.clear()
    await message.answer("✅ Операция отменена.")


@router.callback_query(F.data == "unsubscribe")
async def callback_unsubscribe(callback: CallbackQuery):
    """обработчик отписки"""
    from config import CHANNEL_ID
    
    user_id = callback.from_user.id
    
    subscription = await db.get_user_subscription(user_id)
    
    if not subscription:
        await callback.answer("❌ У вас нет активной подписки", show_alert=True)
        return
    
    tariff_type = subscription.get("tariff_type")
    subscription_id = subscription.get("prodamus_subscription_id")
    customer_email = subscription.get("customer_email")
    customer_phone = subscription.get("customer_phone")
    
    if tariff_type not in ["lifetime", "trial"] and subscription_id:
        try:
            # используем email для отписки (tg_user_id не используется для подписи)
            if customer_email:
                success, error_msg = await prodamus_api.set_subscription_activity(
                    subscription=str(subscription_id),
                    customer_email=customer_email,
                    customer_phone=customer_phone,
                    active=False,
                    as_manager=True
                )
                if not success:
                    logger.warning(f"Не удалось отменить подписку через Prodamus API для пользователя {user_id}: {error_msg}")
                else:
                    logger.info(f"✅ Подписка отменена в Prodamus для пользователя {user_id}, email={customer_email}")
            else:
                logger.warning(f"Нет email для отмены подписки в Prodamus, user_id={user_id}")
        except Exception as e:
            logger.error(f"Ошибка при отмене подписки в Prodamus: {e}")
    
    await db.deactivate_subscription(user_id)
    
    try:
        if CHANNEL_ID:
            bot = callback.bot
            await bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
    except Exception as e:
        logger.error(f"Ошибка при удалении пользователя {user_id} из канала: {e}", exc_info=True)
    
    text = "❌ Вы отписались от канала. Доступ прекращен."
    await callback.message.edit_text(text, reply_markup=get_back_to_main())
    await callback.answer()
