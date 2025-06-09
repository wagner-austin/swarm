import logging
from bot.plugins.base_di import BaseDIClientCog  # <- move here
import discord
from discord import app_commands
from discord.ext import commands

from bot.core.api.browser.session_manager import SessionManager
from bot.core.api.browser.actions import BrowserActions
from bot.core.api.browser.exceptions import InvalidURLError, NavigationError

__all__ = ["Browser"]

logger = logging.getLogger(__name__)

USAGE: str = "Automate an on-device Chrome browser."

# The group name is hard-wired below; no separate constants required.
_ENTRY_CMD = "browser"


# --------------------------------------------------
class Browser(
    BaseDIClientCog, commands.GroupCog, group_name="browser", group_description=USAGE
):  # noqa: E501
    def __init__(self, bot: commands.Bot) -> None:
        commands.GroupCog.__init__(self)  # GroupCog init
        BaseDIClientCog.__init__(self, bot)  # DI resolution

        self._session_manager: SessionManager = self.container.session_manager()
        self._browser_actions: BrowserActions = self.container.browser_actions()

    async def cog_unload(
        self,
    ) -> None:  # Should be async as per discord.py Cog superclass
        if self._session_manager:
            logger.info("Browser cog unloading, stopping browser session manager...")
            await self._session_manager.stop()
            logger.info("Browser session manager stopped during cog unload.")

    # ------------------------------------------------------------------+
    # /browser start
    # ------------------------------------------------------------------+
    @app_commands.command(name="start", description="Launch Chrome, optionally at URL")
    @app_commands.describe(
        url="URL to open (optional)",
        visible="Show window instead of headless for this launch",
    )
    async def start(  # noqa: D401 (imperative mood)
        self,
        interaction: discord.Interaction,
        url: str | None = None,
        visible: bool = False,
    ) -> None:
        assert self._session_manager is not None, (
            "Browser session manager is not initialized."
        )
        await interaction.response.defer(thinking=True)
        start_msg = await self._session_manager.start(headless=not visible)
        final_msg = start_msg
        if url:
            try:
                logger.info(
                    f"Initial start message: {start_msg}. Now opening URL: {url}"
                )
                open_msg = await self._browser_actions.open(url)
                final_msg = f"{start_msg}\n{open_msg}".strip()
            except (InvalidURLError, NavigationError) as e:
                logger.error(
                    f"Error opening URL '{url}' after start: {e}", exc_info=True
                )
                await interaction.followup.send(
                    f"{start_msg}\n⚠️ Error opening URL: {e}"
                )
                return
            except Exception as e:  # Catch any other exception from open
                logger.error(
                    f"Unexpected error opening URL '{url}' after start: {e}",
                    exc_info=True,
                )
                await interaction.followup.send(
                    f"{start_msg}\n⚠️ Unexpected error opening URL: {e}"
                )
                return
        await interaction.followup.send(final_msg)

    # ------------------------------------------------------------------+
    # /browser open
    # ------------------------------------------------------------------+
    @app_commands.command(
        name="open", description="Navigate to a URL in the active session"
    )
    @app_commands.describe(url="URL to navigate to")
    async def open(
        self,
        interaction: discord.Interaction,
        url: str,
    ) -> None:
        assert self._browser_actions is not None, "Browser actions are not initialized."
        # Note: The 'visible' parameter's previous effect of setting a persistent headless preference
        # via `set_preferred_headless` is removed as SessionManager doesn't have this method in PR1 scope.
        # If the session wasn't alive, _ensure_alive_and_ready would have started it.
        # Visibility is determined by how the session was last started.
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            open_msg = await self._browser_actions.open(url)
        except InvalidURLError as e:
            await interaction.followup.send(content=str(e))
            return
        except NavigationError as e:
            await interaction.followup.send(content=f"⚠️ Navigation failed: {e}")
            return
        except Exception as e:  # Catch any other unexpected error from open
            logger.error(f"Unexpected error during open: {e}", exc_info=True)
            await interaction.followup.send(
                content=f"⚙️ An unexpected error occurred: {e}"
            )
            return

        await interaction.followup.send(content=open_msg)

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
        assert self._session_manager is not None, (
            "Browser session manager is not initialized."
        )
        await interaction.response.defer(thinking=True)
        headless_val = not visible
        await self._session_manager.stop()  # Stop the current session
        msg = await self._session_manager.start(
            headless=headless_val
        )  # Start a new one
        await interaction.followup.send(msg)

    # ------------------------------------------------------------------+
    # /browser screenshot
    # ------------------------------------------------------------------+
    @app_commands.command(
        name="screenshot", description="Take a screenshot of the current view"
    )
    async def screenshot(self, interaction: discord.Interaction) -> None:
        assert self._browser_actions is not None, "Browser actions are not initialized."
        await interaction.response.defer(thinking=True)

        filepath, msg = await self._browser_actions.screenshot()

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
        assert self._session_manager is not None, (
            "Browser session manager is not initialized."
        )
        await interaction.response.defer(thinking=True, ephemeral=True)
        msg = await self._session_manager.stop()
        await interaction.followup.send(msg)

    # ------------------------------------------------------------------+
    # /browser status
    # ------------------------------------------------------------------+
    @app_commands.command(name="status", description="Report browser session status")
    async def status(self, interaction: discord.Interaction) -> None:
        assert self._session_manager is not None, (
            "Browser session manager is not initialized."
        )
        await interaction.response.defer(thinking=True, ephemeral=True)

        # Only auto-restart if a session was ever started and then died.
        if self._session_manager.has_session():
            try:
                await self._session_manager._ensure_alive()
            except Exception:
                # If the window was killed, _ensure_alive() may throw or fail;
                # we swallow it so status() can report “dead” or “restarted” state.
                pass

        # Now report status; if no session exists, this will say “not running”
        try:
            status_msg = self._session_manager.status()
        except Exception as e:
            logger.error(f"Error getting browser status: {e}", exc_info=True)
            status_msg = f"⚠️ Error retrieving browser status: {e}"

        await interaction.followup.send(status_msg)


async def setup(bot: commands.Bot) -> None:
    """Setup function for the browser plugin.

    This is called by the bot when loading the extension.
    Dependencies are injected into the cog via the DI container.
    """
    await bot.add_cog(Browser(bot))


__all__ = ["Browser"]
