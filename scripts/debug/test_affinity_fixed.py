#!/usr/bin/env python
"""Test session affinity after fixing the router."""

import time

import redis

from swarm.celery_app import app
from swarm.tasks.browser import goto, screenshot

print("Testing session affinity with fixed router...")

# Send goto task
print("\n1. Sending goto task...")
goto_result = goto.delay(url="https://example.com")
result = goto_result.get(timeout=60)
task_id = result["task_id"]
print(f"   Got task_id: {task_id}")

# Check Redis for affinity

r = redis.from_url(
    "redis://default:AcKiAAIjcDE1MDQ1NTAwMThkNzQ0N2E0OGRhYzAxZjQyZTQyOTUzN3AxMA@localhost:6380/0",
    decode_responses=True,
)
owner = r.get(f"browser:affinity:{task_id}")
print(f"   Session owner: {owner}")

# Send screenshot - should route to same worker
print(f"\n2. Sending screenshot with task_id={task_id}...")
screenshot_result = screenshot.delay(task_id=task_id)
print(f"   Task ID: {screenshot_result.id}")

try:
    result = screenshot_result.get(timeout=30)
    print(f"   Success! Got screenshot of {len(result.get('data', ''))} bytes")
except Exception as e:
    print(f"   Failed: {type(e).__name__}: {e}")

# Try another screenshot to confirm it still works
print("\n3. Sending another screenshot to confirm affinity...")
screenshot_result2 = screenshot.delay(task_id=task_id)
print(f"   Task ID: {screenshot_result2.id}")

try:
    result = screenshot_result2.get(timeout=30)
    print(f"   Success! Got screenshot of {len(result.get('data', ''))} bytes")
except Exception as e:
    print(f"   Failed: {type(e).__name__}: {e}")

print("\nSession affinity test complete!")
