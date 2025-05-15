"""
bot_plugins.subcommand_mixin
----------------------------
Re-usable helper that wraps `handle_subcommands()` and centralises the
repetitive try/except/await boilerplate used by several plugins.
"""
from __future__ import annotations
import asyncio
import logging
from bot_plugins.commands.subcommand_dispatcher import handle_subcommands, PluginArgError

class SubcommandPluginMixin:
    """
    Drop-in mix-in for any plugin that delegates to `handle_subcommands()`.
    """

    async def dispatch_subcommands(
        self,
        args: str,
        subcommands: dict,
        usage_msg: str,
        *,
        unknown_subcmd_msg: str = "Unknown subcommand",
        parse_mode: str = "positional",
        parse_maxsplit: int = -1,
        default_subcommand: str | None = None,
    ) -> str:
        log = getattr(self, "logger", None) or logging.getLogger(__name__)
        try:
            result = handle_subcommands(
                args,
                subcommands=subcommands,
                usage_msg=usage_msg,
                unknown_subcmd_msg=unknown_subcmd_msg,
                parse_mode=parse_mode,
                parse_maxsplit=parse_maxsplit,
                default_subcommand=default_subcommand,
            )
            # `handle_subcommands` may itself return a coroutine from a
            # subcommand – await it transparently.
            if asyncio.iscoroutine(result):
                result = await result

            if isinstance(result, str):
                return result
            log.warning("Subcommand returned non-string %r", result)
            return ""
        except PluginArgError as exc:
            return str(exc)
        except Exception:                       # noqa: BLE001
            log.exception("Unhandled error in subcommand dispatcher")
            return "An internal error occurred."
