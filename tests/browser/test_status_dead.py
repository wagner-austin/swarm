import pytest
from bot.core.api.browser_service import BrowserService
from tests.helpers.dummy_dead_driver import DeadAfterOne

@pytest.mark.asyncio
async def test_status_dead(monkeypatch):
    monkeypatch.setattr(
        "bot.core.api.browser.session.create_uc_driver",
        lambda *a, **kw: DeadAfterOne(),
    )
    svc = BrowserService()
    await svc.start()
    # kill it
    svc._session.driver._dead = True   # type: ignore[attr-defined]
    assert "DEAD" in svc.status()
