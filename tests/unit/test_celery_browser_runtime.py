import asyncio
from types import SimpleNamespace

import pytest

from swarm.distributed import celery_browser as cb_mod


class _FakeAsyncResult:
    def __init__(self, response: dict):
        self._response = response

    def get(self, timeout: float | None = None):
        return self._response


class _SendTaskRecorder:
    def __init__(self):
        self.calls: list[tuple[str, dict | None]] = []

    def __call__(self, name: str, kwargs: dict | None = None, queue: str | None = None):
        # Record only task name and kwargs for assertion
        self.calls.append((name, kwargs))
        # Provide minimal responses for start/goto/screenshot/status
        if name == "browser.start":
            # Return a stable session id
            return _FakeAsyncResult({"success": True, "session_id": "session-123"})
        elif name == "browser.goto":
            return _FakeAsyncResult({"success": True, "url": kwargs.get("url"), "session_id": kwargs.get("session_id", "")})
        elif name == "browser.screenshot":
            # Minimal success result with base64-like stub
            return _FakeAsyncResult({"success": True, "data": ""})
        elif name == "browser.status":
            return _FakeAsyncResult({"success": True, "data": {"status": "healthy"}})
        else:
            return _FakeAsyncResult({"success": True})


@pytest.mark.asyncio
async def test_runtime_passes_task_id_when_set(monkeypatch):
    recorder = _SendTaskRecorder()
    monkeypatch.setattr(cb_mod.app, "send_task", recorder)

    rt = cb_mod.CeleryBrowserRuntime()
    rt.set_session("discord:1:2")

    await rt.goto("https://example.com")
    await rt.screenshot()

    # Ensure both calls carried session_id
    names_kwargs = recorder.calls
    # Expect at least two task calls after setting the session (goto + screenshot)
    assert any(n == "browser.goto" and k and k.get("session_id") == "discord:1:2" for n, k in names_kwargs)
    assert any(n == "browser.screenshot" and k and k.get("session_id") == "discord:1:2" for n, k in names_kwargs)


@pytest.mark.asyncio
async def test_runtime_lazy_start_creates_session(monkeypatch):
    recorder = _SendTaskRecorder()
    monkeypatch.setattr(cb_mod.app, "send_task", recorder)

    rt = cb_mod.CeleryBrowserRuntime()
    # No session set; goto should trigger start first
    await rt.goto("https://example.com")

    # First call should be browser.start, then browser.goto with session_id
    assert recorder.calls[0][0] == "browser.start"
    # Find the goto call and assert it has a session_id
    goto_calls = [k for n, k in recorder.calls if n == "browser.goto"]
    assert goto_calls, "Expected a browser.goto call"
    assert goto_calls[0].get("session_id") == "session-123"
