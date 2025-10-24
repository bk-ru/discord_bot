from discord.ext import commands
import discord
from database.models import User, LabWork
from tortoise.exceptions import DoesNotExist
from typing import Union

from utils.feedback import ensure_feedback_channel, send_feedback_message
from cogs.labs.views import LabReviewView
from cogs.labs.utils import safe_respond

class LabsCog(commands.Cog):
    """Команды для сдачи и проверки лабораторных работ."""

    def __init__(self, bot):
        self.bot = bot
        self.feedback_channels: dict[int, discord.TextChannel] = {}
        
    async def _get_or_create_feedback_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        cached = self.feedback_channels.get(guild.id)
        if cached and cached.guild:
            return cached

        channel = await ensure_feedback_channel(guild)
        if channel:
            self.feedback_channels[guild.id] = channel
        return channel

    async def _log_feedback(self, guild: discord.Guild, text: str) -> None:
        channel = await self._get_or_create_feedback_channel(guild)
        if channel:
            try:
                await channel.send(text)
                return
            except Exception:
                pass
        await send_feedback_message(guild, text)

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
                defaults={"file_url": file_url, "status": "отправлено", "teacher_file_url": None}
            )
            if created:
                # запись уже с нужными полями
                pass
            else:
                # обновляем через query (обходит partial), затем грузим полную запись
                await LabWork.filter(user=user, lab_number=lab_number).update(
                    file_url=file_url,
                    status="отправлено",
                    teacher_file_url=None,
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
        if lab.teacher_file_url:
            embed.add_field(name='Исправленный файл', value=lab.teacher_file_url, inline=False)

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
        corrected_url = None
        if ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            corrected_url = attachment.url
            lab.teacher_file_url = corrected_url
        await lab.save()

        await ctx.send(f"🛠️ Лабораторная №{lab_number} студента {student.mention} отправлена на доработку.")

        student_message = f'🛠️ Твоя лабораторная №{lab_number} отправлена на доработку.\nКомментарий: {comment}'
        if corrected_url:
            student_message += f'\nИсправленный файл: {corrected_url}'
            await ctx.send(f'📎 Исправленный файл для студента: {corrected_url}')
            await self._log_feedback(
                ctx.guild,
                f'📎 {ctx.author.mention} приложил исправленный файл для лабораторной №{lab_number}: {corrected_url}'
            )
        await student.send(student_message)
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
            teacher_file_url=None,
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

async def setup(bot):
    await bot.add_cog(LabsCog(bot))
