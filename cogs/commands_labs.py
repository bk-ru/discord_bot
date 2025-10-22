from discord.ext import commands
import discord
from discord import ui, ButtonStyle, Interaction
from database.models import User, LabWork
from tortoise.exceptions import DoesNotExist
from typing import Union
import traceback
import re

async def _safe_respond(interaction, content, *, ephemeral=True):
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(content, ephemeral=ephemeral)
    except Exception as e:
        cog = interaction.client.get_cog("LabsCog")
        if cog and hasattr(cog, "_log_feedback"):
            await cog._log_feedback(interaction.guild, f"❌ safe_respond: {e}")

class LabsCog(commands.Cog):
    """Команды для сдачи и проверки лабораторных работ."""

    def __init__(self, bot):
        self.bot = bot
        
    async def _get_or_create_feedback_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        """Возвращает канал {bot}-feedback, создаёт при необходимости в категории с названием бота."""
        try:
            bot_member = guild.me
            bot_name = bot_member.display_name if bot_member else "Bot"

            # Категория под имя бота
            category = discord.utils.get(guild.categories, name=bot_name)
            if not category:
                category = await guild.create_category(bot_name, reason="Категория под служебные каналы бота")
            
            # Сам канал
            ch_name = f"{bot_name.lower()}-feedback"
            channel = discord.utils.get(guild.text_channels, name=ch_name)
            if channel and channel.category != category:
                # Перенесём в правильную категорию
                await channel.edit(category=category)
                return channel

            if not channel:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
                }
                channel = await guild.create_text_channel(
                    ch_name, category=category, overwrites=overwrites, reason="Лог действий бота"
                )
                try:
                    await channel.send(f"📝 Канал логирования для {bot_name} создан.")
                except Exception:
                    pass
            return channel
        except Exception as e:
            print(f"[feedback] Не удалось создать/получить feedback-канал: {e}")
            return None

    async def _log_feedback(self, guild: discord.Guild, text: str) -> None:
        """Пишет сообщение в feedback-канал (с защитой от ошибок)."""
        try:
            ch = await self._get_or_create_feedback_channel(guild)
            if ch:
                await ch.send(text)
            else:
                print(f"[feedback:FALLBACK] {text}")
        except Exception as e:
            print(f"[feedback] Ошибка при отправке сообщения: {e} | {text}")

    # -------------------- Команды студента --------------------

    @commands.command(name="submit")
    async def submit_lab(self, ctx, lab_number: int):
        """
        Сдать лабораторную работу.
        Использование: !submit <номер> (с прикреплённым файлом в этом же сообщении
        ИЛИ в одном из последних сообщений пользователя в канале).
        """
        try:
            # 1) Вложение из текущего или последних сообщений автора
            attachment = ctx.message.attachments[0] if ctx.message.attachments else None
            if not attachment:
                await ctx.send("📎 Прикрепи файл к сообщению с командой `!submit <номер>`.")
                await self._log_feedback(ctx.guild, f"⚠️ {ctx.author.mention} попытался отправить лабораторную №{lab_number} без вложения.")
                return

            file_url = attachment.url

            # 2) Пользователь в БД
            user = await self._ensure_user(ctx.author)

            # 2.1) Пытаемся определить группу по категории канала
            detected_group = None
            category = getattr(ctx.channel, "category", None)
            if category and category.name:
                detected_group = category.name.strip()

                # Исключаем служебные категории (бота/неизвестные)
                bot_member = ctx.guild.me
                bot_names = {
                    self.bot.user.name.lower() if self.bot.user else "",
                    (bot_member.display_name.lower() if bot_member and bot_member.display_name else "")
                }
                if detected_group and detected_group.lower() not in {"", "неизвестные"} and detected_group.lower() not in bot_names:
                    if user.group != detected_group:
                        await User.filter(id=user.id).update(group=detected_group)
                        user.group = detected_group
                        await self._log_feedback(
                            ctx.guild,
                            f"🔄 {ctx.author.mention} теперь относится к группе **{detected_group}** (определена по категории канала)."
                        )
                else:
                    detected_group = None

            # 3) Создаём/обновляем запись БЕЗ сохранения partial-модели
            lab, created = await LabWork.get_or_create(
                user=user,
                lab_number=lab_number,
                defaults={"file_url": file_url, "status": "отправлено"}
            )
            if created:
                # запись уже с нужными полями
                pass
            else:
                # обновляем через query (обходит partial), затем грузим полную запись
                await LabWork.filter(user=user, lab_number=lab_number).update(
                    file_url=file_url,
                    status="отправлено",
                )
                lab = await LabWork.get(user=user, lab_number=lab_number)  # теперь НЕ partial

            # 4) Публикация/обновление в канале преподавателя (если есть группа)
            if user.group and user.group.lower() != "неизвестные":
                try:
                    await self._post_to_teacher_channel(ctx, lab, user.group, file_url, requester=ctx.author)
                except Exception as e:
                    await ctx.send(f"⚠️ Работа сохранена, но не удалось опубликовать в канале преподавателя: `{e}`")
                    await self._log_feedback(
                        ctx.guild,
                        f"⚠️ Ошибка публикации работы №{lab_number} в канал преподавателя: {e}"
                    )
            else:
                await self._log_feedback(
                    ctx.guild,
                    f"ℹ️ {ctx.author.mention} отправил лабораторную №{lab_number}, но группа не указана — канал преподавателя пропущен."
                )

            # 5) Ответ пользователю
            msg = "✅ Лабораторная успешно отправлена." if created else "🔁 Лабораторная обновлена и повторно отправлена."
            await ctx.send(f"{msg}\n📘 Лабораторная №{lab_number}\n📎 {file_url}")

        except Exception as e:
            print(f"[!submit] Ошибка: {e}")
            await ctx.send(f"❌ Ошибка при обработке `!submit`: `{e}`")

    
    @submit_lab.error
    async def submit_lab_error(self, ctx, error):
        from discord.ext.commands import MissingRequiredArgument, BadArgument, CommandInvokeError

        if isinstance(error, MissingRequiredArgument):
            await ctx.send("❗ Укажи номер работы: `!submit <номер>` и прикрепи файл.")
        elif isinstance(error, BadArgument):
            await ctx.send("❗ Номер работы должен быть целым числом: `!submit 1`.")
        elif isinstance(error, CommandInvokeError):
            # Разворачиваем первопричину
            await ctx.send(f"❌ Ошибка выполнения: `{error.original}`")
        else:
            await ctx.send(f"❌ Ошибка: `{error}`")



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

    @commands.has_permissions(administrator=True)
    @commands.command(name="deletelab")
    async def delete_lab(self, ctx, student: discord.Member, lab_number: int):
        """Удалить лабораторную работу студента вместе с сообщениями преподавателя."""
        user = await User.get_or_none(discord_id=student.id)
        if not user:
            await ctx.send("⚠️ Студент не найден в базе данных.")
            return

        lab = await LabWork.get_or_none(user=user, lab_number=lab_number)
        if not lab:
            await ctx.send(f"⚠️ У студента нет лабораторной №{lab_number}.")
            return

        # Удаляем сообщение преподавателя, если оно осталось
        if lab.teacher_channel_id and lab.teacher_message_id:
            channel = ctx.guild.get_channel(lab.teacher_channel_id)
            if isinstance(channel, discord.TextChannel):
                try:
                    msg = await channel.fetch_message(lab.teacher_message_id)
                    await msg.delete()
                except Exception:
                    pass

        await self._log_feedback(
            ctx.guild,
            f"🗑️ {ctx.author.mention} удалил работу №{lab_number} пользователя {student.mention}."
        )

        await lab.delete()
        await ctx.send(f"✅ Работа №{lab_number} пользователя {student.mention} удалена.")
        try:
            await student.send(
                f"🗑️ Твоя лабораторная №{lab_number} была удалена администратором {ctx.author.mention}."
            )
        except Exception:
            pass
        
    @commands.has_permissions(administrator=True)
    @commands.command(name="labfile")
    async def lab_file(self, ctx, student: discord.Member, lab_number: int):
        """Получить ссылку на файл лабораторной работы студента."""
        user = await User.get_or_none(discord_id=student.id)
        if not user:
            await ctx.send("⚠️ Студент не найден в базе данных.")
            return

        lab = await LabWork.get_or_none(user=user, lab_number=lab_number)
        if not lab:
            await ctx.send(f"⚠️ У студента нет лабораторной №{lab_number}.")
            return

        if not lab.file_url:
            await ctx.send("⚠️ Для этой работы не сохранена ссылка на файл.")
            return

        await ctx.send(f"📎 Файл лабораторной №{lab_number} студента {student.mention}: {lab.file_url}")

    @commands.has_permissions(administrator=True)
    @commands.command(name="resubmitlab")
    async def resubmit_lab(self, ctx, student: discord.Member, lab_number: int):
        """Заменить файл лабораторной и повторно отправить работу на проверку."""
        if not ctx.message.attachments:
            await ctx.send("📎 Прикрепите исправленный файл к сообщению с командой.")
            return

        attachment = ctx.message.attachments[0]
        file_url = attachment.url

        user = await User.get_or_none(discord_id=student.id)
        if not user:
            await ctx.send("⚠️ Студент не найден в базе данных.")
            return

        lab = await LabWork.get_or_none(user=user, lab_number=lab_number)
        if not lab:
            await ctx.send(f"⚠️ У студента нет лабораторной №{lab_number}.")
            return

        await LabWork.filter(id=lab.id).update(
            file_url=file_url,
            status="отправлено",
        )
        lab = await LabWork.get(id=lab.id)

        await self._log_feedback(
            ctx.guild,
            f"🔄 {ctx.author.mention} заменил файл лабораторной №{lab_number} для {student.mention}."
        )

        if user.group and user.group.lower() != "неизвестные":
            try:
                await self._post_to_teacher_channel(ctx, lab, user.group, file_url, requester=ctx.author)
            except Exception as e:
                await ctx.send(f"⚠️ Файл обновлён, но не удалось опубликовать сообщение в канале преподавателя: `{e}`")

        await ctx.send(f"✅ Лабораторная №{lab_number} для {student.mention} обновлена.")
        try:
            await student.send(
                f"🔄 Ваша лабораторная №{lab_number} была обновлена администратором {ctx.author.mention}. Новый файл: {file_url}"
            )
        except Exception:
            pass

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
        
    async def get_or_create_teacher_channel(
        self,
        guild: discord.Guild,
        group_name: str,
        requester: discord.Member | None = None,
    ):
        """Создаёт/возвращает канал преподавателя для группы и логирует все шаги в feedback."""
        if not group_name:
            await self._log_feedback(guild, "⚠️ Не задано название группы для канала преподавателя.")
            return None
        group_name = group_name.strip()

        await self._log_feedback(guild, f"🔎 Поиск/создание инфраструктуры преподавателя для группы **{group_name}**...")

        # 1) Категория группы
        category = discord.utils.get(guild.categories, name=group_name)
        if not category:
            try:
                category = await guild.create_category(
                    name=group_name,
                    reason="Создана автоматически для группы"
                )
                await self._log_feedback(guild, f"📁 Создана категория группы **{group_name}**.")
            except Exception as e:
                await self._log_feedback(guild, f"❌ Не удалось создать категорию **{group_name}**: `{e}`")
                return None
        else:
            await self._log_feedback(guild, f"📂 Категория **{group_name}** найдена (id={category.id}).")

        # 2) Права доступа
        teacher_role = (
            discord.utils.get(guild.roles, name="Преподаватель")
            or discord.utils.get(guild.roles, name="Преподы")
            or discord.utils.get(guild.roles, name="Teacher")
        )
        admin_roles = [r for r in guild.roles if r.permissions.administrator]

        def _is_staff(m: discord.Member) -> bool:
            p = m.guild_permissions
            return p.administrator or p.manage_guild or p.manage_channels

        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            ),
        }
        if teacher_role:
            overwrites[teacher_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )
        for r in admin_roles:
            overwrites[r] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )
        if requester and _is_staff(requester):
            overwrites[requester] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )

        # 3) Канал преподавателя
        teacher_channel_name = f"преподаватель-{group_name.lower()}"
        teacher_channel = discord.utils.get(category.text_channels, name=teacher_channel_name)

        if not teacher_channel:
            try:
                teacher_channel = await category.create_text_channel(
                    name=teacher_channel_name,
                    overwrites=overwrites,
                    topic=f"📘 Канал преподавателя для группы {group_name} (проверка лабораторных)"
                )
                await self._log_feedback(
                    guild,
                    f"✅ Создан канал преподавателя {teacher_channel.mention} в категории **{group_name}**."
                )
                try:
                    await teacher_channel.send(
                        f"👨‍🏫 Канал преподавателя для группы **{group_name}** создан. "
                        f"Доступ: роль {'`'+teacher_role.name+'`' if teacher_role else '—'}; "
                        f"админ-ролей: {len(admin_roles)}; "
                        f"{'инициатор добавлен' if requester and _is_staff(requester) else 'инициатор НЕ добавлен'}."
                    )
                except Exception:
                    pass
            except Exception as e:
                await self._log_feedback(guild, f"❌ Не удалось создать канал преподавателя: `{e}`")
                return None
        else:
            try:
                await teacher_channel.edit(overwrites=overwrites)
                await self._log_feedback(
                    guild,
                    f"ℹ️ Канал преподавателя {teacher_channel.mention} уже существовал — права обновлены."
                )
            except Exception as e:
                await self._log_feedback(guild, f"⚠️ Не удалось обновить права {teacher_channel.mention}: `{e}`")

        # Финальный отчёт, кто точно видит канал
        visible = []
        if teacher_role:
            visible.append(f"роль `{teacher_role.name}`")
        if admin_roles:
            visible.append(f"{len(admin_roles)} админ-ролей")
        if requester and _is_staff(requester):
            visible.append(f"инициатор {requester.mention}")
        await self._log_feedback(
            guild,
            "👁 Доступ к каналу преподавателя: " + (", ".join(visible) if visible else "только бот/админы по праву Administrator")
        )

        return teacher_channel



    
    async def _post_to_teacher_channel(
        self,
        ctx,
        lab: LabWork,
        group_name: str,
        file_url: str,
        requester: discord.Member | None = None
    ) -> bool:
        """Постит/обновляет сообщение о работе в канал преподавателя с подробным логом в feedback."""
        group_name = (group_name or "").strip()
        if not group_name or group_name.lower() == "неизвестные":
            await self._log_feedback(ctx.guild, f"⚠️ Группа не задана/неизвестна для {ctx.author.mention} — публикация пропущена.")
            return False

        await self._log_feedback(ctx.guild, f"🧪 Публикация работы №{lab.lab_number} в канал преподавателя группы **{group_name}**...")

        teacher_channel = await self.get_or_create_teacher_channel(ctx.guild, group_name, requester=requester)
        if not teacher_channel:
            await self._log_feedback(ctx.guild, f"❌ Канал преподавателя для **{group_name}** недоступен/не создан.")
            return False

        # если по какой-то причине пришла partial-модель — догружаем
        if getattr(lab, "id", None) is None:
            lab = await LabWork.get(user_id=lab.user_id, lab_number=lab.lab_number)

        # удалить старое сообщение, если есть
        if getattr(lab, "teacher_message_id", None):
            try:
                old_msg = await teacher_channel.fetch_message(lab.teacher_message_id)
                await old_msg.delete()
                await self._log_feedback(ctx.guild, f"🧹 Удалено старое сообщение о работе №{lab.lab_number} (msg_id={lab.teacher_message_id}).")
            except Exception as e:
                await self._log_feedback(ctx.guild, f"⚠️ Не удалось удалить старое сообщение (msg_id={lab.teacher_message_id}): `{e}`")

        # время
        try:
            when = (lab.updated_at or lab.submitted_at).strftime("%d.%m.%Y %H:%M")
        except Exception:
            when = "только что"

        embed = discord.Embed(
            title=f"🧪 Лабораторная №{lab.lab_number}",
            description=(f"👤 Студент: {ctx.author.mention}\n"
                        f"📎 [Файл]({file_url})\n"
                        f"🕓 Отправлено: {when}"),
            color=discord.Color.blurple()
        )
        embed.set_footer(text="Выберите действие ниже")

        try:
            msg = await teacher_channel.send(embed=embed, view=LabReviewView(lab))
            lab.teacher_message_id = msg.id
            lab.teacher_channel_id = teacher_channel.id
            await lab.save(update_fields=["teacher_message_id", "teacher_channel_id"])
            await self._log_feedback(ctx.guild, f"📨 Сообщение о работе №{lab.lab_number} опубликовано в {teacher_channel.mention} (msg_id={msg.id}).")
            return True
        except Exception as e:
            await self._log_feedback(ctx.guild, f"❌ Ошибка при публикации в {teacher_channel.mention}: `{e}`")
            return False        

