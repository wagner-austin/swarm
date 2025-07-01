import asyncio
from unittest.mock import MagicMock

import discord
import pytest
from discord.ext import commands

from bot.plugins.commands.metrics_tracker import MetricsTracker


class DummyBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self._user: MagicMock = MagicMock(id=1234)
        self._latency: float = 0.123

    # Expose user as non-optional to avoid "None" checks in tests
    @property
    def user(self) -> MagicMock:  # pragma: no cover
        return self._user

    # Provide read/write latency property
    @property
    def latency(self) -> float:  # pragma: no cover
        return self._latency

    @latency.setter
    def latency(self, value: float) -> None:  # pragma: no cover
        self._latency = value


@pytest.mark.asyncio
async def test_metrics_tracker_increments_metrics() -> None:
    mock_metrics = MagicMock()
    bot: DummyBot = DummyBot()
    cog = MetricsTracker(bot, metrics=mock_metrics)

    # Simulate on_message from self
    message = MagicMock()
    assert bot.user is not None  # narrow Optional[ClientUser | None]
    message.author.id = bot.user.id
    await cog.on_message(message)
    mock_metrics.increment_message_count.assert_called_once()
    mock_metrics.increment_discord_message_count.assert_not_called()

    mock_metrics.reset_mock()
    # Simulate on_message from another user
    message.author.id = 9999
    await cog.on_message(message)
    mock_metrics.increment_discord_message_count.assert_called_once()
    mock_metrics.increment_message_count.assert_not_called()

    # Simulate on_interaction from another user
    interaction = MagicMock()
    interaction.type.name = "application_command"
    interaction.user.id = 9999
    bot.user.id = 1234
    await cog.on_interaction(interaction)
    mock_metrics.increment_discord_message_count.assert_called()

    # Simulate on_interaction from self (should not increment)
    mock_metrics.reset_mock()
    interaction.user.id = bot.user.id
    await cog.on_interaction(interaction)
    mock_metrics.increment_discord_message_count.assert_not_called()
