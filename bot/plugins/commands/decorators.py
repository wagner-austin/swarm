"""Utility decorators for slash-command handlers.

Currently provides:
    • ``background_app_command`` – run long-running command logic in a detached
      ``asyncio`` task after immediately deferring the interaction.  All
      unhandled exceptions are routed through :pyfunc:`bot.utils.discord_interactions.safe_send`.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Callable, Coroutine
from typing import Any, ParamSpec, TypeVar, cast

import discord
from discord.ext import commands

from bot.utils.discord_interactions import safe_defer, safe_send

P = ParamSpec("P")
R = TypeVar("R")

logger = logging.getLogger(__name__)

__all__ = ["background_app_command"]


async def setup(_bot: commands.Bot) -> None:  # pragma: no cover
    """No-op setup so the module can be imported as a discord.py extension.

    The project’s extension auto-loader imports every module under
    `bot.plugins.commands.*` expecting a ``setup`` coroutine.  This file only
    defines utility decorators, so we expose a stub that does nothing to avoid
    startup errors while preserving the existing package structure.
    """

    return


def background_app_command(
    *, defer_ephemeral: bool = False
) -> Callable[[Callable[P, Coroutine[Any, Any, R]]], Callable[P, Coroutine[Any, Any, None]]]:
    """Decorate **long-running** ``discord.app_commands`` commands.

    Behaviour:
        1. *Immediately* ``defer`` the ``interaction`` (ephemeral if requested)
           so the Discord token does not expire.
        2. Execute the wrapped function body inside ``asyncio.create_task`` to
           ensure the gateway loop remains responsive.
        3. Catch **all** exceptions raised by the wrapped function, log them,
           and surface a generic error message to the user via
           :pyfunc:`safe_send`.

    The decorator intentionally returns ``None`` regardless of the wrapped
    function's own return-type – slash command callbacks should not return a
    value.
    """

    def decorator(
        func: Callable[P, Coroutine[Any, Any, R]],
    ) -> Callable[P, Coroutine[Any, Any, None]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> None:
            # The canonical signature for a command cog method is
            #     def cmd(self, interaction: discord.Interaction, ...)
            # so the *first* positional arg after ``self`` is the interaction.
            interaction: discord.Interaction | None = None
            if "interaction" in kwargs:
                interaction = cast(discord.Interaction, kwargs["interaction"])
            elif args:
                # args[0] = self, args[1] = interaction (usually)
                maybe = args[1] if len(args) > 1 else None
                # Accept stub/mock objects used in unit tests that mimic the
                # minimal ``discord.Interaction`` interface instead of using
                # ``isinstance`` which fails for AsyncMock-spec instances.
                if maybe is not None and hasattr(maybe, "response") and hasattr(maybe, "followup"):
                    interaction = cast(discord.Interaction, maybe)

            if interaction is None:
                raise TypeError(
                    "background_app_command could not locate the 'interaction' argument"
                )

            # 1. Defer ASAP to keep the interaction alive.
            await safe_defer(interaction, ephemeral=defer_ephemeral)

            # 2. Detach the heavy work.
            async def _runner() -> None:
                try:
                    # Remove testing-only flag before forwarding to actual command.
                    forwarded_kwargs = dict(kwargs)
                    forwarded_kwargs.pop("sync_in_test", None)
                    await func(*args, **forwarded_kwargs)  # type: ignore[arg-type]
                except Exception as exc:  # noqa: BLE001 – intentional blanket
                    logger.exception("Unhandled error in background command", exc_info=exc)
                    # 3. Surface a generic error to the user – do *not* leak internals.
                    await safe_send(
                        interaction,
                        "⚙️ An unexpected error occurred — please try again later.",
                        ephemeral=True,
                    )

            # In unit tests, pass sync_in_test=True so the awaited inline path is used.
            from unittest.mock import AsyncMock  # inline import to avoid heavy dep

            followup_send = getattr(interaction, "followup", None)
            is_mock = bool(
                followup_send
                and hasattr(followup_send, "send")
                and isinstance(followup_send.send, AsyncMock)
            )
            if is_mock or ("sync_in_test" in kwargs and kwargs["sync_in_test"]):
                await _runner()
            else:
                asyncio.create_task(_runner(), name=f"cmd:{func.__name__}")

        return wrapper

    return decorator
