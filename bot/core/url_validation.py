"""URL validation helpers that respect runtime configuration.

This module extends the generic helpers in :pymod:`bot.utils.urls` by applying
bot-level configuration, notably the *allowed_hosts* setting.  High-level code
(e.g. command cogs) should import :func:`validate_and_normalise_web_url` from
here instead of the utils layer so that configuration enforcement happens in a
single place.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlparse

from bot.core.settings import settings
from bot.utils.urls import normalise

__all__ = ["validate_and_normalise_web_url"]


def validate_and_normalise_web_url(raw: str, *, allowed_hosts: Iterable[str] | None = None) -> str:  # noqa: D401
    """Return a safe, normalised web URL after applying host-allowlist rules.

    Behaviour:
    1. Adds an ``https://`` scheme if missing.
    2. Allows ``file://`` and ``about:`` URLs unchanged.
    3. Rejects hosts that do not look valid (no dot and not *localhost*).
    4. Enforces *allowed_hosts* (case-insensitive).  If this iterable is empty
       or contains ``"*"``, the check is skipped.
    """
    if not raw:
        raise ValueError("URL cannot be empty")

    url = normalise(raw)
    if url.startswith(("file://", "about:")):
        return url

    parsed = urlparse(url)
    host = parsed.hostname or parsed.netloc

    if "." not in host and host.lower() != "localhost":  # basic sanity
        raise ValueError(f"'{raw}' does not look like a valid host")

    allow = list(allowed_hosts) if allowed_hosts is not None else list(settings.allowed_hosts)
    if allow and "*" not in allow and host.lower() not in {h.lower() for h in allow}:
        raise ValueError(f"Navigation to '{host}' is not permitted by configuration")

    return url
