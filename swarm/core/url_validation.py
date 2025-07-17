"""URL validation helpers that respect runtime configuration.

This module extends the generic helpers in :pymod:`swarm.utils.urls` by applying
swarm-level configuration, notably the *allowed_hosts* setting.  High-level code
(e.g. command cogs) should import :func:`validate_and_normalise_web_url` from
here instead of the utils layer so that configuration enforcement happens in a
single place.
"""

from __future__ import annotations

from collections.abc import Iterable

# Re-export the unified helper from swarm.utils.urls while keeping the same public interface
from swarm.utils.urls import validate_and_normalise_web_url as _base

__all__ = ["validate_and_normalise_web_url"]


def validate_and_normalise_web_url(raw: str, *, allowed_hosts: Iterable[str] | None = None) -> str:  # noqa: D401
    """Return a safe, normalised web URL via the unified helper.

    This is merely a backward-compatibility shim; prefer importing
    :func:`swarm.utils.urls.validate_and_normalise_web_url` directly in new code.
    """
    return _base(raw, allowed_hosts=allowed_hosts)
