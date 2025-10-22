from discord.ext import commands
import discord
from database.models import User, LabWork
from tortoise.exceptions import DoesNotExist
from typing import Union


class LabsCog(commands.Cog):
    """Команды для сдачи и проверки лабораторных работ."""

    def __init__(self, bot):
        self.bot = bot

    # -------------------- Команды студента --------------------

    @commands.command(name="submit")
    async def submit_lab(self, ctx, lab_number: int):
        """
        Сдать лабораторную работу.
        Использование: !submit <номер> (с прикреплённым файлом)
        """
        if not ctx.message.attachments:
            await ctx.send("📎 Прикрепи файл с работой к сообщению!")
            return

        attachment = ctx.message.attachments[0]
        file_url = attachment.url

        user = await self._ensure_user(ctx.author)


        lab, created = await LabWork.get_or_create(
            user=user,
            lab_number=lab_number,
            defaults={"file_url": file_url}
        )
        if not created:
            lab.file_url = file_url
            lab.status = "отправлено"
            await lab.save()
            msg = "🔁 Лабораторная обновлена и повторно отправлена."
        else:
            msg = "✅ Лабораторная успешно отправлена."

        await ctx.send(f"{msg}\n📘 Лабораторная №{lab_number}\n📎 {file_url}")

    @commands.command(name="status")
    async def status_lab(self, ctx, lab_number: int):
        """Проверить статус лабораторной работы."""
        user = await User.get_or_none(discord_id=ctx.author.id)
        if not user:
            await ctx.send("❌ Вы ещё не зарегистрированы.")
            return

        lab = await LabWork.get_or_none(user=user, lab_number=lab_number)
        if not lab:
            await ctx.send(f"⚠️ У вас нет лабораторной №{lab_number}.")
            return

        embed = discord.Embed(
            title=f"Лабораторная №{lab.lab_number}",
            description=f"**Статус:** {lab.status.capitalize()}",
            color=discord.Color.green() if lab.status == "зачтено" else discord.Color.orange()
        )
        if lab.feedback:
            embed.add_field(name="Комментарий преподавателя", value=lab.feedback, inline=False)
        if lab.file_url:
            embed.add_field(name="Файл", value=lab.file_url, inline=False)

        await ctx.send(embed=embed)

    @commands.command(name="labs")
    async def list_labs(self, ctx):
        """Показать список всех лабораторных работ."""
        user = await self._ensure_user(ctx.author)

        labs = await LabWork.filter(user=user).order_by("lab_number")
        if not labs:
            await ctx.send("📂 У вас ещё нет лабораторных работ.")
            return

        embed = discord.Embed(title=f"Лабораторные работы {user.first_name} {user.last_name}")
        for lab in labs:
            embed.add_field(
                name=f"№{lab.lab_number} — {lab.status.capitalize()}",
                value=f"[Файл]({lab.file_url})" if lab.file_url else "❌ Нет файла",
                inline=False
            )
        await ctx.send(embed=embed)

    # -------------------- Команды преподавателя --------------------

    @commands.has_permissions(administrator=True)
    @commands.command(name="review")
    async def review_lab(self, ctx, student: discord.Member, lab_number: int, *, comment: str):
        """Отправить лабораторную на доработку."""
        user = await User.get_or_none(discord_id=student.id)
        if not user:
            await ctx.send("❌ Этот студент не найден в базе.")
            return

        lab = await LabWork.get_or_none(user=user, lab_number=lab_number)
        if not lab:
            await ctx.send("⚠️ У студента нет этой лабораторной.")
            return

        lab.status = "на доработке"
        lab.feedback = comment
        await lab.save()
        await ctx.send(f"🛠️ Лабораторная №{lab_number} студента {student.mention} отправлена на доработку.")
        await student.send(f"🛠️ Твоя лабораторная №{lab_number} отправлена на доработку.\nКомментарий: {comment}")

    @commands.has_permissions(administrator=True)
    @commands.command(name="accept")
    async def accept_lab(self, ctx, student: discord.Member, lab_number: int):
        """Зачесть лабораторную работу."""
        user = await User.get_or_none(discord_id=student.id)
        if not user:
            await ctx.send("❌ Этот студент не найден в базе.")
            return

        lab = await LabWork.get_or_none(user=user, lab_number=lab_number)
        if not lab:
            await ctx.send("⚠️ У студента нет этой лабораторной.")
            return

        lab.status = "зачтено"
        await lab.save()
        await ctx.send(f"✅ Лабораторная №{lab_number} студента {student.mention} зачтена.")
        await student.send(f"🎉 Твоя лабораторная №{lab_number} зачтена! Отличная работа!")
        
    async def _ensure_user(self, member: Union[discord.Member, discord.User]) -> User:
        """Возвращает пользователя из БД или создаёт запись на лету (для старых участников)."""
        user = await User.get_or_none(discord_id=member.id)
        if user:
            return user

        # Пытаемся угадать имя/фамилию из display_name; если нет — ставим заглушки
        display = str(getattr(member, "display_name", member.name)).strip()
        first, last = (display.split() + ["-", "-"])[:2]
        return await User.create(
            discord_id=member.id,
            first_name=first,
            last_name=last,
            group="Неизвестные",
        )


async def setup(bot):
    await bot.add_cog(LabsCog(bot))
