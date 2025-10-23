from __future__ import annotations

import discord
from discord import PermissionOverwrite, ui


class ChannelConflictView(ui.View):
    """
    Интерактивный выбор: создать новый личный канал
    или добавить пользователя в существующий.
    После выбора — исходное сообщение удаляется.
    """

    def __init__(
        self,
        member: discord.Member,
        category: discord.CategoryChannel,
        existing_channel: discord.TextChannel,
        feedback_channel: discord.TextChannel | None = None,
    ):
        super().__init__(timeout=None)
        self.member = member
        self.category = category
        self.existing_channel = existing_channel
        self.feedback_channel = feedback_channel  # чтобы избежать AttributeError

    async def _delete_original_message(self, interaction: discord.Interaction) -> None:
        """Удаляет исходное сообщение с кнопками (если возможно)."""
        try:
            await interaction.message.delete()
        except Exception as error:
            try:
                await interaction.followup.send(
                    f"⚠️ Не удалось удалить сообщение: {error}",
                    ephemeral=True,
                )
            except Exception:
                pass  # даже если followup не отправился — не критично

    @ui.button(label="Создать новый", style=discord.ButtonStyle.primary)
    async def create_new(
        self,
        interaction: discord.Interaction,
        button: ui.Button,  # noqa: ARG002 - интерфейс discord.py
    ) -> None:
        """Создание нового личного канала с индексом +1 и обновлением topic."""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "🚫 Только администратор может выполнять это действие.",
                ephemeral=True,
            )
            await self._delete_original_message(interaction)
            return

        # сначала очищаем старые topic с этим ID
        for channel in self.category.text_channels:
            if channel.topic and channel.topic.strip() == str(self.member.id):
                try:
                    await channel.edit(topic=None)
                    print(
                        f"⚙️ Очистил topic у старого канала {channel.name} (ID совпадал)."
                    )
                except Exception as error:
                    print(f"⚠️ Не удалось очистить topic у {channel.name}: {error}")

        base_name = self.member.display_name.lower().replace(" ", "-")
        new_name = base_name
        index = 1
        existing_names = [channel.name for channel in self.category.text_channels]
        while new_name in existing_names:
            new_name = f"{base_name}-{index}"
            index += 1

        overwrites = {
            self.member.guild.default_role: PermissionOverwrite(view_channel=False),
            self.member: PermissionOverwrite(view_channel=True, send_messages=True),
        }
        bot_member = self.category.guild.me
        if bot_member:
            overwrites[bot_member] = PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )
        new_channel = await self.category.create_text_channel(
            new_name,
            overwrites=overwrites,
            topic=str(self.member.id),
        )

        await interaction.response.send_message(
            f"✅ Создан новый личный канал {new_channel.mention}.",
            ephemeral=True,
        )
        if self.feedback_channel:
            await self.feedback_channel.send(
                f"🆕 Создан личный канал {new_channel.mention} для {self.member.mention}. "
                "Старые topic с ID были очищены."
            )
        await self._delete_original_message(interaction)

    @ui.button(label="Добавить в существующий", style=discord.ButtonStyle.success)
    async def add_to_existing(
        self,
        interaction: discord.Interaction,
        button: ui.Button,  # noqa: ARG002 - интерфейс discord.py
    ) -> None:
        """Добавление пользователя в существующий канал."""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "🚫 Только администратор может выполнять это действие.",
                ephemeral=True,
            )
            await self._delete_original_message(interaction)
            return

        await self.existing_channel.set_permissions(
            self.member,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        )
        bot_member = interaction.guild.me
        if bot_member:
            await self.existing_channel.set_permissions(
                bot_member,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )
        await interaction.response.send_message(
            f"✅ Пользователь добавлен в канал {self.existing_channel.mention}.",
            ephemeral=True,
        )
        await self._delete_original_message(interaction)
