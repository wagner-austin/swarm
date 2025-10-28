"""
Thread log-context bootstrapper.

Provides a single, typed entrypoint to bind deployment and service context
for the current thread to avoid drift and unknown fields in logs.
"""

from __future__ import annotations

from typing import TypedDict

from swarm.core.logger_setup import (
    auto_detect_deployment_context,
    bind_deployment_context,
    bind_log_context,
)
from swarm.utils.worker_identity import canonical_worker_id


class ContextSnapshot(TypedDict):
    service: str
    worker_id: str
    hostname: str
    deployment_env: str
    region: str
    container_id: str
    job_id: str


def bootstrap_thread_log_context(
    *,
    service: str,
    hostname: str | None = None,
    worker_id: str | None = None,
    job_id: str | None = None,
) -> ContextSnapshot:
    """Bind deployment and service contextvars for the current thread.

    Args:
        service: Logical service name (e.g., "celery-worker", "celery-router").
        hostname: Optional Celery/OS hostname (may contain '@'). If omitted, the
                  deployment detector is used as a fallback for host binding.
        worker_id: Optional canonical worker id. If omitted, derived from hostname.
        job_id: Optional job id to bind for task-scoped logs.

    Returns:
        A dictionary of resolved context values for observability.
    """
    # Bind deployment context first (hostname/container/env/region)
    deploy_ctx = auto_detect_deployment_context()
    bind_deployment_context(context=deploy_ctx)

    # Resolve worker identity
    resolved_worker_id = worker_id or canonical_worker_id(hostname)

    # Bind service + worker + optional job id
    bind_log_context(service=service, worker_id=resolved_worker_id, job_id=job_id)

    # Return a simple snapshot for debug logs or tests
    snapshot: ContextSnapshot = {
        "service": service,
        "worker_id": resolved_worker_id,
        "hostname": deploy_ctx.get("hostname", "unknown"),
        "deployment_env": deploy_ctx.get("deployment_env", "local"),
        "region": deploy_ctx.get("region", "unknown"),
        "container_id": deploy_ctx.get("container_id", "-"),
        "job_id": job_id or "-",
    }
    return snapshot
