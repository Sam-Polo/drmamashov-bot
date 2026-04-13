import logging
from typing import Dict, Any
from aiogram import Bot
from database.models import Database
from prodamus.api import ProdamusAPI
from config import DATABASE_PATH, CHANNEL_ID, CHANNEL_INVITE_LINK

logger = logging.getLogger(__name__)


class ProdamusWebhookHandler:
    """обработчик webhook-уведомлений от Prodamus"""
    
    def __init__(self, bot: Bot):
        self.bot = bot
        self.db = Database(DATABASE_PATH)
        self.api = ProdamusAPI()
    
    async def handle_webhook(self, data: Dict[str, Any], signature: str) -> bool:
        """обработка webhook от Prodamus"""
        # проверяем подпись
        if not self.api.verify_webhook_signature(data, signature):
            logger.warning("❌ Неверная подпись webhook от Prodamus")
            return False
        
        payment_status = data.get("payment_status", "")
        order_id = data.get("order_id", "")
        order_num = data.get("order_num", "")
        action_code = data.get("subscription[action_code]") or data.get("action_code", "")
        
        # для тестовых запросов пропускаем обработку
        if order_id in ["1", "test"] or order_num in ["1", "test"]:
            return True
        
        # определяем user_id разными способами в зависимости от типа события
        user_id = None
        
        # для событий отмены/истечения подписки ищем по subscription_id или order_num
        if action_code in ["cancel", "expire"]:
            subscription_id = data.get("subscription_id") or data.get("subscription[id]")
            
            # пробуем найти по subscription_id
            if subscription_id:
                subscription = await self.db.get_subscription_by_subscription_id(str(subscription_id))
                if subscription:
                    user_id = subscription["user_id"]
            
            # если не нашли по subscription_id, пробуем по order_num
            if not user_id and order_num:
                subscription = await self.db.get_subscription_by_order_id(order_num)
                if subscription:
                    user_id = subscription["user_id"]
            
            # если все еще не нашли, пробуем извлечь из order_num (если формат tg_*)
            if not user_id and order_num and order_num.startswith("tg_"):
                try:
                    parts = order_num.split("_")
                    if len(parts) >= 2 and parts[0] == "tg":
                        user_id = int(parts[1])
                except (ValueError, IndexError) as e:
                    logger.error(f"Ошибка парсинга order_num: {order_num}: {e}")
            
            if not user_id:
                logger.error(f"Не удалось определить user_id для события {action_code}. Данные: subscription_id={subscription_id}, order_num={order_num}")
                return False
        else:
            # для других событий (оплата) извлекаем user_id из order_num
            if not order_num or not order_num.startswith("tg_"):
                logger.error(f"Неверный формат order_num: {order_num}")
                return False
            
            try:
                parts = order_num.split("_")
                if len(parts) >= 2 and parts[0] == "tg":
                    user_id = int(parts[1])
                else:
                    logger.error(f"Не удалось извлечь user_id из order_num: {order_num}")
                    return False
            except (ValueError, IndexError) as e:
                logger.error(f"Ошибка парсинга order_num: {order_num}: {e}")
                return False
        
        # обрабатываем разные типы событий
        if action_code == "auto_payment":
            await self._handle_auto_payment(user_id, data)
        elif payment_status == "success":
            await self._handle_payment_success(user_id, data)
        elif payment_status in ["failed", "error"]:
            await self._handle_payment_failed(user_id, data)
        elif action_code == "cancel":
            await self._handle_subscription_cancelled(user_id, data)
        elif action_code == "expire":
            await self._handle_subscription_expired(user_id, data)
        
        return True
    
    async def _handle_payment_success(self, user_id: int, data: Dict[str, Any]):
        """обработка успешной оплаты"""
        order_num = data.get("order_num", "")
        
        # определяем тип тарифа из order_num; порядок важен: half_year до monthly (содержит подстроку)
        tariff_type = None
        _ORDER_TARIFF_MAP = [
            ("quarterly", "quarterly"),
            ("half_year", "half_year"),
            ("annual", "annual"),
            ("lifetime", "lifetime"),
            ("monthly", "monthly"),
        ]
        for fragment, ttype in _ORDER_TARIFF_MAP:
            if fragment in order_num:
                tariff_type = ttype
                break
        
        if not tariff_type:
            logger.error(f"Не удалось определить тип тарифа из order_num: {order_num}")
            return
        
        # получаем subscription_id от Prodamus (если есть)
        subscription_id = data.get("subscription_id") or data.get("subscription[id]")
        
        # получаем order_id из данных (может отличаться от order_num)
        order_id = data.get("order_id", "")
        
        # получаем email клиента
        customer_email = data.get("customer_email", "")
        customer_phone = data.get("customer_phone", "")
        
        # проверяем, был ли использован промокод для этого заказа
        # пробуем сначала по order_num, потом по order_id
        order_promo = None
        if order_num:
            order_promo = await self.db.get_order_promocode(order_num)
            logger.info(f"Поиск промокода по order_num={order_num}: {'найден' if order_promo else 'не найден'}")
        if not order_promo and order_id:
            order_promo = await self.db.get_order_promocode(order_id)
            logger.info(f"Поиск промокода по order_id={order_id}: {'найден' if order_promo else 'не найден'}")
        
        if order_promo:
            logger.info(f"🎟️ Найден промокод для заказа: {order_promo.get('promocode')}, скидка: {order_promo.get('discount_amount')}₽")
        
        # проверяем, является ли это подарком
        # пробуем сначала по order_num, потом по order_id
        order_gift = None
        if order_num:
            order_gift = await self.db.get_order_gift(order_num)
            logger.info(f"Поиск подарка по order_num={order_num}: {'найден' if order_gift else 'не найден'}")
        if not order_gift and order_id:
            order_gift = await self.db.get_order_gift(order_id)
            logger.info(f"Поиск подарка по order_id={order_id}: {'найден' if order_gift else 'не найден'}")
        
        # определяем для кого создавать подписку - для плательщика или для получателя подарка
        recipient_user_id = user_id  # по умолчанию для плательщика
        is_gift = False
        if order_gift:
            is_gift = True
            logger.info(f"🎁 Найден подарок для заказа: получатель user_id={order_gift.get('recipient_user_id')}, username={order_gift.get('recipient_username')}")
            # если есть recipient_user_id - используем его
            if order_gift.get("recipient_user_id"):
                recipient_user_id = order_gift["recipient_user_id"]
                logger.info(f"Создаем подписку для получателя подарка: user_id={recipient_user_id}")
            elif order_gift.get("recipient_username"):
                # если только username - нужно найти user_id по username
                # но это сложно, лучше сохранить в gifts и активировать при входе
                # пока создаем подписку для плательщика, а подарок активируется при входе получателя
                logger.warning(f"Подарок с username {order_gift.get('recipient_username')} - подписка будет создана для плательщика, подарок активируется при входе получателя")
                # создаем подарок в таблице gifts для активации при входе
                await self.db.create_gift(
                    tariff_type=order_gift["tariff_type"],
                    giver_user_id=order_gift["giver_user_id"],
                    recipient_username=order_gift["recipient_username"]
                )
        
        # создаем подписку в БД
        from config import TARIFFS
        duration_days = TARIFFS[tariff_type]["duration_days"]
        
        try:
            # для подарков не сохраняем prodamus_subscription_id, т.к. получатель не подписан на списания
            # подписка будет истекать через duration_days и деактивироваться автоматически
            gift_subscription_id = None if is_gift else subscription_id
            gift_order_id = order_num if not is_gift else None  # для подарков order_id тоже не нужен, т.к. он относится к дарителю
            
            await self.db.create_subscription(
                recipient_user_id, 
                tariff_type, 
                duration_days,
                prodamus_subscription_id=gift_subscription_id,
                prodamus_order_id=gift_order_id,
                customer_email=customer_email if not is_gift else None,
                customer_phone=customer_phone if not is_gift else None
            )
            masked_phone = f"***{customer_phone[-4:]}" if customer_phone and len(customer_phone) >= 4 else "None"
            logger.info(
                f"Создана подписка для user_id={recipient_user_id}, tariff_type={tariff_type}, "
                f"is_gift={is_gift}, subscription_id={'None (подарок)' if is_gift else subscription_id}, "
                f"email={customer_email}, phone={masked_phone}"
            )
        except Exception as e:
            logger.error(f"Ошибка при создании подписки в БД: {e}", exc_info=True)
            return
        
        # промокод применяется через demo_period и discount_amount при создании ссылки
        # дополнительное применение скидки через API не требуется
        if order_promo:
            logger.info(f"🎟️ Промокод {order_promo.get('promocode')} применен при создании ссылки (скидка: {order_promo.get('discount_amount')}₽ на первый месяц)")
        
        # разбаниваем получателя подарка (если это подарок) или плательщика
        logger.info(f"🔓 Начинаем разбан пользователя {recipient_user_id}, CHANNEL_ID={CHANNEL_ID}")
        try:
            channel_link = (CHANNEL_INVITE_LINK or "").strip() or None
            if not channel_link:
                logger.warning("⚠️ CHANNEL_INVITE_LINK не установлен в конфиге")
            
            # разбаниваем пользователя, чтобы он мог вернуться по ссылке
            # убираем из списка banned/removed users
            if CHANNEL_ID:
                logger.info(f"🔓 Попытка разбана пользователя {user_id} в канале {CHANNEL_ID}")
                try:
                    # для каналов нужно использовать unban_chat_member без параметров
                    # это уберет пользователя из списка removed users
                    await self.bot.unban_chat_member(
                        chat_id=CHANNEL_ID,
                        user_id=recipient_user_id,
                        only_if_banned=False
                    )
                    logger.info(f"✅ Пользователь {recipient_user_id} разбанен в канале")
                except Exception as e:
                    error_msg = str(e).lower()
                    # админов канала нельзя банить/разбанивать - это нормально
                    if "administrator" in error_msg:
                        logger.info(f"ℹ️ Пользователь {recipient_user_id} является админом канала, разбан не требуется")
                    else:
                        # для остальных ошибок пробуем альтернативный способ
                        logger.warning(f"⚠️ Ошибка при разбане пользователя {recipient_user_id}: {e}")
                        try:
                            logger.info(f"🔄 Попытка альтернативного разбана для user_id={recipient_user_id}")
                            await self.bot.unban_chat_member(chat_id=CHANNEL_ID, user_id=recipient_user_id)
                            logger.info(f"✅ Пользователь {recipient_user_id} разбанен (альтернативный способ)")
                        except Exception as e2:
                            if "administrator" in str(e2).lower():
                                logger.info(f"ℹ️ Пользователь {recipient_user_id} является админом канала")
                            else:
                                logger.error(f"❌ Не удалось разбанить пользователя {recipient_user_id}: {e2}")
            else:
                logger.warning(f"⚠️ CHANNEL_ID не установлен, разбан пропущен")
            
            # отправляем сообщение получателю подарка (если это подарок) или плательщику
            if is_gift:
                # отправляем сообщение получателю подарка
                try:
                    await self.bot.send_message(
                        chat_id=recipient_user_id,
                        text="🎁 Вам подарили подписку!\n\n✅ Подписка активирована.\n\n📬 Материалы рассылки приходят в этот чат по графику.",
                    )
                except Exception as e:
                    logger.warning(f"Не удалось отправить сообщение получателю подарка {recipient_user_id}: {e}")

            # отправляем сообщение плательщику (дарителю)
            try:
                # формируем текст сообщения (продукт: рассылка + опционально канал)
                if is_gift:
                    payment_text = (
                        "✅ Оплата успешно получена!\n\n"
                        "🎁 Подарок оплачен, получатель уведомлён.\n\n"
                        "Материалы программы уходят в чат с ботом по расписанию рассылки."
                    )
                else:
                    payment_text = (
                        "✅ Оплата успешно получена!\n\n"
                        "✅ Подписка активирована.\n\n"
                        "📬 Первый выпуск рассылки придёт в этот чат в течение минуты."
                    )
                
                await self.bot.send_message(
                    chat_id=user_id,
                    text=payment_text
                )
            except Exception as e:
                logger.warning(f"Не удалось отправить сообщение плательщику {user_id}: {e}")
        except Exception as e:
            logger.error(f"Ошибка при отправке ссылки пользователю {user_id}: {e}", exc_info=True)
    
    async def _handle_auto_payment(self, user_id: int, data: Dict[str, Any]):
        """обработка рекуррентного списания — продлеваем существующую подписку"""
        order_num = data.get("order_num", "")

        # определяем тариф из order_num
        tariff_type = None
        _ORDER_TARIFF_MAP = [
            ("quarterly", "quarterly"),
            ("half_year", "half_year"),
            ("annual", "annual"),
            ("lifetime", "lifetime"),
            ("monthly", "monthly"),
        ]
        for fragment, ttype in _ORDER_TARIFF_MAP:
            if fragment in order_num:
                tariff_type = ttype
                break

        if not tariff_type:
            logger.error(f"auto_payment: не удалось определить тариф из order_num: {order_num}")
            return

        from config import TARIFFS
        tariff_info = TARIFFS.get(tariff_type)
        if not tariff_info:
            logger.error(f"auto_payment: тариф {tariff_type} не найден в config")
            return

        duration_days = tariff_info["duration_days"]

        extended = await self.db.extend_subscription(user_id, duration_days)
        if extended:
            logger.info(
                f"auto_payment: подписка user_id={user_id} продлена на {duration_days} дней "
                f"(тариф {tariff_type}, order_num={order_num})"
            )
            try:
                await self.bot.send_message(
                    chat_id=user_id,
                    text=f"✅ Подписка продлена! Следующее списание через {duration_days} дней."
                )
            except Exception as e:
                logger.warning(f"auto_payment: не удалось уведомить user_id={user_id}: {e}")
        else:
            # нет активной подписки — создаём новую (fallback)
            logger.warning(f"auto_payment: нет активной подписки для user_id={user_id}, создаю новую")
            await self._handle_payment_success(user_id, data)

    async def _handle_payment_failed(self, user_id: int, data: Dict[str, Any]):
        """обработка неудачной оплаты"""
        try:
            await self.bot.send_message(
                chat_id=user_id,
                text="❌ Оплата не прошла. Пожалуйста, попробуйте еще раз или обратитесь в поддержку."
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}", exc_info=True)
    
    async def _handle_subscription_cancelled(self, user_id: int, data: Dict[str, Any]):
        """обработка отмены подписки"""
        logger.info(f"Отмена подписки для пользователя {user_id}")
        
        # деактивируем подписку (можем использовать разные методы в зависимости от данных)
        subscription_id = data.get("subscription_id") or data.get("subscription[id]")
        order_num = data.get("order_num", "")
        
        if subscription_id:
            # деактивируем по subscription_id
            deactivated_user_id = await self.db.deactivate_subscription_by_subscription_id(str(subscription_id))
            if deactivated_user_id and deactivated_user_id != user_id:
                logger.warning(f"user_id из БД ({deactivated_user_id}) не совпадает с найденным ({user_id})")
                user_id = deactivated_user_id
        elif order_num:
            # деактивируем по order_id
            deactivated_user_id = await self.db.deactivate_subscription_by_order_id(order_num)
            if deactivated_user_id and deactivated_user_id != user_id:
                logger.warning(f"user_id из БД ({deactivated_user_id}) не совпадает с найденным ({user_id})")
                user_id = deactivated_user_id
        else:
            # деактивируем по user_id
            await self.db.deactivate_subscription(user_id)
        
        # удаляем пользователя из канала
        try:
            if CHANNEL_ID:
                await self.bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
                logger.info(f"✅ Пользователь {user_id} забанен в канале")
        except Exception as e:
            if "user is an administrator of the chat" in str(e):
                logger.info(f"ℹ️ Пользователь {user_id} является админом канала, бан пропущен")
            else:
                logger.error(f"Ошибка при удалении пользователя {user_id} из канала: {e}", exc_info=True)
        
        # отправляем уведомление
        try:
            await self.bot.send_message(
                chat_id=user_id,
                text="❌ Ваша подписка отменена."
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}", exc_info=True)
    
    async def _handle_subscription_expired(self, user_id: int, data: Dict[str, Any]):
        """обработка истечения подписки"""
        logger.info(f"Истечение подписки для пользователя {user_id}")
        
        # деактивируем подписку (можем использовать разные методы в зависимости от данных)
        subscription_id = data.get("subscription_id") or data.get("subscription[id]")
        order_num = data.get("order_num", "")
        
        if subscription_id:
            # деактивируем по subscription_id
            deactivated_user_id = await self.db.deactivate_subscription_by_subscription_id(str(subscription_id))
            if deactivated_user_id and deactivated_user_id != user_id:
                logger.warning(f"user_id из БД ({deactivated_user_id}) не совпадает с найденным ({user_id})")
                user_id = deactivated_user_id
        elif order_num:
            # деактивируем по order_id
            deactivated_user_id = await self.db.deactivate_subscription_by_order_id(order_num)
            if deactivated_user_id and deactivated_user_id != user_id:
                logger.warning(f"user_id из БД ({deactivated_user_id}) не совпадает с найденным ({user_id})")
                user_id = deactivated_user_id
        else:
            # деактивируем по user_id
            await self.db.deactivate_subscription(user_id)
        
        # удаляем пользователя из канала
        try:
            if CHANNEL_ID:
                await self.bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        except Exception as e:
            logger.error(f"Ошибка при удалении пользователя {user_id} из канала: {e}", exc_info=True)
        
        # отправляем уведомление
        try:
            await self.bot.send_message(
                chat_id=user_id,
                text="⏰ Срок вашей подписки истёк.\n\nВы можете продлить подписку в разделе 'Подписка'."
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}", exc_info=True)
