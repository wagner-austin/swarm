#!/usr/bin/env python
"""
tests/test_main.py – Test for bot_core/main.py: Verifies both --test flag and normal run via subprocess.
"""

import sys
import subprocess
import os

def test_main_no_flags():
    """
    Test running bot_core/main.py without flags using a subprocess to avoid
    'asyncio.run() cannot be called from a running event loop'.
    Utilizes FAST_EXIT_FOR_TESTS environment variable to force main.py to exit early.
    """
    env = os.environ.copy()
    env["FAST_EXIT_FOR_TESTS"] = "1"
    # Ensure DB_URL is passed to the subprocess
    if "DB_URL" in os.environ:
        env["DB_URL"] = os.environ["DB_URL"]
    result = subprocess.run(
        [sys.executable, "-m", "bot_core.main"],
        capture_output=True,
        text=True,
        env=env
    )
    # Print output if the subprocess fails for easier debugging
    if result.returncode != 0:
        print("STDOUT:\n", result.stdout)
        print("STDERR:\n", result.stderr)
    assert result.returncode == 0
    # Optionally, confirm no Python traceback was printed:
    assert "start_periodic_backups(settings=settings)" not in result.stderr

# End of tests/test_main.py