class LabReviewView(ui.View):
    """Кнопки для проверки лабораторной преподавателем."""

    def __init__(self, labwork):
        super().__init__(timeout=None)
        self.labwork = labwork  # объект ORM LabWork

    async def _get_student(self, guild: discord.Guild, interaction: Interaction):
        user_obj = getattr(self.labwork, "user", None)
        if not user_obj:
            try:
                await self.labwork.fetch_related("user")
                user_obj = self.labwork.user
            except Exception:
                user_obj = await User.get_or_none(id=getattr(self.labwork, "user_id", None))

        discord_member = None
        discord_id = getattr(user_obj, "discord_id", None) if user_obj else None

        if discord_id:
            discord_member = guild.get_member(discord_id) or await guild.fetch_member(discord_id)

        # Резерв: достаём из сообщения и, если нужно, записываем discord_id в БД
        if discord_member is None:
            parsed = await self._extract_student_from_teacher_message(interaction)
            if parsed:
                discord_member = parsed
                if user_obj and (not getattr(user_obj, "discord_id", None) or user_obj.discord_id != parsed.id):
                    try:
                        await User.filter(id=user_obj.id).update(discord_id=parsed.id)  # фиксируем в БД
                        user_obj.discord_id = parsed.id
                    except Exception:
                        pass

        return discord_member, user_obj
    
    async def _extract_student_from_teacher_message(self, interaction: Interaction) -> discord.Member | None:
        msg_id = getattr(self.labwork, "teacher_message_id", None)
        channel_id = getattr(self.labwork, "teacher_channel_id", None)
        if not msg_id:
            return None

        channel: discord.TextChannel | None = None
        if channel_id:
            channel = interaction.guild.get_channel(channel_id)
        if channel is None or not isinstance(channel, discord.TextChannel):
            channel = interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None
        if channel is None:
            return None

        try:
            msg = await channel.fetch_message(msg_id)
        except Exception:
            return None

        # 1) если есть прямые mentions — берём первого
        if msg.mentions:
            m = msg.mentions[0]
            return interaction.guild.get_member(m.id) or await interaction.guild.fetch_member(m.id)

        # 2) иначе пробуем парсить из embed.description "👤 Студент: <@123...>"
        if msg.embeds:
            desc = (msg.embeds[0].description or "")
            m = re.search(r"<@!?(\d+)>", desc)
            if m:
                uid = int(m.group(1))
                try:
                    return interaction.guild.get_member(uid) or await interaction.guild.fetch_member(uid)
                except Exception:
                    return None
        return None

    async def _process_result(
        self,
        interaction: Interaction,
        *,
        status: str,
        teacher_reply: str,
        feedback: str | None = None,
    ) -> None:
        """Сохраняет статус, уведомляет студента, очищает сообщение преподавателя."""
        self.labwork.status = status
        if feedback is not None:
            self.labwork.feedback = feedback
        try:
            await self.labwork.save(update_fields=["status", "feedback"])
        except Exception as e:
            cog = interaction.client.get_cog("LabsCog")
            if cog and hasattr(cog, "_log_feedback"):
                await cog._log_feedback(interaction.guild, f"❌ save(status/feedback) failed: {e}")

        await self._notify_student_and_channel(interaction, status, feedback)
        await _safe_respond(interaction, teacher_reply, ephemeral=True)
        await self._delete_teacher_message(interaction)

        student_for_log, user_obj = await self._get_student(interaction.guild, interaction)
        student_label = (
            student_for_log.mention
            if student_for_log
            else (f"<@{getattr(user_obj, 'discord_id', None)}>" if user_obj and getattr(user_obj, "discord_id", None) else f"db_user_id={getattr(self.labwork, 'user_id', None)}")
        )
        
        cog = interaction.client.get_cog("LabsCog")
        if cog and hasattr(cog, "_log_feedback"):
            try:
                await cog._log_feedback(
                    interaction.guild,
                    (
                        f"🛠️ Лабораторная №{self.labwork.lab_number} для {student_label} "
                        f"отмечена как {status.upper()} преподавателем {interaction.user.mention}. "
                        f"Комментарий: {feedback or '—'}."
                    )
                )
            except Exception:
                pass

    async def _notify_student_and_channel(
        self,
        interaction: Interaction,
        status: str,
        feedback: str | None,
    ) -> None:
        """Отправляет уведомления студенту в личку и его приватный канал."""
        student, user_obj = await self._get_student(interaction.guild, interaction)
        discord_id = getattr(user_obj, "discord_id", None) if user_obj else None

        base_message = (
            f"🧪 Лабораторная №{self.labwork.lab_number} "
            f"помечена преподавателем {interaction.user.mention} как **{status.upper()}**."
        )
        if feedback:
            base_message += f"\n💬 Комментарий: {feedback}"

        log_bits: list[str] = []

        if not user_obj:
            log_bits.append("ORM-запись пользователя не найдена; уведомление пропущено.")
            cog = interaction.client.get_cog("LabsCog")
            if cog and hasattr(cog, "_log_feedback"):
                try:
                    await cog._log_feedback(interaction.guild, " | ".join(log_bits))
                except Exception:
                    pass
            return

        student_label = (
            student.mention if student else (f"<@{discord_id}>" if discord_id else "неизвестен")
        )
        log_bits.append(
            f"Статус лабораторной №{self.labwork.lab_number}: {status}. Студент {student_label} (discord_id={discord_id})."
        )

        if student:
            try:
                await student.send(base_message)
                log_bits.append("DM: отправлено.")
            except Exception as dm_err:
                log_bits.append(f"DM: не доставлено ({dm_err}).")
        else:
            log_bits.append("DM: пропущено (участник не найден на сервере).")

        # ищем личный канал по topic или названию фамилия-имя
        target_id = student.id if student else discord_id
        def _is_personal(ch: discord.TextChannel) -> bool:
            topic_value = (ch.topic or "").strip()
            if target_id and topic_value == str(target_id):
                return True
            if topic_value and topic_value == str(self.labwork.user_id):
                return True
            first = (getattr(user_obj, "first_name", "") or "").strip().lower()
            last = (getattr(user_obj, "last_name", "") or "").strip().lower()
            if not first or not last:
                return False
            expected_name = f"{last.replace(' ', '-')}-{first.replace(' ', '-')}"
            alt_name = f"{first.replace(' ', '-')}-{last.replace(' ', '-')}"
            if ch.name in (expected_name, alt_name):
                return True
            if ch.name.startswith(f"{expected_name}-") or ch.name.startswith(f"{alt_name}-"):
                return True
            return False

        personal_channel = discord.utils.find(
            lambda ch: isinstance(ch, discord.TextChannel) and _is_personal(ch),
            interaction.guild.text_channels,
        )
        if personal_channel:
            mention_prefix = (
                student.mention if student else (f"<@{target_id}>" if target_id else user_obj.first_name)
            )
            channel_message = f"{mention_prefix} {base_message}"
            try:
                await personal_channel.send(channel_message)
                log_bits.append(f"Канал {personal_channel.mention} (id={personal_channel.id}): отправлено.")
            except Exception as ch_err:
                log_bits.append(f"Канал {personal_channel.mention} (id={getattr(personal_channel, 'id', '?')}): ошибка ({ch_err}).")
        else:
            expected_name = (
                f"{(getattr(user_obj, 'last_name', '') or '').lower()}-"
                f"{(getattr(user_obj, 'first_name', '') or '').lower()}"
            )
            log_bits.append(
                f"Личный канал: не найден (target_id={target_id}, ожидаемые имена '{expected_name}' / "
                f"'{(getattr(user_obj, 'first_name', '') or '').lower()}-"
                f"{(getattr(user_obj, 'last_name', '') or '').lower()}')."
            )

        teacher_channel_id = getattr(self.labwork, "teacher_channel_id", None)
        teacher_message_id = getattr(self.labwork, "teacher_message_id", None)
        log_bits.append(f"ID канала преподавателя: {teacher_channel_id}, msg_id: {teacher_message_id}.")
        comment_text = feedback if feedback else "—"
        log_bits.append(f"Feedback: статус='{status}', комментарий='{comment_text}'.")

        cog = interaction.client.get_cog("LabsCog")
        if cog and hasattr(cog, "_log_feedback"):
            try:
                await cog._log_feedback(interaction.guild, " | ".join(log_bits))
            except Exception:
                pass

    async def _delete_teacher_message(self, interaction: Interaction) -> None:
        """Удаляет сообщение с кнопками из канала преподавателя и очищает ссылки."""
        msg_id = getattr(self.labwork, "teacher_message_id", None)
        channel_id = getattr(self.labwork, "teacher_channel_id", None)
        if not msg_id:
            return

        channel: discord.TextChannel | None = None
        if channel_id:
            channel = interaction.guild.get_channel(channel_id)
        if channel is None or not isinstance(channel, discord.TextChannel):
            channel = interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None

        if channel:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.delete()
            except Exception:
                pass

        self.labwork.teacher_message_id = None
        self.labwork.teacher_channel_id = None
        try:
            await self.labwork.save(update_fields=["teacher_message_id", "teacher_channel_id"])
        except Exception as e:
            cog = interaction.client.get_cog("LabsCog")
            if cog and hasattr(cog, "_log_feedback"):
                await cog._log_feedback(interaction.guild, f"⚠️ cleanup pointers failed: {e}")

    @ui.button(label="Зачтено ✅", style=ButtonStyle.success)
    async def accept(self, interaction: Interaction, button: ui.Button):
        await self._process_result(
            interaction,
            status="зачтено",
            teacher_reply=f"✅ Работа №{self.labwork.lab_number} зачтена.",
        )

    @ui.button(label="На доработку 🛠", style=ButtonStyle.danger)
    async def review(self, interaction: Interaction, button: ui.Button):
        modal = FeedbackModal(self.labwork, parent_view=self)
        await interaction.response.send_modal(modal)


