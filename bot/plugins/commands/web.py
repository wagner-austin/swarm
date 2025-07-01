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

from bot.browser.runtime import BrowserRuntime
from bot.plugins.base_di import BaseDIClientCog
from bot.plugins.commands.decorators import background_app_command
from bot.utils.discord_interactions import safe_defer

# safe_send and validate_and_normalise_web_url are injected for testability
# Import centralised Discord interaction helpers
from bot.webapi.decorators import (
    CommandResult,
    browser_command,
    browser_mutating,
)

# --- validation helpers for this cog -------------------------------------
logger = logging.getLogger(__name__)


class Web(
    BaseDIClientCog, commands.GroupCog, name="web", description="Control a web browser instance."
):
    def __init__(
        self,
        bot: Bot,
        browser_runtime: BrowserRuntime | None = None,
        safe_send_func: Callable[..., Any] | None = None,
        validate_url_func: Callable[[str], str] | None = None,
    ) -> None:
        BaseDIClientCog.__init__(self, bot)
        self.bot = bot
        self.runtime: BrowserRuntime = (
            browser_runtime if browser_runtime is not None else self.container.browser_runtime()
        )
        from bot.utils.discord_interactions import safe_send as default_safe_send
        from bot.utils.urls import validate_and_normalise_web_url as default_validate_url

        self.safe_send = safe_send_func if safe_send_func is not None else default_safe_send
        self.validate_url = (
            validate_url_func if validate_url_func is not None else default_validate_url
        )

    @app_commands.command(name="start", description="Start a browser session with an optional URL.")
    @app_commands.describe(url="Optional URL to navigate to.")
    @browser_mutating()
    async def start(
        self, interaction: discord.Interaction, url: str | None = None
    ) -> CommandResult | None:
        """Open a new browser page and optionally navigate to the specified URL."""
        if url:
            try:
                processed_url = self.validate_url(url)
                return (
                    "goto",
                    (processed_url,),
                    f"🟢 Started browser and navigated to **{processed_url}**",
                )
            except ValueError as e:
                await self.safe_send(
                    interaction,
                    f"❌ Invalid URL: {e}. Please include a scheme (e.g., http:// or https://).",
                    ephemeral=True,
                )
                return None
        else:
            # Just start the browser without navigating anywhere specific
            return ("health_check", (), "🟢 Browser started successfully.")

    @app_commands.command(
        name="open", description="Navigate to the specified URL in the current browser."
    )
    @app_commands.describe(url="The URL to navigate to.")
    @browser_mutating()
    async def open(self, interaction: discord.Interaction, url: str) -> CommandResult | None:
        """Navigates the current browser to the specified URL."""
        try:
            processed_url = self.validate_url(url)
            return ("goto", (processed_url,), f"🟢 Navigated to **{processed_url}**")
        except ValueError as e:
            await self.safe_send(
                interaction,
                f"❌ Invalid URL: {e}. Please include a scheme (e.g., http:// or https://).",
                ephemeral=True,
            )
            return None

    # ------------------------------------------------------------------+
    # internal helpers (used by close / closeall and legacy paths)      |
    # ------------------------------------------------------------------+

    # Helper removed - now using @read_only_guard() decorator instead

    @app_commands.command(name="screenshot", description="Take a screenshot of the current page.")
    @app_commands.describe(filename="Optional filename for the screenshot.")
    @browser_command(queued=True, allow_mutation=False)
    async def screenshot(
        self, interaction: discord.Interaction, filename: str | None = None
    ) -> CommandResult | None:
        """Take a screenshot of the current browser page."""
        actual_filename = filename or "screenshot.png"
        if not any(actual_filename.endswith(ext) for ext in [".png", ".jpg", ".jpeg"]):
            actual_filename += ".png"  # Default to PNG if no extension

        # Create subfolder for screenshots
        screenshots_dir = Path("./screenshots")
        screenshots_dir.mkdir(exist_ok=True)

        # Generate unique filename for storage
        timestamp = int(time.time())
        unique_name = f"{timestamp}_{actual_filename}"
        screenshot_path = screenshots_dir / unique_name

        if screenshot_path.exists():
            await self.safe_send(
                interaction,
                f"❌ File already exists: {actual_filename}",
                ephemeral=True,
            )
            return None

        # Ask the browser to take a screenshot and wait for completion
        chan = interaction.channel_id
        assert chan is not None  # mypy: Optional → int

        # Ensure we acknowledge the interaction promptly; otherwise Discord will
        # show “The application did not respond”.  We defer **before** kicking
        # off the asynchronous browser work.
        if not interaction.response.is_done():
            await safe_defer(interaction, thinking=True, ephemeral=True)

        async def process_screenshot() -> None:
            try:
                # Enqueue the screenshot action and wait until the browser worker
                # signals completion.  *enqueue()* returns a Future that resolves
                # when the underlying Playwright operation has finished.
                cmd_future = await self.runtime.enqueue(chan, "screenshot", screenshot_path)
                await cmd_future  # ensures the file has been written
                if screenshot_path.exists() and screenshot_path.stat().st_size > 0:
                    await self.safe_send(
                        interaction,
                        "✔️ Screenshot captured:",
                        file=discord.File(screenshot_path, filename=actual_filename),
                    )
                else:
                    await self.safe_send(
                        interaction,
                        "❌ Failed to capture screenshot (empty or missing file).",
                    )
            except Exception as e:
                await self.safe_send(
                    interaction,
                    f"❌ Error sending screenshot: {e}",
                )
            finally:
                # Clean up temporary file
                if screenshot_path.exists():
                    try:
                        screenshot_path.unlink()
                    except Exception as e:
                        logger.error(f"Error deleting screenshot: {e}")

        # We should schedule this to run after the browser action completes
        # For now, we'll use asyncio.create_task, but a better implementation could
        # await the future returned by self._runner.enqueue
        asyncio.create_task(process_screenshot())
        # We already scheduled the browser action ourselves; tell decorator not to queue.
        return None

    @app_commands.command(name="status", description="Show browser status")
    async def status(self, interaction: discord.Interaction) -> None:
        """Show information about the browser instance for the current channel."""
        # Defer early so we don't hit the 3-second response window
        await safe_defer(interaction, thinking=True, ephemeral=True)
        # First check if browsers exist
        rows = self.runtime.status()

        # If we have active browsers, perform health check and attempt to heal
        if rows:
            try:
                # Trigger browser self-healing for each channel by executing a minimal health check operation
                for r in rows:
                    chan = r["channel"]
                    try:
                        # This will trigger the self-healing mechanism if browser is closed
                        # We use a 2-second timeout to avoid blocking if there are issues
                        await asyncio.wait_for(
                            self.runtime.enqueue(chan, "health_check"), timeout=2.0
                        )
                    except TimeoutError:
                        # If timeout occurs, continue with other channels
                        pass
                    except Exception:
                        # Ignore any other errors - we'll still show status with what we have
                        pass
            except Exception:
                pass  # Don't let health check errors prevent status display

            # Re-fetch status now that we've attempted healing
            rows = self.runtime.status()

        # Display status information
        if not rows:
            await self.safe_send(interaction, "No active browser workers.", ephemeral=True)
            return

        embed = discord.Embed(title="Browser Workers Status")
        for r in rows:
            status_emoji = "🟢 Idle" if r["idle"] else "🔵 Busy"
            embed.add_field(
                name=f"Channel ID: {r['channel']}",
                value=(f"📂 **Queue** {r['queue']}\n{status_emoji}\n"),
                inline=False,
            )
        await self.safe_send(interaction, embed=embed, ephemeral=True)

    @app_commands.command(name="close", description="Close the browser for this channel")
    @browser_mutating(queued=False, defer_ephemeral=False)
    @background_app_command(defer_ephemeral=False)
    async def close(self, interaction: discord.Interaction) -> None:
        """Close the browser instance for the current channel."""
        chan = interaction.channel_id
        assert chan is not None

        # First check if a browser exists for this channel
        rows = [r for r in self.runtime.status() if r["channel"] == chan]
        if not rows:
            await self.safe_send(
                interaction,
                "No browser running for this channel.",
                ephemeral=True,
            )
            return

        try:
            # Close the browser for this channel
            await self.runtime.close_channel(chan)
            await self.safe_send(interaction, "✅ Browser closed successfully.", ephemeral=True)
        except Exception as exc:
            await self.safe_send(
                interaction,
                f"❌ Error closing browser: {type(exc).__name__}: {exc}",
                ephemeral=True,
            )

    @app_commands.command(name="closeall", description="Close all browser instances (admin only)")
    @app_commands.default_permissions(administrator=True)
    @browser_mutating(queued=False, defer_ephemeral=True)
    @background_app_command(defer_ephemeral=True)
    async def closeall(self, interaction: discord.Interaction) -> None:
        """Close all browser instances across all channels (admin only)."""
        # The decorator already enforces permissions; no extra checks needed

        # Check if there are any active browsers
        rows = self.runtime.status()
        if not rows:
            await self.safe_send(
                interaction,
                "No active browser instances to close.",
                ephemeral=True,
            )
            return

        try:
            # Close all browsers
            await self.runtime.close_all()
            await self.safe_send(
                interaction,
                f"✅ Successfully closed {len(rows)} browser instance(s).",
                ephemeral=True,
            )
        except Exception as exc:
            await self.safe_send(
                interaction,
                f"❌ Error closing browsers: {type(exc).__name__}: {exc}",
                ephemeral=True,
            )


async def setup(bot: Bot) -> None:
    await bot.add_cog(Web(bot))
