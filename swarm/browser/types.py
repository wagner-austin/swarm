from typing import Literal, NotRequired, TypedDict


class Command(TypedDict):
    """A unit of work the runtime executes inside the Playwright thread."""

    action: str
    args: tuple[object, ...]
    kwargs: dict[str, object]
    future: object


__all__ = ["Command"]


class BrowserEngineStatus(TypedDict):
    """Structured status for a single browser engine/session."""

    worker_id: str
    status: Literal["healthy", "unhealthy", "error", "not_found", "unknown"]
    browser_active: bool
    page_active: bool
    url: str | None
    uptime: float
    sessions: int
    error: NotRequired[str | None]
    session_id: NotRequired[str]


class BrowserStatusAggregate(TypedDict):
    """Aggregate status returned to callers (e.g., /web status)."""

    active_sessions: int
    sessions: list[BrowserEngineStatus]


class StatusTaskResponse(TypedDict):
    """Envelope returned by the Celery task browser.status."""

    success: bool
    data: BrowserEngineStatus


__all__ += [
    "BrowserEngineStatus",
    "BrowserStatusAggregate",
    "StatusTaskResponse",
]


# --- Task result shapes ----------------------------------------------------


class GotoTaskResponse(TypedDict):
    success: bool
    session_id: str
    url: str


class ClickTaskResponse(TypedDict):
    success: bool
    session_id: str
    selector: str


class FillTaskResponse(TypedDict):
    success: bool
    session_id: str
    selector: str
    text: str


class UploadTaskResponse(TypedDict):
    success: bool
    session_id: str
    selector: str
    file_path: str


class WaitForTaskResponse(TypedDict):
    success: bool
    session_id: str
    selector: str
    state: Literal["visible", "hidden", "attached", "detached"]


class ScreenshotTaskResponse(TypedDict):
    success: bool
    session_id: str
    data: str  # base64-encoded PNG bytes


class StartTaskResponse(TypedDict):
    success: bool
    session_id: str


class CleanupTaskResponse(TypedDict):
    success: bool
    session_id: str


class ScrapeDataItem(TypedDict):
    action: dict[str, object]
    result: dict[str, object]


class ScrapeDataResponse(TypedDict):
    success: bool
    session_id: str
    url: str
    results: list[ScrapeDataItem]


__all__ += [
    "GotoTaskResponse",
    "ClickTaskResponse",
    "FillTaskResponse",
    "UploadTaskResponse",
    "WaitForTaskResponse",
    "ScreenshotTaskResponse",
    "StartTaskResponse",
    "CleanupTaskResponse",
    "ScrapeDataResponse",
    "ScrapeDataItem",
]
