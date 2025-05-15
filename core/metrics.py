"""
core/metrics.py - Metrics tracking for the Signal bot.
Tracks process uptime and number of messages sent.
"""

import time

process_start_time = time.time()
messages_sent = 0
discord_messages_processed = 0

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

# End of core/metrics.py