import logging
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database.models import Database
from prodamus.api import ProdamusAPI
from keyboards.inline import get_back_to_main, get_main_menu
from keyboards.reply import get_phone_request_keyboard
from config import DATABASE_PATH, TARIFFS, GIFTS_ENABLED, PROMOCODES_ENABLED
from handlers.common import WELCOME_TEXT

logger = logging.getLogger(__name__)

router = Router()
db = Database(DATABASE_PATH)
prodamus_api = ProdamusAPI()


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

    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="subscription")]
    ])
    await _render_payment_menu(
        message,
        state,
        "📱 Поделитесь номером через кнопку ниже или введите вручную в формате +79991234567.\n\n"
        "Телефон нужен для привязки клиента в платежной системе.",
        reply_markup=inline_kb,
    )
    # отдельное сообщение с reply-кнопкой (нельзя добавить к edit_message)
    phone_kb_msg = await message.answer(
        "👇",
        reply_markup=get_phone_request_keyboard(),
    )
    await state.update_data(phone_kb_msg_id=phone_kb_msg.message_id)


async def _clear_phone_keyboard(message: Message, state: FSMContext):
    """удаляем reply-кнопку шера и убираем reply keyboard через ReplyKeyboardRemove"""
    from aiogram.types import ReplyKeyboardRemove as RKR
    data = await state.get_data()
    phone_kb_msg_id = data.get("phone_kb_msg_id")
    # удаляем сообщение с reply-кнопкой
    if phone_kb_msg_id:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=phone_kb_msg_id)
        except Exception:
            pass
    # убираем reply keyboard служебным сообщением (иначе не пропадёт)
    try:
        tmp = await message.answer(".", reply_markup=RKR())
        await tmp.delete()
    except Exception:
        pass


@router.message(PaymentStates.waiting_for_phone, F.contact)
async def process_contact_for_payment(message: Message, state: FSMContext):
    """обработка шера контакта из Telegram"""
    await _clear_phone_keyboard(message, state)
    await _safe_delete_user_message(message)

    contact = message.contact
    raw = contact.phone_number or ""
    # нормализация: 79... → +79..., 89... → +79...
    digits = raw.replace("+", "").replace(" ", "").replace("-", "")
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    normalized = f"+{digits}" if digits else ""
    phone = _normalize_phone(normalized)

    if not phone:
        inline_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="subscription")]
        ])
        await _render_payment_menu(
            message,
            state,
            "❌ Не удалось распознать номер из контакта. Введите вручную в формате +79991234567:",
            reply_markup=inline_kb,
        )
        phone_kb_msg = await message.answer("👇", reply_markup=get_phone_request_keyboard())
        await state.update_data(phone_kb_msg_id=phone_kb_msg.message_id)
        return

    await _process_phone_and_pay(message, state, phone)


@router.message(PaymentStates.waiting_for_phone)
async def process_phone_for_payment(message: Message, state: FSMContext):
    """обработка введённого вручную телефона"""
    await _clear_phone_keyboard(message, state)
    phone = _normalize_phone(message.text or "")
    await _safe_delete_user_message(message)

    if not phone:
        inline_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="subscription")]
        ])
        await _render_payment_menu(
            message,
            state,
            "❌ Неверный формат. Нужен строго формат +79991234567.\n\nИли нажмите кнопку 👇",
            reply_markup=inline_kb,
        )
        phone_kb_msg = await message.answer("👇", reply_markup=get_phone_request_keyboard())
        await state.update_data(phone_kb_msg_id=phone_kb_msg.message_id)
        return

    await _process_phone_and_pay(message, state, phone)


async def _process_phone_and_pay(message: Message, state: FSMContext, phone: str):
    """общая логика после получения валидного телефона"""

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

⚠️ Перед оплатой отключите VPN.

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
    
    # TODO: при включении промокодов — сохранять email/phone в state из promo-flow
    # и передавать их сюда. Сейчас промокоды отключены (PROMOCODES_ENABLED=False).
    # Без email/phone подпись Prodamus будет отличаться.
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

