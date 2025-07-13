import asyncio
from typing import Any, Optional

from bot.distributed.broker import Broker
from bot.distributed.model import new_job


class RemoteTankpitRuntime:
    def __init__(self, broker: Broker) -> None:
        self._broker = broker

    async def spawn(self, server: str, bot_name: str | None = None, **kwargs: Any) -> None:
        job = new_job("tankpit.spawn", server, bot_name=bot_name, **kwargs)
        await self._broker.publish_and_wait(job)

    async def move(self, direction: str, steps: int = 1, *, worker_hint: str | None = None) -> None:
        job = new_job("tankpit.move", direction, steps=steps, worker=worker_hint)
        await self._broker.publish_and_wait(job)

    # Add more methods as needed to mirror the local TankpitRuntime interface
