from __future__ import annotations

import discord
from discord import ui


class DeleteChannelView(ui.View):
    """Выбор при уходе пользователя: удалить или оставить канал."""

    def __init__(
        self,
        channel: discord.TextChannel,
        feedback_channel: discord.TextChannel | None = None,
    ):
        super().__init__(timeout=None)
        self.channel = channel
        self.channel_id = channel.id  # сохраняем ID канала
        self.feedback_channel = feedback_channel
        self.message = None  # сюда сохраним ссылку на сообщение с кнопками

    async def _delete_original_message(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.message.delete()
        except Exception:
            pass

    @ui.button(label="Удалить канал", style=discord.ButtonStyle.danger)
    async def delete_channel(
        self,
        interaction: discord.Interaction,
        button: ui.Button,  # noqa: ARG002 - интерфейс discord.py
    ) -> None:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "🚫 Только администратор может это делать.",
                ephemeral=True,
            )
            await self._delete_original_message(interaction)
            return

        try:
            await self.channel.delete(reason="Удалён после выхода участника.")
            await interaction.response.send_message(
                f"✅ Канал **{self.channel.name}** удалён.",
                ephemeral=True,
            )
            if self.feedback_channel:
                await self.feedback_channel.send(
                    f"🗑️ Канал **{self.channel.name}** удалён по решению {interaction.user.mention}."
                )
        except Exception as error:
            await interaction.response.send_message(
                f"⚠️ Ошибка при удалении канала: {error}",
                ephemeral=True,
            )
        finally:
            await self._delete_original_message(interaction)

    @ui.button(label="Не удалять", style=discord.ButtonStyle.success)
    async def keep_channel(
        self,
        interaction: discord.Interaction,
        button: ui.Button,  # noqa: ARG002 - интерфейс discord.py
    ) -> None:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "🚫 Только администратор может это делать.",
                ephemeral=True,
            )
            await self._delete_original_message(interaction)
            return

        await interaction.response.send_message(
            f"✅ Канал **{self.channel.name}** сохранён.",
            ephemeral=True,
        )
        if self.feedback_channel:
            await self.feedback_channel.send(
                f"📁 Канал **{self.channel.name}** сохранён по решению {interaction.user.mention}."
            )
        await self._delete_original_message(interaction)
