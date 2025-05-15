#!/usr/bin/env python3
"""
plugins/commands/sora_explore_scraper.py - Sora Explore plugin command for managing Sora Explore sessions.
Handles start, stop, download, and status commands.
Usage:
  @bot sora explore start   -> Launch browser and open Sora Explore page.
  @bot sora explore stop    -> Close the browser.
  @bot sora explore download -> Download/capture from the first thumbnail.
  @bot sora explore status  -> Check current state.
"""

import logging
import asyncio
from bot_plugins.manager import plugin
from bot_core.permissions import OWNER
from bot_plugins.abstract import BasePlugin
from bot_plugins.commands.subcommand_dispatcher import handle_subcommands, PluginArgError
from bot_plugins.messages import INTERNAL_ERROR

# Import the updated Sora Explore API
try:
    from bot_core.api.sora_explore_api import (
        start_sora_explore_session,
        stop_sora_explore_session,
        download_sora_explore_session,
        get_sora_explore_session_status
    )
    _SORA_OK = True
except Exception as _exc:
    _SORA_OK = False
    _SORA_ERR = str(_exc)

logger = logging.getLogger(__name__)

@plugin(commands=["sora explore"], canonical="sora explore", required_role=OWNER)
class SoraExploreScraperPlugin(BasePlugin):
    """
    Sora Explore plugin command that calls the stable Sora Explore API 
    to manage a Sora Explore session (start, stop, download, status).

    Usage:
      @bot sora explore start   -> Launch browser and open Sora Explore page.
      @bot sora explore stop    -> Close the browser.
      @bot sora explore download -> Download/capture from the first thumbnail.
      @bot sora explore status  -> Check current state.
    """
    def __init__(self):
        super().__init__(
            "sora explore",
            help_text=(
                "Open a Chrome browser with a Sora Explore session; "
                "use 'download' to capture images or videos, "
                "and 'stop' to close the browser."
            )
        )
        self.subcommands = {
            "start":     self._sub_start,
            "stop":      self._sub_stop,
            "download":  lambda rest: self._sub_download(rest, self.ctx),
            "status":    self._sub_status,
        }

    async def run_command(
        self,
        args: str,
        ctx,
        state_machine,
        **kwargs
    ) -> str:
        self.ctx = ctx
        usage = (
            "Usage:\n"
            "  @bot sora explore start   -> Launch browser and open Sora Explore page.\n"
            "  @bot sora explore stop    -> Close the browser.\n"
            "  @bot sora explore download -> Download/capture from the first thumbnail.\n"
            "  @bot sora explore status  -> Check current state.\n"
        )
        try:
            result = handle_subcommands(
                args,
                subcommands=self.subcommands,
                usage_msg=usage,
                unknown_subcmd_msg="Unknown subcommand. See usage:\n" + usage
            )
            # If the result is a coroutine, await it.
            if asyncio.iscoroutine(result):
                result = await result

            # Ensure the result is a string.
            if not isinstance(result, str):
                logger.warning("Plugin 'sora explore' returned non-string or None. Converting to empty string.")
                result = ""
            return result
        except PluginArgError as pae:
            print(f"(Sora) Arg parsing error: {pae}")
            return str(pae)
        except Exception as e:
            print(f"(Sora) Unexpected error in run_command: {e}")
            return INTERNAL_ERROR

    def _sub_start(self, rest_args):
        if not _SORA_OK:
            return f"Sora-explore unavailable ({_SORA_ERR})."
        return start_sora_explore_session()

    def _sub_stop(self, rest_args):
        if not _SORA_OK:
            return f"Sora-explore unavailable ({_SORA_ERR})."
        return stop_sora_explore_session()

    def _sub_download(self, rest_args, ctx):
        """
        Returns the coroutine for the download command, so handle_subcommands can await it.
        """
        if not _SORA_OK:
            return f"Sora-explore unavailable ({_SORA_ERR})."
        if ctx is None:
            return "(Sora) Error: No Discord context provided for download."
        return download_sora_explore_session(ctx)

    def _sub_status(self, rest_args):
        if not _SORA_OK:
            return f"Sora-explore unavailable ({_SORA_ERR})."
        return get_sora_explore_session_status()


# End of plugins/commands/sora_explore_scraper.py