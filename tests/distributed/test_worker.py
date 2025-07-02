import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from bot.distributed.model import Job
from bot.distributed.worker import (
    _browser_engines,
    _tankpit_engines,
    cleanup_browser_session,
    cleanup_tankpit_session,
    handle_browser_job,
    handle_tankpit_job,
)


@pytest.mark.asyncio
async def test_browser_job_dispatch_and_cleanup() -> None:
    # Patch BrowserEngine to avoid launching real browser
    with patch("bot.distributed.worker.BrowserEngine", autospec=True) as MockBrowserEngine:
        mock_engine = MockBrowserEngine.return_value
        mock_engine.start = AsyncMock()
        mock_engine.goto = AsyncMock()
        mock_engine.stop = AsyncMock()
        session_id = "test-session"
        job = Job(
            id="job1",
            type="browser.goto",
            args=("https://example.com",),
            kwargs={"session_id": session_id, "close_session": True},
            reply_to="reply-stream",
            created_ts=0.0,
        )
        await handle_browser_job(job)
        # Engine should be created, method called, and then cleaned up
        mock_engine.start.assert_awaited_once()
        mock_engine.goto.assert_awaited_once_with("https://example.com")
        mock_engine.stop.assert_awaited_once_with(graceful=True)
        assert session_id not in _browser_engines


@pytest.mark.asyncio
async def test_tankpit_job_dispatch_and_cleanup() -> None:
    # Patch TankPitEngine to avoid real game logic
    with patch("bot.distributed.worker.TankPitEngine", autospec=True) as MockTankpitEngine:
        mock_engine = MockTankpitEngine.return_value
        mock_engine.start = AsyncMock()
        mock_engine.move = AsyncMock()
        mock_engine.stop = AsyncMock()
        session_id = "tank-session"
        job = Job(
            id="job2",
            type="tankpit.move",
            args=("up",),
            kwargs={"session_id": session_id, "close_session": True},
            reply_to="reply-stream",
            created_ts=0.0,
        )
        await handle_tankpit_job(job)
        mock_engine.start.assert_awaited_once()
        mock_engine.move.assert_awaited_once_with("up")
        mock_engine.stop.assert_awaited_once_with(graceful=True)
        assert session_id not in _tankpit_engines


@pytest.mark.asyncio
async def test_browser_job_unknown_method() -> None:
    with patch("bot.distributed.worker.BrowserEngine", autospec=True) as MockBrowserEngine:
        mock_engine = MockBrowserEngine.return_value
        mock_engine.start = AsyncMock()
        session_id = "unknown-method"
        job = Job(
            id="job3",
            type="browser.unknown_method",
            args=(),
            kwargs={"session_id": session_id, "close_session": True},
            reply_to="reply-stream",
            created_ts=0.0,
        )
        await handle_browser_job(job)
        # Should not raise, should not call any method, should cleanup
        mock_engine.start.assert_awaited_once()
        mock_engine.stop.assert_awaited_once_with(graceful=True)
        assert session_id not in _browser_engines


@pytest.mark.asyncio
async def test_tankpit_job_unknown_method() -> None:
    with patch("bot.distributed.worker.TankPitEngine", autospec=True) as MockTankpitEngine:
        mock_engine = MockTankpitEngine.return_value
        mock_engine.start = AsyncMock()
        session_id = "unknown-method"
        job = Job(
            id="job4",
            type="tankpit.unknown_method",
            args=(),
            kwargs={"session_id": session_id, "close_session": True},
            reply_to="reply-stream",
            created_ts=0.0,
        )
        await handle_tankpit_job(job)
        mock_engine.start.assert_awaited_once()
        mock_engine.stop.assert_awaited_once_with(graceful=True)
        assert session_id not in _tankpit_engines
