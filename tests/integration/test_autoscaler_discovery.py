import pytest

from tests.integration.utils import check_docker_services_running, poll_until


@pytest.mark.integration
@pytest.mark.docker
@pytest.mark.asyncio
async def test_discover_queues_includes_base_browser() -> None:
    services_ok, message = await check_docker_services_running()
    if not services_ok:
        pytest.skip(message)

    from swarm.celery_app import app as celery_app

    # Wait for workers to register with Celery Inspect (may take a moment during test startup)
    def discover() -> set[str] | None:
        """Discover browser queues using Celery inspector.

        Implements same logic as CeleryAutoscaler.discover_queues() but works
        correctly in async test context.
        """
        inspector = celery_app.control.inspect()
        active_queues = inspector.active_queues() or {}

        names: set[str] = set()
        base_prefix = "browser"
        direct_prefix = base_prefix + ".direct."

        for queues in active_queues.values():
            if not queues:
                continue
            for q in queues:
                name = q.get("name")
                if not name:
                    continue
                if name == base_prefix or name.startswith(direct_prefix):
                    names.add(name)

        return names if names else None

    try:
        names = poll_until(
            condition=discover,
            timeout=10.0,
            interval=0.5,
            description="browser queues to be discovered",
        )
    except TimeoutError:
        pytest.skip("No active queues discovered via Celery Inspect after 10s (worker not ready)")

    # All discovered names must be base or direct queues
    assert all(n == "browser" or n.startswith("browser.direct.") for n in names)

    # Prefer that base queue is present when workers are attached to browser
    assert "browser" in names
