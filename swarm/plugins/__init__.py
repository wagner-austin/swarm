"""
plugins/__init__.py
-------------------
Plugin package initialization.
This file imports and exposes command plugins m the commands module.
"""

__all__ = ["commands"]

# Lazy-loading: do not import commands here. It will be loaded when accessed as swarm.plugins.commands.
