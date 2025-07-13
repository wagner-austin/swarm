"""
Fake Message Broker for Testing
================================

Provides a fake implementation of the message broker that doesn't require
actual Redis infrastructure, enabling fast and reliable unit tests.
"""

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union


@dataclass
class Message:
    """Represents a message in the broker."""

    id: str
    stream: str
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
    ack_id: str | None = None


class FakeBroker:
    """
    Fake message broker that simulates Redis Streams behavior
    without requiring actual Redis infrastructure.
    """

    def __init__(
        self, should_fail: bool = False, fail_message: str = "Simulated broker failure"
    ) -> None:
        self.should_fail = should_fail
        self.fail_message = fail_message
        self.streams: dict[str, list[Message]] = {}
        self.pending_responses: dict[str, Any] = {}
        self.call_history: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.consumer_groups: dict[str, list[str]] = {}
        self._response_delay = 0.01  # Default response delay

    def _record_call(self, method_name: str, *args: Any, **kwargs: Any) -> None:
        """Record method calls for test verification."""
        self.call_history.append((method_name, args, kwargs))

    def set_response_delay(self, delay: float) -> None:
        """Set the simulated response delay."""
        self._response_delay = delay

    async def publish(self, stream: str, data: dict[str, Any]) -> str:
        """Publish a message to a stream."""
        self._record_call("publish", stream, data)

        if self.should_fail:
            raise RuntimeError(self.fail_message)

        await asyncio.sleep(0.001)

        message_id = str(uuid.uuid4())
        message = Message(id=message_id, stream=stream, data=data)

        if stream not in self.streams:
            self.streams[stream] = []

        self.streams[stream].append(message)
        return message_id

    async def publish_and_wait(
        self, request_stream: str, response_stream: str, data: dict[str, Any], timeout: float = 30.0
    ) -> dict[str, Any]:
        """Publish a message and wait for a response."""
        self._record_call(
            "publish_and_wait", request_stream, response_stream, data, timeout=timeout
        )

        if self.should_fail:
            raise RuntimeError(self.fail_message)

        # Generate correlation ID
        correlation_id = str(uuid.uuid4())
        data["correlation_id"] = correlation_id

        # Publish the request
        await self.publish(request_stream, data)

        # Wait for response (simulate async processing)
        await asyncio.sleep(self._response_delay)

        # Check if we have a pre-configured response
        if correlation_id in self.pending_responses:
            response = self.pending_responses.pop(correlation_id)
            if isinstance(response, Exception):
                raise response
            return response  # type: ignore[no-any-return]

        # Default response based on request type
        if "command" in data:
            command = data["command"]
            if command == "goto":
                return {"status": "success", "url": data.get("url", "https://example.com")}
            elif command == "screenshot":
                return {"status": "success", "data": "base64_encoded_screenshot_data"}
            elif command == "start":
                return {"status": "success", "worker_id": "fake-worker-123"}
            elif command == "status":
                return {
                    "status": "success",
                    "worker_id": "fake-worker-123",
                    "sessions": 1,
                    "uptime": 100.0,
                }

        # Generic success response
        return {"status": "success", "correlation_id": correlation_id}

    def set_response(self, correlation_id: str, response: dict[str, Any] | Exception) -> None:
        """Pre-configure a response for a specific correlation ID."""
        self.pending_responses[correlation_id] = response

    async def subscribe(
        self,
        streams: list[str],
        handler: Callable[[str, dict[str, Any]], Awaitable[None]],
        group: str | None = None,
        consumer: str | None = None,
    ) -> None:
        """Subscribe to streams (simplified for testing)."""
        self._record_call("subscribe", streams, group=group, consumer=consumer)

        if self.should_fail:
            raise RuntimeError(self.fail_message)

        await asyncio.sleep(0.001)

        # Record consumer group membership
        if group and consumer:
            if group not in self.consumer_groups:
                self.consumer_groups[group] = []
            if consumer not in self.consumer_groups[group]:
                self.consumer_groups[group].append(consumer)

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        """Acknowledge a message."""
        self._record_call("ack", stream, group, message_id)

        if self.should_fail:
            raise RuntimeError(self.fail_message)

        await asyncio.sleep(0.001)

    def get_stream_messages(self, stream: str) -> list[Message]:
        """Get all messages in a stream (test helper)."""
        return self.streams.get(stream, [])

    def get_message_count(self, stream: str) -> int:
        """Get the number of messages in a stream."""
        return len(self.streams.get(stream, []))

    def get_last_message(self, stream: str) -> Message | None:
        """Get the last message in a stream."""
        messages = self.streams.get(stream, [])
        return messages[-1] if messages else None

    def was_called(self, method_name: str) -> bool:
        """Check if a method was called during testing."""
        return any(call[0] == method_name for call in self.call_history)

    def get_call_args(self, method_name: str) -> tuple[tuple[Any, ...], dict[str, Any]] | None:
        """Get the arguments from the last call to a method."""
        for call in reversed(self.call_history):
            if call[0] == method_name:
                return call[1], call[2]
        return None

    def get_call_count(self, method_name: str) -> int:
        """Get the number of times a method was called."""
        return sum(1 for call in self.call_history if call[0] == method_name)

    def reset(self) -> None:
        """Clear all data and call history for fresh test state."""
        self.streams.clear()
        self.pending_responses.clear()
        self.call_history.clear()
        self.consumer_groups.clear()


class FakeTimeoutBroker(FakeBroker):
    """
    Fake broker that simulates timeout scenarios for testing.
    """

    def __init__(self, timeout_after: int = 1, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.timeout_after = timeout_after
        self.call_count = 0

    async def publish_and_wait(
        self, request_stream: str, response_stream: str, data: dict[str, Any], timeout: float = 30.0
    ) -> dict[str, Any]:
        """Simulate timeouts after a certain number of calls."""
        self.call_count += 1

        if self.call_count >= self.timeout_after:
            # Simulate timeout
            await asyncio.sleep(timeout + 0.1)
            raise TimeoutError(f"Timeout waiting for response after {timeout}s")

        return await super().publish_and_wait(request_stream, response_stream, data, timeout)
