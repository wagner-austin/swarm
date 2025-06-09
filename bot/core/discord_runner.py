# src/bot_core/discord_runner.py
import logging
from pathlib import Path
from typing import Any
import discord  # Import discord itself for discord.errors.LoginFailure
from discord import Intents
from discord.ext import commands

from bot.core.settings import settings
from bot.infra.tankpit.proxy.service import ProxyService
from bot.core.api.browser_service import BrowserService  # Added for DI
from bot.plugins.commands.browser import (
    setup as browser_cog_setup,
)  # Added for manual loading
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


async def run_bot(proxy_service: ProxyService | None) -> None:
    """
    Creates, configures, and starts the Discord bot.
    Handles bot-specific lifecycle and error events.
    """
    if not settings.discord_token:
        logger.critical("DISCORD_TOKEN is not set. Bot cannot start.")
        return

    intents = Intents.default()
    # prefix is ignored but must exist → mention-only
    # No legacy prefixes – users interact via slash menu or @mention.
    bot = MyBot(command_prefix=None, intents=intents)
    if proxy_service:
        bot.proxy_service = proxy_service  # Store the proxy service instance on the bot

    discovered_extensions = _discover_extensions()
    manually_loaded_extensions = {
        "bot.plugins.commands.browser",
        "bot.plugins.commands.proxy",
    }

    for ext_name in discovered_extensions:
        if ext_name in manually_loaded_extensions:
            logger.info(
                f"Skipping automatic load for {ext_name}; will be loaded manually with DI."
            )
            continue

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

    if proxy_service:
        try:
            from bot.plugins.commands.proxy import setup as proxy_setup_func

            await proxy_setup_func(bot, proxy_service=proxy_service)
            logger.info(
                "Successfully loaded 'bot.plugins.commands.proxy' with ProxyService injection."
            )
        except ImportError:
            logger.error(
                "Failed to import 'bot.plugins.commands.proxy'. Ensure it exists and is importable."
            )
        except AttributeError:
            logger.error("'setup' function not found in 'bot.plugins.commands.proxy'.")
        except Exception as e:
            logger.exception(
                "Failed to manually load 'bot.plugins.commands.proxy'", exc_info=e
            )
    elif os.environ.get("FAST_EXIT_FOR_TESTS") != "1":
        logger.warning(
            "ProxyService is not available. Skipping load of 'bot.plugins.commands.proxy'."
        )

    # Manually load the Browser cog with BrowserService dependency injection
    try:
        browser_service_instance = BrowserService()
        await browser_cog_setup(bot, browser_service_instance)
        logger.info(
            "Successfully loaded 'bot.plugins.commands.browser' with BrowserService injection."
        )
    except ImportError:
        logger.error(
            "Failed to import 'bot.plugins.commands.browser' or 'BrowserService'. Ensure they exist and are importable."
        )
    except AttributeError as e:
        logger.error(
            f"'setup' function not found in 'bot.plugins.commands.browser' or BrowserService init failed: {e}"
        )
    except Exception as e:
        logger.exception(
            "Failed to manually load 'bot.plugins.commands.browser'", exc_info=e
        )

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
        if isinstance(error, discord.app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"⏱️ Cooldown – try again in {error.retry_after:.1f}s", ephemeral=True
            )
            return
        raise error

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
        # Attempt to stop the proxy service first
        if (
            hasattr(bot, "proxy_service")
            and bot.proxy_service
            and hasattr(bot.proxy_service, "stop")
        ):
            logger.info("Attempting to stop ProxyService...")
            try:
                await bot.proxy_service.stop()  # Assuming stop() is async
                logger.info("ProxyService stopped.")
            except Exception as e:
                logger.exception(
                    "Error stopping ProxyService during shutdown:", exc_info=e
                )

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
