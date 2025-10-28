from __future__ import annotations

from typing import Protocol

import discord


class SafeSendFunc(Protocol):
    async def __call__(
        self,
        interaction: discord.Interaction,
        content: str | None = None,
        *,
        embed: discord.Embed | None = None,
        file: discord.File | None = None,
        ephemeral: bool = False,
        suppress_embeds: bool = False,
        silent: bool = False,
        tts: bool = False,
    ) -> None: ...


class SafeDeferFunc(Protocol):
    async def __call__(
        self,
        interaction: discord.Interaction,
        *,
        thinking: bool = True,
        ephemeral: bool = False,
    ) -> None: ...


__all__ = ["SafeSendFunc", "SafeDeferFunc"]
