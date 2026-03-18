# Пример запроса к API Prodamus для создания ссылки на оплату

## Пример HTTP запроса (curl)

**Запрос на создание платежной ссылки:**

По документации Prodamus запрос отправляется на URL платежной формы (не на `/api/pay`):

```bash
# GET запрос (рекомендуется по документации)
curl "https://nugaeva.payform.ru/?sys=nugaevadancebot&do=link&order_id=tg_123456789_monthly_1700000000&subscription=2608400&customer_email=user_123456789@telegram.local&customer_name=Telegram%20User%20123456789&success_url=https://t.me/dancenugaevabot?start=payment_success&fail_url=https://t.me/dancenugaevabot?start=payment_fail&signature=<вычисленная_подпись>"

# Или POST запрос
curl -X POST https://nugaeva.payform.ru/ \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "sys=nugaevadancebot" \
  -d "do=link" \
  -d "order_id=tg_123456789_monthly_1700000000" \
  -d "subscription=2608400" \
  -d "customer_email=user_123456789@telegram.local" \
  -d "customer_name=Telegram User 123456789" \
  -d "success_url=https://t.me/dancenugaevabot?start=payment_success" \
  -d "fail_url=https://t.me/dancenugaevabot?start=payment_fail" \
  -d "signature=<вычисленная_подпись>"
```

**Важно**: 
- URL: `https://nugaeva.payform.ru/` (URL платежной формы, не `/api/pay`)
- `do=link` - возвращает ссылку в текстовом формате
- `do=pay` - сразу отправляет на оплату
- Для подписок: параметр `subscription` с `product_id`
- Для разовых товаров: параметр `products` как массив

**Параметры запроса (URL-encoded):**

```
sys=nugaevadancebot
do=pay
customer_email=user_123456789@telegram.local
customer_phone=
products=[{"name":"1 месяц","price":990,"quantity":1}]
order_id=tg_123456789_monthly_1700000000
customer_name=Telegram User 123456789
success_url=https://t.me/dancenugaevabot?start=payment_success
fail_url=https://t.me/dancenugaevabot?start=payment_fail
signature=<вычисленная_подпись>
```

## Формирование подписи

Подпись формируется следующим образом:

1. Берем все параметры запроса (кроме `signature`)
2. Сортируем их по ключу в алфавитном порядке
3. Формируем строку: `key1=value1&key2=value2&...&api_key`
4. Вычисляем SHA256 хеш от этой строки

**Пример строки для подписи:**
```
customer_email=user_123456789@telegram.local&customer_name=Telegram User 123456789&customer_phone=&do=pay&fail_url=https://t.me/dancenugaevabot?start=payment_fail&order_id=tg_123456789_monthly_1700000000&products=[{"name":"1 месяц","price":990,"quantity":1}]&success_url=https://t.me/dancenugaevabot?start=payment_success&sys=nugaevadancebot&<API_KEY>
```

**Где `<API_KEY>`** - это значение `PRODAMUS_API_KEY` из настроек.

## Пример ответа

**Успешный ответ:**
```json
{
  "status": "success",
  "url": "https://payform.ru/.../payment_link"
}
```

**Ошибка:**
```json
{
  "status": "error",
  "message": "Описание ошибки"
}
```

## Пример webhook запроса от Prodamus

**URL для webhook:** `https://nugaevadance.ru/webhook/prodamus`

**Метод:** `POST`

**Content-Type:** `multipart/form-data`

**Заголовки:**
```
POST /webhook/prodamus HTTP/1.1
Host: nugaevadance.ru
Content-Type: multipart/form-data; boundary=----WebKitFormBoundary7MA4YWxkTrZu0gW
Sign: <подпись_webhook>
```

**Тело запроса (multipart/form-data):**

```
------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="date"

2025-11-22T00:00:00+03:00
------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="order_id"

tg_123456789_monthly_1700000000
------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="order_num"

test
------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="domain"

nugaevadance.ru
------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="sum"

990.00
------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="customer_phone"

+79999999999
------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="customer_email"

email@domain.com
------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="payment_type"

Пластиковая карта Visa, MasterCard, МИР
------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="payment_status"

success
------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="payment_status_description"

Успешная оплата
------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="subscription_id"

<id_подписки>
------WebKitFormBoundary7MA4YWxkTrZu0gW--
```

**Или в виде curl (имитация запроса от Prodamus):**

```bash
curl -X POST https://nugaevadance.ru/webhook/prodamus \
  -H "Content-Type: multipart/form-data" \
  -H "Sign: <подпись_webhook>" \
  -F "date=2025-11-22T00:00:00+03:00" \
  -F "order_id=tg_123456789_monthly_1700000000" \
  -F "order_num=test" \
  -F "domain=nugaevadance.ru" \
  -F "sum=990.00" \
  -F "customer_phone=+79999999999" \
  -F "customer_email=email@domain.com" \
  -F "payment_type=Пластиковая карта Visa, MasterCard, МИР" \
  -F "payment_status=success" \
  -F "payment_status_description=Успешная оплата"
```

## Формирование подписи webhook

Подпись webhook формируется аналогично:

1. Берем все параметры из webhook (кроме `signature` и `sign`)
2. Сортируем по ключу
3. Формируем строку: `key1=value1&key2=value2&...&webhook_secret`
4. Вычисляем SHA256 хеш

**Где `webhook_secret`** - это значение `PRODAMUS_WEBHOOK_SECRET` из настроек.

## Требования к ответу на webhook

При успешной обработке webhook должен вернуть:

**HTTP Status Code:** `200`

**Response Body:**
```json
{
  "status": "ok"
}
```

