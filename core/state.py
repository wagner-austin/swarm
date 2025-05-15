"""
core/state.py - State management for the Signal bot.
Defines the BotState enum and BotStateMachine for managing bot lifecycle states.
"""

import enum

class BotState(enum.Enum):
    RUNNING = "RUNNING"
    SHUTTING_DOWN = "SHUTTING_DOWN"

class BotStateMachine:
    def __init__(self) -> None:
        # Initial state is RUNNING.
        self.current_state: BotState = BotState.RUNNING

    def shutdown(self) -> None:
        """
        Transition the state to shutting down.
        """
        self.current_state = BotState.SHUTTING_DOWN

    def should_continue(self) -> bool:
        """
        Check if the bot should continue running.
        
        Returns:
            bool: True if state is RUNNING, else False.
        """
        return self.current_state == BotState.RUNNING

# End of core/state.py
