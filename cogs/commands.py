# cogs/commands.py

from discord.ext import commands
import discord
from discord import PermissionOverwrite
from utils.file_manager import ensure_group_sheet
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
        - создаёт роль с названием группы
        - создаёт текстовый канал #группа-<имя> с доступом для роли
        Использование: !addgroup ГР-01
        """
        if not group_name:
            await ctx.send("❗ Укажи имя группы. Пример: `!addgroup ГР-01`")
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
        if role is None:
            try:
                role = await guild.create_role(name=group_name)
                role_msg = "создана"
            except discord.Forbidden:
                await ctx.send("❌ Мне нужны права **Manage Roles** (Управлять ролями).")
                return
        else:
            role_msg = "уже существует"

        # 3) Канал
        channel_name = f"группа-{group_name.lower()}"
        channel = discord.utils.get(guild.text_channels, name=channel_name)
        if channel is None:
            overwrites = {
                guild.default_role: PermissionOverwrite(view_channel=False),
                role: PermissionOverwrite(view_channel=True, send_messages=True),
            }
            try:
                await guild.create_text_channel(channel_name, overwrites=overwrites)
                ch_msg = "создан"
            except discord.Forbidden:
                await ctx.send("❌ Мне нужны права **Manage Channels** (Управлять каналами).")
                return
        else:
            # Обновим права на всякий случай
            try:
                await channel.edit(overwrites={
                    guild.default_role: PermissionOverwrite(view_channel=False),
                    role: PermissionOverwrite(view_channel=True, send_messages=True),
                })
                ch_msg = "уже был, права обновлены"
            except discord.Forbidden:
                await ctx.send("❌ Не смог обновить права канала. Нужны права **Manage Channels**.")
                return

        excel_msg = "лист создан" if created else "лист уже был"
        await ctx.send(
            f"✅ Группа **{group_name}** готова: {excel_msg}, роль {role_msg}, канал {ch_msg}."
        )

    @add_group.error
    async def add_group_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("⛔ Эта команда только для администраторов.")
        else:
            await ctx.send(f"❌ Ошибка: {error}")
