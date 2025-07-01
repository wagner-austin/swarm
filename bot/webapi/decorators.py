"""bot.webapi.decorators
========================
Reusable decorators and type aliases shared across browser-related cogs.

These helpers were extracted from *bot/plugins/commands/web.py* so that other
cogs (e.g. `/pdf`, `/social`) can share the same permission guard and
queue-handling logic without importing from inside another cog, avoiding circular
imports.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Callable, Coroutine, ParamSpec, cast

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.settings import settings
from bot.utils.discord_interactions import safe_defer, safe_send
from bot.utils.discord_owner import get_owner

logger = logging.getLogger(__name__)

P = ParamSpec("P")

# ---------------------------------------------------------------------------
# Public type alias
# ---------------------------------------------------------------------------

CommandResult = tuple[str, tuple[Any, ...], str]

# ---------------------------------------------------------------------------
# Permission guard – read-only browser mode
# ---------------------------------------------------------------------------


def read_only_guard() -> Callable[[Callable[..., Coroutine[Any, Any, Any]]], Any]:
    """Prevent mutating commands when ``settings.browser.read_only`` is *True*.

    The decorated command is still allowed when the invoking user is either the
    bot owner or holds the **Administrator** guild permission.
    """

    async def predicate(inter: discord.Interaction) -> bool:  # noqa: D401
        if not settings.browser.read_only:
            return True

        client = inter.client
        if not isinstance(client, commands.Bot):
            return False  # Not a bot context, cannot resolve owner

        try:
            owner = await get_owner(client)
            is_owner = inter.user.id == owner.id
        except RuntimeError:
            is_owner = False

        is_admin = (
            isinstance(inter.user, discord.Member) and inter.user.guild_permissions.administrator
        )

        if is_owner or is_admin:
            return True

        await safe_send(
            inter,
            "🔒 The browser is currently in **read-only** mode; mutating actions are disabled.",
            ephemeral=True,
        )
        return False

    return app_commands.check(predicate)


# ---------------------------------------------------------------------------
# Main decorator used by browser slash-commands
# ---------------------------------------------------------------------------


def browser_command(
    *,
    queued: bool = True,
    allow_mutation: bool = False,
    defer_ephemeral: bool = False,
) -> Callable[[Callable[..., Coroutine[Any, Any, CommandResult | None]]], Any]:
    """Wrap a slash-command handler so that

    1. the interaction is *deferred* quickly,
    2. command arguments are validated inside the handler before we show a spinner,
    3. (optionally) the :pyclass:`~bot.browser.runtime.BrowserRuntime` queue is utilised, and
    4. common error handling is applied consistently across commands.
    """

    def decorator(
        func: Callable[P, Coroutine[Any, Any, CommandResult | None]],
    ) -> Callable[P, Coroutine[Any, Any, None]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> None:
            self_obj, interaction = args[:2]  # Cog methods: (self, interaction, ...)
            if not isinstance(interaction, discord.Interaction):
                raise TypeError("browser_command expects Interaction as second argument")

            # Execute the underlying handler ***first*** so it can validate inputs
            # (e.g. URL format) before we show the Discord "thinking" state.
            result = await func(*args, **kwargs)
            if result is None:
                return  # Handler already responded or validation failed.

            op, op_args, success_msg = result

            # ------------------------------------------------------------------
            # Defer early so the user sees instant feedback
            # ------------------------------------------------------------------
            if defer_ephemeral:
                await safe_defer(interaction, thinking=True, ephemeral=True)
            else:
                await safe_defer(interaction, thinking=True)

            # ------------------------------------------------------------------
            # Non-queued commands simply return here (handler did the work)
            # ------------------------------------------------------------------
            if not queued:
                return

            chan_id = interaction.channel_id
            if chan_id is None:
                await safe_send(
                    interaction,
                    "This command must be used inside a text channel.",
                    ephemeral=True,
                )
                return

            # ------------------------------------------------------------------
            # Enqueue the operation in BrowserRuntime
            # ------------------------------------------------------------------
            try:
                runtime = getattr(self_obj, "runtime")
                # Dispatch operation to browser worker. We intentionally do not await the returned
                # Future/task here; the worker manages execution completion.
                fut = await runtime.enqueue(chan_id, op, *op_args)

                # Prevent unhandled-exception noise; log a concise error instead.
                def _log(f: object) -> None:  # noqa: D401 – callback must be sync
                    # Skip mocks that don’t behave like real Futures (e.g. AsyncMock in tests)
                    from unittest.mock import (
                        AsyncMock,  # local import to avoid test dependency overhead
                    )

                    if not isinstance(f, asyncio.Future) or isinstance(f, AsyncMock):
                        return
                    try:
                        exc = f.exception()
                        if exc is not None:
                            logger.error("Browser command '%s' failed: %s", op, exc)
                    except Exception:
                        # Any access failure shouldn’t raise inside callback
                        pass

                if isinstance(fut, asyncio.Future):
                    fut.add_done_callback(_log)

                if success_msg:
                    await safe_send(interaction, success_msg)
            except asyncio.QueueFull:
                await safe_send(
                    interaction,
                    "❌ The browser command queue is full. Please try again later.",
                    ephemeral=True,
                )
            except Exception as exc:  # noqa: BLE001
                await safe_send(
                    interaction,
                    f"❌ {type(exc).__name__}: {exc}",
                    ephemeral=True,
                )

        if allow_mutation:
            return cast(Callable[P, Coroutine[Any, Any, None]], read_only_guard()(wrapper))
        return cast(Callable[P, Coroutine[Any, Any, None]], wrapper)

    return decorator


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------


def browser_mutating(
    *,
    queued: bool = True,
    defer_ephemeral: bool = False,
) -> Callable[[Callable[..., Coroutine[Any, Any, CommandResult | None]]], Any]:
    """Return a decorator for state-changing browser commands.

    Equivalent to ``browser_command(allow_mutation=True)`` but conveys intent
    explicitly when decorating a mutating slash-command.
    """

    return browser_command(queued=queued, allow_mutation=True, defer_ephemeral=defer_ephemeral)


__all__: list[str] = [
    "CommandResult",
    "read_only_guard",
    "browser_command",
    "browser_mutating",
]
