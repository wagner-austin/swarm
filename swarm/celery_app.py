"""
Celery configuration for Swarm distributed task queue.

This replaces the custom broker.py with Celery, providing:
- Automatic Redis failover
- Built-in retry logic
- Task routing based on type
- Better connection pooling
- Monitoring via Flower
"""

from __future__ import annotations

import logging
import os
import ssl
from typing import Any, Iterator

import celery.signals as signals
from celery import Celery
from celery.app.task import Task as CeleryTask
from kombu import Queue

from swarm.core.logger_setup import bind_log_context, setup_logging
from swarm.core.settings import Settings

# Initialize logging first
setup_logging()
logger = logging.getLogger(__name__)
settings = Settings()

# Log startup configuration
logger.info("Initializing Celery configuration")
logger.info(f"Environment: {os.getenv('ENVIRONMENT', 'development')}")
logger.info(f"Redis enabled: {settings.redis.enabled}")
logger.info(f"Redis URL from settings: {'SET' if settings.redis.url else 'NOT SET'}")

# Get Celery broker URLs from environment
# This can be a single URL or semicolon-separated list for failover
celery_broker_urls = os.getenv("CELERY_BROKER_URLS")
logger.info(f"CELERY_BROKER_URLS env var: {'SET' if celery_broker_urls else 'NOT SET'}")

# Fallback to REDIS_URL if CELERY_BROKER_URLS not set
if not celery_broker_urls:
    primary_url = settings.redis.url
    if not primary_url:
        logger.error("FATAL: Neither CELERY_BROKER_URLS nor REDIS_URL configured")
        logger.error(
            f"Environment variables checked: CELERY_BROKER_URLS={celery_broker_urls}, REDIS__URL={os.getenv('REDIS__URL')}"
        )
        raise ValueError("Neither CELERY_BROKER_URLS nor REDIS_URL configured")
    celery_broker_urls = primary_url
    logger.warning("CELERY_BROKER_URLS not set, using REDIS_URL from settings")

# Parse broker URLs - handle both single URL and semicolon-separated list
broker_urls: str | list[str]
if ";" in celery_broker_urls:
    broker_urls_list = celery_broker_urls.split(";")
    broker_urls = [url.strip() for url in broker_urls_list if url.strip()]
    logger.info(f"Celery configured with {len(broker_urls)} broker URLs for failover")
    # Log sanitized URLs (hide passwords)
    for i, url in enumerate(broker_urls):
        sanitized = url.split("@")[1] if "@" in url else url
        logger.info(f"  Broker {i + 1}: ...@{sanitized}")
else:
    broker_urls = celery_broker_urls
    sanitized = broker_urls.split("@")[1] if "@" in broker_urls else broker_urls
    logger.info(f"Celery configured with single broker URL: ...@{sanitized}")

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


# Configure Celery
app.conf.update(
    broker_url=broker_urls,  # List of URLs for automatic failover!
    # Result backend must be a single URL - use primary only
    result_backend=broker_urls[0] if isinstance(broker_urls, list) else broker_urls,
    broker_failover_strategy="round-robin",  # Use built-in round-robin strategy
    broker_connection_retry_on_startup=True,  # Retry connection on startup
    broker_connection_retry=True,  # Retry broker connection on failure
    broker_connection_max_retries=10,  # Max retries before giving up
    broker_pool_limit=10,  # Connection pool size
    broker_transport_options={
        "priority_steps": list(range(10)),
        # Visibility timeout should be longer than the longest task
        "visibility_timeout": 43200,  # 12 hours for long-running tasks
        # Health check interval
        "health_check_interval": 30,  # Check broker health every 30 seconds
        # Socket options for better reliability through HAProxy
        "socket_keepalive": True,
        "socket_timeout": 10,
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
    # Event settings for monitoring
    worker_send_task_events=True,  # Send task events for Flower
    task_send_sent_event=True,  # Send event when task is sent
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

# Configure Celery signals for logging context


@signals.task_prerun.connect
def bind_task_context(
    sender: CeleryTask[Any, Any],
    task_id: str,
    task: CeleryTask[Any, Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    **extra: Any,
) -> None:
    """Bind task context to all logs within this task."""
    bind_log_context(job_id=task_id)
    logger.debug(f"Task {task.name} starting with ID {task_id}")


@signals.task_postrun.connect
def unbind_task_context(
    sender: CeleryTask[Any, Any],
    task_id: str,
    task: CeleryTask[Any, Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    retval: Any | None,
    state: str,
    **extra: Any,
) -> None:
    """Clear task context after task completes."""
    logger.debug(f"Task {task.name} completed with ID {task_id}")
    bind_log_context(job_id="-")


@signals.task_failure.connect
def log_task_failure(
    sender: CeleryTask[Any, Any],
    task_id: str,
    exception: Exception,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    traceback: Any,
    einfo: Any,
    **extra: Any,
) -> None:
    """Log task failures with full context."""
    logger.error(f"Task failed with ID {task_id}: {exception}")


# Log configuration on startup
if isinstance(broker_urls, list):
    logger.info(f"Celery broker failover configured with {len(broker_urls)} URLs")
    logger.info("Failover strategy: round-robin")
else:
    logger.info("Celery configured with single broker URL")


def get_celery_app() -> Celery:
    """Get the configured Celery application."""
    return app
