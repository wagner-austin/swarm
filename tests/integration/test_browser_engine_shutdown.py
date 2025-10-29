"""Integration test: BrowserEngine shutdown does not leak zombie Chromes.

Validates the architectural change that makes the engine loop the sole owner of
cleanup, drains tasks (no cancel), and stops the loop deterministically.

Requirements:
- Docker daemon available (workers run in containers)
- At least one browser worker running and emitting heartbeats in HAProxy DB 0
"""

from __future__ import annotations

import os
import time
from typing import Final

import docker
import pytest
import redis

from swarm.tasks.browser import goto, screenshot
from tests.integration.utils import check_docker_services_running


@pytest.fixture(scope="module", autouse=True)
def verify_docker_services() -> None:
    async def _check() -> tuple[bool, str]:
        return await check_docker_services_running()

    import asyncio

    ok, msg = asyncio.run(_check())
    if not ok:
        pytest.skip(msg)


def _wait_for_browser_worker(timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    pw = os.getenv("REDIS_PASSWORD", "")
    redis_url = f"redis://default:{pw}@localhost:6380/0" if pw else "redis://localhost:6380/0"
    client = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2)
    try:
        while time.time() < deadline:
            now = time.time()
            fresh_seconds = 90.0
            for key in client.scan_iter(match="worker:heartbeat:browser:*"):
                data = client.hgetall(key)
                ts_str = data.get("timestamp")
                if not ts_str:
                    continue
                try:
                    ts = float(ts_str)
                except Exception:
                    continue
                if (now - ts) <= fresh_seconds:
                    # Found at least one fresh heartbeat
                    time.sleep(0.5)
                    return
            time.sleep(1.0)
    finally:
        try:
            client.close()
        except Exception:
            pass
    raise RuntimeError("No browser worker heartbeat observed in HAProxy DB 0 within timeout")


def _list_browser_worker_containers() -> list[docker.models.containers.Container]:
    client = docker.from_env()
    # Filter by labels applied by autoscaler
    filters = {
        "label": [
            "swarm.project=swarm",
            "discord.worker.type=browser",
        ]
    }
    try:
        containers = client.containers.list(filters=filters)
        return list(containers)
    except Exception:
        return []


def _count_defunct_chrome(container: docker.models.containers.Container) -> int:
    """Return number of Chrome processes in <defunct> (Z) state inside container.

    Uses Docker top via Engine API; does not require 'ps' inside the image.
    """
    try:
        info = container.top()
    except Exception:
        return 0
    titles = info.get("Titles") or []
    rows: list[list[str]] = info.get("Processes") or []
    lower_titles = [str(t).lower() for t in titles]
    # Heuristic: find STAT/S column if present
    stat_index = None
    for i, t in enumerate(lower_titles):
        if t in {"stat", "s", "state"}:
            stat_index = i
            break

    count = 0
    for row in rows:
        line = " ".join(str(x) for x in row)
        if "chrome" not in line.lower():
            continue
        is_defunct = "<defunct>" in line.lower()
        if not is_defunct and stat_index is not None and stat_index < len(row):
            is_defunct = "Z" in str(row[stat_index])
        if is_defunct:
            count += 1
    return count


@pytest.mark.integration
@pytest.mark.docker
@pytest.mark.timeout(120)
def test_engine_shutdown_creates_no_new_zombies() -> None:
    """Start/cleanup multiple sessions; verify no new zombie Chromes are created.

    The test establishes a baseline defunct Chrome count across all browser worker
    containers, exercises several lifecycle cycles via Celery tasks, then asserts
    the final count is not higher than the baseline.
    """
    # Ensure a worker is up and heartbeats are visible in HAProxy DB 0
    _wait_for_browser_worker(timeout=40.0)

    workers = _list_browser_worker_containers()
    assert workers, "No browser worker containers found"

    baseline = sum(_count_defunct_chrome(c) for c in workers)

    # Exercise start/close cycles through Celery tasks
    N: Final[int] = 5
    for i in range(N):
        res = goto.delay(url="https://example.com")
        goto_res = res.get(timeout=45)
        assert goto_res.get("success") is True
        sid = str(goto_res.get("session_id"))
        # Trigger auto-cleanup via screenshot with auto_cleanup=True
        shot = screenshot.delay(session_id=sid, auto_cleanup=True)
        shot_res = shot.get(timeout=45)
        assert shot_res.get("success") is True

    # Re-read defunct count across all browser workers
    final = sum(_count_defunct_chrome(c) for c in workers)

    assert final <= baseline, f"Zombie Chrome count increased: baseline={baseline}, final={final}"
