"""
config.py
Загружает переменные окружения и задаёт базовые настройки бота и базы данных.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Discord токен
TOKEN = os.getenv('DISCORD_TOKEN')

# Путь к Excel-файлу со студентами
FILE_PATH = os.getenv('READER_FILE_PATH', os.path.join(os.getcwd(), 'students.xlsx'))

# Конфигурация Tortoise ORM + Aerich для миграций
TORTOISE_CONFIG = {
    "connections": {
        "default": "sqlite://database.sqlite3"
    },
    "apps": {
        "models": {  # твои модели приложения
            "models": ["database.models"],  # путь до модуля, где лежат модели
            "default_connection": "default",
        },
        "aerich": {  # служебное приложение Aerich
            "models": ["aerich.models"],
            "default_connection": "default",
        },
    },
}
