from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Callable

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import Bot

from bot.distributed.broker import Broker

# safe_send and validate_and_normalise_web_url are injected for testability
# Import centralised Discord interaction helpers
from bot.distributed.remote_browser import RemoteBrowserRuntime
from bot.frontends.discord.discord_interactions import safe_defer
from bot.plugins.base_di import BaseDIClientCog
from bot.plugins.commands.decorators import background_app_command

# --- validation helpers for this cog -------------------------------------
logger = logging.getLogger(__name__)


class Web(
    BaseDIClientCog, commands.GroupCog, name="web", description="Control a web browser instance."
):
    def __init__(
        self,
        bot: Bot,
        safe_send_func: Callable[..., Any] | None = None,
        validate_url_func: Callable[[str], str] | None = None,
    ) -> None:
        BaseDIClientCog.__init__(self, bot)
        self.bot = bot
        # No local runtime: all browser commands use distributed remote runtime

        from bot.frontends.discord.discord_interactions import safe_send as default_safe_send
        from bot.utils.urls import validate_and_normalise_web_url as default_validate_url

        self.safe_send = safe_send_func if safe_send_func is not None else default_safe_send
        self.validate_url = (
            validate_url_func if validate_url_func is not None else default_validate_url
        )
        # Distributed browser runtime (uses Redis broker)
        # TODO: Use DI to inject shared Broker if available
        import os

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.browser = RemoteBrowserRuntime(Broker(redis_url))

    @app_commands.command(name="start", description="Start a browser session with an optional URL.")
    @app_commands.describe(url="Optional URL to navigate to.")
    async def start(self, interaction: discord.Interaction, url: str | None = None) -> None:
        """Open a new browser page and optionally navigate to the specified URL."""
        await safe_defer(interaction, ephemeral=True, thinking=True)
        if url:
            try:
                processed_url = self.validate_url(url)
                await self.browser.goto(processed_url, worker_hint=str(interaction.user.id))
                await self.safe_send(
                    interaction,
                    f"🟢 Started browser and navigated to **{processed_url}**",
                    ephemeral=True,
                )
            except ValueError as e:
                await self.safe_send(
                    interaction,
                    f"❌ Invalid URL: {e}. Please include a scheme (e.g., http:// or https://).",
                    ephemeral=True,
                )

        else:
            # Just start the browser without navigating anywhere specific
            await self.browser.start(worker_hint=str(interaction.user.id))
            await self.safe_send(interaction, "🟢 Browser started successfully.", ephemeral=True)
            return

    @app_commands.command(
        name="open", description="Navigate to the specified URL in the current browser."
    )
    @app_commands.describe(url="The URL to navigate to.")
    async def open(self, interaction: discord.Interaction, url: str) -> None:
        """Navigates the current browser to the specified URL."""
        try:
            processed_url = self.validate_url(url)
            await self.browser.goto(processed_url, worker_hint=str(interaction.user.id))
            await self.safe_send(
                interaction,
                f"🟢 Navigated to **{processed_url}**",
                ephemeral=True,
            )
        except ValueError as e:
            await self.safe_send(
                interaction,
                f"❌ Invalid URL: {e}. Please include a scheme (e.g., http:// or https://).",
                ephemeral=True,
            )

    # ------------------------------------------------------------------+
    # internal helpers (used by close / closeall and legacy paths)      |
    # ------------------------------------------------------------------+

    # Helper removed - now using @read_only_guard() decorator instead

    @app_commands.command(name="screenshot", description="Take a screenshot.")
    async def screenshot(
        self, interaction: discord.Interaction, filename: str | None = None
    ) -> None:
        """Take a screenshot of the current browser page."""
        actual_filename = filename or "screenshot.png"
        if not any(actual_filename.endswith(ext) for ext in [".png", ".jpg", ".jpeg"]):
            actual_filename += ".png"  # Default to PNG if no extension

        screenshots_dir = Path("./screenshots")
        screenshots_dir.mkdir(exist_ok=True)

        timestamp = int(time.time())
        unique_name = f"{timestamp}_{actual_filename}"
        screenshot_path = screenshots_dir / unique_name

        if screenshot_path.exists():
            await self.safe_send(
                interaction,
                f"❌ File already exists: {actual_filename}",
                ephemeral=True,
            )

        chan = interaction.channel_id
        assert chan is not None

        if not interaction.response.is_done():
            await safe_defer(interaction, thinking=True, ephemeral=True)

        async def process_screenshot() -> None:
            try:
                img_bytes = await self.browser.screenshot(
                    filename=actual_filename, worker_hint=str(interaction.user.id)
                )
                screenshot_path.write_bytes(img_bytes)
                file = discord.File(screenshot_path, filename=actual_filename)
                await self.safe_send(
                    interaction,
                    content="🖼️ Screenshot taken.",
                    file=file,
                )
            except Exception as e:
                await self.safe_send(
                    interaction,
                    f"❌ Error sending screenshot: {e}",
                )
            finally:
                if screenshot_path.exists():
                    try:
                        screenshot_path.unlink()
                    except Exception as e:
                        logger.error(f"Error deleting screenshot: {e}")

        asyncio.create_task(process_screenshot())

    @app_commands.command(name="status", description="Show browser status")
    async def status(self, interaction: discord.Interaction) -> None:
        """Show information about the browser instance for the current channel."""
        await safe_defer(interaction, thinking=True, ephemeral=True)
        try:
            status = await self.browser.status(worker_hint=str(interaction.user.id))
            # Format status for display
            if not status:
                await self.safe_send(interaction, "No active browser workers.", ephemeral=True)
                return
            embed = discord.Embed(
                title="Browser Worker Status", description="Status for this channel"
            )
            for k, v in status.items():
                embed.add_field(name=str(k), value=str(v), inline=False)
            await self.safe_send(interaction, embed=embed, ephemeral=True)
            return
        except Exception as exc:
            await self.safe_send(interaction, f"❌ Error fetching status: {exc}", ephemeral=True)
            return

    @app_commands.command(name="close", description="Close the browser for this channel")
    @background_app_command(defer_ephemeral=False)
    async def close(self, interaction: discord.Interaction) -> None:
        """Close the browser instance for the current channel."""
        chan = interaction.channel_id
        assert chan is not None

        # Close the browser for this channel using distributed bridge/manager
        try:
            await self.browser.close_channel(channel_id=chan, worker_hint=str(interaction.user.id))
            await self.safe_send(interaction, "🟢 Browser closed for this channel.", ephemeral=True)
        except Exception as exc:
            await self.safe_send(
                interaction,
                f"❌ Error closing browser: {type(exc).__name__}: {exc}",
                ephemeral=True,
            )

    @app_commands.command(name="closeall", description="Close all browser instances (admin only)")
    @app_commands.default_permissions(administrator=True)
    @background_app_command(defer_ephemeral=True)
    async def closeall(self, interaction: discord.Interaction) -> None:
        """Close all browser instances across all channels (admin only)."""
        # The decorator already enforces permissions; no extra checks needed

        # Close all browsers using distributed bridge/manager
        try:
            await self.browser.close_all(worker_hint=str(interaction.user.id))
            await self.safe_send(interaction, "🟢 All browser instances closed.", ephemeral=True)
        except Exception as exc:
            await self.safe_send(
                interaction,
                f"❌ Error closing browsers: {type(exc).__name__}: {exc}",
                ephemeral=True,
            )


async def setup(bot: Bot) -> None:
    await bot.add_cog(Web(bot))
