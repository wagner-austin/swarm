"""
Fake Discord Objects for Testing
=================================

Provides fake implementations of Discord.py objects that don't require
actual Discord connections, enabling fast and reliable unit tests.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from unittest.mock import AsyncMock


@dataclass
class FakeUser:
    """Fake Discord User object."""

    id: int
    name: str
    discriminator: str = "0000"
    bot: bool = False
    system: bool = False

    def __str__(self) -> str:
        return f"{self.name}#{self.discriminator}"

    @property
    def mention(self) -> str:
        return f"<@{self.id}>"


@dataclass
class FakeChannel:
    """Fake Discord Channel object."""

    id: int
    name: str
    type: int = 0  # Text channel

    @property
    def mention(self) -> str:
        return f"<#{self.id}>"


@dataclass
class FakeGuild:
    """Fake Discord Guild object."""

    id: int
    name: str
    owner_id: int
    member_count: int = 1


@dataclass
class FakeMessage:
    """Fake Discord Message object."""

    id: int
    content: str
    author: FakeUser
    channel: FakeChannel
    guild: FakeGuild | None = None
    embeds: list[Any] = field(default_factory=list)
    attachments: list[Any] = field(default_factory=list)


class FakeInteractionResponse:
    """Fake Discord InteractionResponse for testing."""

    def __init__(self) -> None:
        self.deferred = False
        self.sent = False
        self.defer_calls: list[dict[str, Any]] = []
        self.send_message_calls: list[dict[str, Any]] = []

    async def defer(self, ephemeral: bool = False, thinking: bool = False) -> None:
        """Simulate deferring the response."""
        await asyncio.sleep(0.001)
        self.deferred = True
        self.defer_calls.append({"ephemeral": ephemeral, "thinking": thinking})

    async def send_message(
        self,
        content: str | None = None,
        embed: Any | None = None,
        embeds: list[Any] | None = None,
        ephemeral: bool = False,
    ) -> None:
        """Simulate sending a response message."""
        await asyncio.sleep(0.001)
        self.sent = True
        self.send_message_calls.append(
            {"content": content, "embed": embed, "embeds": embeds, "ephemeral": ephemeral}
        )


class FakeFollowup:
    """Fake Discord Followup for testing."""

    def __init__(self) -> None:
        self.send_calls: list[dict[str, Any]] = []

    async def send(
        self,
        content: str | None = None,
        embed: Any | None = None,
        embeds: list[Any] | None = None,
        ephemeral: bool = False,
    ) -> FakeMessage:
        """Simulate sending a followup message."""
        await asyncio.sleep(0.001)
        self.send_calls.append(
            {"content": content, "embed": embed, "embeds": embeds, "ephemeral": ephemeral}
        )
        # Return a fake message
        return FakeMessage(
            id=123456789,
            content=content or "",
            author=FakeUser(id=1, name="TestBot", bot=True),
            channel=FakeChannel(id=1, name="test-channel"),
        )


class FakeInteraction:
    """
    Fake Discord Interaction object that simulates real interaction behavior
    without requiring actual Discord connections.
    """

    def __init__(
        self,
        user_id: int = 123456789,
        user_name: str = "TestUser",
        channel_id: int = 987654321,
        channel_name: str = "test-channel",
        guild_id: int | None = 111111111,
        guild_name: str = "Test Guild",
    ) -> None:
        # Set up user
        self.user = FakeUser(id=user_id, name=user_name)

        # Set up channel
        self.channel = FakeChannel(id=channel_id, name=channel_name)
        self.channel_id = channel_id

        # Set up guild
        if guild_id:
            self.guild: FakeGuild | None = FakeGuild(id=guild_id, name=guild_name, owner_id=user_id)
            self.guild_id: int | None = guild_id
        else:
            self.guild = None
            self.guild_id = None

        # Set up response and followup
        self.response = FakeInteractionResponse()
        self.followup = FakeFollowup()

        # Track calls
        self.call_history: list[tuple[str, dict[str, Any]]] = []

    @property
    def created_at(self) -> float:
        """Simulate creation timestamp."""
        return 1640995200.0  # Fixed timestamp for testing

    def is_expired(self) -> bool:
        """Check if interaction is expired (always False for testing)."""
        return False

    async def delete_original_response(self) -> None:
        """Simulate deleting the original response."""
        await asyncio.sleep(0.001)
        self.call_history.append(("delete_original_response", {}))

    async def edit_original_response(
        self, content: str | None = None, embed: Any | None = None, embeds: list[Any] | None = None
    ) -> FakeMessage:
        """Simulate editing the original response."""
        await asyncio.sleep(0.001)
        self.call_history.append(
            ("edit_original_response", {"content": content, "embed": embed, "embeds": embeds})
        )
        return FakeMessage(
            id=123456789,
            content=content or "",
            author=FakeUser(id=1, name="TestBot", bot=True),
            channel=self.channel,
        )

    def get_response_count(self) -> int:
        """Get total number of responses sent."""
        return (
            len(self.response.defer_calls)
            + len(self.response.send_message_calls)
            + len(self.followup.send_calls)
        )

    def get_last_response(self) -> dict[str, Any] | None:
        """Get the last response sent (from any method)."""
        all_responses = []

        for call in self.response.defer_calls:
            all_responses.append({"type": "defer", **call})

        for call in self.response.send_message_calls:
            all_responses.append({"type": "send_message", **call})

        for call in self.followup.send_calls:
            all_responses.append({"type": "followup", **call})

        return all_responses[-1] if all_responses else None

    def reset(self) -> None:
        """Reset all call history for fresh test state."""
        self.response = FakeInteractionResponse()
        self.followup = FakeFollowup()
        self.call_history.clear()


class FakeBot:
    """
    Fake Discord Bot object for testing.
    """

    def __init__(
        self,
        user_id: int = 123456789,
        user_name: str = "TestBot",
        owner_id: int = 987654321,
        latency: float = 0.05,
    ) -> None:
        self.user = FakeUser(id=user_id, name=user_name, bot=True)
        self.owner_id = owner_id
        self.latency = latency
        self.guilds: list[FakeGuild] = []
        self.shard_id: int | None = None
        self.shard_count: int | None = None
        self._ready = True
        self._closed = False
        self.container: Any | None = None

    def is_ready(self) -> bool:
        """Check if bot is ready."""
        return self._ready

    def is_closed(self) -> bool:
        """Check if bot is closed."""
        return self._closed

    async def close(self) -> None:
        """Simulate closing the swarm."""
        await asyncio.sleep(0.001)
        self._closed = True

    async def wait_until_ready(self) -> None:
        """Simulate waiting until ready."""
        await asyncio.sleep(0.001)

    def add_guild(self, guild: FakeGuild) -> None:
        """Add a guild to the swarm."""
        self.guilds.append(guild)

    def get_guild(self, guild_id: int) -> FakeGuild | None:
        """Get a guild by ID."""
        for guild in self.guilds:
            if guild.id == guild_id:
                return guild
        return None
