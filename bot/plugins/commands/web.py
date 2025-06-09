from __future__ import annotations

import logging
import asyncio
import tempfile
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from typing import Any
from bot.core.settings import settings

from bot.core.api.browser.runner import WebRunner
from bot.core.browser_manager import browser_manager
from discord.ext.commands import Bot
from bot.utils.urls import validate_and_normalise_web_url
from bot.core.api.browser.exceptions import (
    InvalidURLError,
)


# --- validation helpers for this cog -------------------------------------
def _normalise_url_or_raise(raw: str) -> str:
    # Reject strings that do not explicitly specify a scheme
    # – this is what the test‐suite expects (“example.com” must be invalid).
    if "://" not in raw:
        raise InvalidURLError(f"'{raw}' does not look like an external web URL")

    try:
        return validate_and_normalise_web_url(raw)
    except ValueError as exc:
        raise InvalidURLError(str(exc)) from None


log = logging.getLogger(__name__)


class Web(commands.GroupCog, name="web", description="Control a web browser instance."):
    # ------------- helper ---------------------------------------------------
    async def _check_mutation_allowed(self, interaction: discord.Interaction) -> bool:
        """Return True if the caller may execute state‑changing actions."""
        if not settings.browser.read_only:
            return True
        # owners & admins bypass read‑only
        is_owner = await self.bot.is_owner(interaction.user)

        has_admin = False
        if isinstance(interaction.user, discord.Member):  # Check if user is a Member
            # Now it's safe to access guild_permissions
            if (
                interaction.user.guild_permissions
            ):  # Ensure guild_permissions is not None
                has_admin = interaction.user.guild_permissions.administrator

        if is_owner or has_admin:
            return True
        await interaction.response.send_message(
            "🔒 The browser is currently in **read‑only** mode; mutating actions are disabled.",
            ephemeral=True,
        )
        return False

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self._runner = WebRunner()

    # ------------------------------------------------------------------+
    #  shared helper – one place for uniform defer/queue/error handling  +
    # ------------------------------------------------------------------+
    async def _run(
        self,
        interaction: discord.Interaction,
        op: str,
        *op_args: Any,
        success: str,
        defer_ephemeral: bool = False,
    ) -> None:
        chan = await self._ensure_channel_id(interaction)
        if chan is None:
            return
        if defer_ephemeral:
            await interaction.response.defer(thinking=True, ephemeral=True)
        else:
            await interaction.response.defer(thinking=True)
        try:
            await self._runner.enqueue(chan, op, *op_args)
            await interaction.followup.send(success)
        except asyncio.QueueFull:
            await interaction.followup.send(
                "❌ The browser command queue is full. Please try again later.",
                ephemeral=True,
            )
        except Exception as exc:
            await interaction.followup.send(
                f"❌ {type(exc).__name__}: {exc}", ephemeral=True
            )

    async def _ensure_channel_id(self, interaction: discord.Interaction) -> int | None:
        if interaction.channel_id is None:
            await interaction.response.send_message(
                "This command must be used in a channel context where a channel ID is available.",
                ephemeral=True,
            )
            return None
        return interaction.channel_id

    @app_commands.command(name="start", description="Open a page at the given URL.")
    @app_commands.describe(url="The URL to navigate to.")
    async def start(self, interaction: discord.Interaction, url: str) -> None:
        """Opens a new browser page and navigates to the specified URL."""
        try:
            processed_url = _normalise_url_or_raise(url)
        except InvalidURLError as e:
            await interaction.response.send_message(
                f"❌ Invalid URL: {e}. Please include a scheme (e.g., http:// or https://).",
                ephemeral=True,
            )
            return

        await self._run(
            interaction,
            "goto",
            processed_url,
            success=f"🟢 Navigated to **{processed_url}**",
        )

    @app_commands.command(
        name="click", description="Click an element matching the CSS selector."
    )
    @app_commands.describe(selector="The CSS selector of the element to click.")
    async def click(self, interaction: discord.Interaction, selector: str) -> None:
        """Clicks an element on the current page."""
        if not await self._check_mutation_allowed(interaction):
            return

        await self._run(
            interaction,
            "click",
            selector,
            success=f"✔️ Clicked `{selector}`",
            defer_ephemeral=True,
        )

    @app_commands.command(name="fill", description="Fill a form field with text.")
    @app_commands.describe(
        selector="The CSS selector of the form field.", text="The text to fill."
    )
    async def fill(
        self, interaction: discord.Interaction, selector: str, text: str
    ) -> None:
        """Fills a form field on the current page."""
        if not await self._check_mutation_allowed(interaction):
            return

        await self._run(
            interaction,
            "fill",
            selector,
            text,
            success=f"✔️ Filled `{selector}`.",
            defer_ephemeral=True,
        )

    @app_commands.command(
        name="upload", description="Upload a file to an input element."
    )
    @app_commands.describe(
        selector="The CSS selector of the file input element.",
        file="The file to upload.",
    )
    async def upload(
        self, interaction: discord.Interaction, selector: str, file: discord.Attachment
    ) -> None:
        """Uploads a file to a file input on the current page."""
        if not await self._check_mutation_allowed(interaction):
            return

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / file.filename
            # Download the file to a temporary location
            await file.save(temp_path)

            await self._run(
                interaction,
                "upload",
                selector,
                temp_path,
                success=f"✔️ Uploaded `{file.filename}` to `{selector}`.",
                defer_ephemeral=True,
            )

    @app_commands.command(
        name="wait",
        description="Wait for an element to be visible, hidden, attached, or detached.",
    )
    @app_commands.describe(
        selector="The CSS selector of the element to wait for.",
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
    async def wait(
        self, interaction: discord.Interaction, selector: str, state: str = "visible"
    ) -> None:
        """Waits for an element on the current page to reach a certain state."""
        # Convert the state string to an enum value
        valid_states = ["attached", "detached", "visible", "hidden"]
        if state.lower() not in valid_states:
            await interaction.response.send_message(
                f"❌ Invalid state '{state}'. Valid options are: {', '.join(valid_states)}",
                ephemeral=True,
            )
            return

        await self._run(
            interaction,
            "wait_for",
            selector,
            state.lower(),
            success=f"✔️ Waited for `{selector}` to be `{state}`.",
        )

    @app_commands.command(
        name="screenshot", description="Take a screenshot of the current page."
    )
    @app_commands.describe(
        filename="Optional filename for the screenshot (e.g., page.png)."
    )
    async def screenshot(
        self, interaction: discord.Interaction, filename: str | None = None
    ) -> None:
        """Takes a screenshot of the current browser page."""
        actual_filename = filename or "screenshot.png"
        if not any(
            actual_filename.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg")
        ):
            actual_filename += ".png"

        screenshot_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=f"_{actual_filename.replace('/', '_').replace('\\', '_')}",
                delete=False,
            ) as tmp:
                screenshot_path = Path(tmp.name)

            # Use _run for the core logic
            await self._run(
                interaction,
                "screenshot",
                screenshot_path,
                success="",  # We'll handle sending the file ourselves
            )

            if screenshot_path.exists() and screenshot_path.stat().st_size > 0:
                discord_file = discord.File(screenshot_path, filename=actual_filename)
                await interaction.followup.send(file=discord_file)
            else:
                await interaction.followup.send(
                    "❌ Failed to take screenshot or screenshot is empty.",
                    ephemeral=True,
                )
        except Exception as e:
            # Main exceptions are already handled by _run
            log.error(f"Error handling screenshot file: {e}", exc_info=True)
        finally:
            if screenshot_path and screenshot_path.exists():
                try:
                    screenshot_path.unlink()
                except Exception as e_unlink:
                    log.error(
                        f"Error deleting temp screenshot file {screenshot_path}: {e_unlink}"
                    )

    @app_commands.command(
        name="status", description="Show browser status for this channel"
    )
    async def status(self, interaction: discord.Interaction) -> None:
        """Shows information about the browser instance for the current channel."""
        chan = await self._ensure_channel_id(interaction)
        if chan is None:
            return

        rows = [r for r in browser_manager.status_readout() if r["channel"] == chan]
        if not rows:
            await interaction.response.send_message(
                "No browser running for this channel.", ephemeral=True
            )
            return

        r = rows[0]
        await interaction.response.send_message(
            f"🗂️ Queue: {r['queue_len']} • "
            f"📄 Pages: {r['pages']} • "
            f"{'🟢 Idle' if r['idle'] else '🔵 Busy'}",
            ephemeral=True,
        )

    @app_commands.command(
        name="close", description="Close the browser for this channel"
    )
    async def close(self, interaction: discord.Interaction) -> None:
        """Closes the browser instance for the current channel."""
        chan = await self._ensure_channel_id(interaction)
        if chan is None:
            return

        if not await self._check_mutation_allowed(interaction):
            return

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


async def setup(bot: Bot) -> None:
    await bot.add_cog(Web(bot))
