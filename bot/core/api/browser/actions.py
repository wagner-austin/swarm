from __future__ import annotations

import enum


class BrowserAction(str, enum.Enum):
    """Available browser actions that can be invoked via Commands.

    Each value corresponds to a method name in BrowserEngine.
    """

    GOTO = "goto"
    CLICK = "click"
    TYPE = "type"
    SCREENSHOT = "screenshot"
    WAIT_FOR_SELECTOR = "wait_for_selector"
    EVALUATE = "evaluate"
    CLOSE = "close"
    # Add more actions as needed
