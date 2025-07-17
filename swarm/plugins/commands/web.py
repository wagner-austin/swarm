from __future__ import annotations

import asyncio
import logging
import time
from io import BytesIO
from typing import TYPE_CHECKING, Any, Callable

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import Bot

if TYPE_CHECKING:
    from swarm.core.containers import Container

# safe_send and validate_and_normalise_web_url are injected for testability
# Import centralised Discord interaction helpers
from swarm.distributed.celery_browser import CeleryBrowserRuntime
from swarm.frontends.discord.discord_interactions import safe_defer
from swarm.plugins.base_di import BaseDIClientCog
from swarm.plugins.commands.decorators import background_app_command

# --- validation helpers for this cog -------------------------------------
logger = logging.getLogger(__name__)


class Web(
    BaseDIClientCog, commands.GroupCog, name="web", description="Control a web browser instance."
):
    def __init__(
        self,
        *,
        discord_bot: Bot,
        browser: CeleryBrowserRuntime | None = None,
        safe_send_func: Callable[..., Any] | None = None,
        validate_url_func: Callable[[str], str] | None = None,
    ) -> None:
        BaseDIClientCog.__init__(self, discord_bot)
        self.discord_bot = discord_bot

        from swarm.frontends.discord.discord_interactions import safe_send as default_safe_send
        from swarm.utils.urls import validate_and_normalise_web_url as default_validate_url

        self.safe_send = safe_send_func if safe_send_func is not None else default_safe_send
        self.validate_url = (
            validate_url_func if validate_url_func is not None else default_validate_url
        )
        # Browser runtime injected via DI container if not supplied
        if browser is None:
            browser = CeleryBrowserRuntime()
        self.browser = browser

    async def _check_browser_health(self) -> bool:
        """Check if browser workers are healthy before executing commands."""
        try:
            # Get health status from Redis via DI container
            container = self.discord_bot.container  # type: ignore[attr-defined]
            redis_client = container.redis_client()

            health_data = await redis_client.hgetall("browser:health")
            if not health_data:
                # No health data available, assume healthy for backward compatibility
                return True

            is_degraded = health_data.get(b"is_degraded", b"false").decode() == "true"
            return not is_degraded

        except Exception as exc:
            logger.warning(f"Could not check browser health: {exc}")
            # Assume healthy if health check fails to avoid blocking commands
            return True

    @app_commands.command(name="start", description="Start a browser session with an optional URL.")
    @app_commands.describe(url="Optional URL to navigate to.")
    async def start(self, interaction: discord.Interaction, url: str | None = None) -> None:
        """Open a new browser page and optionally navigate to the specified URL."""
        await safe_defer(interaction, ephemeral=True, thinking=True)
        try:
            if url:
                processed_url = self.validate_url(url)
                # Start browser first, then navigate
                await self.browser.start()
                await self.browser.goto(processed_url)
                await self.safe_send(
                    interaction,
                    f"🟢 Started browser and navigated to **{processed_url}**",
                    ephemeral=True,
                )
            else:
                # Just start the browser without navigating anywhere specific
                await self.browser.start()
                await self.safe_send(
                    interaction, "🟢 Browser started successfully.", ephemeral=True
                )

        except ValueError as e:
            await self.safe_send(
                interaction,
                f"❌ Invalid URL: {e}. Please include a scheme (e.g., http:// or https://).",
                ephemeral=True,
            )
        except Exception as exc:
            # Consistent error handling using discord_bot exception hierarchy
            from swarm.browser.exceptions import BrowserError
            from swarm.core.exceptions import OperationTimeoutError, WorkerUnavailableError

            if isinstance(exc, WorkerUnavailableError):
                await self.safe_send(
                    interaction,
                    "⚠️ Browser workers temporarily unavailable. Try again in a moment.",
                    ephemeral=True,
                )
                logger.warning(f"Worker unavailable for start: {exc}")
            elif isinstance(exc, OperationTimeoutError):
                await self.safe_send(
                    interaction, "⏱️ Browser startup timed out. Please try again.", ephemeral=True
                )
                logger.warning(f"Start timeout: {exc}")
            elif isinstance(exc, BrowserError):
                await self.safe_send(
                    interaction, "🌐 Browser error occurred. Please try again.", ephemeral=True
                )
                logger.error(f"Browser error during start: {exc}")
            else:
                await self.safe_send(
                    interaction, f"❌ Failed to start browser: {exc}", ephemeral=True
                )
                logger.exception("Unexpected start failure")

    @app_commands.command(
        name="open", description="Navigate to the specified URL in the current browser."
    )
    @app_commands.describe(url="The URL to navigate to.")
    async def open(self, interaction: discord.Interaction, url: str) -> None:
        """Navigates the current browser to the specified URL."""
        await safe_defer(interaction, ephemeral=True, thinking=True)
        try:
            processed_url = self.validate_url(url)
            await self.browser.goto(processed_url)
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
        except Exception as exc:
            # Consistent error handling using discord_bot exception hierarchy
            from swarm.browser.exceptions import BrowserError
            from swarm.core.exceptions import OperationTimeoutError, WorkerUnavailableError

            if isinstance(exc, WorkerUnavailableError):
                await self.safe_send(
                    interaction,
                    "⚠️ Browser workers temporarily unavailable. Try again in a moment.",
                    ephemeral=True,
                )
                logger.warning(f"Worker unavailable for navigation: {exc}")
            elif isinstance(exc, OperationTimeoutError):
                await self.safe_send(
                    interaction,
                    "⏱️ Navigation timed out. The page might be loading slowly.",
                    ephemeral=True,
                )
                logger.warning(f"Navigation timeout: {exc}")
            elif isinstance(exc, BrowserError):
                await self.safe_send(
                    interaction,
                    "🌐 Browser error occurred. Please check the URL and try again.",
                    ephemeral=True,
                )
                logger.error(f"Browser error during navigation: {exc}")
            else:
                await self.safe_send(interaction, f"❌ Failed to navigate: {exc}", ephemeral=True)
                logger.exception("Unexpected navigation failure")

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
            actual_filename += ".png"  # Default to PNG

        timestamp = int(time.time())
        unique_name = f"{timestamp}_{actual_filename}"

        await safe_defer(interaction, thinking=True, ephemeral=False)

        # Check browser health before attempting screenshot
        if not await self._check_browser_health():
            await self.safe_send(
                interaction,
                "⚠️ Browser workers are currently unavailable. Please try again in a moment.",
                ephemeral=True,
            )
            return

        try:
            img_bytes: bytes = await self.browser.screenshot(
                filename=unique_name,
            )
            if len(img_bytes) > 7 << 20:  # > 7 MiB, resize
                try:
                    from swarm.utils.images import resize_png

                    img_bytes = await resize_png(img_bytes, max_dim=1920)
                except Exception as exc:
                    logger.warning("resize failed: %s", exc)
            fp = BytesIO(img_bytes)
            fp.seek(0)
            file = discord.File(fp, filename=actual_filename)
            await self.safe_send(interaction, content="🖼️ Screenshot taken.", file=file)
        except Exception as exc:
            # Consistent error handling using discord_bot exception hierarchy
            from swarm.browser.exceptions import BrowserError
            from swarm.core.exceptions import OperationTimeoutError, WorkerUnavailableError

            if isinstance(exc, WorkerUnavailableError):
                await self.safe_send(
                    interaction,
                    "⚠️ Browser workers temporarily unavailable. Try again in a moment.",
                    ephemeral=True,
                )
                logger.warning(f"Worker unavailable for screenshot: {exc}")
            elif isinstance(exc, OperationTimeoutError):
                await self.safe_send(
                    interaction,
                    "⏱️ Screenshot timed out. The page might be loading slowly.",
                    ephemeral=True,
                )
                logger.warning(f"Screenshot timeout: {exc}")
            elif isinstance(exc, BrowserError):
                await self.safe_send(
                    interaction,
                    "🌐 Browser error occurred. Check if the page loaded correctly.",
                    ephemeral=True,
                )
                logger.error(f"Browser error during screenshot: {exc}")
            else:
                # Fallback for unexpected errors
                await self.safe_send(interaction, f"❌ Screenshot failed: {exc}", ephemeral=True)
                logger.exception("Unexpected screenshot failure")

    @app_commands.command(name="status", description="Show browser status")
    async def status(self, interaction: discord.Interaction) -> None:
        """Show information about the browser instance for the current channel."""
        await safe_defer(interaction, thinking=True, ephemeral=True)
        try:
            status = await self.browser.status()
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
            # Consistent error handling using discord_bot exception hierarchy
            from swarm.browser.exceptions import BrowserError
            from swarm.core.exceptions import OperationTimeoutError, WorkerUnavailableError

            if isinstance(exc, WorkerUnavailableError):
                await self.safe_send(
                    interaction,
                    "⚠️ Browser workers temporarily unavailable. Try again in a moment.",
                    ephemeral=True,
                )
                logger.warning(f"Worker unavailable for status: {exc}")
            elif isinstance(exc, OperationTimeoutError):
                await self.safe_send(
                    interaction, "⏱️ Status check timed out. Workers may be busy.", ephemeral=True
                )
                logger.warning(f"Status timeout: {exc}")
            elif isinstance(exc, BrowserError):
                await self.safe_send(
                    interaction, "🌐 Browser error occurred while checking status.", ephemeral=True
                )
                logger.error(f"Browser error during status check: {exc}")
            else:
                await self.safe_send(
                    interaction, f"❌ Error fetching status: {exc}", ephemeral=True
                )
                logger.exception("Unexpected status failure")
            return


async def setup(discord_bot: Bot, container: Container | None = None) -> None:
    await discord_bot.add_cog(
        Web(
            discord_bot=discord_bot,
            browser=CeleryBrowserRuntime(),
        )
    )
