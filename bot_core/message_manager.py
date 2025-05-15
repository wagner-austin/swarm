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
from bot_core.utils.user_helpers import extract_user_id

if TYPE_CHECKING:
    from bot_core.parsers.message_parser import ParsedMessage

import logging
from bot_core.state import BotStateMachine
from bot_plugins.manager import dispatch_message

logger = logging.getLogger(__name__)

class MessageManager:
    """
    MessageManager - Aggregated facade for message processing.
    """
    def __init__(self, state_machine: Optional[BotStateMachine] = None, settings=None) -> None:
        from bot_core.state import BotStateMachine
        self.state_machine = state_machine if state_machine else BotStateMachine()
        self.settings = settings

    async def process_message(
        self,
        parsed: "ParsedMessage",
        ctx: Any
    ) -> str:
        """
        Process the incoming message by routing to plugin or chat plugin.
        'ctx' is the Discord context (e.g., discord.Message).
        Returns a single string response (or an empty string if no response).
        Always returns an awaitable.
        """
        sender_id = extract_user_id(ctx)
        # Route: if parsed.command, dispatch to plugin; else, route to chat plugin
        if getattr(parsed, "command", None):
            resp = await dispatch_message(parsed, ctx, self.state_machine)
            return resp or ""
        # Fallback: call chat plugin for idle chatter
        resp = await dispatch_message(
            dc_replace(parsed, command="chat", args=parsed.body or ""),
            ctx,
            self.state_machine
        )
        return resp or ""

# End of managers/message_manager.py