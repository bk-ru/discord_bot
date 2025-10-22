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
from discord import PermissionOverwrite, ui
from database.init_db import init_db
from utils.file_manager import add_or_check_student, ensure_excel_exists

from discord import ui, PermissionOverwrite

# cogs/events.py

class ChannelConflictView(ui.View):
    """
    Интерактивный выбор: создать новый личный канал
    или добавить пользователя в существующий.
    После выбора — исходное сообщение удаляется.
    """

    def __init__(self, member: discord.Member, category: discord.CategoryChannel,
                 existing_channel: discord.TextChannel, feedback_channel: discord.TextChannel = None):
        super().__init__(timeout=None)
        self.member = member
        self.category = category
        self.existing_channel = existing_channel
        self.feedback_channel = feedback_channel  # ✅ добавлено, чтобы избежать AttributeError

    async def _delete_original_message(self, interaction: discord.Interaction):
        """Удаляет исходное сообщение с кнопками (если возможно)."""
        try:
            await interaction.message.delete()
        except Exception as e:
            try:
                await interaction.followup.send(f"⚠️ Не удалось удалить сообщение: {e}", ephemeral=True)
            except Exception:
                pass  # даже если не удалось отправить followup — не критично

    @ui.button(label="Создать новый", style=discord.ButtonStyle.primary)
    async def create_new(self, interaction: discord.Interaction, button: ui.Button):
        """Создание нового личного канала с индексом +1 и обновлением topic."""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "⛔ Только администратор может выполнять это действие.", ephemeral=True
            )
            await self._delete_original_message(interaction)
            return

        # 🧹 Сначала очищаем старые topic с этим ID
        for ch in self.category.text_channels:
            if ch.topic and ch.topic.strip() == str(self.member.id):
                try:
                    await ch.edit(topic=None)
                    print(f"⚙️ Очистил topic у старого канала {ch.name} (ID совпадал).")
                except Exception as e:
                    print(f"⚠️ Не удалось очистить topic у {ch.name}: {e}")

        base_name = self.member.display_name.lower().replace(" ", "-")
        new_name = base_name
        i = 1
        existing_names = [ch.name for ch in self.category.text_channels]
        while new_name in existing_names:
            new_name = f"{base_name}-{i}"
            i += 1

        overwrites = {
            self.member.guild.default_role: PermissionOverwrite(view_channel=False),
            self.member: PermissionOverwrite(view_channel=True, send_messages=True),
        }
        new_channel = await self.category.create_text_channel(
            new_name, overwrites=overwrites, topic=str(self.member.id)
        )

        await interaction.response.send_message(
            f"✅ Создан новый личный канал {new_channel.mention}.", ephemeral=True
        )
        if self.feedback_channel:
            await self.feedback_channel.send(
                f"🆕 Создан новый личный канал {new_channel.mention} для {self.member.mention}. "
                f"Старые topic с ID были очищены."
            )
        await self._delete_original_message(interaction)


    @ui.button(label="Добавить в существующий", style=discord.ButtonStyle.success)
    async def add_to_existing(self, interaction: discord.Interaction, button: ui.Button):
        """Добавление пользователя в существующий канал."""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "⛔ Только администратор может выполнять это действие.", ephemeral=True
            )
            await self._delete_original_message(interaction)
            return

        await self.existing_channel.set_permissions(
            self.member,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        )
        await interaction.response.send_message(
            f"✅ Пользователь добавлен в существующий канал {self.existing_channel.mention}.",
            ephemeral=True,
        )
        await self._delete_original_message(interaction)



