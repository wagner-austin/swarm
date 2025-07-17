"""
swarm.core package bootstrap.
Loads configuration first, then re-exports public sub-modules so external
code can simply `import swarm.core as sc`.
"""

# ----- standard libs -----
from importlib import import_module
from types import ModuleType
from typing import List

# ----- public re-exports -----
# 1) create the symbol table *first*
__all__: list[str] = []

# ---------------------------------------------------------------------------+
# Export the *instance* so `from swarm.core import settings` works at runtime  #
# and for Mypy.                                                              #
# ---------------------------------------------------------------------------+

# expose extras and freeze public surface
for _name in ["logger_setup"]:
    mod: ModuleType = import_module(f".{_name}", __name__)
    globals()[_name] = mod
    __all__.append(_name)
