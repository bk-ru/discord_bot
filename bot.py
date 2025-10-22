"""
bot.py
Точка входа для запуска Discord-бота.
"""

import discord
from discord.ext import commands
from config import TOKEN
from cogs.events import EventsCog
from cogs.commands import BasicCommands

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.messages = True

bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command("help")

@bot.event
async def on_ready():
    """Вызывается, когда бот полностью готов к работе."""
    print(f"✅ Бот {bot.user} успешно запущен и готов к работе!")


async def load_extensions():
    """Асинхронная загрузка когов."""
    await bot.load_extension("cogs.events")
    await bot.load_extension("cogs.commands")
    print("🔧 Коги успешно загружены.")


async def main():
    """Основная точка входа."""
    async with bot:
        await load_extensions()
        await bot.start(TOKEN)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
