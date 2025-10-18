"""
config.py
Загружает переменные окружения и задаёт базовые настройки бота и базы данных.
"""

import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
FILE_PATH = os.getenv('READER_FILE_PATH', os.path.join(os.getcwd(), 'students.xlsx'))

TORTOISE_CONFIG = {
    'connections': {'default': 'sqlite://database.sqlite3'},
    'apps': {
        'models': {
            'models': ['database.models'],
            'default_connection': 'default',
        }
    }
}
