"""
Celery configuration for Swarm distributed task queue.

This replaces the custom broker.py with Celery, providing:
- Automatic Redis failover
- Built-in retry logic
- Task routing based on type
- Better connection pooling
- Monitoring via Prometheus/Grafana
"""

from __future__ import annotations

import logging
import os
import ssl
from typing import Iterator

import celery.signals as signals
from celery.app.base import Celery
from celery.app.task import Task as CeleryTask
from kombu import Queue

import swarm.distributed.lifecycle_signals as _lifecycle_signals  # noqa: F401
from swarm.core.logger_setup import bind_log_context
from swarm.core.settings import Settings
from swarm.distributed.browser_router import BrowserSessionRouter

logger = logging.getLogger(__name__)

settings = Settings()

# Determine if we're in production (standardized on DEPLOYMENT_ENV)
is_production = os.getenv("DEPLOYMENT_ENV", "local").lower() == "production"


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


def create_celery(
    name: str = "swarm",
    broker_url: str | None = None,
    result_backend: str | None = None,
) -> Celery:
    """Create a Celery application with the given configuration.

    This factory pattern allows tests to create isolated Celery instances
    without affecting the global app state.
    """
    # Use provided broker URL or fall back to environment
    if broker_url is None:
        # Get Celery broker URLs from environment
        # This can be a single URL or semicolon-separated list for failover
        celery_broker_urls = os.getenv("CELERY_BROKER_URLS")
        # Fallback to REDIS_URL if CELERY_BROKER_URLS not set
        if not celery_broker_urls:
            primary_url = settings.redis.url
            if not primary_url:
                raise ValueError("Neither CELERY_BROKER_URLS nor REDIS_URL configured")
            celery_broker_urls = primary_url
    else:
        celery_broker_urls = broker_url

    # Parse broker URLs - handle both single URL and semicolon-separated list
    broker_urls: str | list[str]
    if ";" in celery_broker_urls:
        broker_urls_list = celery_broker_urls.split(";")
        broker_urls = [url.strip() for url in broker_urls_list if url.strip()]
    else:
        broker_urls = celery_broker_urls

    # Process URLs to add SSL parameters
    if isinstance(broker_urls, list):
        broker_urls = [fix_ssl_url(url) for url in broker_urls]
    else:
        broker_urls = fix_ssl_url(broker_urls)

    # Use provided result backend or default to broker URL
    if result_backend is None:
        result_backend = broker_urls[0] if isinstance(broker_urls, list) else broker_urls

    # Create Celery app
    celery_app = Celery(name)

    # Connection pool limit - prevents unbounded socket creation
    POOL_LIMIT = 10

    # Configure Celery
    celery_app.conf.update(
        broker_url=broker_urls,  # List of URLs for automatic failover!
        # Result backend must be a single URL - use primary only
        result_backend=result_backend,
        # Preserve our logging configuration in workers
        worker_hijack_root_logger=False,
        broker_failover_strategy="round-robin",  # Use built-in round-robin strategy
        broker_connection_retry_on_startup=True,  # Retry connection on startup
        broker_connection_retry=True,  # Retry broker connection on failure
        broker_connection_max_retries=10,  # Max retries before giving up
        broker_pool_limit=POOL_LIMIT,  # Connection pool size for broker
        # CRITICAL: Cap result backend connections to prevent socket exhaustion
        redis_backend_max_connections=POOL_LIMIT,  # Was unbounded (None)
        broker_transport_options={
            "priority_steps": list(range(10)),
            # Visibility timeout should be longer than the longest task
            "visibility_timeout": 43200,  # 12 hours for long-running tasks
            # Health check interval
            "health_check_interval": 30,  # Check broker health every 30 seconds
            # Socket options for better reliability through HAProxy
            "socket_keepalive": True,
            "socket_timeout": 10,
            # Max connections for Celery 5.3+
            "max_connections": POOL_LIMIT,
        },
        # Result backend transport options - needed for Celery <5.3
        result_backend_transport_options={
            "max_connections": POOL_LIMIT,
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
        # Result expiration - CRITICAL for free tier Redis (Upstash 100k commands/10 days)
        # Clean up task results after 1 hour to prevent infinite accumulation
        result_expires=3600,  # 1 hour in seconds
        # Event settings for monitoring
        # DISABLED by default - events cost 10-20 Redis commands per task!
        # celery-exporter provides metrics WITHOUT events via Celery Inspect API
        # celery-exporter provides metrics WITHOUT events via Celery Inspect API
        # Set CELERY_SEND_EVENTS=true environment variable to enable for debugging
        worker_send_task_events=os.getenv("CELERY_SEND_EVENTS", "false").lower() == "true",
        task_send_sent_event=os.getenv("CELERY_SEND_EVENTS", "false").lower() == "true",
    )

    # Define task queues for different job types
    celery_app.conf.task_routes = {
        "browser.*": {"queue": "browser"},
        "browser.cleanup": {"queue": "browser"},  # Explicit for clarity
        "browser.scrape_data": {"queue": "default"},  # Orchestration task runs on default queue
        "tankpit.*": {"queue": "tankpit"},
        "llm.*": {"queue": "llm"},
    }

    celery_app.conf.task_queues = (
        Queue("browser", routing_key="browser", priority=5),
        Queue("tankpit", routing_key="tankpit", priority=3),
        Queue("llm", routing_key="llm", priority=1),
        Queue("default", routing_key="default", priority=0),
    )

    # Import tasks to register them
    celery_app.autodiscover_tasks(["swarm.tasks"])

    return celery_app


# Create the default global app instance using the factory
app = create_celery()

# Preserve the existing dict while adding the router object
prev_routes = app.conf.task_routes

# Celery accepts a list/tuple mixing router objects and dicts
# BrowserSessionRouter gets first shot, falls through to dict if it returns None
app.conf.task_routes = [BrowserSessionRouter(), prev_routes]

# Configure Celery signals for logging context


@signals.task_prerun.connect
def bind_task_context(
    sender: object,
    task_id: str,
    task: object,
    args: tuple[object, ...],
    kwargs: dict[str, object],
    **extra: object,
) -> None:
    """Bind task context to all logs within this task."""
    # Bind full context for the executing worker thread
    try:
        from swarm.utils.context_bootstrap import bootstrap_thread_log_context

        request = getattr(task, "request", None)
        hostname = getattr(request, "hostname", None)
        bootstrap_thread_log_context(service="celery-worker", hostname=hostname, job_id=task_id)
    except Exception as e:
        # Best effort fallback: still bind service to avoid 'unknown' in logs
        logger.warning(f"Failed to bootstrap full task context: {e}")
        bind_log_context(service="celery-worker", job_id=task_id)
    name = getattr(task, "name", "unknown")
    logger.debug(f"Task {name} starting with ID {task_id}")


@signals.task_postrun.connect
def unbind_task_context(
    sender: object,
    task_id: str,
    task: object,
    args: tuple[object, ...],
    kwargs: dict[str, object],
    retval: object | None,
    state: str,
    **extra: object,
) -> None:
    """Clear task context after task completes."""
    name = getattr(task, "name", "unknown")
    logger.debug(f"Task {name} completed with ID {task_id}")
    bind_log_context(job_id="-")


@signals.task_failure.connect
def log_task_failure(
    sender: object,
    task_id: str,
    exception: Exception,
    args: tuple[object, ...],
    kwargs: dict[str, object],
    traceback: object,
    einfo: object,
    **extra: object,
) -> None:
    """Log task failures with full context."""
    logger.error(f"Task failed with ID {task_id}: {exception}")


"""Worker lifecycle management

Registers each Celery worker in Redis and maintains a lightweight heartbeat
used by the BrowserHealthMonitor and the affinity router.
"""

_worker_lifecycle = None  # Global instance


@signals.worker_process_init.connect
def bind_worker_context(**kwargs: object) -> None:
    """Bind logging context in each worker subprocess.

    This runs in each forked worker process, ensuring logs have proper
    service and worker_id context instead of 'unknown'.
    """
    from swarm.core.logger_setup import (
        auto_detect_deployment_context,
        bind_deployment_context,
        bind_log_context,
    )

    # Bind deployment context (hostname, container_id, etc)
    deployment_context = auto_detect_deployment_context()
    bind_deployment_context(context=deployment_context)

    # Bind service context - worker_id will be set in worker_ready
    bind_log_context(service="celery-worker")

    logger.debug("Worker subprocess logging context bound")


@signals.worker_ready.connect
def register_worker(sender: object, **kwargs: object) -> None:
    """Register worker when Celery starts."""
    from swarm.core.logger_setup import bind_log_context
    from swarm.distributed.worker_lifecycle import WorkerLifecycle

    global _worker_lifecycle

    # Extract worker ID from hostname
    # Celery hostname format: "name@host" or just "host"
    hostname = sender.hostname if hasattr(sender, "hostname") else None
    if not hostname:
        logger.error("Cannot register worker: no hostname found")
        return

    # Use centralized identity helper for consistency
    try:
        from swarm.utils.worker_identity import canonical_worker_id

        worker_id = canonical_worker_id(hostname)
    except Exception:
        # Fallback to basic split
        worker_id = hostname.split("@", 1)[1] if "@" in hostname else hostname

    # Bind full thread context for the worker main thread
    try:
        from swarm.utils.context_bootstrap import bootstrap_thread_log_context

        bootstrap_thread_log_context(service="celery-worker", worker_id=worker_id)
    except Exception as e:
        logger.warning(f"Failed to bootstrap worker thread context: {e}")
        bind_log_context(service="celery-worker", worker_id=worker_id)

    logger.info(f"Worker ready signal received, registering worker: {worker_id}")

    try:
        # Create and register lifecycle manager
        _worker_lifecycle = WorkerLifecycle(worker_id)
        _worker_lifecycle.register()
        _worker_lifecycle.start_heartbeat()

        logger.info(f"Worker {worker_id} registered and heartbeat started")
    except Exception as e:
        logger.error(f"Failed to register worker {worker_id}: {e}", exc_info=True)

    # Per-worker direct queue is configured via the worker entrypoint (scripts/entrypoint.worker.sh)
    # to avoid duplication and control-plane races.


@signals.worker_shutting_down.connect
def unregister_worker(sender: object, **kwargs: object) -> None:
    """Clean up when worker shuts down."""
    global _worker_lifecycle

    if _worker_lifecycle:
        logger.info(f"Worker shutting down, stopping heartbeat for {_worker_lifecycle.worker_id}")
        try:
            _worker_lifecycle.stop_heartbeat()
        except Exception as e:
            logger.error(f"Error during worker shutdown: {e}", exc_info=True)
        finally:
            _worker_lifecycle = None
