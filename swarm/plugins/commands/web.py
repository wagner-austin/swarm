from __future__ import annotations

import asyncio
import logging
import time
from io import BytesIO
from typing import TYPE_CHECKING, Callable

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import Bot

if TYPE_CHECKING:
    from swarm.core.containers import Container

# safe_send and validate_and_normalise_web_url are injected for testability
# Import centralised Discord interaction helpers
from swarm.browser.types import BrowserStatusAggregate
from swarm.distributed.celery_browser import CeleryBrowserRuntime
from swarm.frontends.discord.discord_interactions import safe_defer
from swarm.frontends.discord.types import SafeSendFunc
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
        safe_send_func: SafeSendFunc | None = None,
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

    def _session_id_for_interaction(self, interaction: discord.Interaction) -> str:
        """Derive a stable session id for this Discord context (guild/channel).

        Uses guild_id if present, otherwise 'dm'. Always includes channel_id.
        """
        guild_part = str(interaction.guild_id) if interaction.guild_id is not None else "dm"
        channel_part = str(interaction.channel_id)
        return f"discord:{guild_part}:{channel_part}"

    async def _check_browser_health(self) -> bool:
        """Check if browser workers are healthy before executing commands.

        Uses fail-safe logic: only returns True if workers are confirmed healthy.
        Returns False (degraded) if no health data, errors, or workers are down.
        """
        try:
            # Get health monitor cog
            from swarm.plugins.monitor.browser_health import BrowserHealthMonitor

            monitor = self.discord_bot.get_cog("BrowserHealthMonitor")
            if not isinstance(monitor, BrowserHealthMonitor):
                # Fallback to Redis-based health status if monitor is unavailable
                try:
                    redis_client = self.container.redis_client()
                except Exception:
                    logger.warning("Health monitor not available, treating as degraded")
                    return False

                try:
                    raw = await redis_client.hgetall("browser:health")
                except Exception as exc:
                    logger.warning("Health check via Redis failed: %s", exc)
                    return False

                if not raw:
                    return False

                # Normalize bytes -> str
                def _to_str(v: object) -> str:
                    if isinstance(v, bytes):
                        try:
                            return v.decode()
                        except Exception:
                            return ""
                    return str(v)

                is_degraded_str = _to_str(
                    raw.get(b"is_degraded") if isinstance(raw, dict) else None
                )
                is_degraded_norm = is_degraded_str.strip().lower()
                is_degraded = is_degraded_norm in {"1", "true", "yes"}
                return not is_degraded

            status = monitor.get_health_status()  # Synchronous - no await needed

            # Check for errors in health status
            if "error" in status:
                logger.warning(f"Health check error: {status['error']}, treating as degraded")
                return False

            # FAIL-SAFE: Only healthy if explicitly not degraded
            is_healthy = not status.get("is_degraded", True)

            if not is_healthy:
                logger.debug(
                    f"Browser pool degraded: {status.get('healthy_workers', 0)}/{status.get('min_required', 1)} workers"
                )

            return is_healthy

        except Exception as exc:
            # FAIL-SAFE: Health check errors = degraded
            logger.error(f"Health check failed: {exc}", exc_info=True)
            return False

    @app_commands.command(name="start", description="Start a browser session with an optional URL.")
    @app_commands.describe(url="Optional URL to navigate to.")
    async def start(self, interaction: discord.Interaction, url: str | None = None) -> None:
        """Open a new browser page and optionally navigate to the specified URL."""
        await safe_defer(interaction, ephemeral=True, thinking=True)
        try:
            session_id = self._session_id_for_interaction(interaction)
            if url:
                processed_url = self.validate_url(url)
                # Start browser first, then navigate
                await self.browser.start(session_id=session_id)
                await self.browser.goto(processed_url, session_id=session_id)
                await self.safe_send(
                    interaction,
                    f"🟢 Started browser and navigated to **{processed_url}**",
                    ephemeral=True,
                )
            else:
                # Just start the browser without navigating anywhere specific
                await self.browser.start(session_id=session_id)
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
            session_id = self._session_id_for_interaction(interaction)
            await self.browser.goto(processed_url, session_id=session_id)
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
            session_id = self._session_id_for_interaction(interaction)
            img_bytes: bytes = await self.browser.screenshot(
                filename=unique_name,
                session_id=session_id,
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
            session_id = self._session_id_for_interaction(interaction)
            status: BrowserStatusAggregate = await self.browser.status(session_id=session_id)
            # Format status for display
            if not status:
                await self.safe_send(interaction, "No active browser workers.", ephemeral=True)
                return
            embed = discord.Embed(
                title="Browser Worker Status",
                description="Status for this channel",
                colour=discord.Colour.blurple(),
            )

            # Active sessions summary
            active_sessions = 0
            if isinstance(status, dict):
                val = status.get("active_sessions", 0)
                try:
                    active_sessions = int(val) if isinstance(val, int | str) else 0
                except Exception:
                    active_sessions = 0
            embed.add_field(name="Active Sessions", value=str(active_sessions), inline=False)

            # Per-session details
            sessions = status.get("sessions") if isinstance(status, dict) else None
            if isinstance(sessions, list) and sessions:
                for idx, sess in enumerate(sessions, start=1):
                    if not isinstance(sess, dict):
                        # If the payload is not a dict, render a safe string
                        embed.add_field(name=f"Session {idx}", value=str(sess), inline=False)
                        continue

                    s_id = sess.get("session_id") or "unknown"
                    s_worker = sess.get("worker_id") or "unknown"
                    s_state = sess.get("status") or "unknown"
                    s_url = sess.get("url") or "N/A"

                    value = (
                        f"Session ID: {s_id}\nWorker: {s_worker}\nStatus: {s_state}\nURL: {s_url}"
                    )
                    embed.add_field(name=f"Session {idx}", value=value, inline=False)
            else:
                embed.add_field(
                    name="Sessions", value="No session details available.", inline=False
                )
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
