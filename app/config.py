"""Конфигурация бота с загрузкой переменных окружения."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# Токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения. Создайте .env файл с BOT_TOKEN=your_token")

# Путь к базе данных SQLite
DB_PATH = os.getenv("DB_PATH", "theatre_bot.db")

# Директория для экспорта файлов
EXPORT_DIR = Path(os.getenv("EXPORT_DIR", "exports"))
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# Настройки прокси (опционально)
PROXY_URL = os.getenv("PROXY_URL")  # Например: http://proxy.example.com:8080 или socks5://proxy.example.com:1080

