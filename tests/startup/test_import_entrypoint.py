"""Ensures that `python -m bot.core` can be imported in a fresh interpreter.

We *spawn* a subprocess so the module graph starts from a clean slate –-
identical to production.  Any circular-import or side-effect crash will
fail this test.
"""

from __future__ import annotations

import subprocess
import sys


def test_module_entrypoint_imports_cleanly() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "bot.core", "--help"],  # --help exits immediately
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # We expect a zero exit-code (or 2 if argparse prints help);
    # anything ≥ 3 means the import stack blew up.
    assert proc.returncode in (0, 2), proc.stderr
