"""
core/metrics.py – runtime counters + helpers.

This file now carries full type hints so it passes `mypy --strict`.
"""

from __future__ import annotations
import time
from typing import Any, Dict

process_start_time = time.time()
messages_sent = 0
discord_messages_processed = 0
_patched_discord_send = False


def increment_discord_message_count() -> None:
    """
    Increment the count of Discord messages processed.
    """
    global discord_messages_processed
    discord_messages_processed += 1


def get_discord_messages_processed() -> int:
    """
    Return the number of Discord messages processed.
    """
    return discord_messages_processed


def increment_message_count() -> None:
    """
    Increment the count of messages sent.
    """
    global messages_sent
    messages_sent += 1


def get_uptime() -> float:
    """
    Return the uptime of the process in seconds.
    """
    return time.time() - process_start_time


# ---------------------------------------------------------------------------+
# Public helpers                                                             +
# ---------------------------------------------------------------------------+


def patch_discord_context_send() -> None:
    """
    Monkey-patch ``discord.ext.commands.Context.send`` once so that
    *every* outbound message increases ``messages_sent`` automatically.
    The patch is idempotent and safe to call multiple times.
    """
    global _patched_discord_send
    if _patched_discord_send:
        return

    from discord.ext import commands

    original_send = commands.Context.send

    async def _counting_send(  # noqa: D401 – simple function
        self: "commands.Context[Any]",
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        increment_message_count()
        return await original_send(self, *args, **kwargs)

    # mismatched signature on purpose → ignore the “method-assign” error
    commands.Context.send = _counting_send  # type: ignore[method-assign]
    _patched_discord_send = True


def get_stats() -> Dict[str, float | int]:
    """
    Convenience – returns a dict that callers (e.g. the future ``!status``
    command) can format any way they like.
    """
    return {
        "uptime_s": get_uptime(),
        "messages_sent": messages_sent,
        "discord_messages_processed": discord_messages_processed,
    }


# End of core/metrics.py
