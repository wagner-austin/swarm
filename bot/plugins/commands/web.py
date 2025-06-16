from __future__ import annotations

import logging
import asyncio
import tempfile
import time
from pathlib import Path
import functools
from typing import Any, Callable, TypeVar, Optional, Coroutine, ParamSpec, cast

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.settings import settings

from bot.browser import WebRunner
from bot.core.browser_manager import browser_manager
from discord.ext.commands import Bot
from bot.utils.urls import validate_and_normalise_web_url


# --- validation helpers for this cog -------------------------------------
log = logging.getLogger(__name__)

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
        if (
            isinstance(interaction.user, discord.Member)
            and interaction.user.guild_permissions
        ):
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
                await interaction.response.defer(thinking=True, ephemeral=True)
            else:
                # Regular spinner (e.g. /start, /open…)
                await interaction.response.defer(thinking=True)

            # Unpack operation details
            op, op_args, success_msg = result

            # If not queued, just return (the command handled everything internally)
            if not queued:
                return

            # Queue the operation
            try:
                await self._runner.enqueue(chan, op, *op_args)
                if success_msg:
                    await interaction.followup.send(success_msg)
            except asyncio.QueueFull:
                await interaction.followup.send(
                    "❌ The browser command queue is full. Please try again later.",
                    ephemeral=True,
                )
            except Exception as exc:
                await interaction.followup.send(
                    f"❌ {type(exc).__name__}: {exc}", ephemeral=True
                )
            return

        # Attach the guard at the very end so it wraps the *wrapper* that Discord sees
        if allow_mutation:
            return cast(
                Callable[
                    [Any, discord.Interaction, Any, Any], Coroutine[Any, Any, None]
                ],
                read_only_guard()(wrapper),
            )
        return wrapper

    return decorator


