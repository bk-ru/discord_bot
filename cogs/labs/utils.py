from __future__ import annotations

from typing import Any

import discord

from utils.feedback import send_feedback_message


async def safe_respond(
    interaction: discord.Interaction,
    content: Any,
    *,
    ephemeral: bool = True,
) -> None:
    """
    Безопасный ответ во взаимодействии: если исходный response уже отправлен,
    используем followup. В случае ошибки пишем в канал обратной связи.
    """
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(content, ephemeral=ephemeral)
    except Exception as error:
        guild = getattr(interaction, "guild", None)
        if guild:
            await send_feedback_message(
                guild,
                f"⚠️ safe_respond: {error}",
            )
