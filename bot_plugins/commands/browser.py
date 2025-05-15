import os
import asyncio
import logging
from bot_plugins.manager import plugin
from bot_core.permissions import OWNER
from bot_plugins.abstract import BasePlugin
from bot_plugins.commands.subcommand_dispatcher import handle_subcommands
from bot_core.parsers.plugin_arg_parser import PluginArgError
from bot_core.api import browser_session_api as bs_api
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
    def __init__(self):
        super().__init__("browser", help_text="Control a headless Chrome session")
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

    def _sub_start(self, rest):
        url = rest[0] if rest else None
        msg = bs_api.start_browser_session()
        if url and bs_api._session:
            # schedule navigation as coroutine
            async def nav():
                await bs_api._session.navigate(url)
            asyncio.create_task(nav())
        return msg

    def _sub_open(self, rest):
        if not rest:
            return USAGE
        url = rest[0]
        if not bs_api._session:
            return "No active session. Use 'start' first."
        asyncio.create_task(bs_api._session.navigate(url))
        return "Navigating…"

    def _sub_screenshot(self, rest):
        if not bs_api._session:
            return "No active session. Use 'start' first."
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"screenshot_{ts}.png"
        fpath = settings.browser_download_dir or "./browser_downloads"
        full_path = os.path.join(fpath, fname)
        path = bs_api._session.screenshot(full_path)
        return f"Screenshot saved to {path}"

    def _sub_stop(self, rest):
        return bs_api.stop_browser_session()

    def _sub_status(self, rest):
        return bs_api.get_browser_session_status()
