import pytest
from bot.core.api.browser_service import BrowserService
from tests.helpers.dummy_dead_driver import DeadAfterOne

@pytest.mark.asyncio
async def test_auto_revive(monkeypatch):
    monkeypatch.setattr(
        "bot.core.api.browser.session.create_uc_driver",
        lambda *a, **kw: DeadAfterOne(),
    )
    svc = BrowserService()
    await svc.start()          # alive
    assert svc.alive()

    # first open works; driver dies internally
    await svc.open("https://example.com")
    assert svc.alive() is False    # now dead

    # next open triggers auto-restart
    msg = await svc.open("https://example.com")
    assert "fresh session" in msg.lower()
    assert svc.alive()
