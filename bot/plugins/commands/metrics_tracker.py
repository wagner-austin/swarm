"""
Runtime counters for uptime and traffic volume.

This cog uses *public* discord.py gateway hooks – no monkey-patching required.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Coroutine, cast

import discord  # need both Message & Interaction types
from discord.ext import commands

from bot.core import metrics as default_metrics
from bot.core.telemetry import BOT_LATENCY


class MetricsTracker(commands.Cog):
    """Increment lightweight counters for /status."""

    def __init__(self, bot: commands.Bot, metrics: Any = default_metrics) -> None:
        # keep a ref so we can recognise our own messages
        self.bot = bot
        self.metrics = metrics
        # start latency updater background task
        self._latency_task: asyncio.Task[None] | None = None

    async def cog_load(self) -> None:  # noqa: D401
        """Start background latency updater once the cog is ready."""
        if self._latency_task is None:
            self._latency_task = asyncio.create_task(self._latency_loop())

    async def cog_unload(self) -> None:  # noqa: D401
        if self._latency_task:
            self._latency_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._latency_task

    def __del__(self) -> None:
        # Fallback for tests that don't call cog_unload(). Ensure the task finishes
        # so the event loop does not complain about pending tasks on shutdown.
        if self._latency_task and not self._latency_task.done():
            self._latency_task.cancel()
            try:
                loop: asyncio.AbstractEventLoop = self._latency_task.get_loop()
                # If the loop is still alive, give it a chance to finish the task.
                if loop.is_running() and not loop.is_closed():
                    import concurrent.futures

                    # Run the coroutine completion in a thread-safe manner and
                    # wait briefly (max 100 ms) – long enough for a clean
                    # cancellation but short enough to stay non-blocking.
                    async def _await_task(t: asyncio.Task[None]) -> None:  # pragma: no cover
                        with contextlib.suppress(asyncio.CancelledError):
                            await t

                    fut: concurrent.futures.Future[None] = asyncio.run_coroutine_threadsafe(
                        _await_task(self._latency_task),
                        loop,
                    )
                    try:
                        fut.result(timeout=0.1)
                    except (asyncio.CancelledError, concurrent.futures.TimeoutError):
                        # Either expected cancellation or we ran out of time –
                        # in both cases we do not care because the task is
                        # already cancelled.
                        pass
            except Exception:  # pragma: no cover – best-effort cleanup
                pass

    async def _latency_loop(self) -> None:
        """Update the bot latency gauge every 30 s while the bot is running.

        The loop exits automatically once the bot is closed or the task is
        cancelled. This prevents spurious "Task was destroyed but it is pending"
        warnings during test teardown when the event loop is closed before the
        task naturally finishes.
        """
        try:
            while not self.bot.is_closed():
                latency = float(self.bot.latency or 0.0)
                BOT_LATENCY.observe(latency)
                # Sleep *inside* the running loop so cancellation can interrupt
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            # Expected during shutdown – swallow to mark the task as finished
            pass

    # ------------------------------------------------------------------+
    # Inbound messages – everything the gateway delivers in MESSAGE_CREATE
    # ------------------------------------------------------------------+
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:  # noqa: D401
        """
        *If* the author is **us** → outbound counter.<br>
        Otherwise → inbound counter.
        """
        if (
            self.bot.user  # may be None during early startup
            and message.author.id == self.bot.user.id
        ):
            self.metrics.increment_message_count()
        else:
            self.metrics.increment_discord_message_count()

    # ------------------------------------------------------------------+
    # Slash-command / component / autocomplete traffic                  |
    # ------------------------------------------------------------------+
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:  # noqa: D401
        """
        Every **user-initiated Interaction** counts as inbound traffic.

        We ignore pings, heartbeats, and our own follow-ups (those don’t reach `on_interaction` anyway).
        """
        if (
            interaction.type.name != "ping"  # not a gateway keep-alive
            and interaction.user  # guaranteed for app commands
            and (
                self.bot.user is None  # startup race-condition
                or interaction.user.id != self.bot.user.id
            )
        ):
            self.metrics.increment_discord_message_count()


async def setup(bot: commands.Bot, metrics: Any | None = None) -> None:  # noqa: D401 – entry point
    await bot.add_cog(MetricsTracker(bot, metrics=metrics or default_metrics))
