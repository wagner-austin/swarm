"""
core/state.py - State management for the personal Discord bot.
Defines the BotState enum and BotStateMachine for managing bot lifecycle states.
"""

import enum


class BotState(enum.Enum):
    RUNNING = "RUNNING"
    SHUTTING_DOWN = "SHUTTING_DOWN"


class BotStateMachine:
    def __init__(self) -> None:
        self.current_state: BotState = BotState.RUNNING

    def shutdown(self) -> None:
        self.current_state = BotState.SHUTTING_DOWN

    def should_continue(self) -> bool:
        return self.current_state == BotState.RUNNING


__all__ = ["BotState", "BotStateMachine"]
