#!/usr/bin/env python
"""
plugins/commands/subcommand_dispatcher.py - Subcommand dispatch utility.
Provides a high-level `handle_subcommands(...)` function for consistent subcommand parsing.
"""

from typing import List, Dict, Callable, Optional
from bot_core.parsers.argument_parser import parse_plugin_arguments
from bot_core.parsers.plugin_arg_parser import PluginArgError


def dispatch_subcommand(tokens: List[str],
                        subcommands: Dict[str, Callable[..., str]],
                        usage_msg: str = None,
                        unknown_subcmd_msg: str = None) -> str:
    """
    Dispatch subcommand based on tokens.
    Raises PluginArgError if no subcommand is specified or unrecognized.
    """
    if not tokens:
        final_msg = usage_msg or "No subcommand specified."
        raise PluginArgError(final_msg)

    cmd = tokens[0].lower()
    rest = tokens[1:]

    if cmd not in subcommands:
        msg_parts = []
        if unknown_subcmd_msg:
            msg_parts.append(unknown_subcmd_msg)
        if usage_msg:
            msg_parts.append(usage_msg)
        if not msg_parts:
            msg_parts = [f"Unknown subcommand '{cmd}'."]
        combined_message = "\n\n".join(msg_parts)
        raise PluginArgError(combined_message)

    return subcommands[cmd](rest)


def handle_subcommands(args: str,
                       subcommands: Dict[str, Callable[[List[str]], str]],
                       usage_msg: str,
                       unknown_subcmd_msg: str = "Unknown subcommand",
                       parse_mode: str = 'positional',
                       parse_maxsplit: int = -1,
                       default_subcommand: Optional[str] = None) -> str:
    """
    Parse and dispatch subcommands from the given argument string.
    If no tokens are parsed and default_subcommand is provided, it will be used.
    """
    if not args.strip():
        if default_subcommand:
            tokens = [default_subcommand]
        else:
            raise PluginArgError(usage_msg)
    else:
        parsed = parse_plugin_arguments(args, mode=parse_mode, maxsplit=parse_maxsplit)
        tokens = parsed["tokens"]
        if not tokens and default_subcommand:
            tokens = [default_subcommand]
        elif not tokens:
            raise PluginArgError(usage_msg)

    return dispatch_subcommand(tokens, subcommands, usage_msg, unknown_subcmd_msg)

# End of plugins/commands/subcommand_dispatcher.py