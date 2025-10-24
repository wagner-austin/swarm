#!/usr/bin/env python
"""Test direct routing to worker queues."""

# Enable debug logging
import logging
import time

import redis
from celery import Celery
from celery.app.control import Inspect

from swarm.celery_app import app
from swarm.tasks.browser import goto, screenshot

logging.basicConfig(level=logging.DEBUG)

print("Starting direct routing test...")

# First, let's check what workers are available

inspector = Inspect(app=app)
active_queues = inspector.active_queues()
print("\nActive workers and their queues:")
for worker, queues in (active_queues or {}).items():
    print(f"  {worker}:")
    for q in queues:
        print(f"    - {q['name']}")

# Send a goto task normally (should work)
print("\n1. Sending goto task (normal routing)...")
goto_result = goto.delay(url="https://example.com")
print(f"   Task ID: {goto_result.id}")

# Wait for it to complete
print("   Waiting for completion...")
result = goto_result.get(timeout=60)
print(f"   Result: {result}")
task_id = result["task_id"]

# Now send screenshot with same task_id (should route to same worker)
print(f"\n2. Sending screenshot task with task_id={task_id}...")
screenshot_result = screenshot.delay(task_id=task_id)
print(f"   Task ID: {screenshot_result.id}")

# Wait for it
print("   Waiting for completion...")
try:
    result = screenshot_result.get(timeout=30)
    print(f"   Result: Success! Got screenshot of {len(result.get('data', ''))} bytes")
except Exception as e:
    print(f"   Result: Failed with {type(e).__name__}: {e}")

# Check Redis to see what's in the affinity registry

# Use redis.from_url for sync client
redis_url = (
    "redis://default:AcKiAAIjcDE1MDQ1NTAwMThkNzQ0N2E0OGRhYzAxZjQyZTQyOTUzN3AxMA@localhost:6380/0"
)
r = redis.from_url(
    redis_url,
    decode_responses=True,  # Use string mode to avoid decode errors
)
# Assert we have the scan_iter method
assert hasattr(r, "scan_iter")
assert hasattr(r, "get")
# Use getattr to work around mypy's limitations with Redis generics
scan_iter = getattr(r, "scan_iter")
affinity_keys = list(scan_iter("browser:affinity:*"))
print(f"\n3. Session affinity keys in Redis: {len(affinity_keys)}")
for key in affinity_keys:
    owner = r.get(key)
    print(f"   {key}: {owner if owner else 'None'}")
