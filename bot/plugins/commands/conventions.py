"""
Shared helpers & constants for every command cog.
"""

from typing import Any
from discord.ext import commands


class CommandSpecMixin(commands.Cog):
    """
    Mixin that enforces three public attributes on every cog:

        USAGE        – human-readable multi-line help block
        _ENTRY_CMD   – top-level invocation word (e.g. 'browser')
        CMD_*        – one constant per sub-command
    """

    # subclasses must override:
    USAGE: str
    _ENTRY_CMD: str

    async def cog_command_error(
        self,
        ctx: commands.Context[Any],
        error: Exception,
    ) -> None:
        from discord.ext import commands

        if isinstance(error, commands.CommandNotFound):
            bad = ctx.invoked_with or "?"
            await ctx.send(f"⚠️ Unknown sub-command `{bad}`.\n{self.USAGE}")
            return
        raise error


__all__ = ["CommandSpecMixin"]
