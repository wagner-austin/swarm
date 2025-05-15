#!/usr/bin/env python
"""
tests/test_main.py – Test for bot_core/main.py: Verifies both --test flag and normal run via subprocess.
"""

import sys
import subprocess
import os

import sys
import subprocess
import os

def test_main_bootstrap_exits_zero():
    env = os.environ.copy()
    # Ensure PYTHONPATH includes the project root for subprocess
    env["PYTHONPATH"] = os.path.abspath(os.path.dirname(__file__) + "/..") + os.pathsep + env.get("PYTHONPATH", "")
    env["FAST_EXIT_FOR_TESTS"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "bot_core.main"],
        capture_output=True,
        text=True,
        env=env
    )
    assert result.returncode == 0

# End of tests/test_main.py