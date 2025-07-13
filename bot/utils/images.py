"""Utility helpers for basic image manipulation used by commands.

Currently only contains PNG down-sizing logic so screenshots always fit
Discord's 8 MiB upload limit.  Heavyweight image processing libraries are
avoided – we rely on Pillow, which is already in the poetry dependencies
for other features.
"""

from __future__ import annotations

import asyncio
from io import BytesIO

from PIL import Image

__all__ = ["resize_png"]


async def resize_png(data: bytes, *, max_dim: int = 1920) -> bytes:
    """Resize *data* (PNG or JPEG bytes) so that the largest dimension is
    ``max_dim`` pixels.  Runs in a thread-pool so the event-loop is not
    blocked.
    """

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _resize_sync, data, max_dim)


def _resize_sync(data: bytes, max_dim: int) -> bytes:  # pragma: no cover
    with Image.open(BytesIO(data)) as img:
        img.thumbnail((max_dim, max_dim))
        buf = BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
