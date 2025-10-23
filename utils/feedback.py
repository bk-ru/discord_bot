"""
Utilities for creating and using feedback channels across bot components.
"""

from __future__ import annotations

import logging
from typing import Optional

import discord

logger = logging.getLogger(__name__)


async def ensure_feedback_channel(
    guild: discord.Guild,
    *,
    bot_member: Optional[discord.Member] = None,
    category_reason: str | None = None,
    channel_reason: str | None = None,
) -> Optional[discord.TextChannel]:
    """
    Ensure that the guild contains a feedback channel that the bot can use.

    The channel is created inside a category named after the bot. The channel
    itself uses the naming convention ``{bot_name.lower()}-feedback``. Returns
    the created or existing channel, or ``None`` if creation fails.
    """
    bot_member = bot_member or guild.me
    bot_name = bot_member.display_name if bot_member else "Bot"

    category = discord.utils.get(guild.categories, name=bot_name)
    if not category:
        try:
            category = await guild.create_category(
                bot_name,
                reason=category_reason or "Ensure feedback infrastructure for bot",
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to create feedback category in %s: %s", guild.id, exc)
            category = None

    channel_name = f"{bot_name.lower()}-feedback"
    channel = discord.utils.get(guild.text_channels, name=channel_name)

    if channel and category and channel.category != category:
        try:
            await channel.edit(category=category)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to move feedback channel in %s: %s", guild.id, exc)
    elif not channel:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
        }
        effective_bot_member = bot_member or guild.me
        if effective_bot_member:
            overwrites[effective_bot_member] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )
        try:
            channel = await guild.create_text_channel(
                channel_name,
                category=category,
                overwrites=overwrites,
                reason=channel_reason or "Create feedback channel for bot",
            )
            if bot_member:
                await channel.set_permissions(
                    bot_member,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )
            try:
                await channel.send(
                    f"Создан канал обратной связи для {bot_name}. Используйте его для логов и уведомлений."
                )
            except Exception:
                pass
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to create feedback channel in %s: %s", guild.id, exc)
            return None

    return channel


async def send_feedback_message(
    guild: discord.Guild,
    message: str,
    *,
    bot_member: Optional[discord.Member] = None,
    fallback_logger=logger.warning,
) -> None:
    """
    Send a message into the feedback channel. Falls back to logging when the
    channel cannot be created or accessed.
    """
    channel = await ensure_feedback_channel(guild, bot_member=bot_member)
    if channel:
        try:
            await channel.send(message)
            return
        except Exception as exc:  # pragma: no cover - defensive logging
            fallback_logger("Failed to send feedback message to %s: %s", guild.id, exc)

    fallback_logger("Feedback fallback for guild %s: %s", guild.id, message)
