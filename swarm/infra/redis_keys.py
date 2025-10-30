from __future__ import annotations

from typing import Final

# Affinity mapping for session ownership
AFFINITY_PREFIX: Final[str] = "browser:affinity:"

# Worker heartbeat keys (TTL denotes liveness)
HEARTBEAT_PREFIX: Final[str] = "worker:heartbeat:browser:"

# Worker registry keys (static metadata + status)
WORKER_PREFIX: Final[str] = "browser:worker:"

# Per-worker session set
WORKER_SESSIONS_PREFIX: Final[str] = "browser:worker_sessions:"

# Transient session state (e.g., current URL)
SESSION_STATE_PREFIX: Final[str] = "browser:session:"

# Health snapshot hash
HEALTH_KEY: Final[str] = "browser:health"


def affinity_key(session_id: str) -> str:
    return f"{AFFINITY_PREFIX}{session_id}"


def heartbeat_key(worker_id: str) -> str:
    return f"{HEARTBEAT_PREFIX}{worker_id}"


def worker_key(worker_id: str) -> str:
    return f"{WORKER_PREFIX}{worker_id}"


def worker_sessions_key(worker_id: str) -> str:
    return f"{WORKER_SESSIONS_PREFIX}{worker_id}"


def session_state_key(session_id: str) -> str:
    return f"{SESSION_STATE_PREFIX}{session_id}"


# ---------------------------------------------------------------------------
# Scan patterns (centralized to prevent drift)
# ---------------------------------------------------------------------------
def affinity_scan_pattern() -> str:
    return f"{AFFINITY_PREFIX}*"


def heartbeat_scan_pattern() -> str:
    return f"{HEARTBEAT_PREFIX}*"


def workers_scan_pattern() -> str:
    return f"{WORKER_PREFIX}*"


def worker_sessions_scan_pattern() -> str:
    return f"{WORKER_SESSIONS_PREFIX}*"


def session_state_scan_pattern() -> str:
    return f"{SESSION_STATE_PREFIX}*"


# ---------------------------------------------------------------------------
# Key parsers (authoritative; avoid ad-hoc rsplit/substring)
# ---------------------------------------------------------------------------
def session_id_from_affinity_key(key: str) -> str:
    if not key.startswith(AFFINITY_PREFIX):
        raise ValueError(f"Not an affinity key: {key}")
    return key[len(AFFINITY_PREFIX) :]


def worker_id_from_heartbeat_key(key: str) -> str:
    if not key.startswith(HEARTBEAT_PREFIX):
        raise ValueError(f"Not a heartbeat key: {key}")
    return key[len(HEARTBEAT_PREFIX) :]


def worker_id_from_worker_key(key: str) -> str:
    if not key.startswith(WORKER_PREFIX):
        raise ValueError(f"Not a worker key: {key}")
    return key[len(WORKER_PREFIX) :]


def worker_id_from_worker_sessions_key(key: str) -> str:
    if not key.startswith(WORKER_SESSIONS_PREFIX):
        raise ValueError(f"Not a worker sessions key: {key}")
    return key[len(WORKER_SESSIONS_PREFIX) :]


def session_id_from_session_state_key(key: str) -> str:
    if not key.startswith(SESSION_STATE_PREFIX):
        raise ValueError(f"Not a session state key: {key}")
    return key[len(SESSION_STATE_PREFIX) :]
