"""Top-level AI package.

This package holds abstractions and concrete implementations related to
Large-Language-Model backends.  It purposefully stays lightweight so that
production code outside `swarm.ai.*` never imports vendor SDKs directly.
"""

from __future__ import annotations

# Re-export the formal contract so callers can import from swarm.ai instead of
# swarm.ai.contracts.
from .contracts import LLMProvider, Message  # noqa: F401

__all__ = [
    "LLMProvider",
    "Message",
]
