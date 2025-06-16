from __future__ import annotations

import logging
import os  # Added for os.getenv
from typing import TYPE_CHECKING

import discord
from discord.app_commands import CheckFailure, CommandOnCooldown

if TYPE_CHECKING:
    from bot.core.discord.boot import MyBot
    # Container is no longer needed by on_ready in this version
    # from bot.core.containers import Container

logger = logging.getLogger(__name__)


# Container removed from arguments
def register_event_handlers(bot: MyBot) -> None:
    """
    Defines and registers event handlers for the bot.
    """

    @bot.event
    async def on_ready() -> None:
        """Called when the bot is done preparing the data received from Discord."""
        # Matches the version from discord_runner.py before refactor
        logger.info(f"[bold green]✅ {bot.user} is LIVE[/] – syncing slash commands …")

        # 1️⃣ GLOBAL → needed for DM availability everywhere
        await bot.tree.sync()

        # 2️⃣ GUILD  → instant updates in your dev server (optional)
        guild_id_str = os.getenv("DEV_GUILD")
        if guild_id_str:
            try:
                guild_id = int(guild_id_str)
                guild = discord.Object(id=guild_id)
                # Ensure copy_global_to is awaited if it's a coroutine,
                # but it's typically a synchronous method.
                # discord.py docs show it as synchronous.
                bot.tree.copy_global_to(guild=guild)
                await bot.tree.sync(guild=guild)
                logger.info(f"Synced commands to dev guild {guild_id}.")
            except ValueError:
                logger.error(
                    f"Invalid DEV_GUILD ID: {guild_id_str}. Must be an integer."
                )
            except Exception as e:
                logger.exception(
                    f"Failed to sync commands to dev guild {guild_id_str}: {e}"
                )

        logger.info("Slash commands synced.")

        # Start the proxy service if it's available and configured
        # This logic is from the discord_runner.py's on_ready before refactor
        if (
            hasattr(bot, "proxy_service")
            and bot.proxy_service
            and hasattr(bot.proxy_service, "port")  # Check if port attribute exists
            and bot.proxy_service.port > 0
            and hasattr(bot.proxy_service, "start")  # Check if start method exists
            and hasattr(bot.proxy_service, "is_running")  # Check for is_running method
            and not bot.proxy_service.is_running()  # Only start if not already running
        ):
            try:
                logger.info(
                    f"Attempting to start ProxyService on port {bot.proxy_service.port} from on_ready..."
                )
                await (
                    bot.proxy_service.start()
                )  # Assumes bot.proxy_service is an instance
                logger.info(
                    f"ProxyService started successfully from on_ready on port {bot.proxy_service.port}"
                )
            except Exception as e:
                logger.exception(
                    f"Proxy failed to start in on_ready: {e}; shutting bot down"
                )
                await bot.close()  # Critical: shuts down bot on proxy failure
        else:
            logger.info(
                "ProxyService not available/configured as expected, or already running, skipping start attempt in on_ready."
            )

    @bot.event
    async def on_disconnect() -> None:
        logger.info(f"Bot '{bot.user if bot.user else ''}' disconnected from Discord.")

    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction, error: discord.app_commands.AppCommandError
    ) -> None:
        # Using CheckFailure and CommandOnCooldown imported at the top
        if isinstance(error, CheckFailure):
            from bot.utils.discord_interactions import safe_send

            await safe_send(
                interaction,
                "🚫 You don’t have permission to use that command.",
                ephemeral=True,
            )
            return

        if isinstance(error, CommandOnCooldown):
            from bot.utils.discord_interactions import safe_send

            await safe_send(
                interaction,
                f"⏱️ Cooldown – try again in {error.retry_after:.1f}s",
                ephemeral=True,
            )
            return

        logger.error(f"Unhandled app command error: {error}", exc_info=error)
        from bot.utils.discord_interactions import safe_send

        await safe_send(
            interaction,
            "⚙️ An unexpected error occurred. Please try again later.",
            ephemeral=True,
        )

    @bot.event
    async def on_message(message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.content.startswith(("!", ".")):
            await message.channel.send(
                "All commands are now **slash commands** – type `/` to browse available actions 🙂"
            )
