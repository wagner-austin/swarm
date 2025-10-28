from __future__ import annotations

import asyncio
import base64
import json
import logging
import pathlib
import time
import uuid
from dataclasses import asdict, dataclass, field
from types import TracebackType
from typing import TYPE_CHECKING, Awaitable, Callable, Literal, Protocol, TypedDict, TypeGuard

if TYPE_CHECKING:  # Only for type-checkers; avoid hard runtime dependency
    from playwright.async_api import Page, WebSocket

__all__ = ["WSFrameLog", "WSLogger", "jsonl_sink", "InMemorySink"]


class WSParsedPayload(TypedDict, total=False):
    """Structured interpretation of a WebSocket frame payload.

    Optional fields allow protocol-specific decoders to fill what they know
    without enforcing a single schema.
    """

    kind: Literal["text", "binary", "json"]
    text: str
    json: object
    size: int
    opcode: int


@dataclass
class WSFrameLog:
    """
    A single WebSocket frame log entry for AI/ML replay and analytics.
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
    parsed: WSParsedPayload | None = None
    protocol_version: str | None = None
    experiment_id: str | None = None
    event: str | None = None
    extra: dict[str, object] = field(default_factory=dict)

    def to_json(self) -> str:
        d = asdict(self)
        d["payload"] = base64.b64encode(self.payload).decode("ascii")
        return json.dumps(d, separators=(",", ":"), ensure_ascii=False)


class _HasBody(Protocol):
    body: object


class _Gettable(Protocol):
    def get(self, key: str, default: object) -> object: ...


def _has_body(obj: object) -> TypeGuard[_HasBody]:
    return hasattr(obj, "body")


def _has_get(obj: object) -> TypeGuard[_Gettable]:
    return hasattr(obj, "get")


class WSLogger:
    """Async WebSocket frame logger with JSONL sinks.

    - Attach to Playwright Page via `await logger.attach(page)`
    - Use log_frame() for manual RX/TX logging
    - Sink is any async callable: `Callable[[WSFrameLog], Awaitable[None]]`
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
        self._errors: list[tuple[float, Exception, WSFrameLog]] = []

    async def __aenter__(self) -> WSLogger:  # noqa: D401
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
        parsed: WSParsedPayload | None = None,
        event: str | None = None,
        extra: dict[str, object] | None = None,
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
                logging.error("WSLogger sink error: %r", exc)
                self._errors.append((now, exc, entry))

    async def log_event(
        self,
        event: str,
        websocket_id: str | None = None,
        websocket_url: str | None = None,
        extra: dict[str, object] | None = None,
        direction: Literal["RX", "TX"] | None = None,
    ) -> None:
        await self.log_frame(
            direction=direction,
            payload=b"",
            event=event,
            websocket_id=websocket_id,
            websocket_url=websocket_url,
            extra=extra,
        )

    async def attach(self, page: Page) -> None:
        if not hasattr(page, "on"):
            raise RuntimeError(
                "Page object does not support event hooks (is it a Playwright Page?)"
            )

        def _on_ws(ws: WebSocket) -> None:
            websocket_id = uuid.uuid4().hex
            websocket_url = ws.url
            self._websocket_ids[websocket_id] = websocket_url

            async def on_frame(direction: Literal["RX", "TX"], frame: object) -> None:
                if _has_body(frame):
                    payload_obj = frame.body
                elif _has_get(frame):
                    try:
                        payload_obj = frame.get("payload", b"")
                    except Exception:
                        payload_obj = b""
                else:
                    payload_obj = b""
                if isinstance(payload_obj, bytes | bytearray):
                    payload = bytes(payload_obj)
                elif isinstance(payload_obj, str):
                    payload = payload_obj.encode("utf-8")
                else:
                    payload = b""
                await self.log_frame(
                    direction=direction,
                    payload=payload,
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

    async def close(self) -> None:
        if not self._closed:
            await self.log_event("experiment_stop")
            self._closed = True
            if self._sink is not None and hasattr(self._sink, "close"):
                await self._sink.close()


async def jsonl_sink(
    filepath: str, gzip_compress: bool = False
) -> Callable[[WSFrameLog], Awaitable[None]]:
    path = pathlib.Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

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
