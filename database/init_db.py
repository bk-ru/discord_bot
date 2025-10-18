"""
database/init_db.py
Инициализация Tortoise ORM при запуске бота.
"""

from tortoise import Tortoise
from config import TORTOISE_CONFIG

async def init_db():
    """Подключает базу данных и создаёт таблицы при необходимости."""
    await Tortoise.init(config=TORTOISE_CONFIG)
    await Tortoise.generate_schemas()
    print("Схемы базы данных успешно сгенерированы.")
