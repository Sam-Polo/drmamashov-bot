"""
Webhook сервер для приема уведомлений от Prodamus
Запускается отдельно от бота для обработки webhook-запросов
"""
import asyncio
import logging
import os
from aiohttp import web
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from prodamus.webhook import ProdamusWebhookHandler
from config import BOT_TOKEN, PRODAMUS_WEBHOOK_SECRET

# настройка логирования с форматированием
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# инициализация бота и обработчика (с прокси для исходящих запросов к Telegram API)
_proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("SOCKS5_PROXY")
_session = AiohttpSession(proxy=_proxy_url) if _proxy_url else None
if _proxy_url:
    logger.info("🔀 webhook: используется прокси: %s", _proxy_url.split("@")[-1])
bot = Bot(token=BOT_TOKEN, session=_session)
webhook_handler = ProdamusWebhookHandler(bot)


async def prodamus_webhook(request: web.Request):
    """обработчик webhook от Prodamus"""
    try:
        # заметный маркер входящего запроса
        logger.info("-" * 80)
        logger.info(f"📥 ВХОДЯЩИЙ WEBHOOK ОТ PRODAMUS")
        logger.info(f"   IP: {request.remote}")
        logger.info(f"   Method: {request.method}, Path: {request.path_qs}")
        logger.info(f"   Content-Type: {request.headers.get('Content-Type', 'N/A')}")
        logger.info(f"   User-Agent: {request.headers.get('User-Agent', 'N/A')}")
        
        # Prodamus отправляет данные в формате application/x-www-form-urlencoded или multipart/form-data
        # пробуем получить как form data
        try:
            form_data = await request.post()
            data = {}
            # преобразуем в обычный dict, обрабатывая массивы
            for key, value in form_data.items():
                if isinstance(value, list):
                    # если это массив (например products), берем первый элемент или весь массив
                    if len(value) == 1:
                        # если один элемент, проверяем, не строка ли это
                        if isinstance(value[0], str):
                            # возможно, это JSON строка
                            try:
                                import json
                                data[key] = json.loads(value[0])
                            except:
                                data[key] = value
                        else:
                            data[key] = value
                    else:
                        data[key] = value
                else:
                    data[key] = value
        except Exception as e:
            logger.error(f"Ошибка парсинга form data: {e}")
            # пробуем как обычные данные
            try:
                data = await request.json()
            except:
                data = {}
        
        # логируем все заголовки для отладки
        logger.info(f"📋 Заголовки запроса: {dict(request.headers)}")
        logger.info(f"📦 Полученные данные: {data}")
        logger.info(f"📦 Тип данных: {type(data)}")
        logger.info(f"📦 Ключи в данных: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
        
        # получаем подпись из заголовка Sign (Prodamus использует именно этот заголовок)
        signature = request.headers.get("Sign") or request.headers.get("sign") or data.get("signature", "")
        
        logger.info(f"🔐 Подпись из заголовка Sign: {request.headers.get('Sign', 'N/A')[:20] if request.headers.get('Sign') else 'N/A'}...")
        logger.info(f"🔐 Подпись из заголовка sign: {request.headers.get('sign', 'N/A')[:20] if request.headers.get('sign') else 'N/A'}...")
        logger.info(f"🔐 Подпись из данных: {data.get('signature', 'N/A')[:20] if data.get('signature') else 'N/A'}...")
        
        if not signature:
            logger.warning("⚠️ Подпись не найдена в заголовках")
            # для тестовых запросов можем пропустить проверку подписи
            order_id = data.get("order_id", "")
            logger.info(f"   order_id: {order_id}")
            if str(order_id) in ["1", "test"]:
                logger.info("✅ Тестовый запрос без подписи - обрабатываем")
            else:
                logger.error("❌ Подпись не найдена и это не тестовый запрос")
                return web.json_response({"status": "error", "message": "Signature not found"}, status=400)
        
        logger.info(f"🔐 Используемая подпись: {signature[:20]}...")
        
        # обрабатываем webhook
        logger.info("🔄 Начинаем обработку webhook...")
        success = await webhook_handler.handle_webhook(data, signature)
        
        if success:
            logger.info("✅ Webhook успешно обработан")
            logger.info("-" * 80)
            # важно: возвращаем код 200 для успешной обработки (требование Prodamus)
            return web.json_response({"status": "ok"}, status=200)
        else:
            logger.warning("❌ Ошибка обработки webhook: неверная подпись или ошибка обработки")
            logger.info("-" * 80)
            # при ошибке возвращаем 400, чтобы Prodamus знал о проблеме
            return web.json_response({"status": "error", "message": "Invalid signature or processing error"}, status=400)
    
    except Exception as e:
        logger.error(f"Ошибка обработки webhook: {e}", exc_info=True)
        return web.json_response({"status": "error", "message": str(e)}, status=500)


async def health_check(request: web.Request):
    """проверка работоспособности сервера"""
    return web.json_response({"status": "ok"})


async def root_handler(request: web.Request):
    """обработчик корневого пути"""
    logger.info(f"Запрос на корневой путь: {request.method} {request.path_qs} от {request.remote}")
    return web.json_response({"status": "ok", "message": "Webhook server is running"}, status=200)


async def not_found_handler(request: web.Request):
    """обработчик для несуществующих путей"""
    # тихо логируем только подозрительные запросы (не от Prodamus)
    user_agent = request.headers.get("User-Agent", "")
    if "python-requests" not in user_agent.lower() and "prodamus" not in user_agent.lower():
        logger.warning(f"⚠️ Запрос на несуществующий путь: {request.method} {request.path_qs} от {request.remote} (User-Agent: {user_agent})")
    return web.json_response({"status": "not found", "message": "Path not found"}, status=404)


@web.middleware
async def logging_middleware(request: web.Request, handler):
    """middleware для логирования всех запросов"""
    # пропускаем логирование для некорректных HTTP-запросов (сканирование портов)
    try:
        logger.info(f"=== Входящий запрос ===")
        logger.info(f"IP: {request.remote}")
        logger.info(f"Method: {request.method}")
        logger.info(f"Path: {request.path_qs}")
        logger.info(f"Headers: {dict(request.headers)}")
    except Exception as e:
        # если не можем прочитать запрос (некорректный HTTP), просто возвращаем 400
        logger.warning(f"⚠️ Некорректный HTTP-запрос от {getattr(request, 'remote', 'unknown')}: {e}")
        return web.Response(status=400, text="Bad Request")
    
    try:
        response = await handler(request)
        logger.info(f"Response status: {response.status}")
        return response
    except web.HTTPNotFound:
        # для 404 используем специальный обработчик
        return await not_found_handler(request)
    except Exception as e:
        # для других ошибок логируем и возвращаем 500
        logger.error(f"Ошибка в middleware: {e}", exc_info=True)
        return web.json_response({"status": "error", "message": "Internal server error"}, status=500)


def create_app():
    """создание приложения"""
    app = web.Application(middlewares=[logging_middleware])
    
    # маршруты
    app.router.add_post("/webhook/prodamus", prodamus_webhook)
    app.router.add_get("/health", health_check)
    app.router.add_get("/", root_handler)
    app.router.add_post("/", root_handler)
    
    # catch-all обработчик для всех остальных путей (должен быть последним)
    app.router.add_route("*", "/{path:.*}", not_found_handler)
    
    return app


async def main():
    """запуск webhook сервера"""
    # заметный маркер начала запуска
    logger.info("=" * 80)
    logger.info("=" * 80)
    logger.info("🚀 ЗАПУСК WEBHOOK СЕРВЕРА")
    logger.info("=" * 80)
    logger.info("=" * 80)
    
    app = create_app()
    
    # настройка порта (можно указать через переменную окружения)
    import os
    port = int(os.getenv("WEBHOOK_PORT", "8080"))
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    
    # получаем URL из конфига, если указан
    webhook_url = os.getenv("PRODAMUS_WEBHOOK_URL", f"http://localhost:{port}/webhook/prodamus")
    
    logger.info(f"📡 Webhook сервер запущен на порту {port}")
    logger.info(f"🔗 URL для webhook: {webhook_url}")
    logger.info(f"✅ Сервер готов принимать запросы")
    logger.info("=" * 80)
    
    await site.start()
    
    # держим сервер запущенным
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("=" * 80)
        logger.info("🛑 Остановка webhook сервера...")
        logger.info("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())

