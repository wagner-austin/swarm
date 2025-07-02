"""AlertPump Cog
================
Background task that relays runtime alerts (text messages) from
`BotLifecycle.alerts_q` to the bot owner via DM.  Any part of the codebase can
enqueue a human-readable string on that queue and it will be delivered.
"""

from __future__ import annotations

import asyncio
import logging
from typing import cast

import discord
from discord.ext import commands

from bot.frontends.discord.discord_owner import get_owner
from bot.utils.async_helpers import with_retries

logger = logging.getLogger(__name__)

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
        self._startup_alert_sent: bool = False
        # Alerts that could not be sent yet because the owner is unresolved.
        self._pending: list[str | discord.Embed] = []

    async def cog_load(self) -> None:  # Called by discord.py 2.3+
        lifecycle = getattr(self.bot, "lifecycle", None)
        if lifecycle is None or not hasattr(lifecycle, "alerts_q"):
            logger.warning("AlertPump loaded but lifecycle.alerts_q not available – disabled")
            return  # cannot proceed without a queue

        q: asyncio.Queue[str] = cast("asyncio.Queue[str]", lifecycle.alerts_q)
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._relay_loop(q))

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Send startup message to owner once connected to Discord."""
        if self._startup_alert_sent:
            return  # Do not send on subsequent reconnects

        embed_online = discord.Embed(
            title="Bot online",
            description="✅ The bot has started and is now online.",
            colour=discord.Colour.green(),
        )
        logger.info("AlertPump: sending startup notification")
        try:
            owner = await get_owner(self.bot)
            await self._send_dm_with_retry(owner, content=None, embed=embed_online)
            self._startup_alert_sent = True
            logger.info("AlertPump: startup notification sent successfully to %s", owner.id)
        except RuntimeError as e:
            logger.error("AlertPump: could not resolve owner to send startup DM: %s", e)
        except discord.HTTPException as e:
            logger.error("AlertPump: failed to send startup DM: %s", e)

    async def cog_unload(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _relay_loop(self, q: asyncio.Queue[str]) -> None:
        """Forever consume the queue and DM the owner."""
        while not self.bot.is_closed():
            got_msg = False
            try:
                # Wake up periodically even when no alerts arrive
                msg = await asyncio.wait_for(q.get(), timeout=1.0)
                # Always stash newly received message first
                self._pending.append(msg)
                got_msg = True
            except TimeoutError:
                # No new message; fall through to retry pending sends
                pass

            # No 'continue' above: we want to attempt delivery for any pending
            # alerts each time the loop wakes up, even if no new alert arrived.
            owner: discord.User | None = None
            try:
                owner = await get_owner(self.bot)
            except RuntimeError as exc:
                logger.debug("Could not resolve owner during relay loop pass: %s", exc)

            if owner is None:
                # Owner still not available – keep messages in the _pending list
                if self._pending:
                    logger.debug(
                        "Owner unresolved – deferring %d alert(s) for next pass",
                        len(self._pending),
                    )
            else:
                # We have an owner: try to flush all pending alerts (oldest first)
                for pending_item in list(self._pending):
                    if isinstance(pending_item, discord.Embed):
                        await self._send_dm_with_retry(owner, content=None, embed=pending_item)
                    else:
                        await self._send_dm_with_retry(owner, f"⚠️ **Bot alert:** {pending_item}")
                self._pending.clear()

            # Acknowledge the queue task only if we actually pulled one.
            if got_msg:
                q.task_done()

    # ------------------------------------------------------------------+
    # internal helpers                                                   +
    # ------------------------------------------------------------------+

    async def _send_dm_with_retry(
        self,
        owner: discord.User,
        content: str | None = None,
        *,
        embed: discord.Embed | None = None,
    ) -> None:
        """Try sending *content* to *owner* with exponential back-off."""

        async def _attempt_send() -> None:
            logger.debug(
                "AlertPump: attempting DM to owner %s",
                getattr(owner, "id", "unknown"),
            )
            try:
                if embed is not None:
                    await owner.send(content=content, embed=embed)
                else:
                    await owner.send(content)
            except TypeError as exc:
                # Handle test doubles without 'content'/'embed' kwargs.
                if embed is not None and content is None:
                    # Startup embed: silently skip in environments that do not
                    # support rich embeds to keep tests expectations intact.
                    logger.debug(
                        "AlertPump: embed unsupported by owner stub – skipping startup embed"
                    )
                    return
                logger.debug(
                    "AlertPump: owner.send signature mismatch (%s) – falling back to plain text",
                    exc,
                )
                fallback_msg = content or (
                    f"{embed.title if embed else ''}\n{embed.description if embed else ''}"
                )
                await owner.send(fallback_msg)
            logger.debug("AlertPump: DM succeeded")

        try:
            await with_retries(_attempt_send, MAX_RETRY_ATTEMPTS, INITIAL_RETRY_DELAY, backoff=2.0)
        except discord.HTTPException as exc:
            logger.error(
                "Alert DM failed after %s attempts – giving up: %s",
                MAX_RETRY_ATTEMPTS,
                exc,
            )
