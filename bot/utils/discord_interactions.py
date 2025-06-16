"""Hardened helpers for responding to Discord interactions.

This module centralises the boiler-plate required to gracefully handle the
various edge-cases around Discord *interactions*.  In particular it prevents
`Unknown interaction` (HTTP error code **10062**) and `Already
acknowledged` (**40060**) failures from propagating or causing double-respond
bugs.

Usage:
    >>> from bot.utils.discord_interactions import safe_defer, safe_send, safe_followup

These helpers should be the *only* API used by command cogs and global error
handlers when they need to defer, send, or follow-up to an interaction.
"""

from __future__ import annotations

import logging
import inspect
from typing import Any

import discord

__all__ = [
    "safe_defer",
    "safe_send",
    "safe_followup",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


async def safe_defer(
    interaction: discord.Interaction,
    *,
    thinking: bool = True,
    ephemeral: bool = False,
) -> None:
    """Safely defer an *interaction* without raising if it has expired.

    The noop-guard means callers can blindly call ``safe_defer`` without first
    checking ``interaction.response.is_done()``.
    """

    try:
        if ephemeral:
            await interaction.response.defer(thinking=thinking, ephemeral=True)
        else:
            await interaction.response.defer(thinking=thinking)
        # Mark as done for simple test doubles that rely on an attribute flag.
        if hasattr(interaction.response, "_done"):
            try:
                setattr(interaction.response, "_done", True)
            except Exception:
                pass
    except discord.HTTPException as exc:
        # 40060 = interaction already acknowledged; safe to ignore
        if getattr(exc, "code", None) != 40060:
            raise
    except discord.NotFound:
        # Interaction expired – silently ignore so the caller can decide on a
        # fallback strategy (e.g. channel send).
        pass


async def safe_send(
    interaction: discord.Interaction,
    content: str | None = None,
    **kwargs: Any,
) -> None:
    """Send a response/follow-up/channel message in a *safe* order.

    Preference order:
        1. ``interaction.response.send_message`` if the response is unused.
        2. ``interaction.followup.send``.
        3. Fallback to the interaction's channel (if available).

    Any ``discord.HTTPException`` not related to codes *10062* or *40060* is
    re-raised so upstream handlers can decide the appropriate action.
    """

    from typing import cast

    target: discord.abc.Messageable | None = None

    # Robust check that copes with AsyncMock in unit tests.
    done_flag: bool
    try:
        attr = interaction.response.is_done
        if callable(attr):
            maybe = attr()
            if inspect.isawaitable(maybe):
                maybe = await maybe
            done_flag = bool(maybe)
        else:
            done_flag = bool(attr)
    except Exception:
        done_flag = False

    if not done_flag:
        try:
            await interaction.response.send_message(content or "", **kwargs)
            return
        except discord.HTTPException as exc:
            # If the exception is *unknown interaction* or *already
            # acknowledged*, fall through to the next strategy.  Otherwise
            # propagate.
            if exc.code not in (10062, 40060):
                raise
            # fall through

    # Fallback to follow-up webhook.
    try:
        await interaction.followup.send(content or "", **kwargs)
        return
    except discord.HTTPException as exc:
        if exc.code not in (10062, 40060):
            raise
        # The follow-up failed (likely because the token is expired) – as a
        # last resort fall back to the interaction's channel.
        target = cast(discord.abc.Messageable | None, interaction.channel)

    if target is None:  # DM or unknown channel; nothing more we can do.
        return

    # Best-effort channel send.  Swallow all exceptions – we don't want to risk
    # an unhandled error shadowing the root-cause.
    try:
        # The channel API has no concept of ephemerality.
        kwargs.pop("ephemeral", None)
        await target.send(content or "", **kwargs)
    except Exception:  # pragma: no cover – log and swallow
        logger.exception("Final channel send fallback failed.")


async def safe_followup(
    interaction: discord.Interaction,
    content: str | None = None,
    **kwargs: Any,
) -> None:
    """Alias for :pyfunc:`safe_send` kept for semantic clarity.

    Historically the codebase used a ``_safe_followup`` helper inside
    *web.py*.  Retaining the *followup* naming avoids widespread refactors in
    existing call-sites while still unifying the implementation.
    """

    await safe_send(interaction, content, **kwargs)