class FeedbackModal(ui.Modal, title="Комментарий к работе"):
    feedback = ui.TextInput(label="Комментарий преподавателя", style=discord.TextStyle.paragraph, required=True)

    def __init__(self, labwork, parent_view: LabReviewView):
        super().__init__()
        self.labwork = labwork
        self.parent_view = parent_view

    async def on_submit(self, interaction: Interaction):
        try:
            # Если операция может занять время — можно раскомментировать defer:
            # await interaction.response.defer(ephemeral=True)

            await self.parent_view._process_result(
                interaction,
                status="на доработке",
                teacher_reply="📬 Работа отправлена студенту на доработку.",
                feedback=self.feedback.value,
            )
        except Exception as e:
            tb = traceback.format_exc()
            cog = interaction.client.get_cog("LabsCog")
            if cog and hasattr(cog, "_log_feedback"):
                await cog._log_feedback(
                    interaction.guild,
                    f"❌ Modal submit failed: {e}\n```py\n{tb}\n```"
                )
            # Чтобы Discord не показал красную ошибку — даём явный ответ
            await _safe_respond(
                interaction,
                "⚠️ Не удалось сохранить комментарий. Подробности в feedback.",
                ephemeral=True
            )
            
async def setup(bot):
    await bot.add_cog(LabsCog(bot))
