"""
cogs/events.py
Полная версия с расширенным логированием действий бота:
- Группы создаются как категории.
- В каждой категории есть общий канал и личные каналы студентов.
- Бот пишет ВСЕ свои действия в {bot_name}-feedback.
- При выходе участника предлагает удалить его личный канал.
"""

import asyncio
import discord
from discord.ext import commands
from discord import PermissionOverwrite
from database.init_db import init_db
from utils.file_manager import add_or_check_student, ensure_excel_exists
from utils.feedback import ensure_feedback_channel, send_feedback_message
from cogs.views import ChannelConflictView, DeleteChannelView


# cogs/events.py

class EventsCog(commands.Cog):
    """События Discord: регистрация, структура групп, логирование."""

    def __init__(self, bot):
        self.bot = bot
        self.feedback_channels = {}

    # -------------------------------------------------------------------------
    # События
    # -------------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_ready(self):
        """Инициализация при запуске бота."""
        print(f'✅ Бот {self.bot.user} запущен!')
        await init_db()
        ensure_excel_exists()

        for guild in self.bot.guilds:
            fb = await self.get_or_create_feedback_channel(guild)
            self.feedback_channels[guild.id] = fb
            await self.setup_unknown_role_and_channel(guild)
            await self.log_action(guild, f"🚀 Бот готов к работе на сервере **{guild.name}**.")
            
            await self.sync_users_from_guild(guild)

            unknown_role = discord.utils.get(guild.roles, name="Неизвестные")
            if not unknown_role:
                unknown_role = await self.get_or_create_role(guild, "Неизвестные")

            total_checked = 0
            total_dialogs_started = 0

            for member in guild.members:
                if member.bot:
                    continue
                total_checked += 1

                # 1️⃣ Если нет ролей вообще — добавляем 'Неизвестные'
                if len(member.roles) == 1:
                    await member.add_roles(unknown_role)
                    await self.log_action(guild, f"⚙️ {member.mention} не имел ролей — назначена роль 'Неизвестные'.")
                    await self.start_registration_dialog(member, guild, unknown_role)
                    total_dialogs_started += 1
                    continue

                # 2️⃣ Если роль 'Неизвестные' уже есть — тоже запускаем регистрацию
                if unknown_role in member.roles:
                    try:
                        await self.start_registration_dialog(member, guild, unknown_role)
                        total_dialogs_started += 1
                        await self.log_action(guild, f"📩 Повторно запущен диалог регистрации для {member.display_name}.")
                    except discord.Forbidden:
                        await self.log_action(
                            guild,
                            f"⚠️ Не удалось отправить сообщение участнику {member.display_name} (возможно, закрыты ЛС)."
                        )

            await self.log_action(
                guild,
                f"🔎 Проверка завершена: обработано {total_checked} участников, "
                f"запущено {total_dialogs_started} диалогов регистрации."
            )

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Добавление нового пользователя."""
        guild = member.guild
        unknown_role = await self.get_or_create_role(guild, "Неизвестные")
        await member.add_roles(unknown_role)
        await self.log_action(guild, f"🆕 Участник {member.mention} присоединился. Назначена роль 'Неизвестные'.")
        await self.start_registration_dialog(member, guild, unknown_role)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """При выходе участника предлагает удалить его личный канал.
        Перед этим очищает старые сообщения об этом пользователе в feedback."""
        guild = member.guild
        feedback = await self.get_or_create_feedback_channel(guild)

        # 🧹 Очистка старых сообщений об этом пользователе
        try:
            async for msg in feedback.history(limit=100):  # можно увеличить лимит при необходимости
                if (
                    str(member.id) in msg.content
                    or member.display_name.lower() in msg.content.lower()
                    or (msg.embeds and any(member.display_name.lower() in str(e.description).lower() for e in msg.embeds))
                ):
                    try:
                        await msg.delete()
                    except Exception as e:
                        print(f"⚠️ Не удалось удалить сообщение feedback: {e}")
        except Exception as e:
            print(f"⚠️ Ошибка при попытке очистки feedback: {e}")

        # 🔍 Поиск личного канала по topic (где хранится member.id)
        found_channel = None
        for category in guild.categories:
            for ch in category.text_channels:
                if ch.topic and ch.topic.strip() == str(member.id):
                    found_channel = ch
                    break
            if found_channel:
                break

        # ⚙️ Отправка выбора
        if found_channel:
            feedback = await self.get_or_create_feedback_channel(guild)
            view = DeleteChannelView(found_channel, feedback)
            await feedback.send(
                f"⚠️ Пользователь **{member.display_name}** покинул сервер.\n"
                f"Обнаружен его личный канал: {found_channel.mention}\n"
                f"Хотите удалить этот канал?",
                view=view
            )
            await self.log_action(guild, f"👋 {member.display_name} покинул сервер. Найден личный канал {found_channel.name} (по topic).")

        else:
            await feedback.send(
                f"ℹ️ Пользователь **{member.display_name}** покинул сервер, личный канал не найден."
            )
            await self.log_action(guild, f"ℹ️ {member.display_name} покинул сервер. Приватный канал не найден.")
    
    async def send_help_message(self, channel: discord.TextChannel, member: discord.Member, is_personal: bool = False):
        """Отправляет адаптированное приветствие и список доступных команд в канал."""
        user = member
        embed = discord.Embed(
            title="📘 Добро пожаловать!",
            color=discord.Color.blue()
        )

        # Раздел — описание канала
        if is_personal:
            embed.description = (
                f"👋 Привет, {user.mention}!\n"
                f"Это **твой личный канал**. Здесь ты можешь отправлять свои лабораторные работы, "
                f"задавать вопросы преподавателю и получать обратную связь.\n\n"
                f"Только ты и преподаватели видят этот канал."
            )
        else:
            embed.description = (
                f"🎓 Это **общий канал группы**.\n"
                f"Здесь преподаватель будет публиковать важные объявления, материалы и практику. "
                f"Вы также можете задавать здесь вопросы и обсуждать задания со своей группой."
            )

        # Раздел — команды (динамически, как в HelpCog)
        roles = [r.name.lower() for r in user.roles]
        is_admin = user.guild_permissions.administrator

        commands_text = (
            "`!info` — Информация о боте.\n"
            "`!ping` — Проверка задержки.\n"
            "`!help` — Показать список команд.\n"
        )

        if any(r for r in roles if r not in ["@everyone", "неизвестные"]) and not is_admin:
            commands_text += (
                "`!labs` — Список лабораторных.\n"
                "`!submit <номер>` — Отправить работу.\n"
                "`!status <номер>` — Проверить статус.\n"
            )

        if is_admin:
            commands_text += (
                "\n**Управление группами**\n"
                "`!addgroup <название>` — добавить группу.\n"
                "`!removegroup <название>` — удалить группу.\n"
            )

        if is_admin or any("преподаватель" in r for r in roles):
            commands_text += (
                "\n**Работа с лабораторными**\n"
                "`!review @студент <номер> <комментарий>` — отправить работу на доработку.\n"
                "`!accept @студент <номер>` — зачесть лабораторную.\n"
                "`!labfile @студент <номер>` — показать ссылку на файл.\n"
                "`!deletelab @студент <номер>` — удалить лабораторную.\n"
            )
            print(f"⚠️ Не удалось отправить приветствие в {channel.name}: {e}")

    async def sync_users_from_guild(self, guild: discord.Guild):
        """Добавляет в базу всех участников, которых ещё нет."""
        from database.models import User
        import pandas as pd
        from utils.file_manager import file_path

        df = pd.read_excel(file_path, None)  # загружаем все листы
        all_known = {}
        for sheet, data in df.items():
            for _, row in data.iterrows():
                full_name = f"{str(row['ИМЯ']).strip()} {str(row['ФАМИЛИЯ']).strip()}"
                all_known[full_name.lower()] = sheet  # { "иван иванов": "ГР-01", ... }

        created_count = 0
        for member in guild.members:
            if member.bot:
                continue

            existing = await User.get_or_none(discord_id=member.id)
            if existing:
                continue  # уже в базе

            display = member.display_name.strip().split()
            if len(display) >= 2:
                first, last = display[0], display[1]
                group = all_known.get(f"{first.lower()} {last.lower()}", "Неизвестные")
            else:
                first, last, group = member.display_name, "-", "Неизвестные"

            await User.create(
                discord_id=member.id,
                first_name=first,
                last_name=last,
                group=group
            )
            created_count += 1

        await self.log_action(
            guild,
            f"🔁 Синхронизированы пользователи: добавлено {created_count} записей в базу."
        )



    # -------------------------------------------------------------------------
    # Регистрация и структура групп
    # -------------------------------------------------------------------------

    async def start_registration_dialog(self, member: discord.Member, guild: discord.Guild, unknown_role: discord.Role):
        """Диалог в личке: запрос имени, фамилии и группы."""
        intro = (
            "👋 Привет! Добро пожаловать!\n"
            "Введи свои данные в формате: `ИМЯ ФАМИЛИЯ ГРУППА`\n"
            "Пример: Иван Иванов ГР-01\n"
            "Напиши `отмена`, чтобы прервать."
        )
        await member.send(intro)

        def check(m: discord.Message):
            return m.author == member and isinstance(m.channel, discord.DMChannel)

        attempts = 3
        while attempts > 0:
            try:
                msg = await self.bot.wait_for("message", check=check, timeout=300.0)
            except asyncio.TimeoutError:
                await member.send("⏰ Время истекло. Напиши `!verify`, чтобы попробовать снова.")
                await self.log_action(guild, f"⏰ {member.display_name} не завершил регистрацию (таймаут).")
                return

            content = msg.content.strip()
            if content.lower() in ("отмена", "cancel", "stop"):
                await member.send("🚫 Регистрация отменена.")
                await self.log_action(guild, f"🚫 {member.display_name} отменил регистрацию.")
                return

            parts = content.split()
            if len(parts) < 3:
                attempts -= 1
                await member.send(f"❌ Неверный формат. Осталось попыток: {attempts}.")
                await self.log_action(guild, f"⚠️ {member.display_name} ввёл неправильный формат. Осталось попыток: {attempts}.")
                continue

            first_name, last_name, *group_parts = parts
            group = " ".join(group_parts).strip()

            if add_or_check_student(first_name, last_name, group):
                await self.assign_group_role_and_channels(guild, member, first_name, last_name, group, unknown_role)
                await member.send(f"✅ Ты успешно зарегистрирован в группе **{group}**.")
                await self.log_action(guild, f"✅ {member.display_name} добавлен в группу {group}.")
                return
            else:
                attempts -= 1
                await member.send(f"⚠️ Группа '{group}' не найдена. Попробуй снова.")
                await self.log_action(guild, f"⚠️ {member.display_name} указал неизвестную группу '{group}'. Осталось попыток: {attempts}.")

        await member.send("❌ Попытки закончились. Ты останешься в 'Неизвестные'.")
        await self.log_action(guild, f"❌ {member.display_name} не прошёл регистрацию после 3 попыток.")

    async def assign_group_role_and_channels(
        self, guild: discord.Guild, member: discord.Member, first_name: str, last_name: str, group: str, unknown_role: discord.Role
    ):
        """Создание роли, категории и каналов для группы."""
        group_role = await self.get_or_create_role(guild, group)
        await member.add_roles(group_role)
        if unknown_role in member.roles:
            await member.remove_roles(unknown_role)

        # Категория
        category = discord.utils.get(guild.categories, name=group)
        if not category:
            category = await guild.create_category(
                name=group,
                overwrites={
                    guild.default_role: PermissionOverwrite(view_channel=False),
                    group_role: PermissionOverwrite(view_channel=True),
                },
            )
            await self.log_action(guild, f"📂 Создана категория '{group}'.")

        # Общий канал группы
        group_channel_name = group.lower()
        group_channel = discord.utils.get(category.text_channels, name=group_channel_name)
        if not group_channel:
            group_channel = await category.create_text_channel(
                group_channel_name,
                overwrites={
                    guild.default_role: PermissionOverwrite(view_channel=False),
                    group_role: PermissionOverwrite(view_channel=True, send_messages=True),
                },
            )
            await self.log_action(guild, f"💬 Создан групповой канал #{group_channel_name}.")
            await self.send_help_message(group_channel, member, is_personal=False)


        # Персональный канал
        personal_channel_name = f"{last_name.lower()}-{first_name.lower()}"
        personal_channel = discord.utils.get(category.text_channels, name=personal_channel_name)
        if not personal_channel:
            overwrites = {
                guild.default_role: PermissionOverwrite(view_channel=False),
                group_role: PermissionOverwrite(view_channel=False),
                member: PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            }
            bot_member = guild.me
            if bot_member:
                overwrites[bot_member] = PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            personal_channel = await category.create_text_channel(
                personal_channel_name,
                overwrites=overwrites,
                topic=str(member.id)
            )
            await self.log_action(guild, f"👤 Создан личный канал {personal_channel.mention} для {member.display_name}.")
            await self.send_help_message(personal_channel, member, is_personal=True)
        else:
            # ⚠️ Новый лог и вызов интерактивного выбора
            await self.log_action(guild, f"⚠️ Личный канал {personal_channel.name} уже существует для {member.display_name}.")
            feedback = await self.get_or_create_feedback_channel(guild)
            view = ChannelConflictView(member, category, personal_channel, feedback)
            await feedback.send(
                f'⚠️ Текстовый канал "{member.display_name}" в категории "{category.name}" уже существует.\n'
                f'Выберите действие:',
                view=view
            )
        bot_member = guild.me
        if bot_member and personal_channel:
            try:
                await personal_channel.set_permissions(
                    bot_member,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Вспомогательные методы
    # -------------------------------------------------------------------------

    async def get_or_create_role(self, guild, role_name):
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            role = await guild.create_role(name=role_name)
            await self.log_action(guild, f"🎭 Создана роль '{role_name}'.")
        return role

    async def setup_unknown_role_and_channel(self, guild):
        """Создаёт роль и канал 'неизвестные'."""
        unknown_role = await self.get_or_create_role(guild, "Неизвестные")
        overwrites = {
            guild.default_role: PermissionOverwrite(view_channel=False),
            unknown_role: PermissionOverwrite(view_channel=True, send_messages=True),
        }
        channel = discord.utils.get(guild.text_channels, name="неизвестные")
        if not channel:
            await guild.create_text_channel("неизвестные", overwrites=overwrites)
            await self.log_action(guild, "📩 Создан канал #неизвестные.")
        else:
            await channel.edit(overwrites=overwrites)
            await self.log_action(guild, "📩 Канал #неизвестные найден, права доступа обновлены.")

    async def get_or_create_feedback_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        """Возвращает (или создаёт) канал обратной связи для сервера."""
        cached = self.feedback_channels.get(guild.id)
        if cached and cached.guild:
            return cached

        channel = await ensure_feedback_channel(guild)
        if channel:
            self.feedback_channels[guild.id] = channel
        return channel

    async def log_action(self, guild: discord.Guild, message: str) -> None:
        """Отправляет событие в канал обратной связи (с запасным логированием)."""
        channel = await self.get_or_create_feedback_channel(guild)
        if channel:
            try:
                await channel.send(message)
                return
            except Exception:
                pass
        await send_feedback_message(guild, message)



async def setup(bot: commands.Bot):
    """Extension entry point for discord.py."""
    await bot.add_cog(EventsCog(bot))
