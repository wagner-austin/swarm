import asyncio
import base64
import json

import pytest

from bot.browser.ws_logger import InMemorySink, WSLogger


@pytest.mark.asyncio
async def test_wslogger_basic_usage() -> None:
    """Tests the basic functionality of the WSLogger, including context management and sinks."""
    sink = InMemorySink()
    async with WSLogger(
        browser_id="browser-test",
        session_id="session-test",
        episode_id="episode-test",
        protocol_version="abc123",
        experiment_id="exp-42",
        sink=sink,
    ) as logger:
        # Log RX frame
        await logger.log_frame(
            direction="RX",
            payload=b"hello",
            websocket_id="ws-1",
            websocket_url="wss://example.com/ws",
            parsed={"msg": "hi"},
            event=None,
        )
        # Log TX frame
        await logger.log_frame(
            direction="TX",
            payload=b"world",
            websocket_id="ws-1",
            websocket_url="wss://example.com/ws",
        )
        # Log a custom event
        await logger.log_event(
            "websocket_close", websocket_id="ws-1", websocket_url="wss://example.com/ws"
        )

    # After context manager, experiment_stop event must be present
    events = [e for e in sink.entries if e.event is not None]
    assert any(e.event == "experiment_start" for e in events)
    assert any(e.event == "websocket_close" for e in events)
    assert any(e.event == "experiment_stop" for e in events)

    # Check frame fields and base64 encoding
    rx = next(e for e in sink.entries if e.direction == "RX")
    assert rx.payload == b"hello"
    assert rx.parsed == {"msg": "hi"}
    assert rx.browser_id == "browser-test"
    assert rx.session_id == "session-test"
    assert rx.episode_id == "episode-test"
    assert rx.protocol_version == "abc123"
    assert rx.experiment_id == "exp-42"
    assert rx.websocket_id == "ws-1"
    assert rx.websocket_url == "wss://example.com/ws"
    # Confirm base64 encoding in JSON
    j = rx.to_json()
    jdata = json.loads(j)
    assert jdata["payload"] == base64.b64encode(b"hello").decode()

    # Check all entries are present (start, RX, TX, close, stop)
    assert len(sink.entries) == 5