class DeleteChannelView(ui.View):
    """Выбор при уходе пользователя: удалить или оставить канал."""

    def __init__(self, channel: discord.TextChannel, feedback_channel: discord.TextChannel = None):
        super().__init__(timeout=None)
        self.channel = channel
        self.channel_id = channel.id  # сохраняем ID канала
        self.feedback_channel = feedback_channel
        self.message = None  # сюда сохраним ссылку на сообщение с кнопками

    async def _delete_original_message(self, interaction: discord.Interaction):
        try:
            await interaction.message.delete()
        except Exception:
            pass

    @ui.button(label="Удалить канал", style=discord.ButtonStyle.danger)
    async def delete_channel(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⛔ Только администратор может это делать.", ephemeral=True)
            await self._delete_original_message(interaction)
            return

        try:
            await self.channel.delete(reason="Удалён после выхода участника.")
            await interaction.response.send_message(f"✅ Канал **{self.channel.name}** удалён.", ephemeral=True)
            if self.feedback_channel:
                await self.feedback_channel.send(f"🗑️ Канал **{self.channel.name}** удалён по решению {interaction.user.mention}.")
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Ошибка при удалении канала: {e}", ephemeral=True)
        finally:
            await self._delete_original_message(interaction)

    @ui.button(label="Не удалять", style=discord.ButtonStyle.success)
    async def keep_channel(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⛔ Только администратор может это делать.", ephemeral=True)
            await self._delete_original_message(interaction)
            return

        await interaction.response.send_message(f"✅ Канал **{self.channel.name}** сохранён.", ephemeral=True)
        if self.feedback_channel:
            await self.feedback_channel.send(f"📁 Канал **{self.channel.name}** сохранён по решению {interaction.user.mention}.")
        await self._delete_original_message(interaction)


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

        if is_admin or any("преподаватель" in r for r in roles):
            commands_text += (
                "`!addgroup <название>` — Добавить группу.\n"
                "`!reloadlist` — Перезагрузить список студентов.\n"
                "`!announce <текст>` — Объявление всем.\n"
                "`!cleanup_feedback` — Очистить канал feedback.\n"
            )

        embed.add_field(name="💡 Доступные команды", value=commands_text, inline=False)

        try:
            await channel.send(embed=embed)
        except Exception as e:
            print(f"⚠️ Не удалось отправить приветствие в {channel.name}: {e}")




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
            view = ChannelConflictView(member, category, personal_channel)
            await feedback.send(
                f'⚠️ Текстовый канал "{member.display_name}" в категории "{category.name}" уже существует.\n'
                f'Выберите действие:',
                view=view
            )

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

    async def get_or_create_feedback_channel(self, guild: discord.Guild) -> discord.TextChannel:
        """Возвращает канал feedback, создавая при необходимости.
        Размещает его в категории с названием бота."""
        bot_name = guild.me.display_name if guild.me else "Bot"

        # 🗂️ Ищем категорию с именем бота
        category = discord.utils.get(guild.categories, name=bot_name)
        if not category:
            try:
                category = await guild.create_category(bot_name)
                print(f"📁 Создана категория {bot_name}")
            except Exception as e:
                print(f"⚠️ Не удалось создать категорию {bot_name}: {e}")
                category = None

        # 🔍 Проверяем существование канала feedback
        feedback = discord.utils.get(guild.text_channels, name=f"{bot_name.lower()}-feedback")
        if feedback:
            # Если канал найден, но не в нужной категории — перемещаем
            if feedback.category != category and category:
                await feedback.edit(category=category)
            return feedback

        # 🆕 Создаём новый канал в категории
        try:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
            }
            feedback = await guild.create_text_channel(
                f"{bot_name.lower()}-feedback",
                category=category,
                overwrites=overwrites
            )
            print(f"📝 Создан канал {feedback.name} в категории {bot_name}")
            await feedback.send(f"📣 Канал создан автоматически для логов и сообщений от {bot_name}.")
            return feedback
        except Exception as e:
            print(f"⚠️ Не удалось создать канал feedback: {e}")
            return None


    async def log_action(self, guild: discord.Guild, message: str):
        """Пишет сообщение в feedback-канал."""
        fb = self.feedback_channels.get(guild.id)
        if not fb:
            fb = await self.get_or_create_feedback_channel(guild)
            self.feedback_channels[guild.id] = fb
        await fb.send(message)


async def setup(bot: commands.Bot):
    """Extension entry point for discord.py."""
    await bot.add_cog(EventsCog(bot))
