import logging
import discord
from discord import app_commands
from discord.ext import commands  # For commands.Bot, commands.GroupCog
from bot.core.api.browser_service import BrowserService

__all__ = ["Browser"]

logger = logging.getLogger(__name__)

USAGE: str = "Automate an on-device Chrome browser."

# The group name is hard-wired below; no separate constants required.
_ENTRY_CMD = "browser"


class Browser(commands.GroupCog, group_name="browser", group_description=USAGE):
    def __init__(self, bot: commands.Bot, browser_service: BrowserService) -> None:
        super().__init__()
        self.bot = bot
        self._browser = browser_service

    async def cog_unload(
        self,
    ) -> None:  # Should be async as per discord.py Cog superclass
        if self._browser:
            logger.info("Browser cog unloading, stopping browser service...")
            await self._browser.stop()
            logger.info("Browser service stopped during cog unload.")

    # ------------------------------------------------------------------+
    # /browser start
    # ------------------------------------------------------------------+
    @app_commands.command(name="start", description="Launch Chrome, optionally at URL")
    @app_commands.describe(
        url="URL to open (optional)", visible="Show window instead of headless"
    )
    async def start(  # noqa: D401 (imperative mood)
        self,
        interaction: discord.Interaction,
        url: str | None = None,
        visible: bool = False,
    ) -> None:
        assert self._browser is not None, "Browser service is not initialized."
        await interaction.response.defer(thinking=True)
        msg = await self._browser.start(url=url, headless=not visible)
        await interaction.followup.send(msg)

    # ------------------------------------------------------------------+
    # /browser open
    # ------------------------------------------------------------------+
    @app_commands.command(
        name="open", description="Navigate to a URL in the active session"
    )
    @app_commands.describe(
        url="URL to navigate to",
        visible="Show window instead of headless for this and future actions",
    )
    async def open(
        self,
        interaction: discord.Interaction,
        url: str,
        visible: bool = False,
    ) -> None:
        if visible:  # remember GUI preference
            self._browser.set_preferred_headless(False)
        assert self._browser is not None, "Browser service is not initialized."
        await interaction.response.defer(thinking=True, ephemeral=True)
        msg = await self._browser.open(url)
        await interaction.followup.send(msg)

    # ------------------------------------------------------------------+
    # /browser restart
    # ------------------------------------------------------------------+
    @app_commands.command(name="restart", description="Restart the browser session")
    @app_commands.describe(visible="Show window instead of headless")
    async def restart(
        self,
        interaction: discord.Interaction,
        visible: bool = False,
    ) -> None:
        assert self._browser is not None, "Browser service is not initialized."
        await interaction.response.defer(thinking=True)
        headless_val = not visible
        await self._browser.stop()  # Stop the current session
        msg = await self._browser.start(headless=headless_val)  # Start a new one
        await interaction.followup.send(msg)

    # ------------------------------------------------------------------+
    # /browser screenshot
    # ------------------------------------------------------------------+
    @app_commands.command(
        name="screenshot", description="Take a screenshot of the current view"
    )
    async def screenshot(self, interaction: discord.Interaction) -> None:
        assert self._browser is not None, "Browser service is not initialized."
        await interaction.response.defer(thinking=True)

        filepath, msg = await self._browser.screenshot()

        if not filepath:
            await interaction.followup.send(msg)
            return

        import os  # Keep os import local to this method if only used here

        if os.path.exists(filepath):
            # discord.File needs to be imported if not already at top level
            # from discord import File # Assuming discord is imported as 'discord'
            screenshot_file = discord.File(filepath, filename="screenshot.png")
            try:
                await interaction.followup.send(content=msg, file=screenshot_file)
            finally:
                try:
                    os.remove(filepath)
                    logger.info(f"Temporary screenshot file deleted: {filepath}")
                except OSError as e:
                    logger.error(
                        f"Error deleting temporary screenshot file {filepath}: {e}"
                    )
        else:
            logger.warning(f"Screenshot file not found: {filepath}. Message: {msg}")
            await interaction.followup.send(f"{msg} (File not available to send)")

    # ------------------------------------------------------------------+
    # /browser close
    # ------------------------------------------------------------------+
    @app_commands.command(name="close", description="Close the browser session")
    async def close(self, interaction: discord.Interaction) -> None:
        assert self._browser is not None, "Browser service is not initialized."
        await interaction.response.defer(thinking=True, ephemeral=True)
        msg = await self._browser.stop()
        await interaction.followup.send(msg)

    # ------------------------------------------------------------------+
    # /browser status
    # ------------------------------------------------------------------+
    @app_commands.command(name="status", description="Report browser session status")
    async def status(self, interaction: discord.Interaction) -> None:
        assert self._browser is not None, "Browser service is not initialized."
        await interaction.response.defer(thinking=True, ephemeral=True)
        await self._browser._ensure_alive()
        await interaction.followup.send(self._browser.status())


async def setup(bot: commands.Bot, browser_service_instance: BrowserService) -> None:
    """Setup function for the browser plugin.

    This is called by the bot when loading the extension.
    """
    await bot.add_cog(Browser(bot, browser_service_instance))


__all__ = ["Browser"]
