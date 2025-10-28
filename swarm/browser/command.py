from __future__ import annotations

import asyncio
from typing import TypedDict


class Command(TypedDict, total=True):
    action: str
    args: tuple[object, ...]
    kwargs: dict[str, object]
    future: asyncio.Future[object]
