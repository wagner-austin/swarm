"""
Unit tests for Celery signal handlers in swarm.celery_app.

Covers the task_prerun fallback path to ensure the service context
is still bound when bootstrap fails, preventing 'unknown' service fields
in task logs.
"""

from __future__ import annotations

import logging

import pytest

from swarm.core.logger_setup import _ContextFilter


class _DummyRequest:
    def __init__(self, hostname: str | None = None) -> None:
        self.hostname = hostname


class _DummyTask:
    def __init__(self, name: str = "dummy", hostname: str | None = None) -> None:
        self.name = name
        self.request = _DummyRequest(hostname)


def _raising_bootstrap(
    *,
    service: str,
    hostname: str | None = None,
    worker_id: str | None = None,
    job_id: str | None = None,
) -> None:  # pragma: no cover
    # Simulate the bootstrap raising regardless of inputs
    raise RuntimeError("simulated bootstrap failure")


def _make_record() -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="probe",
        args=(),
        exc_info=None,
    )


def test_task_prerun_fallback_binds_service_and_jobid(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """If bootstrap fails, the fallback should still bind service + job_id."""
    from swarm.celery_app import bind_task_context

    # Force the import inside bind_task_context to raise at call time
    monkeypatch.setattr(
        "swarm.utils.context_bootstrap.bootstrap_thread_log_context",
        _raising_bootstrap,
        raising=True,
    )

    # Capture warning from fallback
    caplog.set_level(logging.WARNING, logger="swarm.celery_app")

    # Invoke the signal handler directly
    task_id = "tid-123"
    task = _DummyTask(name="dummy-task", hostname="name@host")
    bind_task_context(sender=None, task_id=task_id, task=task, args=(), kwargs={})

    # Verify warning emitted about fallback
    assert any(
        rec.levelno >= logging.WARNING and "Failed to bootstrap full task context" in rec.message
        for rec in caplog.records
    )

    # Verify that service and job_id are bound in logging context via ContextFilter
    rec = _make_record()
    ctx = _ContextFilter()
    ctx.filter(rec)

    assert getattr(rec, "service") == "celery-worker"
    assert getattr(rec, "job_id") == task_id
