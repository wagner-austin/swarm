#!/usr/bin/env python
"""
plugins/commands/flow.py - Flow management plugin. Provides subcommands for listing, switching, pausing, and creating flows.
Usage:
  @bot flow list
  @bot flow switch <flow_name>
  @bot flow pause [<flow_name>]
  @bot flow create <flow_name>
"""

import logging
from typing import List
from plugins.manager import plugin
from core.permissions import ADMIN
from plugins.commands.subcommand_dispatcher import handle_subcommands, PluginArgError
from plugins.abstract import BasePlugin
from core.utils.user_helpers import extract_user_id
from core.api import flow_state_api
from plugins.messages import (
    FLOW_SWITCH_USAGE,
    FLOW_SWITCH_SUCCESS,
    FLOW_PAUSE_NO_ACTIVE,
    FLOW_PAUSE_SUCCESS,
    FLOW_CREATE_USAGE,
    FLOW_CREATE_SUCCESS,
    INTERNAL_ERROR
)

logger = logging.getLogger(__name__)

@plugin(commands=["flow"], canonical="flow", required_role=ADMIN)
class FlowPlugin(BasePlugin):
    """
    Flow management plugin.
    Provides subcommands to list, switch, pause, and create flows.
    Usage:
      @bot flow list
      @bot flow switch <flow_name>
      @bot flow pause [<flow_name>]
      @bot flow create <flow_name>
    """
    def __init__(self):
        super().__init__(
            "flow",
            help_text=(
                "See the different Flows active on account.")
        )
    
    async def run_command(
        self,
        args: str,
        ctx,
        state_machine,
        **kwargs
    ) -> str:
        usage = (
            "Usage: @bot flow <list|switch|pause|create> [args]\n"
            "Examples:\n"
            "  @bot flow list\n"
            "  @bot flow switch myFlow\n"
            "  @bot flow pause\n"
            "  @bot flow create newFlow"
        )
        subcommands = {
            "list":   lambda rest: self._sub_list(rest, extract_user_id(ctx)),
            "switch": lambda rest: self._sub_switch(rest, extract_user_id(ctx)),
            "pause":  lambda rest: self._sub_pause(rest, extract_user_id(ctx)),
            "create": lambda rest: self._sub_create(rest, extract_user_id(ctx)),
        }
        try:
            return handle_subcommands(
                args,
                subcommands=subcommands,
                usage_msg=usage,
                unknown_subcmd_msg="Unknown subcommand. See usage: " + usage
            )
        except PluginArgError as e:
            self.logger.error(f"Argument parsing error in flow command: {e}", exc_info=True)
            return str(e)
        except Exception as e:
            self.logger.error(f"Unexpected error in flow command: {e}", exc_info=True)
            return INTERNAL_ERROR

    def _sub_list(self, rest: List[str], sender: str) -> str:
        """List all flows for the user."""
        info = self._list_flows(sender)
        lines = [f"Active Flow: {info['active_flow'] or 'None'}"]
        for fname, details in info["flows"].items():
            lines.append(f"- {fname} (step={details['step']}, data_count={details['data_count']})")
        return "\n".join(lines)

    def _sub_switch(self, rest: List[str], sender: str) -> str:
        """Switch to a specified flow."""
        if not rest:
            return FLOW_SWITCH_USAGE
        flow_name = rest[0]
        flow_state_api.resume_flow(sender, flow_name)
        return FLOW_SWITCH_SUCCESS.format(flow_name=flow_name)

    def _sub_pause(self, rest: List[str], sender: str) -> str:
        """Pause the active flow or a specific flow name."""
        if rest:
            flow_name = rest[0]
        else:
            info = self._list_flows(sender)
            flow_name = info["active_flow"]
            if not flow_name:
                return FLOW_PAUSE_NO_ACTIVE
        flow_state_api.pause_flow(sender, flow_name)
        return FLOW_PAUSE_SUCCESS.format(flow_name=flow_name)

    def _sub_create(self, rest: List[str], sender: str) -> str:
        """Create and activate a new flow."""
        if not rest:
            return FLOW_CREATE_USAGE
        flow_name = rest[0]
        flow_state_api.start_flow(sender, flow_name)
        return FLOW_CREATE_SUCCESS.format(flow_name=flow_name)

    def _list_flows(self, phone: str) -> dict:
        """
        Retrieve a dictionary with "active_flow" and "flows" for the user.
        """
        return flow_state_api.list_flows(phone)

# End of plugins/commands/flow.py