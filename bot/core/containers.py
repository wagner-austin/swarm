from pathlib import Path
from typing import TYPE_CHECKING, Any

import redis.asyncio as redis_asyncio
from dependency_injector import containers, providers

from bot.ai import providers as _ai_providers
from bot.core import metrics as default_metrics
from bot.core.settings import Settings
from bot.distributed.backends import DockerApiBackend, FlyIOBackend, KubernetesBackend
from bot.distributed.broker import Broker
from bot.distributed.core.config import DistributedConfig
from bot.distributed.remote_browser import RemoteBrowserRuntime
from bot.distributed.runtime_wrappers import CircuitBreakerRuntime
from bot.distributed.services.scaling_service import ScalingService
from bot.frontends.discord.discord_interactions import safe_send
from bot.history.backends import HistoryBackend
from bot.history.factory import choose as history_backend_factory
from bot.infra.tankpit import engine_factory as tankpit_engine_factory
from bot.plugins.commands.status import Status

# TankPit engine factory (netproxy and ws_addon removed)
# DI cogs that must be referenced in providers.Factory at class-scope


class Container(containers.DeclarativeContainer):
    """Dependency Injection Container for the bot.

    This container holds providers for all core services and configurations.
    Services are typically registered as singletons to ensure a single instance
    is used throughout the application lifecycle.
    """

    # Configuration provider for application settings
    # The actual settings values will be loaded when accessed, typically from .env
    config = providers.Singleton(Settings)

    # Conversation history backend (pluggable)

    # Conversation history backend – pluggable
    history_backend: providers.Singleton[HistoryBackend] = providers.Singleton(
        history_backend_factory, config
    )

    # Mapping of LLM provider singletons discovered in bot.ai.providers
    # Resolve the registry lazily so newly registered providers are seen.
    llm_providers = providers.Callable(lambda: _ai_providers.all())

    # Metrics helper (global module, but now injectable)
    metrics_helper = providers.Object(default_metrics)

    # MetricsTracker cog factory with DI
    from bot.plugins.commands.metrics_tracker import MetricsTracker

    metrics_tracker_cog = providers.Factory(
        MetricsTracker,
        bot=providers.Dependency(),
        metrics=metrics_helper,
    )

    # LoggingAdmin cog factory
    from bot.plugins.commands.logging_admin import LoggingAdmin

    logging_admin_cog = providers.Factory(LoggingAdmin, bot=providers.Dependency())

    # PersonaAdmin cog factory
    from bot.plugins.commands.persona_admin import PersonaAdmin

    persona_admin_cog = providers.Factory(
        PersonaAdmin,
        bot=providers.Dependency(),
        safe_send_func=safe_send,
    )

    # About cog factory
    from bot.plugins.commands.about import About

    about_cog = providers.Factory(About, bot=providers.Dependency())

    # AlertPump cog factory
    from bot.plugins.commands.alert_pump import AlertPump

    alert_pump_cog = providers.Factory(
        AlertPump,
        bot=providers.Dependency(),
        lifecycle=providers.Dependency(),
    )

    # Chat cog factory
    from bot.plugins.commands.chat import Chat

    chat_cog = providers.Factory(Chat, bot=providers.Dependency(), history_backend=history_backend)

    # Shutdown cog factory (DI: inject lifecycle)
    from bot.plugins.commands.shutdown import Shutdown

    shutdown_cog = providers.Factory(
        Shutdown,
        bot=providers.Dependency(),
        lifecycle=providers.Dependency(),
        metrics_mod=metrics_helper,
    )

    # Status cog factory (DI)
    status_cog = providers.Factory(
        Status,
        bot=providers.Dependency(),
        metrics_mod=metrics_helper,
        safe_send_func=safe_send,
    )

    # Web cog factory (DI)
    from bot.plugins.commands.web import Web

    # Shared infrastructure providers ---------------------------------
    redis_client: providers.Singleton[redis_asyncio.Redis] = providers.Singleton(
        redis_asyncio.from_url,
        config().redis.url if callable(config) else Settings().redis.url,
        encoding="utf-8",
        decode_responses=False,
        max_connections=20,
        retry_on_timeout=True,
    )

    broker = providers.Singleton(
        Broker,
        config().redis.url if callable(config) else Settings().redis.url,
    )

    # Distributed configuration
    distributed_config = providers.Singleton(DistributedConfig.load)

    # Scaling backend selection based on environment
    scaling_backend = providers.Singleton(
        lambda: DockerApiBackend()  # Default to Docker API backend
    )

    # Scaling service
    scaling_service = providers.Singleton(
        ScalingService,
        redis_client=redis_client,
        config=distributed_config,
        backend=scaling_backend,
    )

    _raw_remote_browser: providers.Factory[RemoteBrowserRuntime] = providers.Factory(
        RemoteBrowserRuntime,
        broker=broker,
    )

    remote_browser: providers.Factory[CircuitBreakerRuntime] = providers.Factory(
        lambda raw_runtime: CircuitBreakerRuntime(raw_runtime),
        raw_runtime=_raw_remote_browser,
    )

    web_cog = providers.Factory(
        Web,
        bot=providers.Dependency(),
        browser=remote_browser,
    )

    # BrowserHealthMonitor cog factory
    from bot.plugins.monitor.browser_health import BrowserHealthMonitor

    browser_health_monitor_cog = providers.Factory(
        BrowserHealthMonitor,
        bot=providers.Dependency(),
        redis_client=redis_client,
    )

    # Orchestrator cog factory
    from bot.plugins.commands.orchestrator import Orchestrator

    orchestrator_cog = providers.Factory(
        Orchestrator,
        bot=providers.Dependency(),
        broker=broker,
        redis_client=redis_client,
        scaling_service=scaling_service,
        safe_send_func=safe_send,
    )

    # NOTE: BrowserRuntime (local) has been removed. All browser commands are routed via distributed workers.


# Example of how to initialize and use the container (typically in main.py or discord_runner.py):
#
# if __name__ == '__main__':
#     container = Container()
#     container.config.load_dotenv() # If using .env files and pydantic-settings
#
#     # Wire up the container to cogs or other parts of the application
#     # For example, in discord_runner.py, you might do:
#     # container.wire(modules=[__name__, ".cogs.browser_cog_module_if_it_exists"])
#
#     engine = container.browser_engine()
#     runner = container.web_runner()
#     ps = container.proxy_service()
#
#     # Now engine, runner, ps are ready to be used or passed to cogs.
