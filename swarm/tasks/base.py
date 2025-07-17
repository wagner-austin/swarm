"""
Base Celery task definitions for Swarm.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from celery import Task
from swarm.celery_app import app

if TYPE_CHECKING:
    # For type checking, use the generic version
    TaskBase = Task[Any, Any]
else:
    # At runtime, use the non-generic version
    TaskBase = Task

logger = logging.getLogger(__name__)


class SwarmTask(TaskBase):
    """Base task class with common error handling and logging."""

    autoretry_for: tuple[type[Exception], ...] = (Exception,)
    retry_kwargs = {"max_retries": 3}
    retry_backoff = True
    retry_backoff_max = 600  # 10 minutes
    retry_jitter = True

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        """Log task failures."""
        logger.error(f"Task {self.name} failed: {exc}", exc_info=einfo)
        super().on_failure(exc, task_id, args, kwargs, einfo)

    def on_retry(
        self,
        exc: Exception,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        """Log task retries."""
        logger.warning(f"Task {self.name} retrying: {exc}")
        super().on_retry(exc, task_id, args, kwargs, einfo)

    def on_success(
        self, retval: Any, task_id: str, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> None:
        """Log task success."""
        logger.info(f"Task {self.name} completed successfully")
        super().on_success(retval, task_id, args, kwargs)
