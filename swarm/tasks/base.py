"""
Base Celery task definitions for Swarm.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Generic, ParamSpec, TypeVar

from billiard.einfo import ExceptionInfo
from celery import Task as CeleryTask

_P = ParamSpec("_P")
_R = TypeVar("_R")

logger = logging.getLogger(__name__)

# Use TYPE_CHECKING pattern to handle stub vs runtime mismatch
# - Stub declares Task as Generic[_P, _R], but runtime Task is not subscriptable
# - The actual strict typing comes from Generic[_P, _R] on SwarmTask class below
# Solution from: https://mypy.readthedocs.io/en/stable/runtime_troubles.html
if TYPE_CHECKING:

    class SwarmTask(CeleryTask[_P, _R], Generic[_P, _R]):
        """Typed task base for type-checkers only."""

        ...
else:

    class SwarmTask(CeleryTask, Generic[_P, _R]):
        """Runtime task base class with logging hooks."""

        autoretry_for: tuple[type[Exception], ...] = (Exception,)
        retry_kwargs = {"max_retries": 3}
        retry_backoff = True
        retry_backoff_max = 600  # 10 minutes
        retry_jitter = True

        def on_failure(
            self,
            exc: Exception,
            task_id: str,
            args: tuple[object, ...],
            kwargs: dict[str, object],
            einfo: ExceptionInfo,
        ) -> None:
            logger.error(f"Task {self.name} failed: {exc}", exc_info=True)
            super().on_failure(exc, task_id, args, kwargs, einfo)

        def on_retry(
            self,
            exc: Exception,
            task_id: str,
            args: tuple[object, ...],
            kwargs: dict[str, object],
            einfo: ExceptionInfo,
        ) -> None:
            logger.warning(f"Task {self.name} retrying: {exc}")
            super().on_retry(exc, task_id, args, kwargs, einfo)

        def on_success(
            self, retval: _R, task_id: str, args: tuple[object, ...], kwargs: dict[str, object]
        ) -> None:
            logger.info(f"Task {self.name} completed successfully")
            super().on_success(retval, task_id, args, kwargs)
