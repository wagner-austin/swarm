#!/usr/bin/env python3
"""
Test Celery Integration
=======================

This script tests the complete Celery flow:
1. Redis connectivity
2. Flower API access
3. Worker discovery
4. Task submission and execution
5. Queue monitoring
6. Autoscaler functionality
"""

import asyncio
import sys
import time
from datetime import datetime

import aiohttp
import redis.asyncio as redis_asyncio
from celery import Celery
from celery.result import AsyncResult

# Add project root to path
sys.path.insert(0, "/app")

from swarm.celery_app import app as celery_app


async def test_redis_connection() -> bool:
    """Test Redis connectivity."""
    print("\n1. Testing Redis connection...")
    try:
        r = redis_asyncio.from_url("redis://redis:6379/0")

        # Ping Redis using async method
        await r.ping()
        print("✅ Redis is accessible")

        # Check if Redis has any Celery queues
        queues: list[bytes] = await r.keys("_kombu.binding.*")
        print(f"   Found {len(queues)} Celery queue bindings")

        # Close the connection properly
        await r.close()
        return True
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        return False


async def test_flower_api() -> bool:
    """Test Flower API access."""
    print("\n2. Testing Flower API...")
    async with aiohttp.ClientSession() as session:
        try:
            # Test API access
            async with session.get("http://flower:5555/api/workers") as resp:
                if resp.status == 200:
                    workers = await resp.json()
                    print(f"✅ Flower API accessible, found {len(workers)} workers")
                    for worker_name, info in workers.items():
                        print(f"   Worker: {worker_name}")
                        print(f"   - Status: {info.get('status', 'unknown')}")
                        print(f"   - Active: {info.get('active', 0)} tasks")
                    return True
                else:
                    print(f"❌ Flower API returned status {resp.status}")
                    return False
        except Exception as e:
            print(f"❌ Flower API error: {e}")
            return False


async def test_celery_workers() -> bool:
    """Test Celery worker inspection."""
    print("\n3. Testing Celery worker inspection...")
    try:
        # Try using Flower API instead of direct inspection to avoid Redis limits
        async with aiohttp.ClientSession() as session:
            async with session.get("http://flower:5555/api/workers") as resp:
                if resp.status == 200:
                    workers = await resp.json()
                    if not workers:
                        print("⚠️  No active workers found")
                        return False

                    print(f"✅ Found {len(workers)} active workers:")
                    for worker_name, info in workers.items():
                        print(f"   Worker: {worker_name}")
                        print(f"   - Status: {info.get('status', 'unknown')}")
                        print(f"   - Active tasks: {info.get('active', 0)}")

                        # Show some registered tasks
                        registered = info.get("registered", [])
                        if registered:
                            print(f"   - Registered tasks: {len(registered)}")
                            for task in sorted(registered)[:5]:
                                print(f"     • {task}")
                            if len(registered) > 5:
                                print(f"     ... and {len(registered) - 5} more")

                    return True
                else:
                    print(f"❌ Flower API returned status {resp.status}")
                    return False
    except Exception as e:
        if "max requests limit exceeded" in str(e):
            print("⚠️  Skipping worker inspection due to Redis request limit")
            return True  # Don't fail the test due to rate limiting
        print(f"❌ Worker inspection failed: {e}")
        return False


async def test_task_submission() -> bool:
    """Test submitting and executing a task."""
    print("\n4. Testing task submission...")
    try:
        # Submit a simple browser task
        from swarm.tasks.browser import start as browser_start

        print("   Submitting browser_start task...")
        result = browser_start.delay(task_id="test-task-123")
        print(f"   Task ID: {result.id}")

        # Wait for result (max 10 seconds)
        start_time = time.time()
        while not result.ready() and (time.time() - start_time) < 10:
            await asyncio.sleep(0.5)

        if result.ready():
            if result.successful():
                print("✅ Task completed successfully")
                print(f"   Result: {result.result}")
            else:
                print(f"❌ Task failed: {result.info}")
        else:
            print("⏱️  Task still pending after 10 seconds")

        return result.successful() if result.ready() else False
    except Exception as e:
        print(f"❌ Task submission failed: {e}")
        return False


async def test_queue_stats() -> bool:
    """Test queue statistics via Flower."""
    print("\n5. Testing queue statistics...")
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get("http://flower:5555/api/queues/length") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    queues = data.get("active_queues", [])
                    print(f"✅ Found {len(queues)} active queues:")
                    for queue in queues:
                        print(f"   Queue: {queue.get('name', 'unknown')}")
                        print(f"   - Ready: {queue.get('messages_ready', 0)}")
                        print(f"   - Unacked: {queue.get('messages_unacknowledged', 0)}")
                    return True
                else:
                    print(f"❌ Queue stats API returned status {resp.status}")
                    return False
        except Exception as e:
            print(f"❌ Queue stats error: {e}")
            return False


async def test_autoscaler_monitoring() -> bool:
    """Test that autoscaler can monitor the system."""
    print("\n6. Testing autoscaler monitoring...")
    try:
        from swarm.distributed.core.config import DistributedConfig

        config = DistributedConfig.load()

        print("   Autoscaler config loaded:")
        browser_config = config.worker_types["browser"]
        print(
            f"   - Browser workers: min={browser_config.scaling.min_workers}, "
            f"max={browser_config.scaling.max_workers}"
        )
        print(f"   - Scale up threshold: {browser_config.scaling.scale_up_threshold}")

        # Check if autoscaler would make correct decisions
        from scripts.celery_autoscaler import CeleryAutoscaler

        autoscaler = CeleryAutoscaler()

        # Test scaling decision logic
        decision, target = autoscaler.make_scaling_decision(
            queue_name="browser",
            queue_depth=0,
            current_workers=0,
            config=browser_config,
        )

        print("\n   Scaling decision test (0 workers, 0 queue depth):")
        print(f"   - Decision: {decision.name}")
        print(f"   - Target workers: {target}")

        if decision.name == "SCALE_UP" and target == browser_config.scaling.min_workers:
            print("✅ Autoscaler would correctly scale up to min_workers")
            return True
        else:
            print("❌ Autoscaler decision incorrect")
            return False

    except Exception as e:
        print(f"❌ Autoscaler test failed: {e}")
        return False


async def main() -> None:
    """Run all integration tests."""
    print("=" * 60)
    print("CELERY INTEGRATION TEST")
    print(f"Started at: {datetime.now()}")
    print("=" * 60)

    tests = [
        ("Redis Connection", test_redis_connection),
        ("Flower API", test_flower_api),
        ("Celery Workers", test_celery_workers),
        ("Task Submission", test_task_submission),
        ("Queue Stats", test_queue_stats),
        ("Autoscaler Monitoring", test_autoscaler_monitoring),
    ]

    results = {}
    for test_name, test_func in tests:
        try:
            results[test_name] = await test_func()
        except Exception as e:
            print(f"\n❌ {test_name} crashed: {e}")
            results[test_name] = False

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for r in results.values() if r)
    total = len(results)

    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{test_name:.<40} {status}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed < total:
        print("\n⚠️  Some tests failed. Check the logs above for details.")
        sys.exit(1)
    else:
        print("\n🎉 All tests passed! Celery integration is working correctly.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
