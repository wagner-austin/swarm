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

# Import role constants and permission check
from core.permissions import OWNER, has_permission
from core.identity import resolve_role

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
            async def plugin_func(args, ctx, state_machine, **kwargs):
                if inspect.iscoroutinefunction(instance.run_command):
                    return await instance.run_command(args, ctx, state_machine, **kwargs)
                else:
                    return instance.run_command(args, ctx, state_machine, **kwargs)
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
            if inspect.iscoroutinefunction(obj):
                async def plugin_func(args, ctx, state_machine, **kwargs):
                    return await obj(args, ctx, state_machine, **kwargs)
            else:
                async def plugin_func(args, ctx, state_machine, **kwargs):
                    return obj(args, ctx, state_machine, **kwargs)
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
    Load all plugin modules from 'plugins.commands'.
    """
    import plugins.commands
    module_infos = list(pkgutil.walk_packages(plugins.commands.__path__, plugins.commands.__name__ + "."))
    module_names = {module_info.name for module_info in module_infos}

    def import_module_inner(name):
        try:
            importlib.import_module(name)
            logger.info(f"Imported module '{name}'.")
        except Exception as e:
            logger.error(f"Failed to import module '{name}': {e}", exc_info=True)

    if concurrent:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor() as executor:
            futures = {executor.submit(import_module_inner, name): name for name in module_names}
            for future in as_completed(futures):
                mname = futures[future]
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Unexpected error importing module '{mname}': {e}", exc_info=True)
    else:
        for mname in module_names:
            import_module_inner(mname)


def reload_plugins(concurrent: bool = False) -> None:
    """
    Clear existing plugins and reload all plugins.
    """
    clear_plugins()
    load_plugins(concurrent=concurrent)


async def dispatch_message(parsed, ctx, state_machine, logger=None) -> Any:
    """
    dispatch_message - Processes an incoming message by dispatching commands to plugins.
    Also enforces role-based permissions by comparing the user's role
    to the plugin's required_role.

    Returns either a string or a coroutine that the caller should await.
    """
    command: Optional[str] = parsed.command
    if command is None:
        return ""

    if logger is None:
        logger = logging.getLogger(__name__)

    args: Optional[str] = parsed.args

    # ctx is expected to be a discord.Message or compatible object
    user_role = resolve_role(getattr(ctx, 'author', ctx))

    # Attempt to find the plugin info by direct alias lookup
    canonical_cmd = alias_mapping.get(normalize_alias(command))
    plugin_info = None
    if canonical_cmd is not None:
        plugin_info = plugin_registry.get(canonical_cmd)

    # If not found, attempt fuzzy matching
    if not plugin_info:
        available_commands = list(plugin_registry.keys())
        matches = difflib.get_close_matches(normalize_alias(command), available_commands, n=1, cutoff=0.75)
        if matches:
            matched_cmd = matches[0]
            plugin_info = plugin_registry[matched_cmd]
            logger.info(f"Fuzzy matching: '{command}' -> '{matched_cmd}'")
            # If the matched plugin is disabled, treat as None
            if matched_cmd in disabled_plugins:
                return f"Plugin '{matched_cmd}' is currently disabled."
        else:
            return ""

    # If somehow still None, bail out
    if not plugin_info:
        return ""

    # Check if plugin is disabled
    canon_name = None
    for k, v in plugin_registry.items():
        if v is plugin_info:
            canon_name = k
            break
    if canon_name and canon_name in disabled_plugins:
        return f"Plugin '{canon_name}' is currently disabled."

    # Enforce role-based permission
    required_role = plugin_info.get("required_role", OWNER)

    # User role is already determined by resolve_role(sender) in the calling context
    if not has_permission(user_role, required_role):
        return "You do not have permission to use this command."

    plugin_func = plugin_info.get("function")
    if not plugin_func:
        return ""

    try:
        response = await plugin_func(args or "", ctx, state_machine)
        if response is None or not isinstance(response, str):
            logger.warning(
                f"Plugin '{command}' returned non-string or None. Returning empty string."
            )
            response = ""
        return response
    except Exception as e:
        logger.exception(
            f"Error executing plugin for command '{command}' with args '{args}' "
            f"from sender '{getattr(ctx, 'author', ctx)}': {e}"
        )
        return "An internal error occurred while processing your command."

# End of plugins/manager.py