import pytest


@pytest.mark.asyncio
async def test_headless_default(
    monkeypatch: pytest.MonkeyPatch, patch_uc: None
) -> None:
    monkeypatch.delenv("BROWSER_HEADLESS", raising=False)  # use default True
    from bot_core.api.browser_service import BrowserService

    svc = BrowserService()
    await svc.start()  # headless by default
    assert svc._session is not None
    driver = svc._session.driver
    # The dummy driver should have the expected dummy methods
    assert hasattr(driver, "get")
    assert hasattr(driver, "save_screenshot")
    assert hasattr(driver, "quit")
    # It should NOT have the 'real' marker
    assert not getattr(driver, "real", False)
    await svc.stop()
