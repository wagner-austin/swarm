"""
Light-weight helpers that sit **between** Discord cogs and the low-level
BrowserRuntime / RPA layer.

Currently this package only exposes decorator utilities.  More generic browser
helpers (e.g. Playwright wrappers) can live here later without polluting the
command cogs.
"""

from importlib import import_module

# Re-export public sub-modules so callers can do
#     from bot.webapi import decorators
# without importing the whole package tree.
decorators = import_module(".decorators", __name__)  # noqa: F401

__all__: list[str] = ["decorators"]
