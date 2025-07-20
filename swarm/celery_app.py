"""
Celery configuration for Swarm distributed task queue.

This replaces the custom broker.py with Celery, providing:
- Automatic Redis failover
- Built-in retry logic
- Task routing based on type
- Better connection pooling
- Monitoring via Flower
"""

import logging
import os
import ssl
from typing import Any

from celery import Celery
from kombu import Queue

from swarm.core.settings import Settings

logger = logging.getLogger(__name__)
settings = Settings()

# Single authoritative Redis URL
redis_url = settings.redis.url
if not redis_url:
    raise ValueError("REDIS_URL not configured in settings")

# Fix rediss:// URLs for Celery - it requires ssl_cert_reqs in the URL
if redis_url.startswith("rediss://"):
    if "ssl_cert_reqs" not in redis_url:
        # Add ssl_cert_reqs=none to the URL
        if "?" in redis_url:
            redis_url += "&ssl_cert_reqs=none"
        else:
            redis_url += "?ssl_cert_reqs=none"

# Create Celery app with single Redis URL
app = Celery("swarm")

# Configure Celery
app.conf.update(
    broker_url=redis_url,
    result_backend=redis_url,
    broker_transport_options={
        "priority_steps": list(range(10)),
        "visibility_timeout": 3600,  # 1 hour
        "fanout_prefix": True,
        "fanout_patterns": True,
        # SSL settings for rediss:// URLs
        "ssl_cert_reqs": ssl.CERT_NONE,  # Upstash doesn't require client certs
    },
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Retry settings
    task_acks_late=True,  # Acknowledge after task completion
    task_reject_on_worker_lost=True,
    # Performance settings
    worker_prefetch_multiplier=1,  # One task at a time for browser workers
    worker_max_tasks_per_child=100,  # Restart worker after 100 tasks
    # Error handling
    task_default_retry_delay=30,  # 30 seconds
    task_max_retries=3,
)

# Define task queues for different job types
app.conf.task_routes = {
    "browser.*": {"queue": "browser"},
    "browser.cleanup": {"queue": "browser"},  # Explicit for clarity
    "browser.scrape_data": {"queue": "default"},  # Orchestration task runs on default queue
    "tankpit.*": {"queue": "tankpit"},
    "llm.*": {"queue": "llm"},
}

app.conf.task_queues = (
    Queue("browser", routing_key="browser", priority=5),
    Queue("tankpit", routing_key="tankpit", priority=3),
    Queue("llm", routing_key="llm", priority=1),
    Queue("default", routing_key="default", priority=0),
)

# Import tasks to register them
app.autodiscover_tasks(["swarm.tasks"])


def get_celery_app() -> Celery:
    """Get the configured Celery application."""
    return app
