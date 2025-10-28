"""Test script to reproduce SessionLifecycleManager race condition."""

import asyncio
import concurrent.futures
import threading
import time

from swarm.distributed.session_lifecycle import SessionLifecycleManager


def test_concurrent_start():
    """Test what happens when multiple threads call start() simultaneously."""
    manager = SessionLifecycleManager()

    results = []
    errors = []

    def start_manager(thread_id):
        try:
            print(f"Thread {thread_id}: Calling start()")
            manager.start()
            print(f"Thread {thread_id}: start() returned")
            results.append(thread_id)
        except Exception as e:
            print(f"Thread {thread_id}: ERROR: {e}")
            errors.append((thread_id, e))

    # Launch 5 threads simultaneously
    threads = []
    for i in range(5):
        t = threading.Thread(target=start_manager, args=(i,))
        threads.append(t)

    print("Starting all threads...")
    for t in threads:
        t.start()

    print("Waiting for threads to complete...")
    for t in threads:
        t.join(timeout=10)

    print(f"\nResults: {len(results)} succeeded, {len(errors)} failed")
    print(f"Loop running: {manager._loop and manager._loop.is_running()}")
    print(f"Thread alive: {manager._loop_thread and manager._loop_thread.is_alive()}")

    if errors:
        print("\nErrors:")
        for tid, err in errors:
            print(f"  Thread {tid}: {err}")

    # Cleanup
    manager.stop()
    return len(errors) == 0


def test_concurrent_heartbeat():
    """Test what happens when multiple tasks call heartbeat simultaneously."""
    manager = SessionLifecycleManager()
    manager.start()

    async def heartbeat_task(task_id):
        session_id = f"test-session-{task_id}"
        try:
            # Register
            print(f"Task {task_id}: Registering session")
            await manager.register_session(session_id, "test-worker", ttl_seconds=10)

            # Heartbeat multiple times
            for i in range(3):
                print(f"Task {task_id}: Heartbeat {i}")
                await manager.heartbeat_session(session_id)
                await asyncio.sleep(0.1)

            return True
        except Exception as e:
            print(f"Task {task_id}: ERROR: {e}")
            return False

    async def run_concurrent_heartbeats():
        # Run 10 concurrent tasks
        tasks = [heartbeat_task(i) for i in range(10)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results

    print("\nTesting concurrent heartbeats...")
    results = asyncio.run(run_concurrent_heartbeats())

    success_count = sum(1 for r in results if r is True)
    error_count = sum(1 for r in results if isinstance(r, Exception))

    print(f"Results: {success_count} succeeded, {error_count} failed")

    manager.stop()
    return error_count == 0


if __name__ == "__main__":
    print("=" * 60)
    print("Test 1: Concurrent start() calls")
    print("=" * 60)
    success1 = test_concurrent_start()

    print("\n" + "=" * 60)
    print("Test 2: Concurrent heartbeat calls")
    print("=" * 60)
    success2 = test_concurrent_heartbeat()

    print("\n" + "=" * 60)
    if success1 and success2:
        print("✓ All tests passed")
    else:
        print("✗ Some tests failed")
        if not success1:
            print("  - Concurrent start() failed")
        if not success2:
            print("  - Concurrent heartbeat failed")
