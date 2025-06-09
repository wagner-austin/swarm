# src/bot_core/discord_runner.py
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any
import discord  # Import discord itself for discord.errors.LoginFailure
from discord import Intents
from discord.ext import commands

from bot.core.settings import settings
from bot.netproxy.service import ProxyService  # For type hinting MyBot.proxy_service
from bot.core.containers import Container
import os
import asyncio

logger = logging.getLogger(__name__)


class MyBot(commands.Bot):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.proxy_service: ProxyService | None = None


def _discover_extensions() -> list[str]:
    """Discover and load every commands-package cog residing in *bot/plugins/commands*."""
    base_path = Path(__file__).resolve().parent.parent  # bot/
    commands_path = base_path / "plugins" / "commands"
    extensions = []

    if commands_path.is_dir():
        for p in commands_path.glob("*.py"):
            if p.stem != "__init__":
                extensions.append(f"bot.plugins.commands.{p.stem}")
    else:
        logger.warning(
            f"Commands directory not found at {commands_path}, no command plugins loaded from there."
        )

    logger.info(f"Discovered extensions (using allow-list): {extensions}")
    return extensions


async def run_bot() -> None:
    """
    Creates, configures, and starts the Discord bot.
    Handles bot-specific lifecycle and error events.
    """
    if not settings.discord_token:
        logger.critical("DISCORD_TOKEN is not set. Bot cannot start.")
        return

    # Initialize DI container
    container = Container()
    # Replace default Settings() singleton with the already-initialised one
    container.config.override(settings)

    # ------------------------------------------------------------------+
    # Dependency-Injection wiring                                       |
    # ------------------------------------------------------------------+
    #
    #  1.  Import *bot.plugins* once – this gives us the package object
    #      that dependency-injector can hook into.
    #  2.  `packages=[bot.plugins]` installs an import-hook: every module
    #      that is imported *under that package* afterwards is wired
    #      automatically.  Perfect for Discord’s lazy extension loader.
    #
    #  3.  Add `modules=[__name__]` so the runner itself can request
    #      injected services (e.g. in future health checks).
    #
    # ------------------------------------------------------------------+
    # 1. Extension discovery & *pre-import*                            |
    # ------------------------------------------------------------------+
    discovered_extensions = _discover_extensions()

    # Pre-import every commands module so the container can wire them
    # **before** Discord calls their `setup()` and instantiates the cogs.
    import importlib

    modules_to_wire = []
    for ext in discovered_extensions:
        modules_to_wire.append(importlib.import_module(ext))

    # ------------------------------------------------------------------+
    # 2. Dependency-Injection wiring                                    |
    # ------------------------------------------------------------------+
    container.wire(
        modules=[__name__, *modules_to_wire],  # runner + all command modules
    )

    # Start ProxyService if enabled
    ps_instance: ProxyService | None = None
    if container.config().proxy_enabled:
        logger.info("Proxy is enabled in settings. Attempting to start ProxyService...")
        try:
            ps_instance = (
                container.proxy_service()
            )  # DI will provide the configured instance
            await ps_instance.start()
            logger.info(f"ProxyService started successfully on port {ps_instance.port}")
        except Exception as e:
            logger.exception(
                "Failed to start ProxyService. It will be unavailable.", exc_info=e
            )
            ps_instance = None  # Ensure it's None if startup failed
    else:
        logger.info("Proxy is disabled in settings.")

    intents = Intents.default()
    # prefix is ignored but must exist → mention-only
    # No legacy prefixes – users interact via slash menu or @mention.
    bot = MyBot(command_prefix=None, intents=intents)
    # Make the singleton container reachable everywhere
    bot.container = container  # type: ignore[attr-defined]
    if ps_instance and ps_instance.is_running():
        loop = asyncio.get_running_loop()
        setattr(loop, "proxy_service", ps_instance)
        bot.proxy_service = (
            ps_instance  # Store the running proxy service instance on the bot
        )
    else:
        bot.proxy_service = None

    # ------------------------------------------------------------------+
    # 3. Load extensions - the modules are already imported and wired   |
    # ------------------------------------------------------------------+
    logger.info("Loading extensions...")
    for ext_name in discovered_extensions:
        try:
            await bot.load_extension(ext_name)
            logger.info(f"Successfully loaded extension: {ext_name}")
        except commands.ExtensionNotFound:
            logger.error(f"Extension not found: {ext_name}")
        except commands.ExtensionAlreadyLoaded:
            logger.warning(f"Extension already loaded: {ext_name}")
        except commands.NoEntryPointError:
            logger.error(f"Extension {ext_name} has no setup() function.")
        except commands.ExtensionFailed as e:
            logger.exception(
                f"Extension {ext_name} failed to load: {e.original}",
                exc_info=e.original,
            )
        except Exception as e:
            logger.exception(
                f"An unexpected error occurred while loading extension {ext_name}",
                exc_info=e,
            )
    logger.info("Finished loading extensions.")

    # ------------------------------------------------------------
    # Event Handlers                                               #
    # ------------------------------------------------------------+
    # Event Handlers                                              +
    # ------------------------------------------------------------+
    @bot.event
    async def on_ready() -> None:
        logger.info(f"Bot '{bot.user}' connected – syncing slash commands…")

        # 1️⃣ GLOBAL → needed for DM availability everywhere
        await bot.tree.sync()

        # 2️⃣ GUILD  → instant updates in your dev server (optional)
        guild_id = os.getenv("DEV_GUILD")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            bot.tree.copy_global_to(guild=guild)  # sync helper
            await bot.tree.sync(guild=guild)

        logger.info("Slash commands synced.")
        # Start the proxy service if it's available and configured
        if (
            hasattr(bot, "proxy_service")
            and bot.proxy_service
            and bot.proxy_service.port > 0
        ):
            try:
                logger.info(
                    f"Attempting to start ProxyService on port {bot.proxy_service.port}..."
                )
                await bot.proxy_service.start()
            except Exception as e:
                logger.exception(
                    f"Proxy failed to start in on_ready: {e}; shutting bot down"
                )
                await bot.close()
        else:
            logger.info(
                "ProxyService not available or not configured, skipping start in on_ready."
            )

    @bot.event
    async def on_disconnect() -> None:
        logger.info(f"Bot '{bot.user if bot.user else ''}' disconnected from Discord.")

    # Prefix handler gone → replace with slash error listener
    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction, error: discord.app_commands.AppCommandError
    ) -> None:
        from discord.app_commands import (
            CheckFailure,
        )  # Import moved inside for locality

        if isinstance(error, CheckFailure):
            # No permission – be nice but firm
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "🚫 You don’t have permission to use that command.",
                    ephemeral=True,
                )
            return

        if isinstance(error, discord.app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"⏱️ Cooldown – try again in {error.retry_after:.1f}s", ephemeral=True
            )
            return

        # If the error is not handled above, log it and inform the user generically.
        logger.error(f"Unhandled app command error: {error}", exc_info=error)
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "⚙️ An unexpected error occurred. Please try again later.",
                ephemeral=True,
            )
        # No `raise error` here to prevent scary tracebacks in console for unhandled ones,
        # as long as we've informed the user and logged it.

    @bot.event
    async def on_message(message: discord.Message) -> None:  # noqa: D401
        if message.author.bot:  # Ignore messages from other bots
            return
        if message.content.startswith(("!", ".")):  # common legacy prefixes
            await message.channel.send(
                "All commands are now **slash commands** – type `/` to browse available actions 🙂"
            )
        # Do not call await bot.process_commands(message) as we want to disable prefix commands

    try:
        logger.info("Attempting to connect the bot to Discord...")
        await bot.start(settings.discord_token)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info(
            "Shutdown signal received (Ctrl-C/Cancellation). Initiating graceful shutdown…"
        )
    except discord.errors.LoginFailure:
        logger.critical("Failed to log in to Discord. Check your DISCORD_TOKEN.")
    except Exception as e:
        logger.exception(
            "An unexpected error occurred in the bot's main run loop:", exc_info=e
        )
    finally:
        # Attempt to stop services from DI container
        logger.info("Attempting to gracefully shutdown services...")

        # SessionManager is shut down by its cog's cog_unload method.

        # Shutdown ProxyService (if it was started and assigned to bot.proxy_service)
        if bot.proxy_service and hasattr(bot.proxy_service, "stop"):
            logger.info("Shutting down ProxyService...")
            try:
                await bot.proxy_service.stop()
                logger.info("ProxyService shutdown successfully.")
            except Exception as e:
                logger.exception("Error during ProxyService shutdown:", exc_info=e)

        logger.info("Finished service shutdown attempts.")

        # Then close the bot connection
        if bot and not bot.is_closed():  # bot is defined in this scope
            logger.info("Closing bot connection...")
            await bot.close()
            logger.info("Bot connection closed.")
        else:
            logger.info("Bot was already closed or not started.")

        # ------------------------------------------------------------------+
        # Extra: close the hidden aiohttp.ClientSession to avoid           |
        # “Unclosed client session / connector” warnings on shutdown.      |
        # ------------------------------------------------------------------+
        try:
            http = getattr(bot, "http", None)
            session = getattr(
                http, "_HTTPClient__session", None
            )  # discord.py internals
            if session and not session.closed:
                await session.close()
                logger.debug("Closed aiohttp ClientSession cleanly.")
        except Exception as e:  # pragma: no cover – best-effort
            logger.debug(f"Ignoring aiohttp close error: {e}")
