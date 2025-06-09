from __future__ import annotations

import logging
from discord.ext import commands

from bot.core.containers import Container


# A light mix‑in that resolves the DI container once.
class BaseDIClientCog(commands.Cog):
    """
    All cogs that rely on dependency‑injector should inherit from this mix‑in.
    It guarantees that ``self.container`` is always present and initialised.
    """

    container: Container  # populated at runtime

    def __init__(self, bot: commands.Bot) -> None:  # noqa: D401  (imperative)
        super().__init__()
        self.bot = bot
        # Prefer the container the runner already attached
        existing = getattr(bot, "container", None)
        if existing is None:  # unit tests often skip the runner
            existing = Container()
            setattr(bot, "container", existing)
        self.container = existing
        logging.getLogger(__name__).debug(
            "[BaseDIClientCog] container resolved: %s", type(self.container).__name__
        )
