from __future__ import annotations

import asyncio
import logging
import os
from enum import Enum, auto
from typing import TYPE_CHECKING, Callable

import discord
from discord import Intents
from discord.ext import commands  # For extension loading exceptions

from swarm.core import telemetry

# from swarm.core.containers import Container # Forward ref
from swarm.core.discord.boot import MyBot
from swarm.core.discord.di import initialize_and_wire_container
from swarm.core.discord.events import register_event_handlers
from swarm.core.settings import Settings
from swarm.utils.module_discovery import iter_submodules

if TYPE_CHECKING:
    from swarm.core.containers import Container

logger = logging.getLogger(__name__)


class LifecycleState(Enum):
    IDLE = auto()
    STARTING = auto()
    INITIALIZING_SERVICES = auto()
    LOADING_EXTENSIONS = auto()
    REGISTERING_HANDLERS = auto()
    CONNECTING_TO_DISCORD = auto()
    RUNNING = auto()  # Implicitly when bot.start() is running
    SHUTTING_DOWN = auto()
    STOPPED = auto()


class SwarmLifecycle:
    def __init__(self, settings: Settings, *, swarm_factory: Callable[..., MyBot] | None = None):
        self._settings: Settings = settings
        self._bot_factory = swarm_factory
        self._swarm_factory = swarm_factory  # If both are needed for backward compatibility
        # ... other init code ...
        self._state: LifecycleState = LifecycleState.IDLE
        self._swarm: MyBot | None = None
        self._container: Container | None = None
        self._shutdown_event = asyncio.Event()
        # Bounded queue for runtime alerts that should be forwarded to the swarm owner.
        self.alerts_q: asyncio.Queue[str] = asyncio.Queue(maxsize=settings.queues.alerts)

    @property
    def state(self) -> LifecycleState:
        return self._state

    def _set_state(self, new_state: LifecycleState) -> None:
        if self._state == new_state:
            return
        logger.info(f"Bot lifecycle state changing from {self._state.name} to {new_state.name}")
        self._state = new_state

    async def run(self) -> None:
        """Run the bot lifecycle."""
        # Start metrics exporter early in lifecycle
        try:
            telemetry.start_exporter(self._settings.metrics_port)
            logger.info("Telemetry metrics exporter started")
        except Exception as e:
            logger.warning(f"Failed to start telemetry exporter: {e}")

        if self._state != LifecycleState.IDLE:
            logger.warning(
                f"Bot run() called when not in IDLE state (current: {self._state.name}). Ignoring."
            )
            return

        self._set_state(LifecycleState.STARTING)

        if not self._settings.discord_token:
            logger.critical("DISCORD_TOKEN is not set. Bot cannot start.")
            self._set_state(LifecycleState.STOPPED)
            return

        try:
            await self._initialize_services_and_bot()
            await self._load_extensions()
            self._register_event_handlers()  # This is synchronous
            # RUNNING state is implicitly managed by _connect_to_discord blocking call
            await self._connect_to_discord()

        except (KeyboardInterrupt, asyncio.CancelledError) as e:
            logger.info(
                f"Shutdown signal (KeyboardInterrupt/CancelledError: {type(e).__name__}) received."
            )
        except discord.errors.LoginFailure:
            logger.critical("Failed to log in to Discord. Check your DISCORD_TOKEN.")
            self._set_state(LifecycleState.STOPPED)
        except Exception as e:
            logger.exception(
                "An unexpected error occurred in the bot's main run cycle:", exc_info=e
            )
            self._set_state(LifecycleState.STOPPED)
        finally:
            await self.shutdown()

    async def _initialize_services_and_bot(self) -> None:
        self._set_state(LifecycleState.INITIALIZING_SERVICES)
        logger.info("Initializing services and bot instance...")

        # 📈  Start Prometheus exporter before other services spin up
        telemetry.start_exporter(self._settings.metrics_port)

        self._container = initialize_and_wire_container(
            app_settings=self._settings,
            runner_module_name=self.__module__,
        )

        intents = Intents.default()
        if self._bot_factory:
            self._bot = self._bot_factory(intents=intents, container=self._container)
        else:
            self._bot = MyBot(
                command_prefix="-",  # Prefix is not used for slash commands
                intents=intents,
                container=self._container,
                settings=self._settings,
            )
        self._bot.lifecycle = self

        logger.info("Services and bot instance initialized.")

    async def _load_extensions(self) -> None:
        if not self._bot or not self._container:
            logger.error("Bot or container not initialized, cannot load extensions.")
            raise RuntimeError("Bot or container not initialized for extension loading.")

        self._set_state(LifecycleState.LOADING_EXTENSIONS)
        logger.info("Discovering and loading extensions (cogs)...")

        # --- DI-Managed Cogs --- #
        # Load specific cogs directly from the container
        logger.info("Loading DI-managed cogs from container...")
        # MetricsTracker
        metrics_tracker_cog = self._container.metrics_tracker_cog(discord_bot=self._bot)
        await self._bot.add_cog(metrics_tracker_cog)
        # LoggingAdmin
        logging_admin_cog = self._container.logging_admin_cog(discord_bot=self._bot)
        await self._bot.add_cog(logging_admin_cog)
        # PersonaAdmin
        persona_admin_cog = self._container.persona_admin_cog(discord_bot=self._bot)
        await self._bot.add_cog(persona_admin_cog)
        # About
        about_cog = self._container.about_cog(discord_bot=self._bot)
        await self._bot.add_cog(about_cog)
        # AlertPump
        alert_pump_cog = self._container.alert_pump_cog(discord_bot=self._bot, lifecycle=self)
        await self._bot.add_cog(alert_pump_cog)
        # Status (DI-managed)
        status_cog = self._container.status_cog(discord_bot=self._bot)
        await self._bot.add_cog(status_cog)
        # Chat
        chat_cog = self._container.chat_cog(discord_bot=self._bot)
        await self._bot.add_cog(chat_cog)
        # Web (DI-managed)
        web_cog = self._container.web_cog(discord_bot=self._bot)
        await self._bot.add_cog(web_cog)
        # Shutdown (DI-managed)
        shutdown_cog = self._container.shutdown_cog(discord_bot=self._bot, lifecycle=self)
        await self._bot.add_cog(shutdown_cog)
        # BrowserHealthMonitor (DI-managed)
        browser_health_monitor_cog = self._container.browser_health_monitor_cog(
            discord_bot=self._bot
        )
        await self._bot.add_cog(browser_health_monitor_cog)
        logger.info(
            "📈 DI cogs added: MetricsTracker, LoggingAdmin, PersonaAdmin, About, AlertPump, Status, Chat, Web, Shutdown, BrowserHealthMonitor."
        )

        # --- Standard Cogs --- #
        # Use an allow-list to control which standard cogs are loaded.
        keep = {"browser", "chat", "help"}
        discovered_extensions = list(iter_submodules("swarm.plugins"))
        extensions_to_load = [
            ext for ext in discovered_extensions if ext.rsplit(".", 1)[-1] in keep
        ]

        loaded: list[str] = [
            "metrics_tracker",
            "logging_admin",
            "persona_admin",
            "about",
            "alert_pump",
            "status",
            "chat",
            "shutdown",
        ]
        failed: list[str] = []

        di_cogs_to_skip = {
            "metrics_tracker",
            "logging_admin",
            "persona_admin",
            "about",
            "alert_pump",
            "status",
            "chat",
            "shutdown",
        }
        for ext_name in extensions_to_load:
            # DI-managed cogs are loaded above, so we skip them here
            if any(di_cog in ext_name for di_cog in di_cogs_to_skip):
                continue
            try:
                await self._bot.load_extension(ext_name)
                loaded.append(ext_name.rsplit(".", 1)[-1])
            except commands.ExtensionNotFound:
                failed.append(ext_name.rsplit(".", 1)[-1])
                logger.error(f"❌ Extension {ext_name} not found")
            except commands.NoEntryPointError:
                failed.append(ext_name.rsplit(".", 1)[-1])
                logger.error(f"❌ Extension {ext_name} has no setup() function.")
            except commands.ExtensionFailed as e:
                failed.append(ext_name.rsplit(".", 1)[-1])
                logger.error(f"❌ Extension {ext_name} failed: {e.original}")
            except Exception as e:
                failed.append(ext_name.rsplit(".", 1)[-1])
                logger.error(f"❌ Unexpected error loading {ext_name}: {e}")
        logger.info(
            f"🧩 Cogs loaded: {', '.join(sorted(loaded)) or '—'}"
            + (f" | ❌ failed: {', '.join(failed)}" if failed else "")
        )

    def _register_event_handlers(self) -> None:
        if not self._bot:
            logger.error("Bot not initialized, cannot register event handlers.")
            raise RuntimeError("Bot not initialized for event handler registration.")

        self._set_state(LifecycleState.REGISTERING_HANDLERS)
        logger.info("Registering event handlers...")
        register_event_handlers(self._bot)
        logger.info("Event handlers registered.")

    async def _connect_to_discord(self) -> None:
        if not self._bot or not self._settings.discord_token:
            logger.error("Bot or token not available, cannot connect to Discord.")
            raise RuntimeError("Bot or token not available for Discord connection.")

        self._set_state(LifecycleState.CONNECTING_TO_DISCORD)
        logger.info("Attempting to connect the bot to Discord...")
        # This call is blocking until the bot is closed or an error occurs
        # Implicitly, state is RUNNING while this await is active
        await self._bot.start(self._settings.discord_token)
        logger.info("Bot has disconnected from Discord (bot.start() returned).")

    async def shutdown(self, signal_name: str | None = None) -> None:
        if self._state in [LifecycleState.SHUTTING_DOWN, LifecycleState.STOPPED]:
            # Avoid re-entrancy or multiple shutdown calls
            if self._state == LifecycleState.SHUTTING_DOWN:
                logger.info("Shutdown already in progress. Waiting for completion.")
                await self._shutdown_event.wait()
            return

        if signal_name:
            logger.info(f"Shutdown initiated by signal: {signal_name}.")
        else:
            logger.info("Shutdown initiated.")

        self._set_state(LifecycleState.SHUTTING_DOWN)

        logger.info("Attempting to gracefully shutdown services...")

        # No local browser runtime shutdown needed in distributed-only architecture.
        logger.info("Finished service shutdown attempts.")

        if self._bot and not self._bot.is_closed():
            logger.info("Closing bot connection...")
            await self._bot.close()
            logger.info("Bot connection closed.")
        else:
            logger.info("Bot was already closed, not started, or not initialized.")

        self._set_state(LifecycleState.STOPPED)
        self._shutdown_event.set()
        logger.info("Bot has shut down.")

    async def wait_for_shutdown(self) -> None:
        await self._shutdown_event.wait()


# ------------------------------------------------------------------
# Global access hook (used by bot.core.alerts.send_alert)
# ------------------------------------------------------------------

_lifecycle_singleton: SwarmLifecycle | None = None
