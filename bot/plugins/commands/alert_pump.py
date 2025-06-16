"""AlertPump Cog
================
Background task that relays runtime alerts (text messages) from
`BotLifecycle.alerts_q` to the bot owner via DM.  Any part of the codebase can
enqueue a human-readable string on that queue and it will be delivered.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands
from typing import cast

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------+
#  Tunables – can be overridden in tests or future settings                  +
# ---------------------------------------------------------------------------+
MAX_RETRY_ATTEMPTS = 5  # total tries per alert (initial + 4 retries)
INITIAL_RETRY_DELAY = 1.0  # seconds; doubled each time


class AlertPump(commands.Cog):
    """Listens on ``lifecycle.alerts_q`` and forwards messages to the owner."""

    def __init__(self, bot: commands.Bot) -> None:  # noqa: D401 – simple description
        self.bot = bot
        self._task: asyncio.Task[None] | None = None
        self.owner: discord.User | None = None

    async def cog_load(self) -> None:  # Called by discord.py 2.3+
        # Wait until bot is ready only if it's already logging in; avoid calling
        # before the Client has been initialised which raises RuntimeError.
        if hasattr(self.bot, "wait_until_ready"):
            try:
                if not self.bot.is_ready():
                    await self.bot.wait_until_ready()
            except RuntimeError:
                # Client not yet initialised; we'll proceed and owner resolution
                # will retry inside the relay loop once the bot is ready.
                pass
        lifecycle = getattr(self.bot, "lifecycle", None)
        if lifecycle is None or not hasattr(lifecycle, "alerts_q"):
            logger.warning(
                "AlertPump loaded but lifecycle.alerts_q not available – disabled"
            )
            return  # cannot proceed without a queue

        # At this point lifecycle is guaranteed to have 'alerts_q'
        q: asyncio.Queue[str] = cast("asyncio.Queue[str]", lifecycle.alerts_q)
        owner_id = self.bot.owner_id
        if owner_id is not None:
            self.owner = self.bot.get_user(owner_id)
        else:
            self.owner = None

        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._relay_loop(q))

    async def cog_unload(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _relay_loop(self, q: "asyncio.Queue[str]") -> None:
        """Forever consume the queue and DM the owner."""
        while not self.bot.is_closed():
            try:
                # Wake up periodically even when no alerts arrive
                msg = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            try:
                owner = None
                if self.bot.owner_id:
                    owner = self.bot.get_user(self.bot.owner_id)

                if owner is None:
                    # Ensure application info has been fetched and owner cached
                    try:
                        app_info = await self.bot.application_info()
                        owner = app_info.owner
                    except Exception as exc:
                        logger.error("Cannot resolve bot owner: %s", exc)

                if owner is None:
                    logger.warning("Cannot send alert – owner unavailable: %s", msg)
                else:
                    await self._send_dm_with_retry(owner, f"⚠️ **Bot alert:** {msg}")
            finally:
                q.task_done()

    # ------------------------------------------------------------------+
    # internal helpers                                                   +
    # ------------------------------------------------------------------+

    async def _send_dm_with_retry(
        self,
        owner: discord.User,
        content: str,
    ) -> None:
        """Try sending *content* to *owner* with exponential back-off."""

        delay = INITIAL_RETRY_DELAY
        attempt = 0
        while attempt < MAX_RETRY_ATTEMPTS:
            try:
                await owner.send(content)
                return  # success
            except discord.HTTPException as exc:
                attempt += 1
                if attempt >= MAX_RETRY_ATTEMPTS:
                    logger.error(
                        "Alert DM failed after %s attempts – giving up: %s",
                        attempt,
                        exc,
                    )
                    return

                logger.warning(
                    "Alert DM attempt %s/%s failed (%s) – retrying in %.1fs",
                    attempt,
                    MAX_RETRY_ATTEMPTS,
                    exc.__class__.__name__,
                    delay,
                )
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    raise  # respect shutdown
                delay *= 2  # exponential back-off


async def setup(bot: commands.Bot) -> None:  # discord.py extension entry-point
    await bot.add_cog(AlertPump(bot))
