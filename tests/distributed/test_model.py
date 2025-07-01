import time

import pytest

from bot.distributed.model import Job, new_job


def test_job_serialization_roundtrip() -> None:
    job = new_job("browser.goto", "https://example.com", channel=1)
    dumped = job.dumps()
    loaded = Job.loads(dumped)
    assert loaded.id == job.id
    assert loaded.type == job.type
    assert loaded.args == job.args
    assert loaded.kwargs == job.kwargs
    assert loaded.reply_to == job.reply_to
    assert abs(loaded.created_ts - job.created_ts) < 1  # timestamps should be close


def test_job_fields_types() -> None:
    job = new_job("tankpit.spawn", "usw1", bot_name="helper")
    assert isinstance(job.id, str)
    assert isinstance(job.type, str)
    assert isinstance(job.args, tuple)
    assert isinstance(job.kwargs, dict)
    assert isinstance(job.reply_to, str)
    assert isinstance(job.created_ts, float)


def test_job_args_kwargs_content() -> None:
    job = new_job("browser.goto", "https://test.com", channel=5, headless=True)
    assert job.args == ("https://test.com",)
    assert job.kwargs == {"channel": 5, "headless": True}
