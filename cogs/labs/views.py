from __future__ import annotations

import re
import traceback
from typing import Tuple

import discord
from discord import ButtonStyle, Interaction, ui

from database.models import LabWork, User
from utils.feedback import send_feedback_message

from .utils import safe_respond


class LabReviewView(ui.View):
    """Кнопки для проверки лабораторной преподавателем."""

    def __init__(self, labwork: LabWork):
        super().__init__(timeout=None)
        self.labwork = labwork  # ORM объект LabWork

    async def _get_student(
        self,
        guild: discord.Guild,
        interaction: Interaction,
    ) -> Tuple[discord.Member | None, User | None]:
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

        # Резервный путь: достаём из сообщения и при необходимости фиксируем discord_id в БД
        if discord_member is None:
            parsed = await self._extract_student_from_teacher_message(interaction)
            if parsed:
                discord_member = parsed
                if user_obj and (not getattr(user_obj, "discord_id", None) or user_obj.discord_id != parsed.id):
                    try:
                        await User.filter(id=user_obj.id).update(discord_id=parsed.id)
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

        # Если есть прямые mentions — берём первого
        if msg.mentions:
            mention = msg.mentions[0]
            return interaction.guild.get_member(mention.id) or await interaction.guild.fetch_member(mention.id)

        # Иначе пробуем распарсить из embed.description
        if msg.embeds:
            desc = (msg.embeds[0].description or "")
            match = re.search(r"<@!?(\d+)>", desc)
            if match:
                uid = int(match.group(1))
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
        except Exception as error:
            guild = interaction.guild
            if guild:
                await send_feedback_message(guild, f"❌ save(status/feedback) failed: {error}")

        await self._notify_student_and_channel(interaction, status, feedback)
        await safe_respond(interaction, teacher_reply, ephemeral=True)
        await self._delete_teacher_message(interaction)

    async def _notify_student_and_channel(
        self,
        interaction: Interaction,
        status: str,
        feedback: str | None = None,
    ) -> None:
        member, user_obj = await self._get_student(interaction.guild, interaction)
        status_text = status.capitalize()
        embed = discord.Embed(
            title=f"Лабораторная №{self.labwork.lab_number}",
            description=f"**Статус:** {status_text}",
            color=discord.Color.green() if status == "зачтено" else discord.Color.orange(),
        )
        if feedback:
            embed.add_field(name="Комментарий преподавателя", value=feedback, inline=False)
        if self.labwork.file_url:
            embed.add_field(name="Файл", value=self.labwork.file_url, inline=False)

        if member:
            try:
                await member.send(embed=embed)
            except Exception as error:
                if interaction.guild:
                    await send_feedback_message(
                        interaction.guild,
                        f"⚠️ Не удалось отправить ЛС студенту {member.display_name}: {error}",
                    )

        channel_id = getattr(self.labwork, "student_channel_id", None)
        if channel_id:
            channel = interaction.guild.get_channel(channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                try:
                    await channel.send(member.mention if member else "Студент", embed=embed)
                except Exception:
                    pass

        # фиксируем метаданные
        if user_obj and member:
            if user_obj.discord_id != member.id:
                try:
                    await User.filter(id=user_obj.id).update(discord_id=member.id)
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
        except Exception as error:
            if interaction.guild:
                await send_feedback_message(
                    interaction.guild,
                    f"⚠️ cleanup pointers failed: {error}",
                )

    @ui.button(label="Зачтено ✅", style=ButtonStyle.success)
    async def accept(self, interaction: Interaction, button: ui.Button) -> None:  # noqa: ARG002
        await self._process_result(
            interaction,
            status="зачтено",
            teacher_reply=f"✅ Работа №{self.labwork.lab_number} зачтена.",
        )

    @ui.button(label="На доработку 🛠️", style=ButtonStyle.danger)
    async def review(self, interaction: Interaction, button: ui.Button) -> None:  # noqa: ARG002
        modal = FeedbackModal(self.labwork, parent_view=self)
        await interaction.response.send_modal(modal)


class FeedbackModal(ui.Modal, title="Комментарий по лабораторной"):
    feedback = ui.TextInput(
        label="Комментарий преподавателя",
        style=discord.TextStyle.paragraph,
        required=True,
    )

    def __init__(self, labwork: LabWork, parent_view: LabReviewView):
        super().__init__()
        self.labwork = labwork
        self.parent_view = parent_view

    async def on_submit(self, interaction: Interaction) -> None:
        try:
            await self.parent_view._process_result(
                interaction,
                status="на доработку",
                teacher_reply="✍️ Работа отправлена на доработку.",
                feedback=self.feedback.value,
            )
        except Exception as error:
            tb = traceback.format_exc()
            if interaction.guild:
                await send_feedback_message(
                    interaction.guild,
                    f"⚠️ Modal submit failed: {error}\n```py\n{tb}\n```",
                )
            await safe_respond(
                interaction,
                "Не удалось завершить обработку. Попробуйте ещё раз и проверьте feedback.",
                ephemeral=True,
            )
