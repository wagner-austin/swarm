import asyncio
from typing import Protocol
from unittest.mock import AsyncMock

import pytest

from bot.distributed.model import Job
from bot.distributed.worker import HandlerFunc, Worker


class DummyBrokerProtocol(Protocol):
    async def consume(self, group: str, consumer: str) -> Job: ...


class DummyBroker:
    async def consume(self, group: str, consumer: str) -> Job:
        raise NotImplementedError


@pytest.mark.asyncio
async def test_dispatch_calls_correct_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    async def handler_a(job: Job) -> None:
        calls.append(("a", job))

    async def handler_b(job: Job) -> None:
        calls.append(("b", job))

    worker = Worker(DummyBroker(), worker_id="w1")  # type: ignore[arg-type]
    worker.register_handler("a.", handler_a)
    worker.register_handler("b.", handler_b)
    job_a = Job(id="1", type="a.do", args=(), kwargs={}, reply_to="r", created_ts=0)
    job_b = Job(id="2", type="b.do", args=(), kwargs={}, reply_to="r", created_ts=0)
    await worker.dispatch(job_a)
    await worker.dispatch(job_b)
    assert calls == [("a", job_a), ("b", job_b)]


@pytest.mark.asyncio
async def test_dispatch_handler_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    async def handler_err(job: Job) -> None:
        raise RuntimeError("fail")

    worker = Worker(DummyBroker(), worker_id="w1")  # type: ignore[arg-type]
    worker.register_handler("err.", handler_err)
    job = Job(id="1", type="err.do", args=(), kwargs={}, reply_to="r", created_ts=0)
    # Should not raise, should log error
    await worker.dispatch(job)


@pytest.mark.asyncio
async def test_dispatch_no_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = Worker(DummyBroker(), worker_id="w1")  # type: ignore[arg-type]
    job = Job(id="1", type="unknown.do", args=(), kwargs={}, reply_to="r", created_ts=0)
    # Should not raise, should log warning
    await worker.dispatch(job)
