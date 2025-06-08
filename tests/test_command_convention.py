from types import ModuleType
from typing import Iterator
import importlib
import inspect
import pkgutil

PACKAGE: str = "bot.plugins.commands"


def iter_cogs() -> Iterator[ModuleType]:
    """Yield every public command-cog module in the package."""
    for _, name, _ in pkgutil.iter_modules(importlib.import_module(PACKAGE).__path__):
        if name.startswith("_"):
            continue
        yield importlib.import_module(f"{PACKAGE}.{name}")


def test_cog_attributes() -> None:
    for mod in iter_cogs():
        cog_classes = [
            cls
            for _, cls in inspect.getmembers(mod, inspect.isclass)
            if hasattr(cls, "_ENTRY_CMD")
        ]
        for cls in cog_classes:
            assert isinstance(getattr(cls, "USAGE", ""), str) and cls.USAGE.strip(), (
                f"{cls.__name__} missing USAGE"
            )
            assert isinstance(getattr(cls, "_ENTRY_CMD", ""), str) and cls._ENTRY_CMD, (
                f"{cls.__name__} missing _ENTRY_CMD"
            )
            # Ensure all decorator names come from constants
            for func in cls.__dict__.values():
                if hasattr(func, "__commands__"):
                    for cmd in func.__commands__:
                        dec_name = cmd.name
                        pool: set[str] = {
                            v for k, v in cls.__dict__.items() if k.startswith("CMD_")
                        }
                        pool.add(cls._ENTRY_CMD)
                        assert dec_name in pool, (
                            f"{cls.__name__}.{func.__name__} uses literal '{dec_name}' "
                            "not declared in CMD_* constants"
                        )
