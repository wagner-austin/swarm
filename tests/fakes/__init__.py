"""
Test Fakes Module
=================

Provides fake implementations of external dependencies for testing.
These fakes simulate real behavior without requiring actual infrastructure,
enabling fast, reliable, and isolated unit tests.
"""

from .fake_broker import FakeBroker, FakeTimeoutBroker
from .fake_browser import FakeBrowserRuntime, FakeCircuitBreakerRuntime
from .fake_discord import (
    FakeBot,
    FakeChannel,
    FakeGuild,
    FakeInteraction,
    FakeMessage,
    FakeUser,
)
from .fake_history import FakeHistoryBackend
from .fake_history_v2 import FakeHistoryBackendV2
from .fake_redis import FakeRedisClient

__all__ = [
    # Browser fakes
    "FakeBrowserRuntime",
    "FakeCircuitBreakerRuntime",
    # Broker fakes
    "FakeBroker",
    "FakeTimeoutBroker",
    # Discord fakes
    "FakeBot",
    "FakeChannel",
    "FakeGuild",
    "FakeInteraction",
    "FakeMessage",
    "FakeUser",
    # History fakes
    "FakeHistoryBackend",
    "FakeHistoryBackendV2",
    # Redis fakes
    "FakeRedisClient",
]
