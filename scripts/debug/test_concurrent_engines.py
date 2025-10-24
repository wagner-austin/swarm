#!/usr/bin/env python3
"""
Debug script to test concurrent browser engine access and identify deadlocks.

This script simulates what the test_concurrent_session_operations test does
but with extra debugging to understand where things hang.
"""

import asyncio
import logging
import sys
import threading
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(threadName)s] %(name)s - %(levelname)s - %(message)s",
)

# Reduce noise from other loggers
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("celery").setLevel(logging.INFO)


def test_direct_concurrent_access() -> bool:
    """Test concurrent access to browser engines directly (no Celery)."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from swarm.tasks.browser import BrowserTask, _engines, _engines_lock

    print("\n=== Testing Direct Concurrent Access ===\n")

    async def simulate_screenshot(task_id: str, screenshot_id: int) -> bool:
        """Simulate what a screenshot task does."""
        thread_id = threading.current_thread().ident
        loop_id = id(asyncio.get_running_loop())
        print(f"[Screenshot {screenshot_id}] Starting on thread {thread_id}, loop {loop_id}")

        # Create a task instance
        BrowserTask()

        try:
            # This is what the screenshot task does
            print(f"[Screenshot {screenshot_id}] Getting engine for {task_id}")

            # Check if engine already exists
            with _engines_lock:
                existing = _engines.get(task_id)
                if existing and not isinstance(existing, str):  # Not sentinel
                    print(f"[Screenshot {screenshot_id}] Found existing engine")
                    return True
                elif existing == "__creating__":
                    print(f"[Screenshot {screenshot_id}] Engine is being created by another task")

            # Wait a bit to simulate the engine lookup
            await asyncio.sleep(0.05)

            with _engines_lock:
                existing = _engines.get(task_id)
                if existing and not isinstance(existing, str):
                    print(f"[Screenshot {screenshot_id}] Got engine after waiting")
                    return True

            print(f"[Screenshot {screenshot_id}] No engine found")
            return False

        except Exception as e:
            print(f"[Screenshot {screenshot_id}] ERROR: {e}")
            import traceback

            traceback.print_exc()
            return False

    async def run_test() -> bool:
        """Run the concurrent test."""
        task_id = "test-session-123"

        # Check initial state
        with _engines_lock:
            print(f"[Main] Initial engine registry: {list(_engines.keys())}")

        # Mock a browser engine
        mock_engine = MagicMock()
        mock_engine._loop = asyncio.get_running_loop()
        mock_engine.screenshot = AsyncMock()

        # Simulate engine creation by putting it in the registry
        print(f"[Main] Simulating engine creation for task {task_id}")
        with _engines_lock:
            _engines[task_id] = mock_engine
            print(f"[Main] Engine registry after creation: {list(_engines.keys())}")

        # Now run concurrent screenshots
        print("\n[Main] Starting 3 concurrent screenshot tasks")
        tasks = []
        for i in range(3):
            tasks.append(simulate_screenshot(task_id, i))

        # Run them concurrently
        print("[Main] Gathering concurrent tasks...")
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Check results
        print(f"\n[Main] Results: {results}")
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"[Main] Screenshot {i} failed with: {result}")
            elif result:
                print(f"[Main] Screenshot {i} succeeded")
            else:
                print(f"[Main] Screenshot {i} returned False")

        # Cleanup
        with _engines_lock:
            if task_id in _engines:
                del _engines[task_id]
                print(f"[Main] Cleaned up engine for {task_id}")

        return all(r is True for r in results)

    # Run the async test
    success = asyncio.run(run_test())
    print(f"\n=== Test {'PASSED' if success else 'FAILED'} ===\n")
    return success


def test_celery_concurrent_access() -> None:
    """Test concurrent access through Celery tasks."""
    print("\n=== Testing Celery Concurrent Access ===\n")

    from swarm.tasks.browser import cleanup, goto, screenshot

    # Start with goto
    print("[Celery] Sending goto task")
    goto_result = goto.delay(url="https://example.com")
    print(f"[Celery] Goto task ID: {goto_result.id}")

    try:
        goto_res = goto_result.get(timeout=30)
        print(f"[Celery] Goto completed: {goto_res}")
        task_id = goto_res["task_id"]
    except Exception as e:
        print(f"[Celery] Goto failed: {e}")
        assert False, f"Goto failed: {e}"

    # Send concurrent screenshots
    print(f"\n[Celery] Sending 3 concurrent screenshot tasks for session {task_id}")
    screenshot_tasks = []
    for i in range(3):
        task = screenshot.delay(task_id=task_id)
        print(f"[Celery] Screenshot {i} task ID: {task.id}")
        screenshot_tasks.append(task)

    # Wait for results
    success = True
    for i, task in enumerate(screenshot_tasks):
        print(f"\n[Celery] Waiting for screenshot {i} (task {task.id})...")
        try:
            task.get(timeout=10)
            print(f"[Celery] Screenshot {i} completed")
        except Exception as e:
            print(f"[Celery] Screenshot {i} FAILED: {e}")
            success = False
            break

    # Cleanup
    print(f"\n[Celery] Cleaning up session {task_id}")
    cleanup.delay(task_id=task_id).get(timeout=10)

    print(f"\n=== Celery Test {'PASSED' if success else 'FAILED'} ===\n")
    assert success, "One or more screenshot tasks failed"


def check_engine_state() -> None:
    """Check the current state of browser engines."""
    from swarm.tasks.browser import _engines, _engines_lock

    print("\n=== Current Engine State ===")
    with _engines_lock:
        print(f"Total engines: {len(_engines)}")
        for task_id, engine in _engines.items():
            if isinstance(engine, str):
                print(f"  {task_id}: {engine} (sentinel)")
            else:
                print(
                    f"  {task_id}: BrowserEngine(loop={id(engine._loop) if hasattr(engine, '_loop') else 'None'})"
                )
    print("===========================\n")


def main() -> None:
    """Run all debug tests."""
    import sys

    # Check command line args
    if len(sys.argv) > 1:
        test_type = sys.argv[1]
    else:
        test_type = "all"

    print(f"Running test type: {test_type}")

    if test_type in ["direct", "all"]:
        print("\n" + "=" * 60)
        print("TESTING DIRECT CONCURRENT ACCESS")
        print("=" * 60)
        direct_success = test_direct_concurrent_access()
        check_engine_state()

    if test_type in ["celery", "all"]:
        print("\n" + "=" * 60)
        print("TESTING CELERY CONCURRENT ACCESS")
        print("=" * 60)
        # Check if Celery workers are running
        try:
            from swarm.celery_app import app

            inspector = app.control.inspect()
            active = inspector.active()
            if not active:
                print("ERROR: No Celery workers are running!")
                print("Start workers with: make celery-worker")
                sys.exit(1)
            print(f"Found {len(active)} Celery workers: {list(active.keys())}")
        except Exception as e:
            print(f"ERROR checking Celery workers: {e}")
            sys.exit(1)

        test_celery_concurrent_access()
        check_engine_state()
        celery_success = True  # test_celery_concurrent_access uses assertions

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    if test_type == "all":
        print(f"Direct test: {'PASSED' if direct_success else 'FAILED'}")
        print(f"Celery test: {'PASSED' if celery_success else 'FAILED'}")
    elif test_type == "direct":
        print(f"Direct test: {'PASSED' if direct_success else 'FAILED'}")
    elif test_type == "celery":
        print(f"Celery test: {'PASSED' if celery_success else 'FAILED'}")


if __name__ == "__main__":
    main()
