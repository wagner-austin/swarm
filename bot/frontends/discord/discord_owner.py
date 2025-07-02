import asyncio
from typing import Final

import discord
from discord.ext import commands

_owner_lock: Final = asyncio.Lock()
_owner_cache: discord.User | None = None


def clear_owner_cache() -> None:
    """Clear the owner cache. Primarily for testing purposes."""
    global _owner_cache
    _owner_cache = None


async def get_owner(bot: commands.Bot) -> discord.User:
    """Get the bot's owner, with caching.

    The owner is looked up in the following order:
    1.  A cached ``discord.User`` object.
    2.  The ``owner_id`` on the bot, which is looked up via the Discord API.
    3.  The ``owner`` field of the bot's ``application_info``.

    Returns:
        The bot's owner.

    Raises:
        RuntimeError: If the owner cannot be resolved in any way.
    """
    global _owner_cache
    async with _owner_lock:
        if _owner_cache:
            return _owner_cache

        if bot.owner_id:
            owner = await bot.fetch_user(bot.owner_id)
        else:
            app_info = await bot.application_info()
            owner = app_info.owner

        if not owner:
            raise RuntimeError("Could not resolve bot owner")

        _owner_cache = owner
        return _owner_cache
