import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import pytest

from swarm.distributed import celery_browser as cb_mod


class _FakeAsyncResult:
    def __init__(self, response: dict[str, object]):
        self._response = response

    def get(self, timeout: float | None = None) -> dict[str, object]:
        return self._response


class _SendTaskRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def __call__(
        self, name: str, kwargs: dict[str, object] | None = None, queue: str | None = None
    ) -> _FakeAsyncResult:
        # Record only task name and kwargs for assertion
        self.calls.append((name, kwargs))
        # Provide minimal responses for start/goto/screenshot/status
        if name == "browser.start":
            # Return a stable session id
            return _FakeAsyncResult({"success": True, "session_id": "session-123"})
        elif name == "browser.goto":
            return _FakeAsyncResult(
                {
                    "success": True,
                    "url": (kwargs or {}).get("url", ""),
                    "session_id": (kwargs or {}).get("session_id", ""),
                }
            )
        elif name == "browser.screenshot":
            # Minimal success result with base64-like stub
            return _FakeAsyncResult({"success": True, "data": ""})
        elif name == "browser.status":
            return _FakeAsyncResult({"success": True, "data": {"status": "healthy"}})
        else:
            return _FakeAsyncResult({"success": True})


@pytest.mark.asyncio
async def test_runtime_passes_task_id_when_set(monkeypatch: Any) -> None:
    recorder = _SendTaskRecorder()
    # Monkeypatch module-level app with a simple namespace carrying send_task
    monkeypatch.setattr(cb_mod, "app", SimpleNamespace(send_task=recorder))

    rt = cb_mod.CeleryBrowserRuntime()
    rt.set_session("discord:1:2")

    await rt.goto("https://example.com")
    await rt.screenshot()

    # Ensure both calls carried session_id
    names_kwargs = recorder.calls
    # Expect at least two task calls after setting the session (goto + screenshot)
    assert any(
        n == "browser.goto" and k and k.get("session_id") == "discord:1:2" for n, k in names_kwargs
    )
    assert any(
        n == "browser.screenshot" and k and k.get("session_id") == "discord:1:2"
        for n, k in names_kwargs
    )


@pytest.mark.asyncio
async def test_runtime_lazy_start_creates_session(monkeypatch: Any) -> None:
    recorder = _SendTaskRecorder()
    monkeypatch.setattr(cb_mod, "app", SimpleNamespace(send_task=recorder))

    rt = cb_mod.CeleryBrowserRuntime()
    # No session set; goto should trigger start first
    await rt.goto("https://example.com")

    # First call should be browser.start, then browser.goto with session_id
    assert recorder.calls[0][0] == "browser.start"
    # Find the goto call and assert it has a session_id
    goto_calls_dicts = [k for n, k in recorder.calls if n == "browser.goto" and isinstance(k, dict)]
    assert goto_calls_dicts, "Expected a browser.goto call"
    assert goto_calls_dicts[0].get("session_id") == "session-123"