⚠️ Перед оплатой отключите VPN.

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
    
    has_sub = await db.get_user_subscription(callback.from_user.id) is not None
    await callback.message.edit_text(WELCOME_TEXT, reply_markup=get_main_menu(has_sub))


@router.callback_query(F.data.startswith("cancel_gift_"))
async def callback_cancel_gift(callback: CallbackQuery, state: FSMContext):
    """отмена ввода получателя подарка - возврат в главное меню"""
    await callback.answer()
    await state.clear()

    has_sub = await db.get_user_subscription(callback.from_user.id) is not None
    await callback.message.edit_text(WELCOME_TEXT, reply_markup=get_main_menu(has_sub))


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
    
    # TODO: при включении подарков — собирать email/phone дарителя и передавать сюда.
    # Сейчас подарки отключены (GIFTS_ENABLED=False).
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
    
    # TODO: при включении промокодов — передавать email/phone из FSM-state.
    # Сейчас промокоды отключены (PROMOCODES_ENABLED=False).
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

⚠️ Перед оплатой отключите VPN.

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

    # если были в ожидании телефона — убираем reply keyboard
    if current_state == PaymentStates.waiting_for_phone.state:
        await _clear_phone_keyboard(message, state)

    await state.clear()
    await message.answer("✅ Операция отменена.")


@router.callback_query(F.data == "unsubscribe")
async def callback_unsubscribe(callback: CallbackQuery):
    """обработчик отписки"""
    user_id = callback.from_user.id
    
    subscription = await db.get_user_subscription(user_id)
    
    if not subscription:
        await callback.answer("❌ У вас нет активной подписки", show_alert=True)
        return
    
    tariff_type = subscription.get("tariff_type")
    subscription_id = subscription.get("prodamus_subscription_id")
    customer_email = subscription.get("customer_email")
    customer_phone = subscription.get("customer_phone")
    
    # для рекуррентной подписки с привязкой к Prodamus сначала глушим API; при ошибке не трогаем БД и канал
    # ручная выдача (/adduser): subscription_id нет — Prodamus не вызываем, отписка в боте проходит как раньше
    prodamus_ok = True
    prodamus_error = None

    if tariff_type not in ["lifetime", "trial"] and subscription_id:
        if not customer_email:
            prodamus_ok = False
            prodamus_error = "В профиле нет email для отмены в Prodamus."
            logger.warning(f"Нет email для отмены подписки в Prodamus, user_id={user_id}")
        else:
            try:
                success, error_msg = await prodamus_api.set_subscription_activity(
                    subscription=str(subscription_id),
                    customer_email=customer_email,
                    customer_phone=customer_phone,
                    active=False,
                    as_manager=True
                )
                # подписка могла быть создана только с email — повтор без телефона
                if not success and customer_phone:
                    logger.info("setActivity не прошёл с телефоном, пробую только email")
                    success, error_msg = await prodamus_api.set_subscription_activity(
                        subscription=str(subscription_id),
                        customer_email=customer_email,
                        customer_phone=None,
                        active=False,
                        as_manager=True
                    )
                if not success:
                    prodamus_ok = False
                    prodamus_error = error_msg or "ошибка Prodamus"
                    logger.warning(
                        f"Не удалось отменить подписку через Prodamus API для пользователя {user_id}: {prodamus_error}"
                    )
                else:
                    logger.info(f"✅ Подписка отменена в Prodamus для пользователя {user_id}, email={customer_email}")
            except Exception as e:
                prodamus_ok = False
                prodamus_error = str(e)
                logger.error(f"Ошибка при отмене подписки в Prodamus: {e}")

    if not prodamus_ok:
        text = (
            "⚠️ По техническим причинам отменить платную подписку в платёжной системе не удалось.\n\n"
            "Ваша подписка сохранена.\n\n"
            "Напишите в техподдержку — помогут завершить отписку."
        )
        await callback.message.edit_text(text, reply_markup=get_back_to_main())
        await callback.answer()
        return

    await db.deactivate_subscription(user_id)

    text = "❌ Подписка отменена."
    await callback.message.edit_text(text, reply_markup=get_back_to_main())
    await callback.answer()
