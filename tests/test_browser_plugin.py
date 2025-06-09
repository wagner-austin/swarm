import pytest
import sys
from unittest.mock import AsyncMock, MagicMock
from discord import Intents
from discord.ext.commands import Bot
from typing import Any, cast

from dependency_injector import providers

from bot.core.containers import Container
from bot.core.api.browser.actions import BrowserActions
from bot.core.api.browser.exceptions import InvalidURLError
from bot.plugins.commands.browser import Browser

# old MockCtx emulated prefix Context; we now import a tiny Interaction stub
from tests.helpers.mocks import StubInteraction


@pytest.mark.asyncio
async def test_browser_command_flow(monkeypatch: Any, tmp_path: Any) -> None:
    # patch download dir
    monkeypatch.setattr("bot.core.settings.settings.browser_download_dir", tmp_path)

    # service: BrowserService = BrowserService() # Old instantiation
    # mgr_instance was previously used for manual cog instantiation.
    # For full DI testing, mocks should be injected via container overrides.

    from tests.helpers.drivers import DummyDriver

    monkeypatch.setattr(
        "bot.core.api.browser.session.create_uc_driver",
        lambda *a, **kw: DummyDriver(*a, **kw),
    )

    container = Container()
    container.wire(modules=["bot.plugins.commands.browser"])

    dummy_bot: Bot = Bot(command_prefix="!", intents=Intents.default())
    browser_cog: Browser = Browser(bot=dummy_bot)  # Provide objects now resolved

    # Slash commands receive a discord.Interaction.  StubInteraction mimics just
    # the bits Browser.start/open/… touch (response.defer & followup.send).
    ix = StubInteraction(bot=dummy_bot)

    # The attributes `start`, `open`, … are `discord.ext.commands.Command`
    # objects – we need their *coroutine* behind `.callback`.

    # Helper that silences mypy by treating Command.callback as Any
    async def invoke(command_obj: Any, *params: Any, **kw: Any) -> None:
        await cast(Any, command_obj.callback)(*params, **kw)

    # start
    await invoke(browser_cog.start, browser_cog, ix)

    # open valid
    await invoke(browser_cog.open, browser_cog, ix, url="https://example.com")

    # open invalid → our new validation branch
    await invoke(browser_cog.open, browser_cog, ix, url="qwasd")

    # screenshot
    await invoke(browser_cog.screenshot, browser_cog, ix)

    # status
    await invoke(browser_cog.status, browser_cog, ix)

    # close
    await invoke(browser_cog.close, browser_cog, ix)


@pytest.mark.asyncio
async def test_browser_open_command_invalid_url_mocked(
    monkeypatch: Any, tmp_path: Any
) -> None:
    """Test that /browser open handles InvalidURLError from BrowserActions.open correctly using a mock."""
    container = Container()

    # Apply necessary monkeypatches for settings if SessionManager (which might be real) needs them.
    # This mirrors the setup in test_browser_command_flow.
    monkeypatch.setattr("bot.core.settings.settings.browser_download_dir", tmp_path)
    # If SessionManager or other parts of the cog rely on container.config, ensure it's populated or mocked if necessary.
    # For this test, we primarily care about BrowserActions being mocked.

    # Wire the container to the modules where injection will occur.
    # The Browser cog is in 'bot.plugins.commands.browser'.
    # sys.modules[__name__] is for the current test file, in case it also uses @inject (not common for simple tests).
    container.wire(modules=[sys.modules[__name__], "bot.plugins.commands.browser"])

    # Create a mock for BrowserActions
    mock_actions_instance = MagicMock(spec=BrowserActions)
    expected_error_message = "Mocked Invalid URL from test"
    mock_actions_instance.open = AsyncMock(
        side_effect=InvalidURLError(expected_error_message)
    )

    # Create a dummy bot with our container attached
    dummy_bot: Bot = Bot(command_prefix="!", intents=Intents.default())

    # Attach our container to the bot (this is now how cogs get dependencies)
    dummy_bot.container = container  # type: ignore[attr-defined]

    # Override the browser_actions provider in the container with our mock
    container.browser_actions.override(providers.Object(mock_actions_instance))

    # Instantiate the Browser cog - it will now get the mock through bot.container
    browser_cog: Browser = Browser(bot=dummy_bot)

    # Prepare a stub interaction
    ix = StubInteraction(bot=dummy_bot)

    # Helper for invoking the command's callback
    # (Copied from test_browser_command_flow for encapsulation, or could be a shared test fixture/helper)
    async def invoke(command_obj: Any, *params: Any, **kw: Any) -> None:
        await cast(Any, command_obj.callback)(*params, **kw)

    test_url = "http://this.is.a.test/to-trigger-mock"
    # Call the 'open' command on the cog
    await invoke(browser_cog.open, browser_cog, ix, url=test_url)

    # Assert that the mocked BrowserActions.open was called correctly
    mock_actions_instance.open.assert_called_once_with(test_url)

    # Assert that the interaction's followup.send was called with the error message
    # This assumes StubInteraction and its StubFollowup capture sent messages.
    assert hasattr(ix.followup, "sent_messages"), (
        "StubInteraction.followup needs a 'sent_messages' attribute list"
    )
    assert len(ix.followup.sent_messages) == 1, (
        f"Expected 1 followup message, got {len(ix.followup.sent_messages)}: {ix.followup.sent_messages}"
    )
    assert expected_error_message in ix.followup.sent_messages[0], (
        f"Error message '{expected_error_message}' not found in followup: {ix.followup.sent_messages[0]}"
    )

    # Clean up wiring after the test to prevent interference with other tests
    container.unwire()
