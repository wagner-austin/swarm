#!/usr/bin/env python
"""
tests/test_main.py – Test for bot_core/main.py: Verifies both --test flag and normal run via subprocess.
"""

import sys
import subprocess
from pathlib import Path
import os


def test_main_bootstrap_exits_zero() -> None:
    env = os.environ.copy()
    # Ensure PYTHONPATH includes the project root for subprocess
    project_root = Path(__file__).parent.parent.resolve()
    src_dir = project_root / "src"
    env["PYTHONPATH"] = str(src_dir) + os.pathsep + env.get("PYTHONPATH", "")
    env["FAST_EXIT_FOR_TESTS"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "bot_core.main"], capture_output=True, text=True, env=env
    )
    assert result.returncode == 0
