import asyncio
import base64
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from types import TracebackType
from typing import Any, Awaitable, Callable, Dict, Literal, Optional, Union

try:
    from playwright.async_api import Page, WebSocket
except ImportError:
    Page = None  # type: ignore
    WebSocket = None  # type: ignore

__all__ = ["WSFrameLog", "WSLogger", "jsonl_sink", "InMemorySink"]


@dataclass
class WSFrameLog:
    """
    A single WebSocket frame log entry for AI/ML replay and analytics.

    Fields:
        - timestamp: Absolute wall-clock time (UTC seconds)
        - rel_ts: Time since episode start (seconds, float)
        - direction: "RX" (from server), "TX" (to server), or None for events
        - payload: Raw binary payload (base64-encoded in JSONL)
        - browser_id: A unique ID for the browser instance.
        - session_id, episode_id: UUIDs for grouping
        - websocket_id: A unique ID for the WebSocket connection.
        - websocket_url: The URL of the WebSocket connection.
        - parsed: Optionally filled by protocol decoders (None if not parsed).
        - protocol_version: Version of the protocol decoder (e.g., git commit).
        - experiment_id: A user-specified ID for large-scale experiments.
        - event: Special event marker (e.g., "end_of_episode").
        - extra: Dict for future extensibility.
    """

    timestamp: float
    rel_ts: float
    direction: Literal["RX", "TX"] | None
    payload: bytes
    browser_id: str
    session_id: str
    episode_id: str
    websocket_id: str | None = None
    websocket_url: str | None = None
    parsed: dict[str, Any] | None = None
    protocol_version: str | None = None
    experiment_id: str | None = None
    event: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        d = asdict(self)
        d["payload"] = base64.b64encode(self.payload).decode("ascii")
        return json.dumps(d, separators=(",", ":"), ensure_ascii=False)


