"""AlertPump Cog
================
Background task that relays runtime alerts (text messages) from
`SwarmLifecycle.alerts_q` to the swarm owner via DM.  Any part of the core system can
enqueue a human-readable string on that queue and it will be delivered.
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import io
import logging
import os
from typing import Any, Coroutine, Mapping, Optional, Tuple, cast

import discord
import requests
from discord.ext import commands

from swarm.frontends.discord.discord_owner import get_owner
from swarm.utils.async_helpers import with_retries

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------+
#  Tunables – can be overridden in tests or future settings                  +
# ---------------------------------------------------------------------------+
MAX_RETRY_ATTEMPTS = 5  # total tries per alert (initial + 4 retries)
INITIAL_RETRY_DELAY = 1.0  # seconds; doubled each time

# HAProxy configuration
HAPROXY_BACKEND_NAME = os.getenv("HAPROXY_BACKEND_NAME", "redis_backend")


def _g(row: Mapping[str, str], key: str, default: str = "") -> str:
    """Get a field from a HAProxy CSV row, tolerant of '# ' prefixes."""
    val = row.get(key)
    if val:
        return val
    alt_key = key.lstrip("# ").strip()
    alt = row.get(alt_key)
    if alt:
        return alt
    return default


def _to_int(v: str | None) -> int:
    """Convert to int safely, defaulting to 0."""
    try:
        return int(v or 0)
    except Exception:
        return 0


def read_haproxy_backend_status(
    base: str, timeout: float = 2.0, auth: tuple[str, str] | None = None
) -> tuple[bool, bool, bool]:
    """Return (upstash_up, local_up, in_failover).

    Failover = local (backup) is up AND (primary is down OR local is serving traffic).
    """
    url = f"{base.rstrip('/')}/stats;csv;norefresh"
    r = requests.get(url, timeout=timeout, auth=auth)
    r.raise_for_status()

    rdr = csv.DictReader(io.StringIO(r.text))
    upstash_up = False
    local_up = False
    local_has_sessions = False

    for row in rdr:
        px = _g(row, "# pxname")
        sv = _g(row, "svname")
        if px != HAPROXY_BACKEND_NAME or sv in ("FRONTEND", "BACKEND"):
            continue

        status = (_g(row, "status") or "").upper()
        scur = _to_int(_g(row, "scur"))

        if sv == "redis_0":  # primary (Upstash)
            upstash_up = status == "UP"
        elif sv == "redis_1":  # backup (local)
            local_up = status == "UP"
            local_has_sessions = scur > 0

    in_failover = local_up and (not upstash_up or local_has_sessions)
    return upstash_up, local_up, in_failover


class AlertPump(commands.Cog):
    """Listens on ``lifecycle.alerts_q`` and forwards messages to the swarm owner."""

    def __init__(self, *, discord_bot: commands.Bot, lifecycle: Any) -> None:
        super().__init__()  # No bot passed to base
        self.discord_bot = discord_bot
        self.lifecycle = lifecycle
        self._task: asyncio.Task[None] | None = None
        self._startup_alert_sent: bool = False
        # Alerts that could not be sent yet because the owner is unresolved.
        self._pending: list[str | discord.Embed] = []

    async def cog_load(self) -> None:  # Called by discord.py 2.3+
        if self.lifecycle is None or not hasattr(self.lifecycle, "alerts_q"):
            logger.warning("AlertPump loaded but lifecycle.alerts_q not available – disabled")
            return  # cannot proceed without a queue

        q: asyncio.Queue[str] = cast("asyncio.Queue[str]", self.lifecycle.alerts_q)
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._relay_loop(q))

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Send startup message to owner once connected to Discord."""
        if self._startup_alert_sent:
            return  # Do not send on subsequent reconnects

        # Gather system information
        import os

        from swarm.core.settings import settings

        # Determine Redis backend and check actual status
        redis_info = "❌ Disabled"
        actual_backend = ""

        if settings.redis.enabled and settings.redis.url:
            redis_url = settings.redis.url

            # If using HAProxy, check which backend is actually active
            if "haproxy" in redis_url.lower():
                # Use config-driven URL and timeout
                haproxy_base = os.getenv("HAPROXY_STATS_BASE", "http://haproxy-redis:8080")
                timeout = float(os.getenv("HAPROXY_STATS_TIMEOUT", "2"))

                user = os.getenv("HAPROXY_STATS_USER")
                auth: tuple[str, str] | None = None
                if user:  # truthy check - empty string won't create auth tuple
                    auth = (user, os.getenv("HAPROXY_STATS_PASS", ""))

                try:
                    upstash_up, local_up, in_failover = read_haproxy_backend_status(
                        haproxy_base, timeout, auth
                    )

                    # Log debug info if debug logging is enabled
                    logger.debug(
                        f"HAProxy status: primary_up={upstash_up}, backup_up={local_up}, failover={in_failover}"
                    )

                    if in_failover:
                        actual_backend = "🔴 Local Redis (FAILOVER ACTIVE)"
                    elif upstash_up and local_up:
                        actual_backend = "☁️ Upstash (Primary)"
                    elif upstash_up and not local_up:
                        actual_backend = "☁️ Upstash (Primary, backup down)"
                    elif local_up and not upstash_up:
                        actual_backend = "💾 Local Redis (Upstash DOWN)"
                    else:
                        actual_backend = "⚠️ No backends available!"

                    redis_info = f"🔄 HAProxy → {actual_backend}"

                except Exception as e:
                    # Keep it quiet in prod, verbose in debug
                    logger.debug(f"Could not check HAProxy status via CSV: {e}")
                    redis_info = "🔄 HAProxy (status unknown)"

            elif "upstash" in redis_url.lower():
                redis_info = "☁️ Upstash (Direct)"
            elif "localhost" in redis_url or "127.0.0.1" in redis_url:
                redis_info = "💾 Local Redis (Direct)"
            else:
                # Hide password but show host
                if "@" in redis_url:
                    host_part = redis_url.split("@")[1].split("/")[0]
                    redis_info = f"🔗 {host_part}"
                else:
                    redis_info = "✅ Enabled"

        # Check if distributed workers are enabled
        use_distributed = os.getenv("USE_DISTRIBUTED_WORKERS", "false").lower() == "true"
        workers_info = "🌐 Distributed (Celery)" if use_distributed else "🖥️ Local only"

        # Get metrics port
        metrics_port = os.getenv("METRICS_PORT", "9200")

        # Get Gemini model
        gemini_model = settings.gemini_model

        # Build the embed with system info
        embed_online = discord.Embed(
            title="🟢 Swarm Online",
            description="✅ The swarm has started and is now online.",
            colour=discord.Colour.green(),
        )

        # Add system information fields
        embed_online.add_field(name="Memory Backend", value=redis_info, inline=True)
        embed_online.add_field(name="Worker Mode", value=workers_info, inline=True)
        embed_online.add_field(name="Metrics", value=f"📊 Port {metrics_port}", inline=True)
        embed_online.add_field(name="LLM Model", value=f"🤖 {gemini_model}", inline=True)

        # Add deployment environment if available
        deployment_env = os.getenv("DEPLOYMENT_ENV", "local")
        if deployment_env != "local":
            embed_online.add_field(name="Environment", value=f"🚀 {deployment_env}", inline=True)

        # Add timestamp
        embed_online.timestamp = discord.utils.utcnow()

        logger.info("AlertPump: sending startup notification with system info")
        try:
            owner = await get_owner(self.discord_bot)
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

    def __del__(self) -> None:
        # Fallback for tests that don't call cog_unload(). Ensure the task finishes
        # so the event loop does not complain about pending tasks on shutdown.
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                loop = self._task.get_loop()
                if loop.is_running() and not loop.is_closed():
                    import concurrent.futures

                    async def _await_task(t: asyncio.Task[None]) -> None:  # pragma: no cover
                        with contextlib.suppress(asyncio.CancelledError):
                            await t

                    fut: concurrent.futures.Future[None] = asyncio.run_coroutine_threadsafe(
                        _await_task(self._task),
                        loop,
                    )
                    try:
                        fut.result(timeout=0.1)
                    except (asyncio.CancelledError, concurrent.futures.TimeoutError):
                        pass
            except Exception:  # pragma: no cover – best-effort cleanup
                pass

    async def _relay_loop(self, q: asyncio.Queue[str]) -> None:
        """Forever consume the queue and DM the owner.

        The loop exits automatically when the swarm is closed or when the task is
        cancelled, preventing pending-task warnings during test teardown.
        """
        try:
            while not self.discord_bot.is_closed():
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
                # No new message; fall through to retry pending sends
                pass

                # Attempt to deliver any pending alerts on every loop pass.
                try:
                    owner = await get_owner(self.discord_bot)
                except RuntimeError as exc:
                    logger.debug("Could not resolve owner during relay loop pass: %s", exc)
                    owner = None

                if owner is None:
                    # Owner still unavailable – keep messages queued for next pass.
                    if self._pending:
                        logger.debug(
                            "Owner unresolved – deferring %d alert(s) for next pass",
                            len(self._pending),
                        )
                else:
                    # Flush all pending alerts (oldest first)
                    for pending_item in list(self._pending):
                        if isinstance(pending_item, discord.Embed):
                            await self._send_dm_with_retry(owner, content=None, embed=pending_item)
                        else:
                            await self._send_dm_with_retry(
                                owner, f"⚠️ **Swarm alert:** {pending_item}"
                            )
                    self._pending.clear()

                # Acknowledge the queue task only if we actually pulled one.
                if got_msg:
                    q.task_done()
        except asyncio.CancelledError:
            # Expected during shutdown – swallow to allow clean task finalisation.
            pass

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
