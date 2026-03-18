FROM python:3.10-slim

WORKDIR /app

# копируем requirements и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# копируем код приложения
COPY . .

# создаем пользователя для запуска (не root)
# используем фиксированный UID/GID для совместимости с хостом
RUN groupadd -g 1000 botuser && \
    useradd -m -u 1000 -g botuser botuser && \
    chown -R botuser:botuser /app

# создаем директорию для БД с правильными правами
RUN mkdir -p /app/data && \
    chown -R botuser:botuser /app/data && \
    chmod 755 /app/data

USER botuser

# переменные окружения будут переданы через docker-compose или docker run
ENV PYTHONUNBUFFERED=1

