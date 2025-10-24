from __future__ import annotations

import discord
from discord.ext import commands


class GeneralCommands(commands.Cog):
    """Базовые команды Discord-бота."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command()
    async def info(self, ctx: commands.Context) -> None:
        await ctx.send("👋 Привет! Я бот-помощник. Используйте !help для списка возможностей.")

    @commands.command()
    async def ping(self, ctx: commands.Context) -> None:
        await ctx.send(f"Pong! Задержка: {round(self.bot.latency * 1000)}ms")

    @commands.command(aliases=["подтвердиться", "верифицируйся", "verify_me"])
    async def verify(self, ctx: commands.Context) -> None:
        # TODO: реализовать реальную верификацию
        await ctx.send("🔒 Команда верификации пока в разработке. Свяжитесь с модератором.")


class HelpCog(commands.Cog):
    """Формирует справочное сообщение с командами."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="help", help="Подробная справка по основным командам.")
    async def help_command(self, ctx: commands.Context) -> None:
        """Выдаёт основное меню помощи, сгруппированное по типу пользователя."""
        user = ctx.author
        embed = discord.Embed(
            title="📘 Доступные команды бота",
            description=f"👤 Владелец запроса: {user.mention}",
            color=discord.Color.blue(),
        )

        # Базовый набор доступен всем
        embed.add_field(
            name="🧭 Общие команды",
            value=(
                "`!info` — справка о боте.\n"
                "`!ping` — измерение задержки соединения.\n"
                "`!help` — текущее меню помощи."
            ),
            inline=False,
        )

        roles = [role.name.lower() for role in user.roles]
        is_admin = user.guild_permissions.administrator

        # Команды для студентов (все, у кого есть роли помимо @everyone и "Неизвестные")
        if any(role for role in roles if role not in ["@everyone", "неизвестные"]):
            embed.add_field(
                name="📚 Команды для студентов",
                value=(
                    "`!labs` — список доступных лабораторных.\n"
                    "`!submit <номер>` — отправка выполненной лабораторной.\n"
                    "`!status <номер>` — проверка статуса лабораторной."
                ),
                inline=False,
            )

        # Админские / преподавательские команды
        teacher_marker = "преподаватель"  # условное название роли
        has_teacher_access = is_admin or any(teacher_marker in role for role in roles)

        if is_admin:
            embed.add_field(
                name="🏷️ Управление группами",
                value=(
                    "`!addgroup <название>` — создать учебную группу.\n"
                    "`!removegroup <название>` — удалить учебную группу."
                ),
                inline=False,
            )

        if has_teacher_access:
            embed.add_field(
                name="🧪 Команды по лабораторным",
                value=(
                    "`!review @студент <номер> <комментарий>` — отправить работу на доработку.\n"
                    "`!accept @студент <номер>` — зачесть лабораторную.\n"
                    "`!labfile @студент <номер>` — получить ссылку на вложение.\n"
                    "`!deletelab @студент <номер>` — удалить работу."
                ),
                inline=False,
            )

        if len(embed.fields) == 1:
            embed.add_field(
                name="ℹ️ Нет доступных команд",
                value="Похоже, пока что у вас нет дополнительных ролей. Обратитесь к модератору.",
                inline=False,
            )

        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GeneralCommands(bot))
    await bot.add_cog(HelpCog(bot))
