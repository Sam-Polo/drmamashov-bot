import hmac
import hashlib
import json
import time
import asyncio
import logging
from typing import Optional, Dict, Any
import aiohttp
from config import (
    PRODAMUS_API_KEY,
    PRODAMUS_SYS,
    PRODAMUS_WEBHOOK_SECRET,
    PRODAMUS_PAYFORM_URL,
)

logger = logging.getLogger(__name__)


class ProdamusAPI:
    """клиент для работы с Prodamus API"""
    
    def __init__(self):
        self.api_key = PRODAMUS_API_KEY
        self.sys = PRODAMUS_SYS
        self.webhook_secret = PRODAMUS_WEBHOOK_SECRET
        # URL платежной формы (по документации: https://название_поддомена.payform.ru/)
        # берем значение из config, чтобы использовать единый источник env-переменных
        # по умолчанию в config используется nugaeva.payform.ru
        raw_payform_url = (PRODAMUS_PAYFORM_URL or "").strip()

        if not raw_payform_url:
            raw_payform_url = "https://nugaeva.payform.ru/"
            logger.warning(
                "PRODAMUS_PAYFORM_URL пустой, использую значение по умолчанию: %s",
                raw_payform_url
            )

        # если забыли указать схему, нормализуем до https
        if not raw_payform_url.startswith(("http://", "https://")):
            raw_payform_url = f"https://{raw_payform_url}"
            logger.warning(
                "PRODAMUS_PAYFORM_URL был без схемы, нормализован до: %s",
                raw_payform_url
            )

        self.payform_url = raw_payform_url
    
    def _flatten_params(self, value: Any, prefix: str = "") -> list[tuple[str, str]]:
        """приводит вложенные структуры к php-совместным ключам (products[0][name])"""
        items: list[tuple[str, str]] = []
        if isinstance(value, dict):
            for key, nested in value.items():
                new_prefix = f"{prefix}[{key}]" if prefix else str(key)
                items.extend(self._flatten_params(nested, new_prefix))
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                new_prefix = f"{prefix}[{index}]"
                items.extend(self._flatten_params(nested, new_prefix))
        else:
            # prodamus учитывает пустые значения, поэтому приводим None к пустой строке
            items.append((prefix, "" if value is None else str(value)))
        return items
    
    async def create_payment_link(
        self,
        user_id: int,
        tariff_type: str,
        tariff_price: int,
        tariff_name: str,
        duration_days: Optional[int] = None,
        product_id_override: Optional[str] = None,
        promocode: Optional[str] = None,
        discount_amount: Optional[int] = None,
        order_id_override: Optional[str] = None,
        customer_email: Optional[str] = None,
        customer_phone: Optional[str] = None
    ) -> Optional[str]:
        """создание ссылки на оплату
        
        Для monthly и half_year - создается подписка с автосписаниями
        Для lifetime - создается разовый платеж без автосписаний
        
        Args:
            product_id_override: опциональный product_id для переопределения (например, для акций)
            customer_email: email клиента для привязки подписки
            customer_phone: телефон клиента для привязки подписки
        """
        # определяем product_id на основе тарифа
        # для monthly и half_year - это ID подписок в Prodamus
        # для lifetime - это ID разового товара/услуги в Prodamus
        from config import PRODAMUS_PRODUCT_ID_MONTHLY, PRODAMUS_PRODUCT_ID_LIFETIME
        
        # если передан product_id_override, используем его
        if product_id_override:
            product_id = product_id_override
        else:
            product_ids = {
                "monthly": PRODAMUS_PRODUCT_ID_MONTHLY,
                "lifetime": PRODAMUS_PRODUCT_ID_LIFETIME,
            }
            
            product_id = product_ids.get(tariff_type)
            if not product_id:
                return None
        
        # формируем данные для запроса
        # подпись формируется автоматически Prodamus
        if order_id_override:
            order_id = order_id_override
        else:
            order_id = f"tg_{user_id}_{tariff_type}_{int(time.time())}"
        data = {
            "sys": self.sys,
            "do": "link",  # link - возвращает ссылку, pay - сразу отправляет на оплату
            "type": "json",  # для получения JSON ответа
            "order_id": order_id,
        }
        
        # для подписок используется subscription, для разовых товаров - products
        if tariff_type != "lifetime":
            data["subscription"] = product_id
            
            # если есть промокод со скидкой, добавляем демо-период и скидку
            # по документации Prodamus: subscription_demo_period + discount_value = скидка на первый платеж
            # для lifetime (разовый платеж) демо-период не применяется
            if promocode and discount_amount and discount_amount > 0:
                # устанавливаем демо-период на 30 дней
                data["subscription_demo_period"] = 30
                # устанавливаем сумму скидки (по документации - discount_value)
                data["discount_value"] = discount_amount
                logger.info(f"Применение промокода {promocode}: subscription_demo_period=30, discount_value={discount_amount}₽")
        else:
            # для lifetime (разовый платеж) используем products, демо-период не применяется
            data["products"] = [{
                "name": tariff_name,
                "price": tariff_price,
                "quantity": 1
            }]
            # для разовых платежей можно применить скидку через discount_value
            if promocode and discount_amount and discount_amount > 0:
                data["discount_value"] = discount_amount
                logger.info(f"Применение промокода {promocode} для разового платежа: discount_value={discount_amount}₽")
        
        # добавляем URL для редиректа после оплаты
        from config import BOT_USERNAME
        bot_username = BOT_USERNAME if BOT_USERNAME else "your_bot"
        data["success_url"] = f"https://t.me/{bot_username}?start=payment_success"
        data["fail_url"] = f"https://t.me/{bot_username}?start=payment_fail"
        
        # email клиента обязателен для формирования подписи и привязки подписки
        # tg_user_id НЕ передаем в подпись, он сохраняется только в order_id
        data["customer_email"] = customer_email
        if customer_phone:
            data["customer_phone"] = customer_phone
        
        masked_phone = f"***{customer_phone[-4:]}" if customer_phone and len(customer_phone) >= 4 else "None"
        logger.info(
            f"Формирование ссылки для тарифа {tariff_type}, product_id={product_id}, "
            f"email={customer_email}, phone={masked_phone}"
        )
        
        timeout = aiohttp.ClientTimeout(total=30, connect=10, sock_read=10)
        import ssl
        ssl_context = ssl.create_default_context()
        connector = aiohttp.TCPConnector(
            ssl=ssl_context,
            limit=10,
            force_close=True,
            enable_cleanup_closed=True,
            ttl_dns_cache=300,
            use_dns_cache=True
        )
        
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            try:
                # формируем параметры для GET запроса в php-совместном формате
                params = {}
                for flat_key, flat_value in self._flatten_params(data):
                    params[flat_key] = flat_value
                
                # добавляем заголовки
                headers = {
                    "User-Agent": "curl/8.14.1",
                    "Accept": "*/*",
                }
                
                # формируем полный URL для логирования
                import urllib.parse
                query_string = urllib.parse.urlencode(params, doseq=True, quote_via=urllib.parse.quote)
                base_url = self.payform_url.rstrip('/') + '/'
                full_url = f"{base_url}?{query_string}"
                logger.info(f"Отправка GET запроса на {self.payform_url}")
                logger.info(f"Полный URL запроса (первые 300 символов): {full_url[:300]}...")
                
                # отправляем запрос
                request_url = self.payform_url.rstrip('/') + '/'
                async with session.get(
                    request_url,
                    params=params,
                    headers=headers,
                    allow_redirects=True,
                    ssl=True
                ) as response:
                    logger.info(f"✅ Соединение установлено! Статус: {response.status}")
                    response_text = await response.text()
                    
                    logger.info(f"Ответ от Prodamus: статус {response.status}, длина {len(response_text)} символов")
                    
                    if response.status == 200:
                        # при type=json возвращается JSON с полем payment_link
                        link = response_text.strip()
                        
                        # проверяем, это JSON или прямая ссылка
                        if link.startswith("http"):
                            logger.info(f"✅ Получена ссылка на оплату: {link}")
                            # сохраняем промокод для последующего применения скидки
                            if promocode:
                                from database.models import Database
                                from config import DATABASE_PATH
                                db = Database(DATABASE_PATH)
                                await db.save_order_promocode(order_id, promocode, user_id)
                                logger.info(f"Сохранен промокод {promocode} для order_id {order_id}")
                            return link
                        elif link.startswith("{"):
                            # это JSON ответ (при type=json)
                            try:
                                json_response = json.loads(link)
                                link = json_response.get("payment_link") or json_response.get("url") or json_response.get("link")
                                if link and link.startswith("http"):
                                    logger.info(f"✅ Получена ссылка на оплату из JSON: {link}")
                                    # сохраняем промокод для последующего применения скидки
                                    if promocode:
                                        from database.models import Database
                                        from config import DATABASE_PATH
                                        db = Database(DATABASE_PATH)
                                        await db.save_order_promocode(order_id, promocode, user_id)
                                        logger.info(f"Сохранен промокод {promocode} для order_id {order_id}")
                                    return link
                                else:
                                    logger.error(f"❌ В JSON ответе нет payment_link. Ответ: {json_response}")
                            except json.JSONDecodeError as e:
                                logger.error(f"❌ Ошибка парсинга JSON: {e}")
                                logger.error(f"Ответ: {response_text[:500]}")
                        else:
                            # попробуем найти ссылку в тексте ответа
                            import re
                            url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
                            found_urls = re.findall(url_pattern, response_text)
                            if found_urls:
                                logger.info(f"✅ Найдена ссылка в ответе: {found_urls[0]}")
                                # сохраняем промокод для последующего применения скидки
                                if promocode:
                                    from database.models import Database
                                    from config import DATABASE_PATH
                                    db = Database(DATABASE_PATH)
                                    await db.save_order_promocode(order_id, promocode, user_id)
                                    logger.info(f"Сохранен промокод {promocode} для order_id {order_id}")
                                return found_urls[0]
                        
                        logger.error(f"❌ Prodamus вернул неожиданный формат ответа")
                        logger.error(f"Первые 300 символов: {response_text[:300]}")
                    else:
                        logger.error(f"❌ Prodamus вернул статус {response.status}: {response_text[:500]}")
            except asyncio.TimeoutError:
                logger.error("❌ Таймаут при запросе к Prodamus (30 секунд)")
            except aiohttp.ClientConnectorError as e:
                logger.error(f"❌ Ошибка подключения к Prodamus: {e}")
            except Exception as e:
                logger.error(f"❌ Ошибка создания ссылки на оплату: {e}", exc_info=True)
        
        return None
    
    def _sort_recursive(self, data: Any) -> Any:
        """рекурсивная сортировка по ключам (как в PHP ksort)"""
        if isinstance(data, dict):
            # сортируем словарь по ключам
            sorted_dict = {}
            for key in sorted(data.keys()):
                sorted_dict[key] = self._sort_recursive(data[key])
            return sorted_dict
        elif isinstance(data, list):
            # для списков сортируем элементы рекурсивно
            return [self._sort_recursive(item) for item in data]
        else:
            return data
    
    def _convert_to_strings_recursive(self, data: Any) -> Any:
        """рекурсивно преобразует все значения в строки (как в PHP array_walk_recursive)"""
        if isinstance(data, dict):
            return {k: self._convert_to_strings_recursive(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._convert_to_strings_recursive(item) for item in data]
        else:
            return str(data) if data is not None else ""
    
    def _php_to_dict(self, flat_data: Dict[str, Any]) -> Dict[str, Any]:
        """преобразует плоский формат (subscription[id]) во вложенный словарь
        использует логику из библиотеки python-prodamus
        """
        import re
        from copy import deepcopy
        import collections
        
        def dict_build(idx, value):
            """строит вложенную структуру из пути индексов"""
            value = deepcopy(value)
            if len(idx):
                i = idx.pop(0)
                if re.fullmatch(r'[0-9]+', i):
                    # числовой индекс - создаем список
                    return [{} for _ in range(int(i))] + [dict_build(idx, value)]
                else:
                    # строковый ключ - создаем словарь
                    return {i: dict_build(idx, value)}
            else:
                return value
        
        def dict_merge(dct, merge_dct):
            """сливает два словаря рекурсивно"""
            dct = deepcopy(dct)
            for k, v in merge_dct.items():
                if not dct.get(k):
                    dct[k] = deepcopy(v)
                elif k in dct and type(v) != type(dct[k]):
                    raise TypeError(f"Overlapping keys exist with different types: original is {type(dct[k])}, new value is {type(v)}")
                elif isinstance(dct[k], dict) and isinstance(merge_dct[k], collections.abc.Mapping):
                    dct[k] = dict_merge(dct[k], merge_dct[k])
                elif isinstance(v, list):
                    for li, lv in enumerate(v):
                        if len(dct[k]) <= li:
                            dct[k].append(lv)
                        else:
                            dct[k][li] = dict_merge(dct[k][li], lv)
                else:
                    dct[k] = v
            return dct
        
        result = {}
        for k, v in flat_data.items():
            # проверяем, есть ли вложенность (например, subscription[id] или products[0][name])
            match = re.fullmatch(r'([^\[]+)(\[.+\])', k)
            if match:
                # извлекаем путь: ['subscription', 'id'] или ['products', '0', 'name']
                base_key = match.group(1)
                nested_keys = re.findall(r'\[([^\]]+)\]', match.group(2))
                idx = [base_key] + nested_keys
                subdct = dict_build(idx, v)
            else:
                # простой ключ без вложенности
                subdct = {k: v}
            result = dict_merge(result, subdct)
        
        return result
    
    def verify_webhook_signature(self, data: Dict[str, Any], signature: str) -> bool:
        """проверка подписи webhook от Prodamus
        
        Использует алгоритм из библиотеки python-prodamus и PHP Hmac.php:
        1. Преобразует плоский формат (subscription[id]) во вложенный словарь
        2. Рекурсивно преобразует все значения в строки
        3. Рекурсивно сортирует по ключам
        4. Сериализует в JSON с sort_keys=True, ensure_ascii=False
        5. Использует HMAC-SHA256 для создания подписи
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # для тестовых запросов пропускаем проверку подписи
        order_id = data.get("order_id", "")
        if str(order_id) in ["1", "test"]:
            return True
        
        if not self.webhook_secret:
            logger.warning("Webhook secret не установлен - пропускаем проверку подписи")
            return True
        
        # исключаем signature и sign из данных
        filtered_data = {k: v for k, v in data.items() if k not in ["signature", "sign"]}
        
        # преобразуем плоский формат во вложенный словарь
        nested_data = self._php_to_dict(filtered_data)
        
        # рекурсивно преобразуем все значения в строки
        string_data = self._convert_to_strings_recursive(nested_data)
        
        # рекурсивно сортируем по ключам
        sorted_data = self._sort_recursive(string_data)
        
        # сериализуем в JSON
        obj_json = json.dumps(sorted_data, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
        
        # экранируем / как в PHP json_encode (по документации Prodamus)
        obj_json = obj_json.replace('/', '\\/')
        
        # создаем подпись через HMAC-SHA256
        expected_signature = hmac.new(
            bytes(self.webhook_secret, 'utf-8'),
            msg=bytes(obj_json, 'utf-8'),
            digestmod=hashlib.sha256
        ).hexdigest()
        
        # дебаг логирование
        logger.info(f"🔐 Webhook secret (первые 10 символов): {self.webhook_secret[:10]}...")
        logger.info(f"🔐 JSON для подписи (первые 200 символов): {obj_json[:200]}...")
        logger.info(f"🔐 Ожидаемая подпись: {expected_signature}")
        logger.info(f"🔐 Полученная подпись: {signature}")
        
        # сравниваем подписи (case insensitive)
        result = expected_signature.lower() == signature.lower()
        if not result:
            logger.warning(f"❌ Неверная подпись webhook. Проверь PRODAMUS_WEBHOOK_SECRET в .env")
        
        return result
    
    async def set_subscription_activity(
        self, 
        subscription: str, 
        profile_id: int = None,
        customer_email: str = None,
        customer_phone: str = None,
        active: bool = False,
        as_manager: bool = True
    ) -> tuple:
        """управление статусом подписки через setActivity API
        
        Args:
            subscription: ID подписки в Prodamus (строка или число)
            profile_id: ID профиля клиента в Prodamus (опционально)
            customer_email: email клиента (используется для формирования подписи)
            customer_phone: телефон клиента (используется для формирования подписи)
            active: False для деактивации, True для активации
            as_manager: True - от лица менеджера, False - от лица пользователя
            
        Returns:
            tuple: (success: bool, error_message: str or None)
        """
        masked_phone = f"***{customer_phone[-4:]}" if customer_phone and len(customer_phone) >= 4 else "None"
        logger.info(
            f"🔄 setActivity: subscription={subscription}, profile_id={profile_id}, "
            f"customer_email={customer_email}, customer_phone={masked_phone}, "
            f"active={active}, as_manager={as_manager}"
        )
        
        data = {
            "subscription": subscription,
        }
        
        # идентификатор клиента - только email (как при создании платежа)
        # tg_user_id НЕ используем для подписи
        if customer_email:
            data["customer_email"] = customer_email
            if customer_phone:
                data["customer_phone"] = customer_phone
        elif profile_id:
            data["profile"] = profile_id
        
        # используем active_manager или active_user
        if as_manager:
            data["active_manager"] = 1 if active else 0
        else:
            data["active_user"] = 1 if active else 0
        
        # формируем подпись используя уже рабочий подход (JSON-сериализация)
        # 1. Преобразуем все значения в строки
        stringified_data = self._convert_to_strings_recursive(data)
        # 2. Сортируем рекурсивно по ключам
        sorted_data = self._sort_recursive(stringified_data)
        # 3. Сериализуем в JSON
        json_payload = json.dumps(sorted_data, ensure_ascii=False, separators=(',', ':'))
        # 4. Экранируем / как в PHP json_encode
        json_payload = json_payload.replace('/', '\\/')
        # 5. Создаем HMAC-SHA256 подпись (используем API ключ, не webhook secret)
        signature = hmac.new(
            self.api_key.encode('utf-8'),
            json_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        data["signature"] = signature
        
        # отправляем POST запрос
        async with aiohttp.ClientSession() as session:
            try:
                # используем REST API endpoint
                rest_url = self.payform_url.rstrip('/') + '/rest/setActivity/'
                
                # формируем параметры для POST (application/x-www-form-urlencoded)
                params = {}
                for flat_key, flat_value in self._flatten_params(data):
                    params[flat_key] = flat_value
                
                logger.info(f"🔄 setActivity URL: {rest_url}")
                logger.info(f"🔄 setActivity params: {params}")
                
                async with session.post(
                    rest_url,
                    data=params,
                    headers={"User-Agent": "curl/8.14.1", "Accept": "*/*"}
                ) as response:
                    result_text = await response.text()
                    logger.info(f"🔄 setActivity response: status={response.status}, body={result_text[:300]}")
                    
                    if response.status == 200:
                        if result_text.strip() == "success":
                            logger.info("✅ setActivity успешно выполнен")
                            return (True, None)
                        try:
                            result = json.loads(result_text)
                            if result.get("status") == "success":
                                logger.info("✅ setActivity успешно выполнен (JSON)")
                                return (True, None)
                            else:
                                logger.warning(f"⚠️ setActivity неуспешный ответ: {result}")
                                return (False, str(result))
                        except json.JSONDecodeError:
                            logger.error(f"Ошибка парсинга JSON при setActivity: {result_text[:200]}")
                            return (False, result_text[:200])
                    else:
                        logger.error(f"Ошибка setActivity: статус {response.status}, ответ: {result_text}")
                        return (False, result_text)
            except Exception as e:
                logger.error(f"Ошибка setActivity: {e}", exc_info=True)
                return (False, str(e))
        
        return (False, "Unknown error")
    
    async def set_subscription_discount(
        self,
        subscription_id: int,
        discount_value: float,
        num: int,
        tg_user_id: int
    ) -> bool:
        """установка скидки на подписку через setSubscriptionDiscount API
        
        По документации: https://help.prodamus.ru/payform/integracii/rest-api-1/setsubscriptiondiscount
        
        Args:
            subscription_id: ID подписки в Prodamus
            discount_value: размер скидки (десятичное число с точностью до двух знаков)
            num: количество оплат на которые будет действовать скидка (0 = не ограничено)
            tg_user_id: ID пользователя Telegram
        """
        data = {
            "subscription": subscription_id,
            "discount_value": discount_value,
            "num": num,
            "tg_user_id": tg_user_id,
        }
        
        # формируем подпись согласно документации Prodamus
        # используем тот же метод, что и для других REST API запросов
        # преобразуем все значения в строки и сортируем рекурсивно
        stringified_data = self._convert_to_strings_recursive(data)
        sorted_data = self._sort_recursive(stringified_data)
        json_payload = json.dumps(sorted_data, ensure_ascii=False, separators=(',', ':'))
        # экранируем / как в PHP json_encode
        json_payload = json_payload.replace('/', '\\/')
        
        signature = hmac.new(
            self.api_key.encode('utf-8'),
            json_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        data["signature"] = signature
        
        logger.info(f"Применение скидки: subscription_id={subscription_id}, discount_value={discount_value}, num={num}, tg_user_id={tg_user_id}")
        
        # отправляем POST запрос
        async with aiohttp.ClientSession() as session:
            try:
                rest_url = self.payform_url.rstrip('/') + '/rest/setSubscriptionDiscount/'
                
                # формируем параметры для POST (application/x-www-form-urlencoded)
                params = {}
                for key, value in data.items():
                    params[key] = str(value)
                
                logger.info(f"Отправка запроса на {rest_url} с параметрами: {params}")
                
                async with session.post(
                    rest_url,
                    data=params,
                    headers={"User-Agent": "curl/8.14.1", "Accept": "*/*", "Content-Type": "application/x-www-form-urlencoded"}
                ) as response:
                    response_text = await response.text()
                    logger.info(f"Ответ от setSubscriptionDiscount: статус {response.status}, текст: {response_text}")
                    
                    if response.status == 200:
                        if response_text.strip() == "success":
                            logger.info("✅ Скидка успешно применена")
                            return True
                        try:
                            result = json.loads(response_text)
                            return result.get("status") == "success"
                        except json.JSONDecodeError:
                            logger.error(f"Ошибка парсинга JSON при setSubscriptionDiscount: {response_text[:200]}")
                    else:
                        logger.error(f"Ошибка setSubscriptionDiscount: статус {response.status}, ответ: {response_text}")
            except Exception as e:
                logger.error(f"Ошибка setSubscriptionDiscount: {e}", exc_info=True)
        
        return False
