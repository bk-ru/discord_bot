# cogs/commands.py

from discord.ext import commands
import discord
from discord import PermissionOverwrite
from utils.file_manager import ensure_group_sheet, remove_group_sheet
from typing import Optional

class BasicCommands(commands.Cog):
    """Простые команды Discord бота."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def info(self, ctx):
        await ctx.send('Я бот виртуальной кафедры! Используй !help для списка команд.')

    @commands.command()
    async def ping(self, ctx):
        await ctx.send(f'Pong! Задержка: {round(self.bot.latency * 1000)}ms')

    @commands.command(aliases=["верификация", "регистрация", "verify_me"])
    async def verify(self, ctx):
        # (как в прошлой версии)
        ...

    # -------------------------- НОВОЕ: добавление группы --------------------------

    @commands.command(name="addgroup", aliases=["add_group", "добавитьгруппу"])
    @commands.has_permissions(administrator=True)
    async def add_group(self, ctx, *, group_name: Optional[str] = None):
        """
        Создаёт новую группу:
        - добавляет лист в Excel с колонками ИМЯ | ФАМИЛИЯ
        - создаёт роль с названием группы и категорию с ограниченным доступом
        - создаёт текстовый канал внутри категории
        Использование: !addgroup ГР-01
        """
        if not group_name:
            await ctx.send("❗ Укажи имя группы. Пример: `!addgroup ГР-01`")
            return

        group_name = group_name.strip()
        if not group_name:
            await ctx.send("❗ Имя группы не может быть пустым.")
            return

        guild: discord.Guild = ctx.guild
        if guild is None:
            await ctx.send("❗ Команду нужно вызывать с сервера (не в ЛС).")
            return

        # 1) Excel: гарантируем лист
        try:
            created = ensure_group_sheet(group_name)
        except Exception:
            await ctx.send(f"❌ Не удалось создать/проверить лист для группы **{group_name}**. Смотри логи бота.")
            return

        # 2) Роль
        role = discord.utils.get(guild.roles, name=group_name)
        role_created = False
        if role is None:
            try:
                role = await guild.create_role(name=group_name, reason="Создание учебной группы")
                role_created = True
            except discord.Forbidden:
                await ctx.send("❌ Мне нужны права **Manage Roles** (Управлять ролями).")
                return

        # 3) Категория
        category = discord.utils.get(guild.categories, name=group_name)
        category_created = False
        category_overwrites = {
            guild.default_role: PermissionOverwrite(view_channel=False),
            role: PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        if category is None:
            try:
                category = await guild.create_category(
                    name=group_name,
                    overwrites=category_overwrites,
                    reason="Создание учебной группы"
                )
                category_created = True
            except discord.Forbidden:
                await ctx.send("❌ Мне нужны права **Manage Channels** (Управлять каналами).")
                return
        else:
            try:
                await category.edit(overwrites=category_overwrites, reason="Обновление прав учебной группы")
            except discord.Forbidden:
                await ctx.send("❌ Не смог обновить права категории. Нужны права **Manage Channels**.")
                return

        # Гарантируем права для роли и скрываем категорию от остальных
        try:
            await category.set_permissions(role, view_channel=True, send_messages=True, read_message_history=True)
            await category.set_permissions(guild.default_role, view_channel=False)
        except discord.Forbidden:
            await ctx.send("❌ Не удалось обновить права категории. Нужны права **Manage Channels**.")
            return

        # 4) Текстовый канал
        channel_name = group_name.lower().replace(" ", "-")
        channel = discord.utils.get(category.text_channels, name=channel_name)
        channel_created = False
        overwrites = {
            guild.default_role: PermissionOverwrite(view_channel=False),
            role: PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }

        if channel is None:
            # Проверим, не существует ли канал вне категории
            orphan_channel = discord.utils.get(guild.text_channels, name=channel_name)
            if orphan_channel and orphan_channel != channel:
                try:
                    await orphan_channel.edit(
                        category=category,
                        overwrites=overwrites,
                        reason="Перемещение канала учебной группы в категорию"
                    )
                    channel = orphan_channel
                except discord.Forbidden:
                    await ctx.send("❌ Не смог переместить существующий канал. Нужны права **Manage Channels**.")
                    return
            else:
                try:
                    channel = await category.create_text_channel(
                        channel_name,
                        overwrites=overwrites,
                        reason="Создание канала учебной группы"
                    )
                    channel_created = True
                except discord.Forbidden:
                    await ctx.send("❌ Не удалось создать текстовый канал. Нужны права **Manage Channels**.")
                    return
        else:
            try:
                await channel.edit(overwrites=overwrites, reason="Обновление прав канала учебной группы")
            except discord.Forbidden:
                await ctx.send("❌ Не смог обновить права канала. Нужны права **Manage Channels**.")
                return

        excel_msg = "лист создан" if created else "лист уже был"
        role_msg = "роль создана" if role_created else "роль уже существовала"
        category_msg = "категория создана" if category_created else "категория обновлена"
        channel_msg = "канал создан" if channel_created else "канал обновлён"

        await ctx.send(
            f"✅ Группа **{group_name}** готова: {excel_msg}, {role_msg}, {category_msg}, {channel_msg}."
        )

    @add_group.error
    async def add_group_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("⛔ Эта команда только для администраторов.")
        else:
            await ctx.send(f"❌ Ошибка: {error}")

    @commands.command(name="removegroup", aliases=["remove_group", "deletegroup", "удалитьгруппу"])
    @commands.has_permissions(administrator=True)
    async def remove_group(self, ctx, *, group_name: Optional[str] = None):
        """
        Удаляет группу: лист в Excel, категорию, связанные каналы и роль.
        Использование: !removegroup ГР-01
        """
        if not group_name:
            await ctx.send("❗ Укажи имя группы. Пример: `!removegroup ГР-01`")
            return

        group_name = group_name.strip()
        if not group_name:
            await ctx.send("❗ Имя группы не может быть пустым.")
            return

        guild: discord.Guild = ctx.guild
        if guild is None:
            await ctx.send("❗ Команду нужно вызывать с сервера (не в ЛС).")
            return

        statuses = []

        sheet_removed = remove_group_sheet(group_name)
        statuses.append("лист удалён" if sheet_removed else "листа не было")

        role = discord.utils.get(guild.roles, name=group_name)
        if role:
            try:
                await role.delete(reason="Удаление учебной группы")
                statuses.append("роль удалена")
            except discord.Forbidden:
                statuses.append("нет прав удалить роль")
        else:
            statuses.append("роль не найдена")

        category = discord.utils.get(guild.categories, name=group_name)
        if category:
            try:
                await category.delete(reason="Удаление учебной группы")
                statuses.append("категория удалена вместе с каналами")
            except discord.Forbidden:
                statuses.append("нет прав удалить категорию")
        else:
            # На случай старой структуры проверим одиночный канал
            channel_name = group_name.lower().replace(" ", "-")
            channel = discord.utils.get(guild.text_channels, name=channel_name)
            if channel:
                try:
                    await channel.delete(reason="Удаление канала учебной группы")
                    statuses.append("канал удалён")
                except discord.Forbidden:
                    statuses.append("нет прав удалить канал")
            else:
                statuses.append("категория/каналы не найдены")

        await ctx.send(f"ℹ️ Группа **{group_name}**: {', '.join(statuses)}.")

    @remove_group.error
    async def remove_group_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("⛔ Эта команда только для администраторов.")
        else:
            await ctx.send(f"❌ Ошибка: {error}")

class HelpCog(commands.Cog):
    """Динамическая справка по командам."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help", help="Показать список доступных команд.")
    async def help_command(self, ctx):
        """Отправляет справку, учитывая роли и права пользователя."""
        user = ctx.author
        embed = discord.Embed(
            title="📘 Справка по командам",
            description=f"Доступные команды для {user.mention}",
            color=discord.Color.blue()
        )

        # Проверка ролей и прав
        is_admin = user.guild_permissions.administrator
        roles = [r.name.lower() for r in user.roles]

        # 🧩 Базовые команды (для всех)
        embed.add_field(
            name="🧭 Основные команды",
            value=(
                "`!info` — Информация о боте.\n"
                "`!ping` — Проверка задержки соединения.\n"
                "`!help` — Показать это сообщение."
            ),
            inline=False
        )

        # 🎓 Для зарегистрированных студентов
        if any(r for r in roles if r not in ["@everyone", "неизвестные"]):
            embed.add_field(
                name="🎓 Команды для студентов",
                value=(
                    "`!labs` — Просмотр списка своих лабораторных.\n"
                    "`!submit <номер>` — Отправить лабораторную работу.\n"
                    "`!status <номер>` — Проверить статус своей лабораторной."
                ),
                inline=False
            )

        # 🧑‍🏫 Для преподавателей / администраторов
        if is_admin or any("преподаватель" in r for r in roles):
            embed.add_field(
                name="🧑‍🏫 Команды для администраторов",
                value=(
                    "`!addgroup <название>` — Добавить новую группу.\n"
                    "`!removegroup <название>` — Удалить группу, связанные каналы и роль.\n"
                    "`!reloadlist` — Перезагрузить список студентов из Excel.\n"
                    "`!announce <текст>` — Отправить объявление всем студентам.\n"
                    "`!cleanup_feedback` — Очистить старые сообщения из feedback."
                ),
                inline=False
            )

        # ⚙️ Если у пользователя нет особых прав
        if len(embed.fields) == 1:
            embed.add_field(
                name="⚠️ Нет доступных команд",
                value="У вас пока нет команд, требующих особых прав.",
                inline=False
            )

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(BasicCommands(bot))
    await bot.add_cog(HelpCog(bot))
