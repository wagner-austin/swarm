#!/usr/bin/env python
"""
plugins/manager.py
------------------
Unified plugin manager with alias support. Handles registration, loading, and retrieval
of plugins, along with their metadata. Maintains runtime enable/disable functionality and
supports both function-based and class-based plugins. Enforces role-based permission checks.

Focuses on modular, unified, consistent code that facilitates future updates.
"""

import sys
import inspect
import importlib
import pkgutil
import logging
import difflib
from typing import Callable, Any, Optional, Dict, List, Union, Set

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Internal exceptions for plugin dispatch helpers                     #
# ------------------------------------------------------------------ #
class _PluginNotFound(RuntimeError):
    """Raised when no matching plugin exists or the plugin is disabled."""

class _PluginExecutionError(RuntimeError):
    """Raised by execute_plugin() to bubble-up unexpected failures."""

# ------------------------------------------------------------------ #
# Helper: guarantee we always deal with an *awaitable* callable.     #
# ------------------------------------------------------------------ #
def _ensure_awaitable(func):
    """
    Return *func* unchanged if it is already a coroutine-function.
    Otherwise wrap it in a lightweight coroutine so callers can
    always use `await` safely.
    """
    if inspect.iscoroutinefunction(func):
        return func
    async def _wrapper(*a, **kw):          # type: ignore[no-redef]
        return func(*a, **kw)
    return _wrapper

# Import role constants and permission check
from bot_core.permissions import OWNER, has_permission
from bot_core.identity import resolve_role

# Registry: key = canonical command, value = dict with function, aliases, help_visible, category, help_text, required_role.
plugin_registry: Dict[str, Dict[str, Any]] = {}
# Alias mapping: key = alias (normalized), value = canonical command.
alias_mapping: Dict[str, str] = {}
# Track disabled plugins by canonical command name.
disabled_plugins: Set[str] = set()


def normalize_alias(alias: str) -> str:
    """
    Normalize an alias to a standardized format: lowercased and stripped.
    """
    return alias.strip().lower()


def plugin(
    commands: Union[str, List[str]],
    canonical: Optional[str] = None,
    help_visible: bool = True,
    category: Optional[str] = None,
    required_role: str = OWNER
) -> Callable[[Any], Any]:
    """
    Decorator to register a function or class as a plugin command with aliases.

    Parameters:
      commands (Union[str, List[str]]): Command aliases.
      canonical (Optional[str]): Primary command name (default is first alias).
      help_visible (bool): If True, command is shown in help listings.
      category (Optional[str]): Command category.
      required_role (str): Minimum role required to execute this plugin. Defaults to OWNER.
    """
    if isinstance(commands, str):
        commands = [commands]

    normalized_commands = [normalize_alias(cmd) for cmd in commands]
    canonical_name = normalize_alias(canonical) if canonical else normalized_commands[0]

    def decorator(obj: Any) -> Any:
        if inspect.isclass(obj):
            instance = obj()  # Instantiate once
            help_text = getattr(instance, "help_text", "") or (obj.__doc__ or "").strip()
            plugin_func = _ensure_awaitable(instance.run_command)
            plugin_registry[canonical_name] = {
                "function": plugin_func,
                "aliases": normalized_commands,
                "help_visible": help_visible,
                "category": category or "Miscellaneous Commands",
                "help_text": help_text,
                "required_role": required_role,
            }
        else:
            if not hasattr(obj, "help_text"):
                obj.help_text = ""
            help_text = getattr(obj, "help_text", "") or (obj.__doc__ or "").strip()
            plugin_func = _ensure_awaitable(obj)
            plugin_registry[canonical_name] = {
                "function": plugin_func,
                "aliases": normalized_commands,
                "help_visible": help_visible,
                "category": category or "Miscellaneous Commands",
                "help_text": help_text,
                "required_role": required_role,
            }

        # Map all aliases to the canonical command.
        for alias in normalized_commands:
            if alias in alias_mapping and alias_mapping[alias] != canonical_name:
                raise ValueError(f"Duplicate alias '{alias}' already exists for '{alias_mapping[alias]}'.")
            alias_mapping[alias] = canonical_name

        return obj

    return decorator


def get_plugin(command: str) -> Optional[Callable[..., Any]]:
    """
    Retrieve the plugin function for the given command alias.
    Returns None if not found or if the plugin is disabled.
    """
    canonical = alias_mapping.get(normalize_alias(command))
    if not canonical or canonical in disabled_plugins:
        return None
    return plugin_registry.get(canonical, {}).get("function")


