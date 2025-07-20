#!/usr/bin/env python
"""
Celery Worker Entrypoint

Start a Celery worker that processes browser, analysis, and LLM tasks.
Replaces the old distributed.worker with production-grade Celery.

Usage:
    # Browser worker (async tasks with prefork pool - Playwright compatible)
    poetry run celery -A swarm.celery_app worker --loglevel=info --queue=browser --concurrency=4

    # LLM worker (CPU/GPU bound tasks)
    poetry run celery -A swarm.celery_app worker --loglevel=info --queue=llm --concurrency=1

    # Multi-queue worker
    poetry run celery -A swarm.celery_app worker --loglevel=info --queue=browser,analysis,llm

Or with this script:
    # Browser worker - each process handles one task at a time, but each task can drive many tabs
    poetry run python -m swarm.celery_worker --queues=browser --pool=prefork --concurrency=4

    # LLM worker with single process for dedicated GPU/CPU
    poetry run python -m swarm.celery_worker --queues=llm --pool=prefork --concurrency=1

WARNING: Do not use eventlet/gevent pools with Playwright - they monkey-patch socket/threading
and are incompatible with Chromium. Use prefork (default) for browser automation.
"""

import argparse
import logging
import os
import sys
from typing import List, Literal

from celery import Celery

from swarm.celery_app import app
from swarm.core.logger_setup import setup_logging

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Start a Celery worker for Swarm tasks")

    parser.add_argument(
        "--queues",
        type=str,
        default="browser",
        help="Comma-separated list of queues to consume (default: browser)",
    )

    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of concurrent worker processes/threads (default: 1)",
    )

    parser.add_argument(
        "--pool",
        type=str,
        default="prefork",
        choices=["prefork", "eventlet", "gevent", "solo"],
        help="Pool implementation: prefork (default), eventlet/gevent (for async), solo (single thread)",
    )

    parser.add_argument(
        "--loglevel",
        type=str,
        default="info",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Logging level (default: info)",
    )

    parser.add_argument(
        "--hostname",
        type=str,
        default=None,
        help="Set custom worker hostname (default: auto-generated)",
    )

    parser.add_argument(
        "--autoscale",
        type=str,
        default=None,
        help="Autoscaling settings as 'max,min' (e.g., '10,3')",
    )

    parser.add_argument(
        "--max-tasks-per-child",
        type=int,
        default=100,
        help="Maximum tasks per worker before restart (default: 100)",
    )

    parser.add_argument("--without-heartbeat", action="store_true", help="Disable heartbeat events")

    parser.add_argument("--without-gossip", action="store_true", help="Disable gossip events")

    parser.add_argument(
        "--without-mingle",
        action="store_true",
        help="Disable synchronization with other workers at startup",
    )

    return parser.parse_args()


def start_worker(
    queues: list[str],
    concurrency: int,
    loglevel: str,
    pool: Literal["prefork", "eventlet", "gevent", "solo"] = "prefork",
    hostname: str | None = None,
    autoscale: str | None = None,
    max_tasks_per_child: int = 100,
    without_heartbeat: bool = False,
    without_gossip: bool = False,
    without_mingle: bool = False,
) -> None:
    """
    Start a Celery worker with the specified configuration.

    Args:
        queues: List of queue names to consume from
        concurrency: Number of concurrent worker processes/threads
        loglevel: Logging level
        pool: Pool implementation (prefork, eventlet, gevent, solo)
        hostname: Custom worker hostname
        autoscale: Autoscaling configuration as "max,min"
        max_tasks_per_child: Max tasks before worker restart
        without_heartbeat: Disable heartbeat events
        without_gossip: Disable gossip events
        without_mingle: Disable worker synchronization
    """
    # Setup logging
    setup_logging()

    # Log startup information
    logger.info(
        f"Starting Celery worker: queues={queues}, concurrency={concurrency}, loglevel={loglevel}"
    )

    # Start the worker using the Worker class
    from celery.apps.worker import Worker

    worker = Worker(
        app=app,
        hostname=hostname,
        pool_cls=pool,
        loglevel=loglevel,
        concurrency=concurrency,
        queues=queues,
        autoscale=autoscale,
        max_tasks_per_child=max_tasks_per_child,
        without_heartbeat=without_heartbeat,
        without_gossip=without_gossip,
        without_mingle=without_mingle,
    )
    worker.start()


def main() -> None:
    """Run the main entry point."""
    args = parse_args()

    # Parse queues
    queues = [q.strip() for q in args.queues.split(",")]

    # Parse autoscale if provided
    autoscale = None
    if args.autoscale:
        try:
            max_workers, min_workers = args.autoscale.split(",")
            autoscale = f"{max_workers},{min_workers}"
        except ValueError:
            logger.error("Invalid autoscale format. Use 'max,min' (e.g., '10,3')")
            sys.exit(1)

    # Start the worker
    try:
        start_worker(
            queues=queues,
            concurrency=args.concurrency,
            loglevel=args.loglevel,
            pool=args.pool,
            hostname=args.hostname,
            autoscale=autoscale,
            max_tasks_per_child=args.max_tasks_per_child,
            without_heartbeat=args.without_heartbeat,
            without_gossip=args.without_gossip,
            without_mingle=args.without_mingle,
        )
    except KeyboardInterrupt:
        logger.info("Worker shutting down...")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Worker failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
