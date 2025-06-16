from __future__ import annotations

import argparse
import asyncio
import sys
from textwrap import dedent


__all__ = ["cli"]

# ---------------------------------------------------------------------------+
#  Minimal CLI parser                                                         +
# ---------------------------------------------------------------------------+


def _build_parser() -> argparse.ArgumentParser:  # noqa: D401 – imperative style
    """Return a parser that understands *only* ``--help`` and ``--version``.

    The goal is to let ``python -m bot.core --help`` exit **immediately**
    without importing heavyweight runtime modules such as Playwright or
    discord.py.  Anything beyond the two meta-flags will be forwarded to the
    real application once heavy imports are safe.
    """

    try:
        import importlib.metadata as _ilmd

        version: str = (
            _ilmd.version("bot")
            if "bot" in _ilmd.packages_distributions()
            else "unknown"
        )
    except Exception:  # pragma: no cover – metadata lookup best-effort
        version = "unknown"

    parser = argparse.ArgumentParser(
        prog="python -m bot.core",
        add_help=False,  # we add it manually to keep tight control
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=dedent(
            """\
            Discord-bot bootstrap
            --------------------
            Run *without arguments* to start the bot using environment
            variables and the code-base defaults.
            """
        ),
    )

    # Meta flags expected by the test-suite (and humans!)
    parser.add_argument(
        "-h", "--help", action="help", help="show this message and exit"
    )
    parser.add_argument(
        "-V", "--version", action="version", version=f"%(prog)s {version}"
    )
    return parser


# ---------------------------------------------------------------------------+
#  Public entry-point                                                        +
# ---------------------------------------------------------------------------+


def cli(argv: list[str] | None = None) -> None:  # noqa: D401
    """Entry-point for ``python -m bot.core``."""

    # 1️⃣ Handle trivial flags **before** heavy imports.
    _build_parser().parse_known_args(argv)  # exits on -h/-V automatically

    # 2️⃣ Configure logging (idempotent) & launch the real bot.
    from bot.core.logger_setup import setup_logging

    setup_logging()
    from bot.core.main import main  # delayed import keeps --help fast

    asyncio.run(main())


# ---------------------------------------------------------------------------+
#  Module runner                                                             +
# ---------------------------------------------------------------------------+

if __name__ == "__main__":  # pragma: no cover
    try:
        cli(sys.argv[1:])
    except KeyboardInterrupt:  # Graceful ^C during manual runs
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
