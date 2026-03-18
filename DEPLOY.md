# Инструкция по деплою бота на сервер

## Выбор способа деплоя

Есть два варианта:
- **Без Docker** (проще, меньше ресурсов) - см. раздел "Деплой без Docker"
- **С Docker** (изоляция, легче обновления) - см. раздел "Деплой с Docker"

## Требования

- Сервер с Linux (Ubuntu/Debian)
- Python 3.10+ (для варианта без Docker)
- Docker и Docker Compose (для варианта с Docker)
- Доступ по SSH
- Домен (опционально, можно использовать IP)

---

# Деплой БЕЗ Docker (рекомендуется для небольших серверов)

## Шаг 1: Подготовка сервера

### 1.1. Подключение к серверу

```bash
ssh user@your_server_ip
```

### 1.2. Обновление системы

```bash
sudo apt update && sudo apt upgrade -y
```

### 1.3. Установка Python и зависимостей

```bash
sudo apt install python3 python3-pip python3-venv git -y
```

## Шаг 2: Клонирование проекта

```bash
# переходим в домашнюю директорию
cd ~

# клонируем репозиторий (или загружаем файлы через scp/sftp)
git clone https://github.com/your_username/nugaeva-dance-bot.git
# или
# scp -r ./nugaeva-dance-bot user@server_ip:~/

cd nugaeva-dance-bot
```

## Шаг 3: Настройка окружения

### 3.1. Создание виртуального окружения

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3.2. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 3.3. Создание .env файла

```bash
nano .env
```

Вставь все переменные из локального `.env`:

```env
BOT_TOKEN=твой_токен_бота
BOT_USERNAME=твой_бот_username
ADMIN_IDS=123456789,987654321
CHANNEL_ID=-1001234567890

# Prodamus настройки
PRODAMUS_API_KEY=твой_api_ключ
PRODAMUS_SYS=твой_sys
PRODAMUS_WEBHOOK_SECRET=твой_webhook_secret
PRODAMUS_WEBHOOK_URL=https://твой_домен/webhook/prodamus

# Product ID для каждого тарифа
PRODAMUS_PRODUCT_ID_MONTHLY=id_подписки_1_месяц
PRODAMUS_PRODUCT_ID_HALF_YEAR=id_подписки_6_месяцев
PRODAMUS_PRODUCT_ID_LIFETIME=id_подписки_навсегда

# Порт для webhook сервера (по умолчанию 8080)
WEBHOOK_PORT=8080
```

Сохрани: `Ctrl+O`, `Enter`, `Ctrl+X`

## Шаг 4: Настройка systemd для автозапуска

### 4.1. Создание сервиса для бота

```bash
sudo nano /etc/systemd/system/nugaeva-bot.service
```

Вставь:

```ini
[Unit]
Description=Nugaeva Dance Bot
After=network.target

[Service]
Type=simple
User=твой_пользователь
WorkingDirectory=/home/твой_пользователь/nugaeva-dance-bot
Environment="PATH=/home/твой_пользователь/nugaeva-dance-bot/venv/bin"
ExecStart=/home/твой_пользователь/nugaeva-dance-bot/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Важно**: замени `твой_пользователь` на реальное имя пользователя на сервере.

### 4.2. Создание сервиса для webhook сервера

```bash
sudo nano /etc/systemd/system/nugaeva-webhook.service
```

Вставь:

```ini
[Unit]
Description=Nugaeva Webhook Server
After=network.target

[Service]
Type=simple
User=твой_пользователь
WorkingDirectory=/home/твой_пользователь/nugaeva-dance-bot
Environment="PATH=/home/твой_пользователь/nugaeva-dance-bot/venv/bin"
ExecStart=/home/твой_пользователь/nugaeva-dance-bot/venv/bin/python webhook_server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 4.3. Активация сервисов

```bash
# перезагружаем systemd
sudo systemctl daemon-reload

# включаем автозапуск
sudo systemctl enable nugaeva-bot.service
sudo systemctl enable nugaeva-webhook.service

# запускаем сервисы
sudo systemctl start nugaeva-bot.service
sudo systemctl start nugaeva-webhook.service

# проверяем статус
sudo systemctl status nugaeva-bot.service
sudo systemctl status nugaeva-webhook.service
```

## Шаг 5: Настройка доступа к webhook

Есть несколько вариантов. Выбери подходящий:

### Вариант 1: Без reverse proxy (самый простой)

Если у тебя нет домена или не нужен SSL, просто открой порт 8080:

```bash
# порт уже будет открыт после настройки firewall (шаг 6)
# URL для Prodamus: http://твой_IP:8080/webhook/prodamus
```

**Плюсы**: просто, быстро  
**Минусы**: нет SSL, нужен IP адрес

### Вариант 2: Caddy (рекомендуется, если есть домен)

**Важно**: Для HTTPS нужен домен. Если домена нет:
- Можно купить дешевый домен (от 100-200₽/год)
- Или использовать бесплатный домен (Freenom, но ненадежно)
- Или проверить, работает ли Prodamus с HTTP (для тестирования)

