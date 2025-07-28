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
from typing import Any, Iterator

from celery import Celery
from kombu import Queue

from swarm.core.settings import Settings

logger = logging.getLogger(__name__)
settings = Settings()

# Get Celery broker URLs from environment
# This can be a single URL or semicolon-separated list for failover
celery_broker_urls = os.getenv("CELERY_BROKER_URLS")

# Fallback to REDIS_URL if CELERY_BROKER_URLS not set
if not celery_broker_urls:
    primary_url = settings.redis.url
    if not primary_url:
        raise ValueError("Neither CELERY_BROKER_URLS nor REDIS_URL configured")
    celery_broker_urls = primary_url
    logger.warning("CELERY_BROKER_URLS not set, using REDIS_URL")

# Parse broker URLs - handle both single URL and semicolon-separated list
broker_urls: str | list[str]
if ";" in celery_broker_urls:
    broker_urls_list = celery_broker_urls.split(";")
    broker_urls = [url.strip() for url in broker_urls_list if url.strip()]
    logger.info(f"Celery configured with {len(broker_urls)} broker URLs for failover")
else:
    broker_urls = celery_broker_urls
    logger.info("Celery configured with single broker URL")

# Determine if we're in production
is_production = os.getenv("ENVIRONMENT", "development").lower() == "production"


# Fix rediss:// URLs for Celery - it requires ssl_cert_reqs in the URL
def fix_ssl_url(url: str) -> str:
    """Add SSL parameters to rediss:// URLs for Celery."""
    if url.startswith("rediss://"):
        if "ssl_cert_reqs" not in url:
            # In production, use proper certificate validation
            # In dev, disable cert validation for Upstash
            cert_reqs = "required" if is_production else "none"
            separator = "&" if "?" in url else "?"
            url += f"{separator}ssl_cert_reqs={cert_reqs}"
    return url


# Process URLs to add SSL parameters
if isinstance(broker_urls, list):
    broker_urls = [fix_ssl_url(url) for url in broker_urls]
else:
    broker_urls = fix_ssl_url(broker_urls)

# Create Celery app
app = Celery("swarm")


# Define a "prefer primary" failover strategy
def prefer_primary_strategy(servers: list[str]) -> Iterator[str]:
    """Try primary first, then cycle through others."""
    if not servers:
        return
    # Always yield primary first
    yield servers[0]
    # Then round-robin through all servers (including primary)
    index = 0
    while True:
        yield servers[index]
        index = (index + 1) % len(servers)


# Configure Celery
app.conf.update(
    broker_url=broker_urls,  # List of URLs for automatic failover!
    # Result backend must be a single URL - use primary only
    result_backend=broker_urls[0] if isinstance(broker_urls, list) else broker_urls,
    broker_failover_strategy=prefer_primary_strategy,  # Always try primary first
    broker_connection_retry_on_startup=True,  # Retry connection on startup
    broker_connection_retry=True,  # Retry broker connection on failure
    broker_connection_max_retries=10,  # Max retries before giving up
    broker_pool_limit=10,  # Connection pool size
    broker_transport_options={
        "priority_steps": list(range(10)),
        "fanout_prefix": True,
        "fanout_patterns": True,
        # Visibility timeout should be longer than the longest task
        "visibility_timeout": 43200,  # 12 hours for long-running tasks
        # Health check interval
        "health_check_interval": 30,  # Check broker health every 30 seconds
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

# Log configuration on startup
if isinstance(broker_urls, list):
    logger.info(f"Celery broker failover configured with {len(broker_urls)} URLs")
    logger.info("Failover strategy: prefer_primary (always try primary first)")
else:
    logger.info("Celery configured with single broker URL")


def get_celery_app() -> Celery:
    """Get the configured Celery application."""
    return app
