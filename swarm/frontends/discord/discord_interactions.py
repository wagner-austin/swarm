"""Hardened helpers for responding to Discord interactions.

This module centralises the boiler-plate required to gracefully handle the
various edge-cases around Discord *interactions*.  In particular it prevents
`Unknown interaction` (HTTP error code **10062**) and `Already
acknowledged` (**40060**) failures from propagating or causing double-respond
bugs.

Usage:
    >>> from swarm.frontends.discord.discord_interactions import safe_defer, safe_send, safe_followup

These helpers should be the *only* API used by command cogs and global error
handlers when they need to defer, send, or follow-up to an interaction.
"""

from __future__ import annotations

import inspect
import logging
from typing import Mapping

import discord
from swarm.core.settings import DISCORD_LIMIT, settings

__all__ = [
    "safe_defer",
    "safe_send",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _is_done(interaction: discord.Interaction) -> bool:
    """Robustly check if an interaction response is done."""
    try:
        attr = interaction.response.is_done
        if callable(attr):
            maybe = attr()
            if inspect.isawaitable(maybe):
                import asyncio

                loop = asyncio.get_event_loop()
                maybe = loop.run_until_complete(maybe)
            return bool(maybe)
        return bool(attr)
    except Exception:
        return False


async def safe_defer(
    interaction: discord.Interaction,
    *,
    thinking: bool = True,
    ephemeral: bool = False,
    _ignore: tuple[int, ...] = (10062, 10015, 40060),
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
        # Silently swallow common interaction/webhook expiry errors so that
        # higher-level logic can surface the *real* cause instead of a nested
        # defer failure.
        if getattr(exc, "code", None) not in _ignore:
            raise
    except discord.NotFound:
        # Interaction expired – silently ignore so the caller can decide on a
        # fallback strategy (e.g. channel send).
        pass


async def safe_send(
    interaction: discord.Interaction,
    content: str | None = None,
    *,
    embed: discord.Embed | None = None,
    file: discord.File | None = None,
    ephemeral: bool = False,
    suppress_embeds: bool = False,
    silent: bool = False,
    tts: bool = False,
) -> None:
    """Send a response/follow-up/channel message in a *safe* order.

    Preference order:
        1. ``interaction.response.send_message`` if the response is unused.
        2. ``interaction.followup.send``.
        3. Fallback to the interaction's channel (if available).

    All HTTP exceptions from Discord not related to codes *10062* or *40060* are
    re-raised so upstream handlers can decide the appropriate action.
    """
    # Enforce Discord message length limits (settings.discord_chunk_size defaults to 1900)
    if content and isinstance(content, str):
        max_len: int = DISCORD_LIMIT
        if len(content) > max_len:
            content = content[: max_len - 1] + "…"

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
            if embed is not None and file is not None:
                await interaction.response.send_message(
                    content or "",
                    embed=embed,
                    file=file,
                    ephemeral=ephemeral,
                    suppress_embeds=suppress_embeds,
                    silent=silent,
                    tts=tts,
                )
            elif embed is not None:
                await interaction.response.send_message(
                    content or "",
                    embed=embed,
                    ephemeral=ephemeral,
                    suppress_embeds=suppress_embeds,
                    silent=silent,
                    tts=tts,
                )
            elif file is not None:
                await interaction.response.send_message(
                    content or "",
                    file=file,
                    ephemeral=ephemeral,
                    suppress_embeds=suppress_embeds,
                    silent=silent,
                    tts=tts,
                )
            else:
                await interaction.response.send_message(
                    content or "",
                    ephemeral=ephemeral,
                    suppress_embeds=suppress_embeds,
                    silent=silent,
                    tts=tts,
                )
            return
        except discord.HTTPException as exc:
            # If the exception is *unknown interaction* or *already
            # acknowledged*, fall through to the next strategy.  Otherwise
            # propagate.
            if exc.code not in (10062, 10015, 40060):
                raise
            # fall through

    # Fallback to follow-up webhook.
    try:
        if embed is not None and file is not None:
            await interaction.followup.send(
                content or "",
                embed=embed,
                file=file,
                suppress_embeds=suppress_embeds,
                silent=silent,
                tts=tts,
            )
        elif embed is not None:
            await interaction.followup.send(
                content or "",
                embed=embed,
                suppress_embeds=suppress_embeds,
                silent=silent,
                tts=tts,
            )
        elif file is not None:
            await interaction.followup.send(
                content or "",
                file=file,
                suppress_embeds=suppress_embeds,
                silent=silent,
                tts=tts,
            )
        else:
            await interaction.followup.send(
                content or "",
                suppress_embeds=suppress_embeds,
                silent=silent,
                tts=tts,
            )
        return
    except discord.HTTPException as exc:
        if exc.code not in (10062, 10015, 40060):
            raise
        # The follow-up failed (likely because the token is expired) – as a
        # last resort fall back to the interaction's channel.
        chan = getattr(interaction, "channel", None)
        target = chan if isinstance(chan, discord.abc.Messageable) else None

    if target is None:  # DM or unknown channel; nothing more we can do.
        return

    # Best-effort channel send.  Swallow all exceptions – we don't want to risk
    # an unhandled error shadowing the root-cause.
    try:
        # The channel API has no concept of ephemerality.
        if embed is not None and file is not None:
            await target.send(
                content or "",
                embed=embed,
                file=file,
                suppress_embeds=suppress_embeds,
                silent=silent,
                tts=tts,
            )
        elif embed is not None:
            await target.send(
                content or "",
                embed=embed,
                suppress_embeds=suppress_embeds,
                silent=silent,
                tts=tts,
            )
        elif file is not None:
            await target.send(
                content or "",
                file=file,
                suppress_embeds=suppress_embeds,
                silent=silent,
                tts=tts,
            )
        else:
            await target.send(
                content or "",
                suppress_embeds=suppress_embeds,
                silent=silent,
                tts=tts,
            )
    except Exception:  # pragma: no cover – log and swallow
        logger.exception("Final channel send fallback failed.")
