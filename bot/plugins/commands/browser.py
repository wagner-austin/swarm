import logging
from discord.ext import commands
from ..base import BaseCog
from bot.core.api.browser_service import BrowserService
from typing import Any

logger = logging.getLogger(__name__)

# Define command names as constants to ensure consistency
CMD_BROWSER = "browser"
CMD_START = "start"
CMD_OPEN = "open"
CMD_CLOSE = "close"
CMD_SCREENSHOT = "screenshot"
CMD_RESTART = "restart"
CMD_STATUS = "status"

# Using f-strings with the constants ensures consistency between code and docs
USAGE = f"""A browser automation toolkit.

Available subcommands:
  `{CMD_START} <url> [visible]` : Start browser, optionally navigate and make visible.
  `{CMD_OPEN} <url>`            : Navigate to a new URL.
  `{CMD_OPEN} <url> [visible]`  : Same as above but force window if 'visible' given.
  `{CMD_CLOSE}`                 : Close the browser session.
  `{CMD_SCREENSHOT} [filename]`  : Take a screenshot, optionally save to file.
  `{CMD_RESTART} [visible]`     : Drop session and relaunch; optional 'visible'.
  `{CMD_STATUS}`                : Check if the browser is running.
"""


class Browser(BaseCog):
    def __init__(self, bot: commands.Bot, browser_service: BrowserService) -> None:
        super().__init__(bot)
        self._browser: BrowserService = browser_service
        self.__cog_name__ = "Browser"  # Explicitly set cog name

    async def cog_command_error(
        self, ctx: commands.Context[Any], error: Exception
    ) -> None:
        """Handle command errors specific to this cog."""
        if isinstance(error, commands.CommandNotFound):
            # Extract the attempted command from the message
            message_content = ctx.message.content
            command_parts = message_content.split()

            if len(command_parts) >= 2 and command_parts[0].startswith("!"):
                attempted_cmd = command_parts[1]
                await ctx.send(
                    f"⚠️ Unknown browser command: `{attempted_cmd}`.\nUse `!browser` to see available commands."
                )
            else:
                await ctx.send(USAGE)
            return

        # For other errors, log them
        logger.error(f"[Browser] Command error: {error}", exc_info=True)
        await ctx.send(f"Error: {error}")

    async def cog_unload(
        self,
    ) -> None:  # Should be async as per discord.py Cog superclass
        if self._browser:
            logger.info("Browser cog unloading, stopping browser service...")
            await self._browser.stop()
            logger.info("Browser service stopped during cog unload.")

    @commands.group(name=CMD_BROWSER, invoke_without_command=True)
    @commands.is_owner()
    async def browser(self, ctx: commands.Context[Any]) -> None:
        """Control Chrome browser automation."""
        # If no subcommand is given, print usage
        await ctx.send(USAGE)

    @browser.command(name=CMD_START)  # type: ignore[arg-type]
    async def start(
        self,
        ctx: commands.Context[Any],
        url: str | None = None,
        visible: str | None = None,
    ) -> None:
        """Start a browser session.

        Usage: !browser start <url> [visible]
        - <url>: Optional URL to navigate to after starting
        - [visible]: If provided (any value), shows browser window instead of headless mode

        Example: !browser start https://discord.com visible
        """
        assert self._browser is not None, "Browser service is not initialized."

        # If visible is True, we want headless to be False (inverse relationship)
        headless = visible is None

        # Log whether we're running in headless mode or not
        logger.info(f"[Browser] Starting browser with headless={headless}")

        progress_message = await ctx.send("🟡 Launching Chrome …")
        try:
            msg = await self._browser.start(url=url, headless=headless)
            await progress_message.edit(content="🟢 " + msg)
        except ValueError as e:  # ← our new validation
            await progress_message.edit(content=f"🔴 {e}")
        except Exception as e:  # fallback
            # Log the exception for server-side records
            logger.exception(f"Browser start command failed: {e}")
            await progress_message.edit(content=f"🔴 Browser failed: {e}")
            # Re-raise to ensure it's caught by any global error handlers or logged by discord.py
            raise

    @browser.command(name=CMD_OPEN)  # type: ignore[arg-type]
    async def open(
        self,
        ctx: commands.Context[Any],
        url: str | None = None,
        visible: str | None = None,
    ) -> None:
        """Navigate to a URL in the active browser session.

        Usage: !browser open <url>
        - <url>: URL to navigate to

        Example: !browser open https://discord.com
        """
        assert self._browser is not None, "Browser service is not initialized."
        if not url:
            await ctx.send(USAGE)
            return
        # if the caller explicitly said "visible" remember that preference
        if visible is not None:
            self._browser.set_preferred_headless(False)

        msg = await self._browser.open(url)
        await ctx.send(msg)

    @browser.command(name=CMD_RESTART)  # type: ignore[arg-type]
    async def restart(
        self,
        ctx: commands.Context[Any],
        visible: str | None = None,
    ) -> None:
        """Force the session to restart.

        Usage: !browser restart [visible]
        """
        assert self._browser is not None, "Browser service is not initialized."

        headless = visible is None
        self._browser.set_preferred_headless(headless)

        await ctx.send(await self._browser.stop())
        msg = await self._browser.start(headless=headless)
        await ctx.send(msg)

    @browser.command(name=CMD_SCREENSHOT)  # type: ignore[arg-type]
    async def screenshot(self, ctx: commands.Context[Any]) -> None:
        """Take a screenshot of current browser view.

        Takes a screenshot of the currently open page and sends it in the chat.

        Usage: !browser screenshot
        """
        assert self._browser is not None, "Browser service is not initialized."

        # Get screenshot path and message
        filepath, msg = await self._browser.screenshot()

        if not filepath:  # No screenshot was taken
            await ctx.send(msg)
            return

        # Check if the file exists before trying to send it
        import os

        if os.path.exists(filepath):
            # Create a Discord file object from the screenshot path
            from discord import File

            screenshot_file = File(filepath, filename="screenshot.png")

            # Send both the file and the message
            try:
                await ctx.send(file=screenshot_file, content=msg)
            finally:
                # Attempt to delete the temporary screenshot file
                try:
                    os.remove(filepath)
                    logger.info(f"Temporary screenshot file deleted: {filepath}")
                except OSError as e:
                    logger.error(
                        f"Error deleting temporary screenshot file {filepath}: {e}"
                    )
        else:
            # In case the file doesn't exist (could happen in tests or if there's an error)
            # This case implies the screenshot was temporary and might have been cleaned up unexpectedly or never created.
            logger.warning(
                f"Screenshot file not found to send or delete: {filepath}. Message: {msg}"
            )
            await ctx.send(f"{msg} (File not available to send)")

    @browser.command(name=CMD_CLOSE)  # type: ignore[arg-type]
    async def close(self, ctx: commands.Context[Any]) -> None:
        """Close the current browser session.

        Shuts down the browser and cleans up resources.

        Usage: !browser close
        """
        assert self._browser is not None, "Browser service is not initialized."
        msg = (
            await self._browser.stop()
        )  # The method in BrowserService is still named stop()
        await ctx.send(msg)

    @browser.command(name=CMD_STATUS)  # type: ignore[arg-type]
    async def status(self, ctx: commands.Context[Any]) -> None:
        """Check the current browser session status.

        Reports if browser is running and the current URL if available.

        Usage: !browser status
        """
        assert self._browser is not None, "Browser service is not initialized."
        did_restart = await self._browser._ensure_alive()
        msg = self._browser.status()
        if did_restart:
            msg = "🔁 Auto-restarted dead session.\n" + msg
        await ctx.send(msg)


async def setup(bot: commands.Bot, browser_service_instance: BrowserService) -> None:
    """Setup function for the browser plugin.

    This is called by the bot when loading the extension.
    """
    await bot.add_cog(Browser(bot, browser_service_instance))


__all__ = ["Browser"]