Caddy — современный веб-сервер с автоматическим SSL.

#### 5.2.1. Установка Caddy

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
```

#### 5.2.2. Создание конфигурации

```bash
sudo nano /etc/caddy/Caddyfile
```

Вставь:

```
твой_домен.ru {
    reverse_proxy /webhook/prodamus localhost:8080
    reverse_proxy /health localhost:8080
}
```

**Важно**: замени `твой_домен.ru` на свой домен.

#### 5.2.3. Запуск Caddy

```bash
sudo systemctl enable caddy
sudo systemctl start caddy
sudo systemctl reload caddy
```

Caddy автоматически получит SSL сертификат через Let's Encrypt.

**Плюсы**: автоматический SSL, простая настройка  
**Минусы**: нужен домен

### Вариант 3: Nginx (классический вариант)

Если предпочитаешь Nginx:

```bash
sudo apt install nginx -y
sudo nano /etc/nginx/sites-available/nugaeva-bot
```

Вставь:

```nginx
server {
    listen 80;
    server_name твой_домен.ru;

    location /webhook/prodamus {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /health {
        proxy_pass http://127.0.0.1:8080;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/nugaeva-bot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d твой_домен.ru
```

### Вариант 4: Traefik (для Docker)

Если используешь Docker, можно использовать Traefik. Пример `docker-compose.yml`:

```yaml
version: '3.8'

services:
  bot:
    build: .
    environment:
      - BOT_TOKEN=${BOT_TOKEN}
    # ... остальные переменные
    restart: unless-stopped

  webhook:
    build: .
    command: python webhook_server.py
    ports:
      - "8080:8080"
    environment:
      - BOT_TOKEN=${BOT_TOKEN}
    restart: unless-stopped
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.webhook.rule=Host(`твой_домен.ru`)"
      - "traefik.http.routers.webhook.entrypoints=websecure"
      - "traefik.http.routers.webhook.tls.certresolver=letsencrypt"
      - "traefik.http.services.webhook.loadbalancer.server.port=8080"
```

## Шаг 6: Настройка Firewall

```bash
# разрешаем SSH (если еще не разрешен)
sudo ufw allow 22/tcp

# разрешаем HTTP и HTTPS (если используешь Caddy/Nginx)
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# разрешаем порт webhook сервера напрямую (если используешь вариант 1 - без reverse proxy)
sudo ufw allow 8080/tcp

# включаем firewall
sudo ufw enable
```

## Шаг 7: Настройка в Prodamus

1. Зайди в личный кабинет Prodamus
2. Перейди в раздел **"Настройки"**
3. В поле **"URL-адрес для уведомлений"** укажи:
   - **Вариант 1 (без reverse proxy)**: `http://твой_IP:8080/webhook/prodamus`
   - **Вариант 2/3 (Caddy/Nginx с доменом)**: `https://твой_домен.ru/webhook/prodamus`
4. В разделе **"Подписки"** → **"URL адреса для уведомлений о совершении оплат по подписке"** укажи тот же URL
5. Сохрани изменения

**Важно**: 
- Для продакшена рекомендуется использовать HTTPS (варианты 2 или 3), так как Prodamus может требовать защищенное соединение.
- Если нет домена, можно временно использовать HTTP (вариант 1) для тестирования, но для продакшена лучше купить домен и настроить HTTPS.
- Дешевые домены: .ru от 100-200₽/год, .xyz от 200₽/год

## Шаг 8: Проверка работы

### 8.1. Проверка логов бота

```bash
sudo journalctl -u nugaeva-bot.service -f
```

### 8.2. Проверка логов webhook сервера

```bash
sudo journalctl -u nugaeva-webhook.service -f
```

### 8.3. Проверка health endpoint

```bash
# если есть домен
curl https://твой_домен.ru/health

# если нет домена
curl http://твой_IP:8080/health
```

Должен вернуться: `{"status": "ok"}`

## Шаг 9: Обновление бота

При обновлении кода:

```bash
cd ~/nugaeva-dance-bot
git pull  # или загрузи новые файлы
source venv/bin/activate
pip install -r requirements.txt  # если добавились зависимости

# перезапуск сервисов
sudo systemctl restart nugaeva-bot.service
sudo systemctl restart nugaeva-webhook.service
```

## Полезные команды

```bash
# остановить бота
sudo systemctl stop nugaeva-bot.service

# запустить бота
sudo systemctl start nugaeva-bot.service

# перезапустить бота
sudo systemctl restart nugaeva-bot.service

# посмотреть логи
sudo journalctl -u nugaeva-bot.service -n 50

# то же для webhook
sudo systemctl restart nugaeva-webhook.service
sudo journalctl -u nugaeva-webhook.service -n 50
```

## Важные замечания

1. **Безопасность**: Убедись, что `.env` файл не попал в git (он в `.gitignore`)
2. **Бэкапы**: Регулярно делай бэкап `bot.db` (база данных)
3. **Мониторинг**: Следи за логами, особенно после первого запуска
4. **Порты**: Если используешь Nginx, порт 8080 можно закрыть в firewall (он будет доступен только локально)

## Если что-то не работает

1. Проверь логи: `sudo journalctl -u nugaeva-bot.service -n 100`
2. Проверь, что сервисы запущены: `sudo systemctl status nugaeva-bot.service`
3. Проверь, что порты открыты: `sudo netstat -tlnp | grep 8080`
4. Проверь права доступа к файлам: `ls -la ~/nugaeva-dance-bot`

---

# Деплой С Docker (для изоляции и удобства)

## Преимущества Docker

- ✅ Изоляция зависимостей
- ✅ Легче обновление и откат
- ✅ Консистентность окружения
- ✅ Проще управление несколькими сервисами

## Шаг 1: Установка Docker

```bash
# обновляем систему
sudo apt update && sudo apt upgrade -y

# устанавливаем Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# добавляем пользователя в группу docker (чтобы не использовать sudo)
sudo usermod -aG docker $USER
newgrp docker  # или перелогинься

# устанавливаем Docker Compose
sudo apt install docker-compose-plugin -y

# проверяем установку
docker --version
docker compose version
```

## Шаг 2: Подготовка проекта

```bash
cd ~
git clone https://github.com/your_username/nugaeva-dance-bot.git
cd nugaeva-dance-bot
```

## Шаг 3: Создание .env файла

```bash
nano .env
```

Вставь все переменные (те же, что и в варианте без Docker):

```env
BOT_TOKEN=твой_токен_бота
BOT_USERNAME=твой_бот_username
ADMIN_IDS=123456789,987654321
CHANNEL_ID=-1001234567890

PRODAMUS_API_KEY=твой_api_ключ
PRODAMUS_SYS=твой_sys
PRODAMUS_WEBHOOK_SECRET=твой_webhook_secret
PRODAMUS_WEBHOOK_URL=https://твой_домен/webhook/prodamus

PRODAMUS_PRODUCT_ID_MONTHLY=id_подписки_1_месяц
PRODAMUS_PRODUCT_ID_HALF_YEAR=id_подписки_6_месяцев
PRODAMUS_PRODUCT_ID_LIFETIME=id_подписки_навсегда
```

## Шаг 4: Подготовка директории для БД

```bash
# создай директорию data с правильными правами
mkdir -p data

# установи владельца (uid 1000 = botuser в контейнере)
# это позволит контейнеру создавать файлы в этой директории
sudo chown -R 1000:1000 data

# установи безопасные права (владелец: rwx, группа: rx, остальные: rx)
chmod 755 data
```

## Шаг 5: Сборка и запуск

```bash
# собираем образы
docker compose build

# запускаем контейнеры
docker compose up -d

# проверяем статус
docker compose ps

# смотрим логи
docker compose logs -f bot
docker compose logs -f webhook
```

**Важно**: Если после запуска возникают ошибки с правами доступа к БД, проверь:

```bash
# проверь владельца директории data
ls -la data

# должно быть что-то вроде:
# drwxr-xr-x 2 1000 1000 4096 Nov 22 00:00 .

# если владелец другой, исправь:
sudo chown -R 1000:1000 data
```

## Шаг 5: Настройка автозапуска

Docker Compose автоматически перезапускает контейнеры при перезагрузке сервера (благодаря `restart: unless-stopped`).

Если хочешь запускать через systemd:

```bash
sudo nano /etc/systemd/system/nugaeva-docker.service
```

Вставь:

```ini
[Unit]
Description=Nugaeva Bot Docker Compose
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/твой_пользователь/nugaeva-dance-bot
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
User=твой_пользователь
Group=docker

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable nugaeva-docker.service
sudo systemctl start nugaeva-docker.service
```

## Шаг 6: Настройка reverse proxy (Caddy/Nginx)

Аналогично варианту без Docker. В конфигурации Caddy/Nginx укажи `localhost:8080` (порт уже проброшен в docker-compose.yml).

## Шаг 7: Настройка в Prodamus

Аналогично варианту без Docker.

## Обновление бота (Docker)

```bash
cd ~/nugaeva-dance-bot
git pull
docker compose build
docker compose up -d
```

## Полезные команды Docker

```bash
# остановить контейнеры
docker compose down

# запустить контейнеры
docker compose up -d

# перезапустить
docker compose restart

# посмотреть логи
docker compose logs -f

# посмотреть статус
docker compose ps

# зайти в контейнер (для отладки)
docker compose exec bot bash
```

## Бэкап БД (Docker)

```bash
# копируем БД из контейнера
docker compose cp bot:/app/bot.db ./backup/bot_$(date +%Y%m%d_%H%M%S).db
```

---

## Какой вариант выбрать?

**Без Docker**, если:
- Маленький сервер (1GB RAM)
- Хочешь минимум зависимостей
- Не знаком с Docker

**С Docker**, если:
- Хочешь изоляцию окружения
- Планируешь масштабирование
- Удобнее управлять через docker-compose
- Нужна консистентность между dev и prod

