#!/usr/bin/env python
"""Synchronise local .env variables to Fly.io secrets.

Run via `make secrets` (see Makefile). This script is pure-Python so it works
on Windows PowerShell, cmd.exe, bash, CI, etc.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def main() -> None:  # noqa: D401
    env_path = Path(".env")
    if not env_path.exists():
        print(".env file not found", file=sys.stderr)
        sys.exit(1)

    pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
    vars_to_set: list[str] = []
    for line in env_path.read_text().splitlines():
        match = pattern.match(line)
        if match and match.group(2).strip():
            vars_to_set.append(f"{match.group(1)}={match.group(2).strip()}")

    if vars_to_set:
        import shutil

        fly_exe = shutil.which("flyctl") or shutil.which("flyctl.exe")
        if not fly_exe:
            # Attempt automatic install on Windows via winget
            if sys.platform.startswith("win"):
                import shutil

                winget = shutil.which("winget")
                if winget:
                    try:
                        print(
                            "flyctl not found – attempting automatic install via winget…",
                            file=sys.stderr,
                        )
                        subprocess.check_call(
                            [winget, "install", "-e", "--id", "Fly-io.flyctl", "-h"]
                        )
                    except subprocess.CalledProcessError:
                        print(
                            "Automatic winget install failed. Please install Fly CLI manually (https://fly.io/docs/flyctl/install/).",
                            file=sys.stderr,
                        )
                        sys.exit(1)
                    fly_exe = shutil.which("flyctl") or shutil.which("flyctl.exe")
            if not fly_exe:
                print(
                    "flyctl not found in PATH even after install attempt. Install Fly CLI manually (https://fly.io/docs/flyctl/install/) and ensure it's in your PATH.",
                    file=sys.stderr,
                )
                sys.exit(1)
        subprocess.check_call([fly_exe, "secrets", "set", *vars_to_set])
        print("✅  Secrets synced.")
    else:
        print("No non-empty variables to sync.")


if __name__ == "__main__":
    main()
