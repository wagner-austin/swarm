"""Race-condition test for BrowserEngine self-healing restarts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from bot.browser.engine import BrowserEngine


class _DummyPage:  # noqa: D101 – internal test helper
    async def evaluate(self, _script: str) -> int:  # noqa: D401 – emulate page check
        return 1

    async def close(self) -> None:  # noqa: D401
        return None


class _DummyContext:  # noqa: D101 – mimics BrowserContext
    def __init__(self, browser: _DummyBrowser) -> None:
        self._browser = browser

    async def new_page(self) -> _DummyPage:  # noqa: D401
        return _DummyPage()

    async def close(self) -> None:  # noqa: D401
        return None


class _DummyBrowser:  # noqa: D101 – internal test helper
    def __init__(self) -> None:
        self.closed = False

    async def new_page(self) -> _DummyPage:  # noqa: D401 – simple helper
        return _DummyPage()

    async def new_context(self) -> _DummyContext:  # noqa: D401
        return _DummyContext(self)

    async def close(self) -> None:  # noqa: D401
        self.closed = True


class _DummyPlaywright:  # noqa: D101
    def __init__(self, launch_cb: Callable[[], None]) -> None:
        # Chromium launcher exposes .launch() coroutine
        async def _launch(*_a: Any, **_kw: Any) -> _DummyBrowser:  # noqa: ANN001
            launch_cb()
            return _DummyBrowser()

        self.chromium = SimpleNamespace(launch=_launch)

    async def stop(self) -> None:  # noqa: D401
        return None


class _AsyncPlaywrightCtx:  # noqa: D101
    def __init__(self, launch_cb: Callable[[], None]) -> None:
        self._launch_cb = launch_cb

    async def start(self) -> _DummyPlaywright:  # noqa: D401
        # Called by BrowserEngine._restart_browser
        return _DummyPlaywright(self._launch_cb)


@pytest.mark.asyncio()
async def test_browser_engine_concurrent_restart(monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: D401
    """Concurrent _restart_browser calls should not raise and leave engine running."""

    launches: int = 0

    def _inc() -> None:  # closure to track launches
        nonlocal launches
        launches += 1

    # Patch async_playwright used inside BrowserEngine
    monkeypatch.setattr(
        "bot.browser.engine.async_playwright",
        lambda: _AsyncPlaywrightCtx(_inc),
    )

    eng = BrowserEngine(headless=True, proxy=None, timeout_ms=100)

    # Initial start – should create first dummy browser
    await eng.start()
    assert eng.is_running()

    # Simulate failure by closing browser and nulling reference
    if eng._browser is not None:  # pragma: no cover – defensive
        await eng._browser.close()
    eng._browser = None

    # Fire two restarts concurrently
    await asyncio.gather(eng._restart_browser(), eng._restart_browser())

    # Expectations: engine recovered and at least one launch occurred
    assert eng.is_running()
    assert launches >= 1

    # Cleanup
    await eng.stop()
