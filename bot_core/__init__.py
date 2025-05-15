"""
bot_core package bootstrap.
Loads configuration first, then re-exports public sub-modules so external
code can simply `import bot_core as bc`.
"""

# ----- standard libs -----
from importlib import import_module
from types import ModuleType
from typing import List

# ----- public re-exports -----
# 1) create the symbol table *first*
__all__: List[str] = ["settings"]

# 2) pull settings in so `import bot_core.settings` works

# expose extras and freeze public surface
for _name in ["parsers", "logger_setup"]:
    mod: ModuleType = import_module(f".{_name}", __name__)
    globals()[_name] = mod
    __all__.append(_name)
