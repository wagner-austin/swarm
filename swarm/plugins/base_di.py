from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from discord.ext import commands

if TYPE_CHECKING:
    from swarm.core.containers import Container


# A light mix‑in that resolves the DI container once.
class BaseDIClientCog(commands.Cog):
    """
    All cogs that rely on dependency‑injector should inherit from this mix‑in.
    It guarantees that ``self.container`` is always present and initialised.
    """

    container: Container  # populated at runtime

    def __init__(self, discord_bot: commands.Bot) -> None:  # noqa: D401  (imperative)
        super().__init__()
        self.bot = discord_bot
        self.discord_bot = discord_bot
        # Fail fast if container is missing
        if not hasattr(discord_bot, "container"):
            raise RuntimeError(
                "DI container missing – start the bot via discord_runner "
                "or attach a Container in your test fixture."
            )
        self.container = discord_bot.container
        logging.getLogger(__name__).debug(
            "[BaseDIClientCog] container resolved: %s", type(self.container).__name__
        )
