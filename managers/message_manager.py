#!/usr/bin/env python
"""
File: managers/message_manager.py
---------------------------------
Aggregated message manager for unified flow and plugin dispatch.
Processes incoming messages by checking for an active flow first,
and if none exists, dispatches to the appropriate plugin.
Returns a single string response.
"""

from typing import Any, TYPE_CHECKING, Optional
from dataclasses import replace as dc_replace
from core.utils.user_helpers import extract_user_id

if TYPE_CHECKING:
    from parsers.message_parser import ParsedMessage

import logging
from core.state import BotStateMachine
from core.api.flow_state_api import get_active_flow
from plugins.manager import dispatch_message

logger = logging.getLogger(__name__)

class MessageManager:
    """
    MessageManager - Aggregated facade for message processing.
    """
    def __init__(self, state_machine: Optional[BotStateMachine] = None) -> None:
        from core.state import BotStateMachine
        self.state_machine = state_machine if state_machine else BotStateMachine()

    async def process_message(
        self,
        parsed: "ParsedMessage",
        ctx: Any
    ) -> str:
        """
        Process the incoming message by first checking if the user has an active flow.
        If so, route the message to that flow and return its response.
        Otherwise, dispatch the message to the recognized plugin command.
        'ctx' is the Discord context (e.g., discord.Message).
        Returns a single string response (or an empty string if no response).
        Always returns an awaitable.
        """
        sender_id = extract_user_id(ctx)
        # 1) Check if the user is in an active flow
        active_flow = get_active_flow(sender_id)
        if active_flow:
            from managers.flow_manager import FlowManager
            fm = FlowManager()
            resp = fm.handle_flow_input(sender_id, parsed.body or "")
            return resp

        # 2) If not in a flow, check for a plugin command and dispatch it
        if parsed.command:
            resp = await dispatch_message(parsed, ctx, self.state_machine)
            return resp or ""

        # 3) Fallback: call chat plugin for idle chatter
        resp = await dispatch_message(
            dc_replace(parsed, command="chat", args=parsed.body or ""),
            ctx,
            self.state_machine
        )
        return resp or ""

# End of managers/message_manager.py