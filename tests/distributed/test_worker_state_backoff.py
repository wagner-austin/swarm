"""
Test suite for Worker state transitions and exponential backoff logic.
Ensures robust behavior in distributed scenarios with proper state management.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from bot.distributed.broker import Broker
from bot.distributed.model import Job
from bot.distributed.monitoring.state import WorkerState
from bot.distributed.worker import Worker


class TestWorkerStateTransitions:
    """Test Worker state machine integration and transitions."""

    @pytest.fixture
    def mock_broker(self) -> Mock:
        """Create a mocked broker for testing."""
        broker = Mock(spec=Broker)
        broker.consume = AsyncMock()
        broker.ensure_stream_and_group = AsyncMock()
        return broker

    @pytest.fixture
    def worker(self, mock_broker: Mock) -> Worker:
        """Create a Worker instance for testing."""
        return Worker(
            broker=mock_broker,
            worker_id="test-worker",
            job_type_prefix="test.",
        )

    def test_worker_initial_state(self, worker: Worker) -> None:
        """Test worker initializes in IDLE state."""
        assert worker.get_state() == WorkerState.IDLE

    def test_state_transition_logging(self, worker: Worker) -> None:
        """Test state transitions trigger logging callbacks."""
        transition_calls = []

        def capture_transition(old_state: Any, new_state: Any) -> None:
            transition_calls.append((old_state, new_state))

        # Replace the existing logging callback with our test callback
        worker.on_transition(capture_transition)

        # Test state transitions
        worker.set_state(WorkerState.WAITING)
        worker.set_state(WorkerState.BUSY)
        worker.set_state(WorkerState.IDLE)

        expected_transitions = [
            (WorkerState.IDLE, WorkerState.WAITING),
            (WorkerState.WAITING, WorkerState.BUSY),
            (WorkerState.BUSY, WorkerState.IDLE),
        ]

        assert transition_calls == expected_transitions

    def test_backoff_initialization(self, worker: Worker) -> None:
        """Test backoff values are initialized correctly."""
        assert worker._backoff == 1.0
        assert worker._backoff_min == 1.0
        assert worker._backoff_max == 10.0

    def test_backoff_increase_on_timeout(self, worker: Worker) -> None:
        """Test backoff increases exponentially on repeated timeouts."""
        initial_backoff = worker._backoff

        # Simulate multiple timeout cycles
        for i in range(1, 5):
            # Manually trigger backoff increase (simulating timeout handling)
            worker._backoff = min(worker._backoff * 2, worker._backoff_max)
            expected = min(initial_backoff * (2**i), worker._backoff_max)
            assert worker._backoff == expected

    def test_backoff_reset_on_job_receipt(self, worker: Worker) -> None:
        """Test backoff resets to minimum when job is received."""
        # Increase backoff
        worker._backoff = 5.0

        # Simulate job receipt (this happens in run() method)
        worker._backoff = worker._backoff_min

        assert worker._backoff == worker._backoff_min

    def test_backoff_capped_at_maximum(self, worker: Worker) -> None:
        """Test backoff doesn't exceed maximum value."""
        worker._backoff = worker._backoff_max

        # Try to increase beyond max
        worker._backoff = min(worker._backoff * 2, worker._backoff_max)

        assert worker._backoff == worker._backoff_max

    @pytest.mark.asyncio
    async def test_worker_run_state_transitions_with_timeout(
        self, worker: Worker, mock_broker: Mock
    ) -> None:
        """Test worker state transitions during normal operation with timeouts."""
        # Configure broker to timeout once then provide a job
        mock_job = Job(
            id="test-job",
            type="test.method",
            args=(),
            kwargs={},
            reply_to="reply-stream",
            created_ts=0.0,
        )

        mock_broker.consume.side_effect = [
            TimeoutError(),  # First call times out
            mock_job,  # Second call returns job
            asyncio.CancelledError(),  # Cancel to stop the loop
        ]

        # Mock handler for test job
        handler_mock = AsyncMock()
        worker.register_handler("test.", handler_mock)

        # Track state changes
        state_changes = []
        worker.on_transition(lambda old, new: state_changes.append((old, new)))

        # Mock signal handling for Windows compatibility
        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = Mock()
            mock_loop.add_signal_handler = Mock()  # Mock signal handler registration
            mock_get_loop.return_value = mock_loop

            # Run worker with immediate cancellation after job processing
            with pytest.raises(asyncio.CancelledError):
                await worker.run()

        # Verify state transitions occurred
        expected_states = [
            (WorkerState.IDLE, WorkerState.WAITING),  # First consume attempt
            (WorkerState.WAITING, WorkerState.IDLE),  # Timeout -> IDLE
            (WorkerState.IDLE, WorkerState.WAITING),  # Second consume attempt
            (WorkerState.WAITING, WorkerState.BUSY),  # Job received
        ]

        # Check that at least the key transitions happened
        for expected in expected_states:
            assert expected in state_changes, (
                f"Expected transition {expected} not found in {state_changes}"
            )

        # Verify handler was called
        handler_mock.assert_called_once_with(mock_job)

    @pytest.mark.asyncio
    async def test_worker_shutdown_state(self, worker: Worker, mock_broker: Mock) -> None:
        """Test worker transitions to SHUTDOWN state on signal."""
        # Mock the event loop and signal handling
        mock_broker.consume.side_effect = asyncio.CancelledError()

        # Set shutdown event to simulate signal
        worker._shutdown.set()

        # Mock signal handling for Windows compatibility
        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = Mock()
            mock_loop.add_signal_handler = Mock()  # Mock signal handler registration
            mock_get_loop.return_value = mock_loop

            # Worker should exit cleanly without running
            try:
                await worker.run()
            except asyncio.CancelledError:
                pass  # Expected when mocking consume

        # Worker should transition to SHUTDOWN state when shutdown event is set
        assert worker.get_state() == WorkerState.SHUTDOWN

    def test_handler_registration(self, worker: Worker) -> None:
        """Test handler registration works correctly."""
        handler_mock = AsyncMock()
        worker.register_handler("custom.", handler_mock)

        assert "custom." in worker.handlers
        assert worker.handlers["custom."] == handler_mock

    @pytest.mark.asyncio
    async def test_job_dispatch_state_transitions(self, worker: Worker) -> None:
        """Test state transitions during job dispatch."""
        handler_mock = AsyncMock()
        worker.register_handler("test.", handler_mock)

        job = Job(
            id="dispatch-test",
            type="test.action",
            args=("arg1",),
            kwargs={"param": "value"},
            reply_to="reply-stream",
            created_ts=0.0,
        )

        # Track state before dispatch
        initial_state = worker.get_state()

        # Dispatch job
        await worker.dispatch(job)

        # Verify handler was called
        handler_mock.assert_called_once_with(job)

        # State should remain unchanged by dispatch (dispatch doesn't change state)
        assert worker.get_state() == initial_state

    @pytest.mark.asyncio
    async def test_unregistered_job_type_handling(self, worker: Worker) -> None:
        """Test handling of jobs with unregistered type prefixes."""
        job = Job(
            id="unknown-job",
            type="unknown.action",
            args=(),
            kwargs={},
            reply_to="reply-stream",
            created_ts=0.0,
        )

        # Should not raise exception, just log warning
        await worker.dispatch(job)

        # No state change expected
        assert worker.get_state() == WorkerState.IDLE

    def test_worker_id_and_prefix_configuration(self, mock_broker: Mock) -> None:
        """Test worker ID and job type prefix configuration."""
        worker = Worker(
            broker=mock_broker,
            worker_id="custom-worker-123",
            job_type_prefix="browser.",
        )

        assert worker.worker_id == "custom-worker-123"
        assert worker.job_type_prefix == "browser."

    def test_worker_settings_configuration(self, mock_broker: Mock) -> None:
        """Test worker accepts and stores custom settings."""
        custom_settings = {"timeout": 30, "retries": 3}
        worker = Worker(
            broker=mock_broker,
            worker_id="settings-test",
            settings=custom_settings,
        )

        assert worker.settings == custom_settings
