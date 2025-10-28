#!/usr/bin/env python
"""Check that all monitoring components are working correctly."""

import asyncio
import sys
from typing import Dict, List, Tuple

import aiohttp


async def check_service(
    session: aiohttp.ClientSession, name: str, url: str
) -> tuple[str, bool, str]:
    """Check if a service is responding."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                return name, True, "OK"
            else:
                return name, False, f"HTTP {resp.status}"
    except TimeoutError:
        return name, False, "Timeout"
    except Exception as e:
        return name, False, str(e)


async def check_prometheus_targets(session: aiohttp.ClientSession) -> dict[str, str]:
    """Check Prometheus targets health."""
    try:
        async with session.get("http://localhost:9090/api/v1/targets") as resp:
            if resp.status == 200:
                data = await resp.json()
                targets = {}
                for target in data.get("data", {}).get("activeTargets", []):
                    job = target.get("labels", {}).get("job", "unknown")
                    health = target.get("health", "unknown")
                    targets[job] = health
                return targets
            return {"error": f"HTTP {resp.status}"}
    except Exception as e:
        return {"error": str(e)}


async def check_celery_metrics(session: aiohttp.ClientSession) -> dict[str, float]:
    """Fetch some key Celery metrics."""
    metrics = {}
    try:
        async with session.get("http://localhost:9808/metrics") as resp:
            if resp.status == 200:
                text = await resp.text()
                for line in text.split("\n"):
                    if line.startswith("celery_worker_up"):
                        metrics["workers_up"] = float(line.split()[-1])
                    elif line.startswith("celery_queue_length") and "browser" in line:
                        metrics["browser_queue"] = float(line.split()[-1])
                    elif line.startswith("celery_task_sent_total"):
                        # This is a counter, just check it exists
                        metrics["tasks_sent_exists"] = 1.0
    except Exception:
        pass
    return metrics


async def main() -> int:
    """Run all checks."""
    print("🔍 Checking Swarm Monitoring Stack...\n")

    services = [
        ("Prometheus", "http://localhost:9090/-/ready"),
        ("Grafana", "http://localhost:3000/api/health"),
        ("Loki", "http://localhost:3100/ready"),
        ("Celery Exporter", "http://localhost:9808/health"),
        # Flower removed from default stack
    ]

    async with aiohttp.ClientSession() as session:
        # Check services
        print("📊 Service Health:")
        results = await asyncio.gather(
            *[check_service(session, name, url) for name, url in services]
        )

        all_healthy = True
        for name, healthy, status in results:
            icon = "✅" if healthy else "❌"
            print(f"  {icon} {name}: {status}")
            if not healthy:
                all_healthy = False

        # Check Prometheus targets
        print("\n🎯 Prometheus Targets:")
        targets = await check_prometheus_targets(session)
        if "error" in targets:
            print(f"  ❌ Failed to fetch targets: {targets['error']}")
        else:
            for job, health in targets.items():
                icon = "✅" if health == "up" else "❌"
                print(f"  {icon} {job}: {health}")

        # Check Celery metrics
        print("\n📈 Celery Metrics:")
        metrics = await check_celery_metrics(session)
        if metrics:
            if "workers_up" in metrics:
                print(f"  • Active workers: {int(metrics['workers_up'])}")
            if "browser_queue" in metrics:
                print(f"  • Browser queue depth: {int(metrics['browser_queue'])}")
            if "tasks_sent_exists" in metrics:
                print("  • Task metrics: Available")
        else:
            print("  ❌ No Celery metrics available")

        # Provide dashboard links
        print("\n🔗 Dashboard Links:")
        print("  • Grafana: http://localhost:3000 (admin/admin)")
        print("  • Prometheus: http://localhost:9090")
        # Flower removed

        print("\n📚 Next Steps:")
        if all_healthy:
            print("  1. Import Grafana dashboard ID: 10026")
            print("  2. Configure Loki data source in Grafana")
            print("  3. Run a test task to see metrics flow")
        else:
            print("  1. Fix the failed services above")
            print("  2. Run: docker-compose logs <service-name>")
            print("  3. Check docs/celery-monitoring-setup.md")

        return 0 if all_healthy else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
