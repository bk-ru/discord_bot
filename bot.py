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

async def setup_bot():
    """Регистрирует коги и запускает бота."""
    await bot.add_cog(EventsCog(bot))
    await bot.add_cog(BasicCommands(bot))
    print("Логи успешно загружены.")

@bot.event
async def on_ready():
    """Вызывается при готовности бота."""
    print("Бот готов к работе!")

if __name__ == "__main__":
    import asyncio
    asyncio.run(setup_bot())
    bot.run(TOKEN)
