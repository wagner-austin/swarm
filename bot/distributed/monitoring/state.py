"""
State machine primitives for distributed actors (workers, orchestrators, etc).
Designed for extensibility and future-proofing.
"""

from enum import Enum, auto
from typing import Any, Callable, Optional


class WorkerState(Enum):
    IDLE = auto()
    WAITING = auto()
    BUSY = auto()
    ERROR = auto()
    SHUTDOWN = auto()


class BaseStateMachine:
    """
    A simple extensible state machine base class.
    Subclass and extend for richer actor state logic.
    """

    def __init__(self, initial_state: Enum) -> None:
        self.state: Enum = initial_state
        self._last_state: Enum | None = None
        self._on_transition: Callable[[Enum, Enum], Any] | None = None

    def set_state(self, new_state: Enum) -> None:
        if new_state != self.state:
            if self._on_transition:
                self._on_transition(self.state, new_state)
            self._last_state = self.state
            self.state = new_state

    def get_state(self) -> Enum:
        return self.state

    def on_transition(self, callback: Callable[[Enum, Enum], Any]) -> None:
        """Register a callback for state transitions: fn(old_state, new_state)."""
        self._on_transition = callback
