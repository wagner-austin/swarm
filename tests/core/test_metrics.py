"""
tests/core/test_metrics.py - Tests for the metrics module.
Ensures uptime and message counting functionality work as expected.
"""

import bot_core.metrics as metrics

def test_get_uptime():
    uptime = metrics.get_uptime()
    assert isinstance(uptime, float)
    assert uptime >= 0

def test_increment_message_count():
    initial_count = metrics.messages_sent
    metrics.increment_message_count()
    assert metrics.messages_sent == initial_count + 1

# End of tests/core/test_metrics.py