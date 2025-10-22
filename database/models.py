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

    labworks: fields.ReverseRelation["LabWork"]

    class Meta:
        table = "users"

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.group})"

class LabWork(models.Model):
    """
    Таблица лабораторных работ студентов.
    """
    id = fields.IntField(pk=True)
    user = fields.ForeignKeyField("models.User", related_name="labworks")
    lab_number = fields.IntField()  # Номер лабораторной
    file_url = fields.TextField(null=True)  # Ссылка на прикреплённый файл (Discord attachment URL)
    status = fields.CharField(max_length=20, default="отправлено")  # отправлено / на доработке / зачтено
    feedback = fields.TextField(null=True)  # Комментарий преподавателя
    submitted_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "labworks"
        unique_together = ("user", "lab_number")  # одна лабораторная на одного пользователя
