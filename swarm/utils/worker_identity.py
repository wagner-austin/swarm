"""
Typed helpers for canonical worker identity and direct queue naming.

This module centralizes the rules for deriving a worker_id and composing
its direct queue name to prevent format drift across the codebase.
"""

from __future__ import annotations

import socket


def get_os_hostname() -> str:
    """Return the OS hostname for this process/container.

    This is used as a fallback when Celery does not provide a task.request.hostname.
    """
    # socket.gethostname() is sufficient for container IDs and hosts
    host = socket.gethostname().strip()
    return host or "host"


def canonical_worker_id_from_hostname(hostname: str) -> str:
    """Return canonical host-only worker id from a Celery/OS hostname.

    Celery hostnames may be of the form "name@host"; we always return the host part.
    Input may already be host-only; in that case it is returned unchanged.
    """
    hn = hostname.strip()
    return hn.split("@", 1)[1] if "@" in hn else hn


def canonical_worker_id(hostname: str | None) -> str:
    """Return canonical worker id (host-only) from optional hostname.

    Falls back to the OS hostname when the provided value is None or empty.
    """
    base = hostname.strip() if isinstance(hostname, str) else ""
    return canonical_worker_id_from_hostname(base or get_os_hostname())


def direct_queue_name(worker_id: str) -> str:
    """Return the per-worker direct queue for a given canonical worker id."""
    return f"browser.direct.{worker_id}"
