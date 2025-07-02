"""
Utilities for safe dynamic dispatch in distributed, plugin, or job-based systems.

- filter_kwargs_for_method: Filters kwargs to only those accepted by a method.
  Use this before any getattr(...)(*args, **kwargs) with user/job-supplied kwargs.
"""

import inspect
from typing import Any


def filter_kwargs_for_method(method: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """
    Return a dict with only those kwargs accepted by the method signature.
    Prevents TypeError from extra job metadata (e.g. session_id, close_session).
    """
    sig = inspect.signature(method)
    return {k: v for k, v in kwargs.items() if k in sig.parameters}
