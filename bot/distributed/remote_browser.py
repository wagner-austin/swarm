import asyncio
from typing import Any, Optional

from bot.distributed.broker import Broker
from bot.distributed.model import new_job


class RemoteBrowserRuntime:
    def __init__(self, broker: Broker) -> None:
        self._broker = broker

    async def goto(self, url: str, *, worker_hint: str | None = None) -> None:
        job = new_job("browser.goto", url, worker=worker_hint)
        await self._broker.publish_and_wait(job)

    async def click(self, selector: str, *, worker_hint: str | None = None) -> None:
        job = new_job("browser.click", selector, worker=worker_hint)
        await self._broker.publish(job)

    async def start(self, worker_hint: str | None = None) -> None:
        job = new_job("browser.start", worker=worker_hint)
        await self._broker.publish_and_wait(job)

    async def screenshot(
        self, filename: str | None = None, *, worker_hint: str | None = None
    ) -> bytes:
        job = new_job("browser.screenshot", filename=filename, worker=worker_hint)
        result = await self._broker.publish_and_wait(job)
        if not result.get("success"):
            raise RuntimeError(result.get("error", "Screenshot failed"))
        # Assume result['data'] is base64 encoded image bytes
        import base64

        return base64.b64decode(result["data"])

    async def close_channel(self, channel_id: int, *, worker_hint: str | None = None) -> None:
        job = new_job("browser.close_channel", channel_id=channel_id, worker=worker_hint)
        result = await self._broker.publish_and_wait(job)
        if not result.get("success"):
            raise RuntimeError(result.get("error", "Close channel failed"))

    async def close_all(self, *, worker_hint: str | None = None) -> None:
        job = new_job("browser.close_all", worker=worker_hint)
        result = await self._broker.publish_and_wait(job)
        if not result.get("success"):
            raise RuntimeError(result.get("error", "Close all failed"))

    async def status(self, *, worker_hint: str | None = None) -> dict[str, Any]:
        job = new_job("browser.status", worker=worker_hint)
        result = await self._broker.publish_and_wait(job)
        if not result.get("success"):
            raise RuntimeError(result.get("error", "Status failed"))
        data = result.get("data", {})
        if not isinstance(data, dict):
            raise RuntimeError("Status data is not a dict")
        return data
