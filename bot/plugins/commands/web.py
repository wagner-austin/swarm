from __future__ import annotations

import logging
import asyncio
import tempfile
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.settings import settings

from bot.core.api.browser.runner import WebRunner
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
        channel_id = await self._ensure_channel_id(interaction)
        if channel_id is None:
            return

        try:
            processed_url = _normalise_url_or_raise(url)
        except InvalidURLError as e:
            await interaction.response.send_message(
                f"❌ Invalid URL: {e}. Please include a scheme (e.g., http:// or https://).",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)
        try:
            try:
                await self._runner.enqueue(channel_id, "goto", processed_url)
                await interaction.followup.send(f"🟢 Navigated to **{processed_url}**")
            except Exception as exc:
                await interaction.followup.send(
                    f"❌ Navigation failed: {exc}", ephemeral=True
                )
                return
        except asyncio.QueueFull:
            log.warning(f"WebRunner queue full for channel {channel_id}")
            await interaction.followup.send(
                "❌ The browser command queue is full. Please try again later.",
                ephemeral=True,
            )
        except Exception as e:
            log.error(
                f"Error in /web start for {processed_url} in channel {channel_id}: {e}",
                exc_info=True,
            )
            await interaction.followup.send(
                f"❌ An error occurred: {e}", ephemeral=True
            )

    @app_commands.command(
        name="click", description="Click an element matching the CSS selector."
    )
    @app_commands.describe(selector="The CSS selector of the element to click.")
    async def click(self, interaction: discord.Interaction, selector: str) -> None:
        """Clicks an element on the current page."""
        channel_id = await self._ensure_channel_id(interaction)
        if channel_id is None:
            return

        if not await self._check_mutation_allowed(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            try:
                await self._runner.enqueue(channel_id, "click", selector)
                await interaction.followup.send(f"✔️ Clicked `{selector}`")
            except Exception as exc:
                await interaction.followup.send(
                    f"❌ Click failed for `{selector}`: {exc}", ephemeral=True
                )
                return
        except asyncio.QueueFull:
            log.warning(f"WebRunner queue full for channel {channel_id}")
            await interaction.followup.send(
                "❌ The browser command queue is full. Please try again later.",
                ephemeral=True,
            )
        except Exception as e:
            log.error(
                f"Error in /web click for '{selector}' in channel {channel_id}: {e}",
                exc_info=True,
            )
            await interaction.followup.send(
                f"❌ An error occurred while clicking `{selector}`: {e}", ephemeral=True
            )

    @app_commands.command(name="fill", description="Fill a form field with text.")
    @app_commands.describe(
        selector="The CSS selector of the form field.", text="The text to fill."
    )
    async def fill(
        self, interaction: discord.Interaction, selector: str, text: str
    ) -> None:
        """Fills a form field on the current page."""
        channel_id = await self._ensure_channel_id(interaction)
        if channel_id is None:
            return

        if not await self._check_mutation_allowed(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            try:
                await self._runner.enqueue(channel_id, "fill", selector, text)
                await interaction.followup.send(f"✔️ Filled `{selector}`.")
            except Exception as exc:
                await interaction.followup.send(
                    f"❌ Fill failed for `{selector}`: {exc}", ephemeral=True
                )
                return
        except asyncio.QueueFull:
            log.warning(f"WebRunner queue full for channel {channel_id}")
            await interaction.followup.send(
                "❌ The browser command queue is full. Please try again later.",
                ephemeral=True,
            )
        except Exception as e:
            log.error(
                f"Error in /web fill for '{selector}' in channel {channel_id}: {e}",
                exc_info=True,
            )
            await interaction.followup.send(
                f"❌ An error occurred while filling `{selector}`: {e}", ephemeral=True
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
        channel_id = await self._ensure_channel_id(interaction)
        if channel_id is None:
            return

        if not await self._check_mutation_allowed(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        temp_file_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=f"_{file.filename}"
            ) as tmp:
                temp_file_path = Path(tmp.name)
                await file.save(temp_file_path)

            try:
                await self._runner.enqueue(
                    channel_id, "upload", selector, temp_file_path
                )
                await interaction.followup.send(
                    f"✔️ Initiated upload of `{file.filename}` to `{selector}`."
                )
            except Exception as exc:
                await interaction.followup.send(
                    f"❌ Upload failed for `{selector}`: {exc}", ephemeral=True
                )
                return
        except asyncio.QueueFull:
            log.warning(f"WebRunner queue full for channel {channel_id}")
            await interaction.followup.send(
                "❌ The browser command queue is full. Please try again later.",
                ephemeral=True,
            )
        except Exception as e:
            log.error(
                f"Error in /web upload for '{selector}' in channel {channel_id}: {e}",
                exc_info=True,
            )
            await interaction.followup.send(
                f"❌ An error occurred while uploading to `{selector}`: {e}",
                ephemeral=True,
            )
        finally:
            if temp_file_path and temp_file_path.exists():
                try:
                    temp_file_path.unlink()
                except Exception as e_unlink:
                    log.error(
                        f"Error deleting temp upload file {temp_file_path}: {e_unlink}"
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
        channel_id = await self._ensure_channel_id(interaction)
        if channel_id is None:
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            try:
                await self._runner.enqueue(
                    channel_id, "wait_for", selector, state=state
                )
                await interaction.followup.send(
                    f"✔️ Waited for `{selector}` to be `{state}`."
                )
            except Exception as exc:
                await interaction.followup.send(
                    f"❌ Wait failed for `{selector}` (state: {state}): {exc}",
                    ephemeral=True,
                )
                return
        except asyncio.QueueFull:
            log.warning(f"WebRunner queue full for channel {channel_id}")
            await interaction.followup.send(
                "❌ The browser command queue is full. Please try again later.",
                ephemeral=True,
            )
        except Exception as e:
            log.error(
                f"Error in /web wait for '{selector}' (state: {state}) in channel {channel_id}: {e}",
                exc_info=True,
            )
            await interaction.followup.send(
                f"❌ An error occurred while waiting for `{selector}`: {e}",
                ephemeral=True,
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
        channel_id = await self._ensure_channel_id(interaction)
        if channel_id is None:
            return

        await interaction.response.defer(thinking=True)

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

            try:
                await self._runner.enqueue(channel_id, "screenshot", screenshot_path)
            except Exception as exc:
                log.error(
                    f"Error during screenshot enqueue for channel {channel_id}: {exc}",
                    exc_info=True,
                )  # Keep log
                await interaction.followup.send(
                    f"❌ Screenshot command failed during execution: {exc}",
                    ephemeral=True,
                )
                return

            if screenshot_path.exists() and screenshot_path.stat().st_size > 0:
                discord_file = discord.File(screenshot_path, filename=actual_filename)
                await interaction.followup.send(file=discord_file)
            else:
                await interaction.followup.send(
                    "❌ Failed to take screenshot or screenshot is empty.",
                    ephemeral=True,
                )
        except asyncio.QueueFull:
            log.warning(f"WebRunner queue full for channel {channel_id}")
            await interaction.followup.send(
                "❌ The browser command queue is full. Please try again later.",
                ephemeral=True,
            )
        except Exception as e:
            log.error(
                f"Error in /web screenshot for channel {channel_id}: {e}", exc_info=True
            )
            await interaction.followup.send(
                f"❌ An error occurred while taking screenshot: {e}", ephemeral=True
            )
        finally:
            if screenshot_path and screenshot_path.exists():
                try:
                    screenshot_path.unlink()
                except Exception as e_unlink:
                    log.error(
                        f"Error deleting temp screenshot file {screenshot_path}: {e_unlink}"
                    )


async def setup(bot: Bot) -> None:
    await bot.add_cog(Web(bot))
