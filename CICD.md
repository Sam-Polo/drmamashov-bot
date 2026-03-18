# CI/CD (GitHub Actions) + деплой на Ubuntu через Docker Compose

## 0) Что делает CI/CD
- на каждый `push` в `main` (и вручную через `workflow_dispatch`) GitHub Actions подключается по SSH на сервер
- обновляет код до `origin/main`
- пересобирает образы и перезапускает контейнеры `docker compose`

Файл workflow: `.github/workflows/deploy.yml`.

## 1) Подготовка Ubuntu сервера (one-time)
Ниже команды рассчитаны на чистый Ubuntu под `root`.

### 1.1. Установка Docker + Compose plugin

```bash
apt-get update -y
apt-get install -y ca-certificates curl gnupg git

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
docker --version
docker compose version
```

### 1.2. Пользователь `deploy` (рекомендуется вместо root)

```bash
useradd -m -s /bin/bash deploy || true
usermod -aG docker deploy
mkdir -p /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
touch /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh
```

### 1.3. Каталог проекта и первый запуск

```bash
mkdir -p /opt/drmamashov-bot
chown -R deploy:deploy /opt/drmamashov-bot

sudo -u deploy bash -lc '
  set -e
  cd /opt/drmamashov-bot
  if [ ! -d .git ]; then
    # используем ssh-url, чтобы git не требовал логин/пароль
    git clone git@github.com:Sam-Polo/drmamashov-bot.git .
  fi
  mkdir -p data media
'
```

Создай `/opt/drmamashov-bot/.env` на сервере (по образцу `.env.example`), затем:

```bash
sudo -u deploy bash -lc '
  set -e
  cd /opt/drmamashov-bot
  docker compose up -d --build
  docker compose ps
'
```

Логи:

```bash
sudo -u deploy bash -lc 'cd /opt/drmamashov-bot && docker compose logs -f --tail=200 bot'
sudo -u deploy bash -lc 'cd /opt/drmamashov-bot && docker compose logs -f --tail=200 webhook'
```

## 2) SSH ключи (без пароля)

### 2.1. Ключ для твоего ПК
На Windows:

```powershell
ssh-keygen -t ed25519 -C "pc@drmamashov-bot" -f $env:USERPROFILE\\.ssh\\drmamashov_bot_pc
type $env:USERPROFILE\\.ssh\\drmamashov_bot_pc.pub
```

Публичный ключ вставь на сервер в `/home/deploy/.ssh/authorized_keys` (одной строкой):

```bash
sudo -u deploy bash -lc 'nano /home/deploy/.ssh/authorized_keys'
```

Проверка с ПК:

```powershell
ssh -i $env:USERPROFILE\\.ssh\\drmamashov_bot_pc root@155.212.141.11
```

### 2.2. Ключ для GitHub Actions
Сгенерируй отдельный ключ (на ПК или на сервере). Рекомендую на ПК:

```powershell
ssh-keygen -t ed25519 -C "gha@drmamashov-bot" -f $env:USERPROFILE\\.ssh\\drmamashov_bot_gha -N \"\"
type $env:USERPROFILE\\.ssh\\drmamashov_bot_gha.pub
```

Публичный ключ добавь на сервер в `authorized_keys` пользователю `deploy` (новой строкой).

Приватный ключ (`drmamashov_bot_gha`, без `.pub`) добавь в GitHub Secrets как `DEPLOY_SSH_KEY`.

### 2.3. Ключ для git clone/fetch на сервере (GitHub)
Так как в workflow выполняются `git fetch/reset`, на сервере должен быть ssh-доступ к github по ключу (от `root` или от пользователя `deploy`, которым ты запускаешь docker compose).

На сервере сгенерируй ключ для `deploy`:

```bash
sudo -u deploy bash -lc '
  set -e
  mkdir -p ~/.ssh
  chmod 700 ~/.ssh
  if [ ! -f ~/.ssh/id_ed25519 ]; then
    ssh-keygen -t ed25519 -C "deploy@drmamashov-bot" -f ~/.ssh/id_ed25519 -N ""
  fi
  cat ~/.ssh/id_ed25519.pub
'
```

Скопируй вывод (public key) в GitHub:
- либо как `Deploy key` для репозитория `drmamashov-bot`
- либо как `SSH key` в аккаунт, который имеет доступ к репозиторию

Проверь:

```bash
sudo -u deploy bash -lc 'ssh -T git@github.com'
```

Если ты работаешь именно от `root`, а по умолчанию ssh выбирает не тот ключ (что мы уже видели по ошибке `Permission denied (publickey)`),
задай ключ явно через ssh-config:

```bash
cat > /root/.ssh/config <<'EOF'
Host github.com
  User git
  IdentityFile /root/.ssh/github
  IdentitiesOnly yes
EOF
chmod 600 /root/.ssh/config
ssh -T git@github.com
```

Дальше можно снова пробовать clone/fetch через `git@github.com:...`.

## 3) GitHub Secrets (обязательно)
В GitHub → Settings → Secrets and variables → Actions → Secrets добавь:

- `DEPLOY_HOST`: `155.212.141.11`
- `DEPLOY_PORT`: `22`
- `DEPLOY_USER`: `deploy`
- `DEPLOY_PATH`: `/opt/drmamashov-bot`
- `DEPLOY_SSH_KEY`: приватный ключ `ed25519` для Actions

После этого любой `push` в `main` должен запускать автодеплой.

## 4) Усиление безопасности (после того, как ключи проверены)
- отключить парольную аутентификацию SSH
- запретить root-login по паролю

Файлы: `/etc/ssh/sshd_config` и перезапуск `systemctl restart ssh`.

