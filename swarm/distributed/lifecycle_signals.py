"""
Celery worker signals for session lifecycle manager.

Hooks worker startup/shutdown to start/stop the lifecycle manager.
"""

from __future__ import annotations

import logging
from typing import Optional

from celery import signals

from .session_lifecycle import lifecycle_manager

logger = logging.getLogger(__name__)


@signals.worker_ready.connect
def _on_worker_ready(**kwargs: object) -> None:
    try:
        lifecycle_manager.start()
        logger.info("Worker ready: SessionLifecycleManager started")
    except Exception as exc:
        logger.error(f"Failed to start SessionLifecycleManager on worker_ready: {exc}")


@signals.worker_shutdown.connect
def _on_worker_shutdown(**kwargs: object) -> None:
    try:
        lifecycle_manager.stop()
        logger.info("Worker shutdown: SessionLifecycleManager stopped")
    except Exception as exc:
        logger.error(f"Failed to stop SessionLifecycleManager on worker_shutdown: {exc}")
