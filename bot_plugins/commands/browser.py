import os
import asyncio
import logging
from bot_plugins.manager import plugin
from bot_core.permissions import OWNER
from bot_plugins.abstract import BasePlugin
from bot_plugins.commands.subcommand_dispatcher import handle_subcommands
from bot_core.parsers.plugin_arg_parser import PluginArgError
from bot_core.api.browser_service import BrowserService, default_browser_service
from bot_core.settings import settings

logger = logging.getLogger(__name__)

USAGE = (
    "Usage:\n"
    "  @bot browser start [<url>]\n"
    "  @bot browser open <url>\n"
    "  @bot browser screenshot\n"
    "  @bot browser stop\n"
    "  @bot browser status"
)

@plugin(commands=["browser"], canonical="browser", required_role=OWNER)
class BrowserPlugin(BasePlugin):
    def __init__(self, browser_service: BrowserService | None = None):
        super().__init__("browser", help_text="Control a headless Chrome session")
        self.browser = browser_service or default_browser_service
        self.subcommands = {
            "start": self._sub_start,
            "open": self._sub_open,
            "screenshot": self._sub_screenshot,
            "stop": self._sub_stop,
            "status": self._sub_status,
        }

    async def run_command(self, args, ctx, state_machine, **kw):
        try:
            result = handle_subcommands(
                args,
                subcommands=self.subcommands,
                usage_msg=USAGE,
                unknown_subcmd_msg="Unknown subcommand.  See usage:\n" + USAGE,
                parse_mode="positional",
                default_subcommand=None
            )
            if asyncio.iscoroutine(result):
                result = await result
            if isinstance(result, str):
                return result
            logger.warning("Non-string result from subcommand: %r", result)
            return ""
        except PluginArgError as e:
            return str(e)
        except Exception as e:
            logger.exception("Unhandled error in browser plugin")
            return "An internal error occurred."

    async def _sub_start(self, rest):
        url = rest[0] if rest else None
        return await self.browser.start(url=url)

    async def _sub_open(self, rest):
        if not rest:
            return USAGE
        return await self.browser.open(rest[0])

    async def _sub_screenshot(self, rest):
        return await self.browser.screenshot()

    async def _sub_stop(self, rest):
        return await self.browser.stop()

    async def _sub_status(self, rest):
        return self.browser.status()
