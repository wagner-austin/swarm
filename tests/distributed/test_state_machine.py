"""
Test suite for state machine primitives used by distributed actors.
Comprehensive coverage of BaseStateMachine and WorkerState functionality.
"""

from enum import Enum
from typing import Any
from unittest.mock import Mock, call

import pytest

from swarm.distributed.monitoring.state import BaseStateMachine, WorkerState


class TestWorkerState:
    """Test WorkerState enum has all expected values."""

    def test_worker_state_values(self) -> None:
        """Verify all expected worker states are defined."""
        expected_states = {"IDLE", "WAITING", "BUSY", "ERROR", "SHUTDOWN"}
        actual_states = {state.name for state in WorkerState}
        assert actual_states == expected_states

    def test_worker_state_unique_values(self) -> None:
        """Verify each state has a unique auto-generated value."""
        values = [state.value for state in WorkerState]
        assert len(values) == len(set(values))  # All values are unique


class TestBaseStateMachine:
    """Test BaseStateMachine functionality with comprehensive scenarios."""

    def test_initial_state_setting(self) -> None:
        """Test state machine initializes with correct initial state."""
        sm = BaseStateMachine(WorkerState.IDLE)
        assert sm.get_state() == WorkerState.IDLE
        assert sm._last_state is None

    def test_state_transition_basic(self) -> None:
        """Test basic state transitions work correctly."""
        sm = BaseStateMachine(WorkerState.IDLE)
        sm.set_state(WorkerState.WAITING)

        assert sm.get_state() == WorkerState.WAITING
        assert sm._last_state == WorkerState.IDLE

    def test_state_transition_same_state_no_change(self) -> None:
        """Test setting same state doesn't trigger transition callback."""
        transition_callback = Mock()
        sm = BaseStateMachine(WorkerState.IDLE)
        sm.on_transition(transition_callback)

        # Set same state - should not trigger callback
        sm.set_state(WorkerState.IDLE)

        transition_callback.assert_not_called()
        assert sm.get_state() == WorkerState.IDLE
        assert sm._last_state is None

    def test_state_transition_with_callback(self) -> None:
        """Test transition callbacks are called correctly."""
        transition_callback = Mock()
        sm = BaseStateMachine(WorkerState.IDLE)
        sm.on_transition(transition_callback)

        sm.set_state(WorkerState.WAITING)

        transition_callback.assert_called_once_with(WorkerState.IDLE, WorkerState.WAITING)
        assert sm.get_state() == WorkerState.WAITING

    def test_multiple_state_transitions(self) -> None:
        """Test multiple sequential state transitions."""
        transition_callback = Mock()
        sm = BaseStateMachine(WorkerState.IDLE)
        sm.on_transition(transition_callback)

        transitions = [
            (WorkerState.IDLE, WorkerState.WAITING),
            (WorkerState.WAITING, WorkerState.BUSY),
            (WorkerState.BUSY, WorkerState.IDLE),
            (WorkerState.IDLE, WorkerState.ERROR),
            (WorkerState.ERROR, WorkerState.SHUTDOWN),
        ]

        for old_state, new_state in transitions:
            assert sm.get_state() == old_state
            sm.set_state(new_state)
            assert sm.get_state() == new_state
            assert sm._last_state == old_state

        # Verify all transitions were recorded
        assert transition_callback.call_count == len(transitions)
        expected_calls = [call(old, new) for old, new in transitions]
        transition_callback.assert_has_calls(expected_calls)

    def test_callback_replacement(self) -> None:
        """Test that new callback replaces old one."""
        first_callback = Mock()
        second_callback = Mock()

        sm = BaseStateMachine(WorkerState.IDLE)
        sm.on_transition(first_callback)
        sm.on_transition(second_callback)  # Should replace first

        sm.set_state(WorkerState.WAITING)

        first_callback.assert_not_called()
        second_callback.assert_called_once_with(WorkerState.IDLE, WorkerState.WAITING)

    def test_no_callback_set(self) -> None:
        """Test transitions work correctly when no callback is set."""
        sm = BaseStateMachine(WorkerState.IDLE)

        # Should not raise an exception
        sm.set_state(WorkerState.WAITING)
        assert sm.get_state() == WorkerState.WAITING

    def test_callback_exception_handling(self) -> None:
        """Test state transitions continue working even if callback raises exception."""

        def failing_callback(old_state: Enum, new_state: Enum) -> Any:
            raise ValueError("Callback failed")

        sm = BaseStateMachine(WorkerState.IDLE)
        sm.on_transition(failing_callback)

        # Should raise exception from callback and state should NOT change
        with pytest.raises(ValueError, match="Callback failed"):
            sm.set_state(WorkerState.WAITING)

        # State should NOT have changed due to callback failure
        assert sm.get_state() == WorkerState.IDLE
        assert sm._last_state is None

    def test_state_machine_with_different_enum(self) -> None:
        """Test state machine works with different enum types."""
        from enum import Enum, auto

        class CustomState(Enum):
            ALPHA = auto()
            BETA = auto()
            GAMMA = auto()

        sm = BaseStateMachine(CustomState.ALPHA)
        callback = Mock()
        sm.on_transition(callback)

        sm.set_state(CustomState.BETA)
        assert sm.get_state() == CustomState.BETA
        callback.assert_called_once_with(CustomState.ALPHA, CustomState.BETA)