class Web(commands.GroupCog, name="web", description="Control a web browser instance."):
    def __init__(
        self,
        bot: Bot,
        *,
        runner: WebRunner | None = None,
    ) -> None:
        """Create a new *Web* cog.

        Parameters
        ----------
        bot:
            The hosting :class:`discord.ext.commands.Bot` instance.
        runner:
            Optionally provide a pre-configured :class:`WebRunner`.  Supplying a
            custom runner is primarily useful for **unit tests** or advanced
            callers that need fine-grained control over the browser lifecycle.
            If *None* (the default) a fresh :class:`WebRunner` is created – this
            preserves the original production behaviour.
        """

        self.bot = bot
        # Fallback to default behaviour if no runner supplied
        self._runner = runner or WebRunner()

    @app_commands.command(
        name="start", description="Start a browser session with an optional URL."
    )
    @app_commands.describe(url="Optional URL to navigate to.")
    @browser_command(allow_mutation=True)
    async def start(
        self, interaction: discord.Interaction, url: Optional[str] = None
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
    @browser_command(allow_mutation=True)
    async def open(
        self, interaction: discord.Interaction, url: str
    ) -> CommandResult | None:
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

    @app_commands.command(
        name="click", description="Click an element matching the CSS selector."
    )
    @app_commands.describe(selector="The CSS selector of the element to click.")
    @browser_command(allow_mutation=True, defer_ephemeral=True)
    async def click(
        self, interaction: discord.Interaction, selector: str
    ) -> CommandResult:
        """Clicks an element on the current page."""
        return ("click", (selector,), f"✔️ Clicked `{selector}`")

    @app_commands.command(name="fill", description="Fill a form field with text.")
    @app_commands.describe(
        selector="The CSS selector of the form field.", text="The text to fill."
    )
    @browser_command(allow_mutation=True, defer_ephemeral=True)
    async def fill(
        self, interaction: discord.Interaction, selector: str, text: str
    ) -> CommandResult:
        """Fills a form field on the current page."""
        return ("fill", (selector, text), f"✔️ Filled `{selector}`.")

    @app_commands.command(
        name="upload", description="Upload a file to an input element."
    )
    @app_commands.describe(
        selector="The CSS selector of the file input element.",
        attachment="The file to upload.",
    )
    @browser_command(allow_mutation=True, defer_ephemeral=True)
    async def upload(
        self,
        interaction: discord.Interaction,
        selector: str,
        attachment: discord.Attachment,
    ) -> CommandResult | None:
        """Uploads a file to a file input element on the page."""

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / attachment.filename
            # Download the file to a temporary location
            await attachment.save(temp_path)

            # Engine method is called **upload** – keep naming consistent
            return (
                "upload",
                (selector, temp_path),
                f"✔️ Uploaded `{attachment.filename}` to `{selector}`",
            )

    @app_commands.command(
        name="wait",
        description="Wait for an element to be visible, hidden, attached, or detached.",
    )
    @app_commands.describe(
        selector="The CSS selector of the element.",
        state="The state to wait for (default: visible).",
    )
    @app_commands.choices(
        state=[
            app_commands.Choice(name="Visible", value="visible"),
            app_commands.Choice(name="Hidden", value="hidden"),
            app_commands.Choice(name="Attached", value="attached"),
            app_commands.Choice(name="Detached", value="detached"),
        ]
    )
    @browser_command()
    async def wait(
        self, interaction: discord.Interaction, selector: str, state: str = "visible"
    ) -> CommandResult | None:
        """Waits for an element on the current page to reach a certain state."""
        # Playwright supports exactly these four states
        valid_states = ["visible", "hidden", "attached", "detached"]
        if state.lower() not in valid_states:
            await interaction.response.send_message(
                f"❌ Invalid state '{state}'. Valid options: {', '.join(valid_states)}",
                ephemeral=True,
            )
            return None

        return (
            "wait_for",
            (selector, state.lower()),
            f"✔️ Waited for `{selector}` to be `{state}`.",
        )

    # ------------------------------------------------------------------+
    # internal helpers (used by close / closeall and legacy paths)      |
    # ------------------------------------------------------------------+

    # Helper removed - now using @read_only_guard() decorator instead

    @app_commands.command(
        name="screenshot", description="Take a screenshot of the current page."
    )
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
            await interaction.response.defer(thinking=True, ephemeral=True)

        async def process_screenshot() -> None:
            try:
                # Enqueue the screenshot action and wait until the browser worker
                # signals completion.  *enqueue()* returns a Future that resolves
                # when the underlying Playwright operation has finished.
                cmd_future = await self._runner.enqueue(
                    chan, "screenshot", screenshot_path
                )
                await cmd_future  # ensures the file has been written
                if screenshot_path.exists() and screenshot_path.stat().st_size > 0:
                    await _safe_followup(
                        interaction,
                        content="✔️ Screenshot captured:",
                        file=discord.File(screenshot_path, filename=actual_filename),
                    )
                else:
                    await _safe_followup(
                        interaction,
                        "❌ Failed to capture screenshot (empty or missing file).",
                    )
            except Exception as e:
                await _safe_followup(
                    interaction,
                    f"❌ Error sending screenshot: {e}",
                )
            finally:
                # Clean up temporary file
                if screenshot_path.exists():
                    try:
                        screenshot_path.unlink()
                    except Exception as e:
                        log.error(f"Error deleting screenshot: {e}")

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
        rows = browser_manager.status_readout()

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
                            self._runner.enqueue(chan, "health_check"), timeout=2.0
                        )
                    except asyncio.TimeoutError:
                        # If timeout occurs, continue with other channels
                        pass
                    except Exception:
                        # Ignore any other errors - we'll still show status with what we have
                        pass
            except Exception:
                pass  # Don't let health check errors prevent status display

            # Re-fetch status now that we've attempted healing
            rows = browser_manager.status_readout()

        # Display status information
        if not rows:
            await interaction.response.send_message(
                "No active browser workers.", ephemeral=True
            )
            return

        embed = discord.Embed(title="Browser Workers Status")
        for r in rows:
            status_emoji = "🟢 Idle" if r["idle"] else "🔵 Busy"
            embed.add_field(
                name=f"Channel ID: {r['channel']}",
                value=(
                    f"📂 **Queue** {r['queue_len']}\n"
                    f"{status_emoji}\n"
                    f"📄 **Pages** {r['pages']}"
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="close", description="Close the browser for this channel"
    )
    @read_only_guard()  # replaces manual guard
    async def close(self, interaction: discord.Interaction) -> None:
        """Closes the browser instance for the current channel."""
        chan = interaction.channel_id
        assert chan is not None

        # First check if a browser exists for this channel
        rows = [r for r in browser_manager.status_readout() if r["channel"] == chan]
        if not rows:
            await interaction.response.send_message(
                "No browser running for this channel.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)

        try:
            # Close the browser for this channel
            await browser_manager.close_channel(chan)
            await interaction.followup.send(
                "✅ Browser closed successfully.", ephemeral=True
            )
        except Exception as exc:
            await interaction.followup.send(
                f"❌ Error closing browser: {type(exc).__name__}: {exc}", ephemeral=True
            )

    @app_commands.command(
        name="closeall", description="Close all browser instances (admin only)"
    )
    @app_commands.default_permissions(administrator=True)
    async def closeall(self, interaction: discord.Interaction) -> None:
        """Closes all browser instances across all channels (admin only)."""
        # The decorator already enforces permissions; no extra checks needed

        # Check if there are any active browsers
        rows = browser_manager.status_readout()
        if not rows:
            await interaction.response.send_message(
                "No active browser instances to close.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)

        try:
            # Close all browsers
            await browser_manager.close_all()
            await interaction.followup.send(
                f"✅ Successfully closed {len(rows)} browser instance(s).",
                ephemeral=True,
            )
        except Exception as exc:
            await interaction.followup.send(
                f"❌ Error closing browsers: {type(exc).__name__}: {exc}",
                ephemeral=True,
            )


# ---------------------------------------------------------------------------+
#  Local helpers                                                             +
# ---------------------------------------------------------------------------+


async def _safe_followup(
    interaction: discord.Interaction,
    content: str = "",
    *,
    file: discord.File | None = None,
) -> None:
    """Send a follow-up or gracefully fall back when the webhook has expired.

    Discord's type stubs expect *content* to be a ``str`` and *file* to be a
    concrete :class:`discord.File`.  We therefore branch on *file*'s presence
    to keep *mypy --strict* happy.
    """
    try:
        if file is None:
            await interaction.followup.send(content=content, ephemeral=True)
        else:
            await interaction.followup.send(
                content=content,
                file=file,
                ephemeral=True,
            )
    except discord.NotFound:
        # Webhook is gone – send to the channel instead (best effort)
        try:
            chan = interaction.channel
            if chan is not None:
                from typing import cast

                messageable = cast(discord.abc.Messageable, chan)
                if file is None:
                    await messageable.send(content=content)
                else:
                    # The original discord.File's underlying fp may have been closed
                    # during the failed webhook send. Re-create a fresh File object
                    # from the original file path to avoid "I/O operation on closed file".
                    try:
                        file_path = Path(file.fp.name)  # type: ignore[attr-defined]
                        fresh_file = discord.File(file_path, filename=file.filename)
                        await messageable.send(content=content, file=fresh_file)
                    except Exception:
                        # Fall back to message without attachment if file could not be re-read
                        await messageable.send(content=f"{content} (attachment failed)")
        except Exception as inner_exc:  # pragma: no cover – log fallback failure
            log.error(
                "Failed to send fallback screenshot message: %s",
                inner_exc,
                exc_info=True,
            )


async def setup(bot: Bot) -> None:
    await bot.add_cog(Web(bot))
