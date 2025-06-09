# Consolidated public surface for the browser sub‑package.
# Only the stable entry‑points are re‑exported; everything else stays private.

from .engine import BrowserEngine
from .runner import WebRunner
from .exceptions import BrowserError, InvalidURLError  # ← NEW
# BrowserActions & SessionManager removed in #221 – stale references purged

__all__: list[str] = ["BrowserEngine", "WebRunner", "BrowserError", "InvalidURLError"]
