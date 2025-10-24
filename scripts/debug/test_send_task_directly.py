#!/usr/bin/env python
"""Test sending tasks directly to worker queues."""

import time
from typing import Any

from celery import Celery
from celery.app.control import Inspect
from kombu import Exchange, Queue
from kombu.messaging import Producer

from swarm.celery_app import app
from swarm.tasks.browser import screenshot

# Test direct send
print("Testing direct task send to worker queue...")

# First check active workers

inspector = Inspect(app=app)
active_queues = inspector.active_queues()
print("\nActive workers:")
for worker, queues in (active_queues or {}).items():
    print(f"  {worker}")

# Pick first worker
if active_queues:
    worker_name = list(active_queues.keys())[0]
    worker_id = worker_name.split("@")[1]
    direct_queue = f"browser.direct.{worker_id}"

    print(f"\nSending screenshot task directly to queue: {direct_queue}")

    # Method 1: Using apply_async with exchange/routing_key

    result = screenshot.apply_async(
        kwargs={"task_id": "test-direct-123"},
        queue=direct_queue,
        exchange=direct_queue,
        routing_key=direct_queue,
    )
    print(f"Task sent with ID: {result.id}")

    try:
        res = result.get(timeout=10)
        print(f"Success! Result: {res}")
    except Exception as e:
        print(f"Failed: {type(e).__name__}: {e}")

    # Method 2: Using send_task
    print("\nTrying send_task method...")
    result2 = app.send_task(
        "browser.screenshot",
        kwargs={"task_id": "test-direct-456"},
        queue=direct_queue,
        exchange=direct_queue,
        routing_key=direct_queue,
    )
    print(f"Task sent with ID: {result2.id}")

    try:
        res2 = result2.get(timeout=10)
        print(f"Success! Result: {res2}")
    except Exception as e:
        print(f"Failed: {type(e).__name__}: {e}")

    # Method 3: Declare the queue first
    print("\nTrying with queue declaration...")
    # The producer_pool is a kombu.pools.ProducerPool which has acquire method
    # It returns a Producer object from kombu.messaging
    producer_pool: Any = app.producer_pool  # Type is not exported by Celery
    with producer_pool.acquire(block=True) as producer:
        # Declare the exchange and queue
        exchange = Exchange(direct_queue, type="direct")
        queue = Queue(direct_queue, exchange=exchange, routing_key=direct_queue)
        # The producer has a channel property (not attribute) that's a ChannelPromise
        # When accessed, it returns the actual channel
        channel = producer.channel
        # Queue.declare is a method on Queue instances
        queue_instance: Any = queue  # kombu types not fully exported
        queue_instance.declare(channel)

        # Now send the task
        result3 = app.send_task(
            "browser.screenshot",
            kwargs={"task_id": "test-direct-789"},
            queue=direct_queue,
            exchange=direct_queue,
            routing_key=direct_queue,
            producer=producer,
        )
        print(f"Task sent with ID: {result3.id}")

    try:
        res3 = result3.get(timeout=10)
        print(f"Success! Result: {res3}")
    except Exception as e:
        print(f"Failed: {type(e).__name__}: {e}")