class WSLogger:
    """
    Robust, async WebSocket frame logger for gameplay, AI, and analytics.

    Usage:
        async with WSLogger(session_id="...", episode_id="...", sink=await jsonl_sink(...)) as logger:
            await logger.log_frame(...)
            ...
        # Or, manually call close()

    - Attach to Playwright Page via `await logger.attach(page)`
    - Use log_frame() for manual RX/TX logging
    - Sink is any async callable: `Callable[[WSFrameLog], Awaitable[None]]` with a `close()` method (async, even if no-op)
    - The `parsed` field is for protocol decoders: fill it with structured state/action dicts as available; otherwise leave None.
    - For future high-throughput ML, consider swapping out base64/JSONL for binary/Parquet (see TODOs).
    """

    def __init__(
        self,
        browser_id: str | None = None,
        session_id: str | None = None,
        episode_id: str | None = None,
        protocol_version: str | None = None,
        experiment_id: str | None = None,
        sink: Callable[[WSFrameLog], Awaitable[None]] | None = None,
    ):
        self.browser_id = browser_id or uuid.uuid4().hex
        self.session_id = session_id or uuid.uuid4().hex
        self.episode_id = episode_id or uuid.uuid4().hex
        self.protocol_version = protocol_version
        self.experiment_id = experiment_id
        self._sink = sink or (lambda entry: asyncio.sleep(0))
        self._closed = False
        self._lock = asyncio.Lock()
        self._start_ts = time.time()
        self._websocket_ids: dict[str, str] = {}

    async def __aenter__(self) -> "WSLogger":
        # Log experiment_start synchronously when entering context
        await self.log_event("experiment_start")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def log_frame(
        self,
        direction: Literal["RX", "TX"] | None,
        payload: bytes,
        websocket_id: str | None = None,
        websocket_url: str | None = None,
        parsed: dict[str, Any] | None = None,
        event: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        if self._closed:
            return
        now = time.time()
        rel_ts = now - self._start_ts
        entry = WSFrameLog(
            timestamp=now,
            rel_ts=rel_ts,
            direction=direction,
            payload=payload,
            browser_id=self.browser_id,
            session_id=self.session_id,
            episode_id=self.episode_id,
            websocket_id=websocket_id,
            websocket_url=websocket_url,
            parsed=parsed,
            protocol_version=self.protocol_version,
            experiment_id=self.experiment_id,
            event=event,
            extra=extra or {},
        )
        async with self._lock:
            try:
                await self._sink(entry)
            except Exception as exc:
                import logging

                logging.error(f"WSLogger sink error: {exc}")
                if not hasattr(self, "_errors"):
                    self._errors = []
                self._errors.append((now, exc, entry))

    async def log_event(
        self,
        event: str,
        websocket_id: str | None = None,
        websocket_url: str | None = None,
        extra: dict[str, Any] | None = None,
        direction: Literal["RX", "TX"] | None = None,
    ) -> None:
        # Always set payload=b"" for event records (no frame data)
        await self.log_frame(
            direction=direction,
            payload=b"",
            event=event,
            websocket_id=websocket_id,
            websocket_url=websocket_url,
            extra=extra,
        )

    async def attach(self, page: Page) -> None:
        """
        Attach the logger to a Playwright Page to automatically log WebSocket frames.
        """
        if Page is None:
            import logging

            logging.warning("Playwright is not installed; WSLogger.attach() will not function.")
            return
        if not hasattr(page, "on"):
            raise RuntimeError(
                "Page object does not support event hooks (is it a Playwright Page?)"
            )

        def _on_ws(ws: WebSocket) -> None:
            websocket_id = uuid.uuid4().hex
            websocket_url = ws.url
            self._websocket_ids[websocket_id] = websocket_url

            async def on_frame(direction: Literal["RX", "TX"], frame: Any) -> None:
                await self.log_frame(
                    direction=direction,
                    payload=frame.body,
                    websocket_id=websocket_id,
                    websocket_url=websocket_url,
                )

            async def on_close(ws: WebSocket) -> None:
                self._websocket_ids.pop(websocket_id, None)
                await self.log_event(
                    "websocket_close",
                    websocket_id=websocket_id,
                    websocket_url=websocket_url,
                )

            ws.on("framereceived", lambda frame: asyncio.create_task(on_frame("RX", frame)))
            ws.on("framesent", lambda frame: asyncio.create_task(on_frame("TX", frame)))
            ws.on("close", lambda ws: asyncio.create_task(on_close(ws)))

        page.on("websocket", _on_ws)

    async def _on_ws_frame(self, direction: Literal["RX", "TX"], frame: Any) -> None:
        payload = frame.get("payload", b"")
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        await self.log_frame(direction=direction, payload=payload)

    async def close(self) -> None:
        if not self._closed:
            await self.log_event("experiment_stop")
            self._closed = True
            if self._sink is not None and hasattr(self._sink, "close"):
                # The sink's close is dynamically attached, so we can call it.
                await self._sink.close()


# --- Sinks ---


async def jsonl_sink(
    filepath: str, gzip_compress: bool = False
) -> Callable[[WSFrameLog], Awaitable[None]]:
    """
    Write each WSFrameLog as a JSONL line to the given file using an async sink.
    The returned sink exposes an async close() method.
    If gzip_compress=True, writes .jsonl.gz (compressed) using gzip.
    """
    import gzip

    lock = asyncio.Lock()
    if gzip_compress:
        f = await asyncio.to_thread(gzip.open, filepath, "at", encoding="utf-8")
    else:
        f = await asyncio.to_thread(open, filepath, "a", encoding="utf-8")

    async def sink(entry: WSFrameLog) -> None:
        async with lock:
            await asyncio.to_thread(f.write, entry.to_json() + "\n")
            await asyncio.to_thread(f.flush)

    async def close() -> None:
        await asyncio.to_thread(f.close)

    # Dynamically attach the close method to the sink function
    setattr(sink, "close", close)
    return sink


class InMemorySink:
    """An async sink that stores all logs in a list in memory, useful for testing."""

    def __init__(self) -> None:
        self.entries: list[WSFrameLog] = []

    async def __call__(self, entry: WSFrameLog) -> None:
        self.entries.append(entry)

    async def close(self) -> None:
        pass


# --- Example usage in tests or scripts ---
# async def example():
#     logger = WSLogger(sink=await jsonl_sink("session.jsonl"))
#     await logger.log_frame(direction="RX", payload=b"...", parsed=None)
#     await logger.close()
