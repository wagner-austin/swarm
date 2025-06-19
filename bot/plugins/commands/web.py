from __future__ import annotations

import asyncio
import functools
import logging
import time
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, ParamSpec, TypeVar, cast

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import Bot

from bot.browser.runtime import BrowserRuntime
from bot.core.settings import settings
from bot.core.url_validation import validate_and_normalise_web_url
from bot.plugins.commands.decorators import background_app_command

# Import centralised Discord interaction helpers
from bot.utils.discord_interactions import safe_defer, safe_send

# --- validation helpers for this cog -------------------------------------
logger = logging.getLogger(__name__)

# Type parameters for decorator function signatures
P = ParamSpec("P")  # for parameters
T = TypeVar("T")  # for return value

# Command result type
CommandResult = tuple[str, tuple[Any, ...], str]


# --- Helper decorators for browser commands ---
def read_only_guard() -> Callable[[Callable[..., Any]], Any]:
    """Check decorator that allows commands to run only if not in read-only mode or if user is admin/owner."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if not settings.browser.read_only:
            return True  # Not in read-only mode, allow anyone

        # In read-only mode, check if user is owner or admin
        # We need to cast client to Bot (or commands.Bot) to access is_owner
        client = interaction.client
        is_owner = False
        if isinstance(client, commands.Bot):
            is_owner = await client.is_owner(interaction.user)

        has_admin = False
        if isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions:
            has_admin = interaction.user.guild_permissions.administrator

        if is_owner or has_admin:
            return True

        # User doesn't have permission, send error message
        await interaction.response.send_message(
            "🔒 The browser is currently in **read-only** mode; mutating actions are disabled.",
            ephemeral=True,
        )
        return False

    return app_commands.check(predicate)


def browser_command(
    queued: bool = True,
    allow_mutation: bool = False,
    defer_ephemeral: bool = False,
) -> Callable[[Callable[..., Coroutine[Any, Any, CommandResult | None]]], Any]:
    """Decorator that handles common boilerplate for browser commands.

    Args:
        queued: Whether the command should be queued through the WebRunner
        allow_mutation: Whether the command mutates browser state (will apply read_only check)
        defer_ephemeral: Whether the defer response should be ephemeral
    """

    def decorator(
        func: Callable[
            [Any, discord.Interaction, Any, Any],
            Coroutine[Any, Any, CommandResult | None],
        ],
    ) -> Callable[[Any, discord.Interaction, Any, Any], Coroutine[Any, Any, None]]:
        # The outermost function that Discord registers **must** carry the check,
        # otherwise the predicate is never evaluated.

        @functools.wraps(func)
        async def wrapper(
            self: Any, interaction: discord.Interaction, *args: Any, **kwargs: Any
        ) -> None:
            # 0️⃣ Run the inner handler **first** so it can fail fast
            #    (e.g. invalid-URL validation) *before* we show a spinner.
            result = await func(self, interaction, *args, **kwargs)

            # If the inner handler already produced a response we're done.
            if result is None:
                return

            # We now know it's a "real" browser action → safe to defer.
            chan = interaction.channel_id
            if chan is None:
                await interaction.response.send_message(
                    "This command must be used inside a text channel.", ephemeral=True
                )
                return

            if defer_ephemeral:
                # Ephemeral spinner (e.g. /click, /fill…)
                await safe_defer(interaction, thinking=True, ephemeral=True)
            else:
                # Regular spinner (e.g. /start, /open…)
                await safe_defer(interaction, thinking=True)

            # Unpack operation details
            op, op_args, success_msg = result

            # If not queued, just return (the command handled everything internally)
            if not queued:
                return

            # Queue the operation
            try:
                await self.runtime.enqueue(chan, op, *op_args)
                if success_msg:
                    await safe_send(interaction, success_msg)
            except asyncio.QueueFull:
                await safe_send(
                    interaction,
                    "❌ The browser command queue is full. Please try again later.",
                    ephemeral=True,
                )
            except Exception as exc:
                await safe_send(interaction, f"❌ {type(exc).__name__}: {exc}", ephemeral=True)
            return

        # Attach the guard at the very end so it wraps the *wrapper* that Discord sees
        if allow_mutation:
            return cast(
                Callable[[Any, discord.Interaction, Any, Any], Coroutine[Any, Any, None]],
                read_only_guard()(wrapper),
            )
        return wrapper

    return decorator


def browser_mutating(
    queued: bool = True,
    defer_ephemeral: bool = False,
) -> Callable[[Callable[..., Coroutine[Any, Any, CommandResult | None]]], Any]:
    """Convenience decorator for *mutating* browser commands.

    This is equivalent to ``@browser_command(allow_mutation=True)`` but avoids the
    possibility that a future contributor forgets to set ``allow_mutation=True`` and
    accidentally exposes state-changing functionality while the bot is running in
    read-only mode.
    """

    return browser_command(queued=queued, allow_mutation=True, defer_ephemeral=defer_ephemeral)


class Web(commands.GroupCog, name="web", description="Control a web browser instance."):
    def __init__(self, bot: Bot) -> None:  # noqa: D401  (imperative)
        super().__init__()
        self.bot = bot
        # Resolve DI singleton for browser runtime
        # The bot is always started with a DI container attached in discord_runner
        self.runtime: BrowserRuntime = bot.container.browser_runtime()  # type: ignore[attr-defined]

    @app_commands.command(name="start", description="Start a browser session with an optional URL.")
    @app_commands.describe(url="Optional URL to navigate to.")
    @browser_mutating()
    async def start(
        self, interaction: discord.Interaction, url: str | None = None
    ) -> CommandResult | None:
        """Opens a new browser page and optionally navigates to the specified URL."""
        if url:
            try:
                processed_url = validate_and_normalise_web_url(url)
                return (
                    "goto",
                    (processed_url,),
                    f"🟢 Started browser and navigated to **{processed_url}**",
                )
            except ValueError as e:
                await interaction.response.send_message(
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
            processed_url = validate_and_normalise_web_url(url)
            return ("goto", (processed_url,), f"🟢 Navigated to **{processed_url}**")
        except ValueError as e:
            await interaction.response.send_message(
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
        """Takes a screenshot of the current browser page."""
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
            await interaction.response.send_message(
                f"❌ File already exists: {actual_filename}", ephemeral=True
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
                    await safe_send(
                        interaction,
                        "✔️ Screenshot captured:",
                        file=discord.File(screenshot_path, filename=actual_filename),
                    )
                else:
                    await safe_send(
                        interaction,
                        "❌ Failed to capture screenshot (empty or missing file).",
                    )
            except Exception as e:
                await safe_send(
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
        """Shows information about the browser instance for the current channel."""
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
            await interaction.response.send_message("No active browser workers.", ephemeral=True)
            return

        embed = discord.Embed(title="Browser Workers Status")
        for r in rows:
            status_emoji = "🟢 Idle" if r["idle"] else "🔵 Busy"
            embed.add_field(
                name=f"Channel ID: {r['channel']}",
                value=(f"📂 **Queue** {r['queue']}\n{status_emoji}\n"),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="close", description="Close the browser for this channel")
    @browser_mutating(queued=False, defer_ephemeral=False)
    @background_app_command(defer_ephemeral=False)
    async def close(self, interaction: discord.Interaction) -> None:
        """Closes the browser instance for the current channel."""
        chan = interaction.channel_id
        assert chan is not None

        # First check if a browser exists for this channel
        rows = [r for r in self.runtime.status() if r["channel"] == chan]
        if not rows:
            await interaction.response.send_message(
                "No browser running for this channel.", ephemeral=True
            )
            return

        try:
            # Close the browser for this channel
            await self.runtime.close_channel(chan)
            await safe_send(interaction, "✅ Browser closed successfully.", ephemeral=True)
        except Exception as exc:
            await safe_send(
                interaction,
                f"❌ Error closing browser: {type(exc).__name__}: {exc}",
                ephemeral=True,
            )

    @app_commands.command(name="closeall", description="Close all browser instances (admin only)")
    @app_commands.default_permissions(administrator=True)
    @browser_mutating(queued=False, defer_ephemeral=True)
    @background_app_command(defer_ephemeral=True)
    async def closeall(self, interaction: discord.Interaction) -> None:
        """Closes all browser instances across all channels (admin only)."""
        # The decorator already enforces permissions; no extra checks needed

        # Check if there are any active browsers
        rows = self.runtime.status()
        if not rows:
            await interaction.response.send_message(
                "No active browser instances to close.", ephemeral=True
            )
            return

        try:
            # Close all browsers
            await self.runtime.close_all()
            await safe_send(
                interaction,
                f"✅ Successfully closed {len(rows)} browser instance(s).",
                ephemeral=True,
            )
        except Exception as exc:
            await safe_send(
                interaction,
                f"❌ Error closing browsers: {type(exc).__name__}: {exc}",
                ephemeral=True,
            )


async def setup(bot: Bot) -> None:
    await bot.add_cog(Web(bot))
