#!/usr/bin/env python
"""Test that direct queues need to be declared for routing to work."""

import time

import redis
from celery import Celery
from celery.app.control import Inspect
from kombu import Queue

from swarm.celery_app import app
from swarm.tasks.browser import goto, screenshot

print("Testing queue declaration requirement...")

# Check current queues
print(f"\nConfigured task_queues: {[q.name for q in app.conf.task_queues]}")

# Get active workers

inspector = Inspect(app=app)
active_queues = inspector.active_queues()
print("\nActive workers:")
for worker, queues in (active_queues or {}).items():
    print(f"  {worker}")
    worker_id = worker.split("@")[1]
    direct_queue_name = f"browser.direct.{worker_id}"
    print(f"    Expected direct queue: {direct_queue_name}")

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

# Try screenshot without declaring queue
print("\n2. Sending screenshot (router should return direct queue)...")
screenshot_result = screenshot.delay(task_id=task_id)
print(f"   Task ID: {screenshot_result.id}")

try:
    result = screenshot_result.get(timeout=10)
    print(f"   Success! Got {len(result.get('data', ''))} bytes")
except Exception as e:
    print(f"   Failed: {type(e).__name__}: {e}")

# Now dynamically add the direct queue to Celery config
if owner:
    direct_queue_name = f"browser.direct.{owner}"
    print(f"\n3. Adding {direct_queue_name} to task_queues...")

    # Create new queue list with the direct queue
    new_queues = list(app.conf.task_queues)
    new_queues.append(Queue(direct_queue_name, routing_key=direct_queue_name))
    app.conf.task_queues = tuple(new_queues)

    print(f"   Updated queues: {[q.name for q in app.conf.task_queues]}")

    # Try again
    print("\n4. Sending screenshot again with queue declared...")
    screenshot_result2 = screenshot.delay(task_id=task_id)
    print(f"   Task ID: {screenshot_result2.id}")

    try:
        result = screenshot_result2.get(timeout=10)
        print(f"   Success! Got {len(result.get('data', ''))} bytes")
    except Exception as e:
        print(f"   Failed: {type(e).__name__}: {e}")
