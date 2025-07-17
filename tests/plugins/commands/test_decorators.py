from typing import Any, Awaitable, Callable, Coroutine, cast
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from pytest_mock import MockerFixture

from swarm.plugins.commands import decorators

# A helper type for the patched asyncio.create_task
PatchedCreateTask = Callable[[Coroutine[Any, Any, Any]], Awaitable[Any]]


@pytest.fixture
def patch_create_task(mocker: MockerFixture) -> PatchedCreateTask:
    """Fixture to patch asyncio.create_task to run tasks immediately."""

    def run_immediately(coro: Coroutine[Any, Any, Any]) -> Awaitable[Any]:
        return coro

    mocker.patch("asyncio.create_task", side_effect=run_immediately)
    return run_immediately


def make_interaction_mock() -> MagicMock:
    """Return a fake discord.Interaction with AsyncMock followup.send and response.defer."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock(spec=discord.InteractionResponse)
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock(spec=discord.Webhook)
    interaction.followup.send = AsyncMock()
    return interaction


@pytest.mark.asyncio
async def test_background_app_command_defer_and_run(
    patch_create_task: PatchedCreateTask,  # noqa: F841
) -> None:
    """Test that the decorator defers, then runs the command."""
    called: dict[str, bool] = {}
    interaction = make_interaction_mock()

    @decorators.background_app_command(defer_ephemeral=True)
    async def handler(self: Any, interaction: discord.Interaction) -> None:
        called["ran"] = True
        # Should be deferred before running
        cast(AsyncMock, interaction.response.defer).assert_awaited_once()
        cast(AsyncMock, interaction.followup.send).assert_not_awaited()

    class Dummy:
        pass

    dummy = Dummy()
    await handler(dummy, interaction)
    assert called["ran"]
    # Check assertions again after the handler is fully complete
    cast(AsyncMock, interaction.response.defer).assert_awaited_once_with(
        ephemeral=True, thinking=True
    )


@pytest.mark.asyncio
async def test_background_app_command_handles_exception(
    mocker: MockerFixture,
    patch_create_task: PatchedCreateTask,  # noqa: F841
) -> None:
    """Test that exceptions in the command are caught and a message is sent."""
    interaction = make_interaction_mock()
    mock_safe_send = mocker.patch(
        "swarm.plugins.commands.decorators.safe_send", new_callable=AsyncMock
    )

    @decorators.background_app_command()
    async def handler(self: Any, interaction: discord.Interaction) -> None:
        raise RuntimeError("fail")

    class Dummy:
        pass

    dummy = Dummy()
    await handler(dummy, interaction)

    mock_safe_send.assert_awaited_once()
    # Check that the message contains "unexpected error"
    call_args, _ = mock_safe_send.call_args
    assert "unexpected error" in str(call_args[1]).lower()


@pytest.mark.asyncio
async def test_background_app_command_locates_interaction(
    patch_create_task: PatchedCreateTask,  # noqa: F841
) -> None:
    """Test the decorator finds the interaction in kwargs."""
    interaction = make_interaction_mock()
    called: dict[str, bool] = {}

    @decorators.background_app_command()
    async def handler(self: Any, interaction: discord.Interaction) -> None:
        called["ran"] = True

    class Dummy:
        pass

    dummy = Dummy()
    await handler(dummy, interaction=interaction)
    assert called["ran"]


@pytest.mark.asyncio
async def test_background_app_command_raises_without_interaction(
    patch_create_task: PatchedCreateTask,  # noqa: F841
) -> None:
    """Test the decorator raises TypeError if the interaction arg is missing."""

    @decorators.background_app_command()
    async def handler(self: Any, x: int) -> None:
        pass

    class Dummy:
        pass

    dummy = Dummy()
    with pytest.raises(TypeError, match="could not locate the 'interaction' argument"):
        await handler(dummy, 123)
