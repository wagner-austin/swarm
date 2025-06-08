"""
core/metrics.py – runtime counters + helpers.

This file now carries full type hints so it passes `mypy --strict`.
"""

from __future__ import annotations
import time
from typing import Dict

process_start_time: float = time.time()
# incremented by the MetricsTracker cog (outbound socket payloads)
messages_sent: int = 0
# incremented by the MetricsTracker cog (on_message listener)
discord_messages_processed: int = 0


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


# Convenience formatter for HH:MM:SS
def format_hms(seconds: float) -> str:  # noqa: D401 – utility
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    s = int(seconds) % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


# ------------------------------------------------------------+
#  Public helpers – zero monkey-patches, plain counters only   |
# ------------------------------------------------------------+


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