def get_all_plugins() -> Dict[str, Dict[str, Any]]:
    """
    Retrieve all registered plugins.
    """
    return plugin_registry


def disable_plugin(canonical_name: str) -> None:
    """
    Disable a plugin by its canonical name.
    """
    disabled_plugins.add(normalize_alias(canonical_name))


def enable_plugin(canonical_name: str) -> None:
    """
    Enable a previously disabled plugin.
    """
    disabled_plugins.discard(normalize_alias(canonical_name))


def clear_plugins() -> None:
    """
    Clear all registered plugins and aliases.
    """
    plugin_registry.clear()
    alias_mapping.clear()
    disabled_plugins.clear()


def import_module_safe(module_name: str) -> None:
    """
    Safely import or reload a module.
    """
    try:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])
            logger.info(f"Reloaded module '{module_name}'.")
        else:
            importlib.import_module(module_name)
            logger.info(f"Imported module '{module_name}'.")
    except Exception as e:
        logger.error(f"Failed to import module '{module_name}': {e}", exc_info=True)


def load_plugins(concurrent: bool = False) -> None:
    """
    Load all plugin modules registered via entry points (group='bot_plugins').
    Fallback: load all modules in 'bot_plugins.commands' for built-in plugins.
    """
    import importlib.metadata as im
    import pkgutil
    import bot_plugins.commands

    # Third-party & external plugins
    for ep in im.entry_points(group="bot_plugins"):
        import_module_safe(ep.value)

    # Built-ins (fallback)
    for info in pkgutil.walk_packages(bot_plugins.commands.__path__, bot_plugins.commands.__name__ + "."):
        import_module_safe(info.name)



def reload_plugins(concurrent: bool = False) -> None:
    """
    Clear existing plugins and reload all plugins.
    """
    clear_plugins()
    load_plugins(concurrent=concurrent)


def resolve_plugin(parsed) -> tuple[str, dict]:
    """
    Return *(canonical_name, plugin_info)* or raise _PluginNotFound.

    Does alias lookup, fuzzy matching, and disabled-plugin checks but
    **does not** touch permissions or run the code.
    """
    command = normalize_alias(parsed.command or "")
    canonical = alias_mapping.get(command)

    # Direct hit
    if canonical and canonical not in disabled_plugins:
        return canonical, plugin_registry[canonical]

    # Fuzzy match
    if not canonical:
        matches = difflib.get_close_matches(
            command, plugin_registry.keys(), n=1, cutoff=0.75
        )
        if matches:
            canonical = matches[0]
            if canonical not in disabled_plugins:
                logger.info("Fuzzy matching: %s  %s", parsed.command, canonical)
                return canonical, plugin_registry[canonical]

    # Anything else is treated as not found / disabled
    raise _PluginNotFound


def check_permission(plugin_info: dict, user_role: str) -> None:
    """
    Raise PermissionError if *user_role* lacks access to *plugin_info*.
    """
    required = plugin_info.get("required_role", OWNER)
    if not has_permission(user_role, required):
        raise PermissionError


async def execute_plugin(
    plugin_info: dict, args: str, ctx, state_machine, *, logger
) -> str:
    """
    Run the plugin function, catching and re-raising internal errors as
    _PluginExecutionError so dispatch_message() can decide what to say to
    the user.
    """
    plugin_func = plugin_info.get("function")
    if not plugin_func:
        raise _PluginExecutionError("missing plugin function")

    try:
        result = await plugin_func(args, ctx, state_machine)
        if not isinstance(result, str):
            logger.warning(
                "Plugin %s returned non-string %r", plugin_info, type(result)
            )
            return ""
        return result
    except Exception as exc:                     # noqa: BLE001
        logger.exception("Plugin execution failure: %s", exc)
        raise _PluginExecutionError from exc


async def dispatch_message(parsed, ctx, state_machine, logger=None):
    if parsed.command is None:
        return ""

    logger = logger or logging.getLogger(__name__)
    user_role = resolve_role(getattr(ctx, "author", ctx))

    try:
        canonical, info = resolve_plugin(parsed)
        check_permission(info, user_role)
        return await execute_plugin(info, parsed.args or "", ctx, state_machine, logger=logger)

    except _PluginNotFound:
        return ""  # silent fall-through  command not recognised

    except PermissionError:
        return "You do not have permission to use this command."

    except _PluginExecutionError:
        return "An internal error occurred while processing your command."

# End of plugins/manager.py