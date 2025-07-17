from __future__ import annotations

import asyncio
from typing import Any, TypedDict


class Command(TypedDict, total=True):
    action: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    future: asyncio.Future[Any]
