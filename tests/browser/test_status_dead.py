from __future__ import annotations

import pytest
from typing import Any

from bot.core.api.browser_service import BrowserService
from tests.helpers.dummy_dead_driver import DeadAfterOne


@pytest.mark.asyncio
async def test_status_dead(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bot.core.api.browser.session.create_uc_driver",
        lambda *a, **kw: DeadAfterOne(),
    )
    svc: BrowserService = BrowserService()
    await svc.start()

    # prove we have a session and driver, then flip the flag
    assert svc._session is not None
    driver: Any = svc._session.driver
    assert driver is not None
    driver._dead = True  # type: ignore[attr-defined]
    assert "DEAD" in svc.status()
