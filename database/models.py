"""
database/models.py
Определение моделей Tortoise ORM.
"""

from tortoise import models, fields

class User(models.Model):
    """Модель пользователя Discord, сохранённого в базе данных."""
    id = fields.IntField(pk=True)
    discord_id = fields.BigIntField(unique=True)
    first_name = fields.TextField()
    last_name = fields.TextField()
    group = fields.TextField()

    class Meta:
        table = "users"

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.group})"
