import asyncio
from typing import Any, Optional

from bot.distributed.broker import Broker
from bot.distributed.model import new_job


class RemoteBrowserRuntime:
    def __init__(self, broker: Broker) -> None:
        self._broker = broker

    async def goto(self, url: str, *, worker_hint: str | None = None) -> None:
        job = new_job("browser.goto", url, worker=worker_hint)
        await self._broker.publish(job)
        # Optionally, wait for a result or status here if you want synchronous feedback

    async def click(self, selector: str, *, worker_hint: str | None = None) -> None:
        job = new_job("browser.click", selector, worker=worker_hint)
        await self._broker.publish(job)

    # Add more methods as needed to mirror the local BrowserRuntime interface
