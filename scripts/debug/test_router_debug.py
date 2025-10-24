#!/usr/bin/env python
"""Debug script to test if the router is being called."""

import json
from typing import Any

import redis

from swarm.celery_app import app
from swarm.distributed.browser_router import BrowserSessionRouter
from swarm.tasks.browser import screenshot

# Create router
router = BrowserSessionRouter()

# Test data
task_name = "browser.screenshot"
kwargs = {"task_id": "test-session-123"}

# Manually set a session owner in Redis
# Use redis.from_url which returns a sync client
redis_url = (
    "redis://default:AcKiAAIjcDE1MDQ1NTAwMThkNzQ0N2E0OGRhYzAxZjQyZTQyOTUzN3AxMA@localhost:6380/0"
)
redis_client = redis.from_url(
    redis_url,
    decode_responses=True,  # Use string mode for consistency with router
)
# Assert we have the right methods to help mypy
assert hasattr(redis_client, "setex")
assert hasattr(redis_client, "get")
# For sync redis client, setex should work with strings when decode_responses=True
# But mypy doesn't understand this, so we need to work around it
key = "browser:affinity:test-session-123"
value = "test_worker_123"
ttl = 3600
# Use the untyped interface
success = getattr(redis_client, "setex")(key, ttl, value)
assert success

# Test routing
result = router.route_for_task(task_name, args=(), kwargs=kwargs)
print(f"Router result for {task_name}: {result}")

# Check what's in Redis
owner = redis_client.get("browser:affinity:test-session-123")
print(f"Session owner in Redis: {owner}")

# Test with the Celery app

print(f"\nCelery task_routes config: {app.conf.task_routes}")

# Send a test task to see routing

result = screenshot.apply_async(kwargs={"task_id": "test-session-123"})
print(f"Task sent with ID: {result.id}")

# Check the task's destination
# Note: backend.get_task_meta is not a standard Celery method
# Use result.backend instead to get task info

try:
    # Try to get task state
    print(f"Task state: {result.state}")
    print(f"Task info: {result.info}")
except Exception as e:
    print(f"Could not get task info: {e}")

# Also check what the router returns for a real session from the test
real_session = "c1e6685f-5008-40bc-a423-c6de46f35e6a"
real_owner = redis_client.get(f"browser:affinity:{real_session}")
print(f"\nReal session {real_session} owner: {real_owner}")
real_result = router.route_for_task("browser.screenshot", args=(), kwargs={"task_id": real_session})
print(f"Router result for real session: {real_result}")
