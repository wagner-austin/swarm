from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlparse, urlunparse

from bot.core.settings import settings

# ---------------------------------------------------------------------------+
# Public helper – the *only* place that validates a user‑supplied URL        +
# ---------------------------------------------------------------------------+


def validate_and_normalise_web_url(raw: str, *, allowed_hosts: Iterable[str] | None = None) -> str:
    """
    • Add ``https://`` if scheme is missing.
    • Reject anything that is neither http/https nor ``file://`` nor ``about:``.
    • Return the normalised URL otherwise.

    Raises ``ValueError`` on invalid input – high‑level callers translate this
    into their own domain‑specific error (e.g. ``InvalidURLError``).
    """
    if not raw:
        raise ValueError("URL cannot be empty")

    url = normalise(raw)
    if url.startswith(("file://", "about:")):
        return url

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"'{raw}' does not look like an external web URL")

    # Extract the host part (no port) for validation
    host = parsed.hostname or parsed.netloc  # fallback for rare edge‑cases

    # 1) basic sanity (unchanged)
    if "." not in host and host.lower() != "localhost":
        raise ValueError(f"'{raw}' does not look like a valid host")

    # 2) host allow-list enforcement
    allow = list(allowed_hosts) if allowed_hosts is not None else list(settings.allowed_hosts)
    if allow and "*" not in allow and host.lower() not in {h.lower() for h in allow}:
        raise ValueError(f"Navigation to '{host}' is not permitted by configuration")

    # 3) Normalise host casing in the URL we return so callers work with the
    #    validated, lower-case representation and cannot later bypass the
    #    allow-list by using a mixed-case hostname.
    if parsed.netloc != (lc_netloc := parsed.netloc.lower()):
        parsed = parsed._replace(netloc=lc_netloc)
        url = urlunparse(parsed)

    return url


def normalise(url: str) -> str:
    if not url.startswith(("http://", "https://", "file://", "data:", "about:")):
        return f"https://{url}"
    return url


def looks_like_web_url(raw: str) -> bool:
    p = urlparse(normalise(raw))
    host = p.hostname or p.netloc
    return (
        p.scheme in ("http", "https")
        and bool(host)  # Ensure this part is strictly boolean
        and ("." in host or host.lower() == "localhost")
    )
