from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from discord.ext import commands

# This import is for type hinting MyBot.proxy_service.
# It might create a circular dependency if ProxyService itself imports MyBot.
# We should check this later, but for now, it's needed for the type hint.
from bot.netproxy.service import ProxyService

if TYPE_CHECKING:  # To avoid circular imports with the container
    from bot.core.containers import Container
    from bot.core.lifecycle import BotLifecycle

logger = logging.getLogger(__name__)


class MyBot(commands.Bot):
    # Attrs added at runtime, but mypy needs to know for strict type checking.
    container: "Container"
    lifecycle: "BotLifecycle"
    proxy_service: ProxyService | None

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.proxy_service = None


def _discover_extensions() -> list[str]:
    """Discover and load every commands-package cog residing in *bot/plugins/commands*."""
    # Path(__file__) in this context will be .../bot/core/discord/boot.py
    # So, .parent.parent.parent should give us the 'bot' directory.
    base_path = Path(__file__).resolve().parent.parent.parent  # bot/
    commands_path = base_path / "plugins" / "commands"
    extensions = []

    # Memory 1c979e83-c372-4759-aa3a-a9e272910692 mentions an allow-list:
    # KEEP = {"browser", "chat", "help", "proxy"}
    # The current _discover_extensions logic loads all .py files except __init__ and browser_status.
    # For now, I will keep the existing logic as the primary goal is refactoring file structure.
    # We can address the allow-list logic consistency later if needed.
    # The memory also states: "Updated _discover_extensions() to use an allow-list (`KEEP = {\"browser\", \"chat\", \"help\", \"proxy\"}`)"
    # However, the provided code for _discover_extensions does not show this allow-list.
    # I will stick to moving the existing code as-is.

    if commands_path.is_dir():
        for p in commands_path.glob("*.py"):
            if p.stem != "__init__":
                # The memory 1c979e83-c372-4759-aa3a-a9e272910692 mentions KEEP list.
                # The current code has a hardcoded skip for "browser_status".
                # Let's keep the existing logic from discord_runner.py for now.
                if p.stem != "browser_status":  # ← skip legacy cog
                    extensions.append(f"bot.plugins.commands.{p.stem}")
    else:
        logger.warning(
            f"Commands directory not found at {commands_path}, no command plugins loaded from there."
        )

    logger.info(f"Discovered extensions: {extensions}")
    return extensions
