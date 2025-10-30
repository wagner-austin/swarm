"""Test script to reproduce worker heartbeat TTL extension issue."""

import os
import time

import redis

from swarm.distributed.worker_lifecycle import WorkerLifecycle
from swarm.infra.redis_keys import heartbeat_key as hb, worker_key as wk, worker_sessions_key as ws


def test_heartbeat_extends_ttl():
    """Reproduce the test_heartbeat_extends_ttl_continuously failure."""

    # Connect to test Redis (DB 15)
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    # Use DB 15 for testing
    test_redis_url = redis_url.rsplit("/", 1)[0] + "/15"

    print(f"Connecting to Redis: {test_redis_url}")
    redis_client = redis.from_url(test_redis_url, decode_responses=True)

    # Clear any existing data
    worker_key = wk("test-worker")
    sessions_key = ws("test-worker")
    heartbeat_key = hb("test-worker")

    redis_client.delete(worker_key, sessions_key, heartbeat_key)

    # Create worker with short intervals for testing
    from swarm.infra.redis_protocols import wrap_redis_sync

    worker = WorkerLifecycle("test-worker", redis_client=wrap_redis_sync(redis_client))
    worker.heartbeat_interval = 0.2  # 200ms
    worker.heartbeat_timeout = 1  # 1 second TTL

    print(
        f"Worker config: interval={worker.heartbeat_interval}s, timeout={worker.heartbeat_timeout}s"
    )

    # Register worker
    print("\nRegistering worker...")
    worker.register()

    # Check initial state
    print("Initial state:")
    print(f"  worker key exists: {redis_client.exists(worker_key)}")
    print(f"  worker key TTL: {redis_client.ttl(worker_key)}")
    print(f"  heartbeat key exists: {redis_client.exists(heartbeat_key)}")
    print(f"  heartbeat key TTL: {redis_client.ttl(heartbeat_key)}")

    # Start heartbeat
    print("\nStarting heartbeat...")
    worker.start_heartbeat()

    # Monitor for 2 seconds (longer than TTL)
    print("\nMonitoring keys for 2 seconds...")
    for i in range(10):  # 10 iterations * 0.2s = 2s
        time.sleep(0.2)

        worker_exists = redis_client.exists(worker_key)
        worker_ttl = redis_client.ttl(worker_key)
        heartbeat_exists = redis_client.exists(heartbeat_key)
        heartbeat_ttl = redis_client.ttl(heartbeat_key)

        print(
            f"  [{i * 0.2:.1f}s] worker: exists={worker_exists}, ttl={worker_ttl}s | "
            f"heartbeat: exists={heartbeat_exists}, ttl={heartbeat_ttl}s"
        )

        if not worker_exists:
            print(f"\n✗ FAILURE: Worker key disappeared after {i * 0.2:.1f}s!")
            worker.stop_heartbeat()
            return False

    print("\nSUCCESS: Worker key remained alive")
    worker.stop_heartbeat()

    # Cleanup
    redis_client.delete(worker_key, sessions_key, heartbeat_key)
    redis_client.close()
    return True


def test_pipeline_behavior():
    """Test if pipeline is working as expected."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    test_redis_url = redis_url.rsplit("/", 1)[0] + "/15"

    print("\nTesting pipeline behavior...")
    redis_client = redis.from_url(test_redis_url, decode_responses=True)

    test_key = "test:pipeline:key"
    redis_client.delete(test_key)

    # Test 1: Normal operation
    print("\nTest 1: Normal pipeline operation")
    with redis_client.pipeline() as pipe:
        pipe.hset(test_key, "field1", "value1")
        pipe.expire(test_key, 10)
        pipe.execute()

    exists = redis_client.exists(test_key)
    ttl = redis_client.ttl(test_key)
    print(f"  After pipeline: exists={exists}, ttl={ttl}")

    # Test 2: Delete then expire (the bug pattern)
    print("\nTest 2: Delete then expire (potential bug)")
    redis_client.delete(test_key)

    with redis_client.pipeline() as pipe:
        pipe.delete(test_key)  # Delete it
        pipe.expire(test_key, 10)  # Try to set TTL on deleted key
        results = pipe.execute()
        print(f"  Pipeline results: {results}")

    exists_after = redis_client.exists(test_key)
    print(f"  After delete+expire: exists={exists_after}")
    print("  → This demonstrates that EXPIRE on deleted key returns 0 (key not found)")

    # Test 3: Query inside pipeline context
    print("\nTest 3: Query outside pipeline (worker_lifecycle pattern)")
    redis_client.hset(test_key, "field1", "value1")

    with redis_client.pipeline() as pipe:
        # This executes immediately, NOT in the pipeline!
        scard_result = redis_client.scard("some:set:key")
        print(f"  scard result: {scard_result}")

        pipe.hset(test_key, "field2", "value2")
        pipe.expire(test_key, 10)
        pipe_results = pipe.execute()
        print(f"  Pipeline results: {pipe_results}")

    redis_client.delete(test_key)
    redis_client.close()


if __name__ == "__main__":
    print("=" * 70)
    print("Test 1: Pipeline behavior analysis")
    print("=" * 70)
    test_pipeline_behavior()

    print("\n" + "=" * 70)
    print("Test 2: Worker heartbeat TTL extension")
    print("=" * 70)
    success = test_heartbeat_extends_ttl()

    if success:
        print("\nSUCCESS: Heartbeat test passed")
    else:
        print("\nFAILURE: Heartbeat test failed")
