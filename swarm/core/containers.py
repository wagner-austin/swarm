from pathlib import Path
from typing import TYPE_CHECKING, Any

import redis.asyncio as redis_asyncio
from dependency_injector import containers, providers

from swarm.ai import providers as _ai_providers
from swarm.core import metrics as default_metrics
from swarm.core.settings import Settings
from swarm.distributed.backends import DockerApiBackend, FlyIOBackend, KubernetesBackend
from swarm.distributed.celery_browser import CeleryBrowserRuntime
from swarm.distributed.core.config import DistributedConfig
from swarm.distributed.services.scaling_service import ScalingService
from swarm.frontends.discord.discord_interactions import safe_send
from swarm.history.backends import HistoryBackend
from swarm.history.factory import choose as history_backend_factory
from swarm.infra.redis_factory import create_redis_client
from swarm.infra.tankpit import engine_factory as tankpit_engine_factory
from swarm.plugins.commands.status import Status
from swarm.types import RedisBytes

# TankPit engine factory (netproxy and ws_addon removed)
# DI cogs that must be referenced in providers.Factory at class-scope


def _create_redis_client(settings: Settings | None = None) -> RedisBytes:
    """Create Redis client synchronously for DI container."""
    if settings is None:
        settings = Settings()
    if settings.redis.url is None:
        raise ValueError("Redis URL must be configured")
    return redis_asyncio.from_url(settings.redis.url)


class Container(containers.DeclarativeContainer):
    """Dependency Injection Container for the swarm.

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

    # Mapping of LLM provider singletons discovered in swarm.ai.providers
    # Resolve the registry lazily so newly registered providers are seen.
    llm_providers = providers.Callable(lambda: _ai_providers.all())

    # Metrics helper (global module, but now injectable)
    metrics_helper = providers.Object(default_metrics)

    # MetricsTracker cog factory with DI
    from swarm.plugins.commands.metrics_tracker import MetricsTracker

    metrics_tracker_cog = providers.Factory(
        MetricsTracker,
        metrics=metrics_helper,
    )

    # LoggingAdmin cog factory
    from swarm.plugins.commands.logging_admin import LoggingAdmin

    logging_admin_cog = providers.Factory(LoggingAdmin)

    # PersonaAdmin cog factory
    from swarm.plugins.commands.persona_admin import PersonaAdmin

    persona_admin_cog = providers.Factory(
        PersonaAdmin,
        safe_send_func=safe_send,
    )

    # About cog factory
    from swarm.plugins.commands.about import About

    about_cog = providers.Factory(About)

    # AlertPump cog factory
    from swarm.plugins.commands.alert_pump import AlertPump

    alert_pump_cog = providers.Factory(
        AlertPump,
    )

    # Chat cog factory
    from swarm.plugins.commands.chat import Chat

    chat_cog = providers.Factory(Chat, history_backend=history_backend)

    # Shutdown cog factory (DI: inject lifecycle)
    from swarm.plugins.commands.shutdown import Shutdown

    shutdown_cog = providers.Factory(
        Shutdown,
        metrics_mod=metrics_helper,
    )

    # Status cog factory (DI)
    status_cog = providers.Factory(
        Status,
        metrics_mod=metrics_helper,
        safe_send_func=safe_send,
    )

    # Web cog factory (DI)
    from swarm.plugins.commands.web import Web

    # Shared infrastructure providers ---------------------------------
    redis_client = providers.Singleton(_create_redis_client, settings=config)

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

    remote_browser: providers.Factory[CeleryBrowserRuntime] = providers.Factory(
        CeleryBrowserRuntime,
    )

    web_cog = providers.Factory(
        Web,
        browser=remote_browser,
    )

    # BrowserHealthMonitor cog factory
    from swarm.plugins.monitor.browser_health import BrowserHealthMonitor

    browser_health_monitor_cog = providers.Factory(
        BrowserHealthMonitor,
        redis_client=redis_client,
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
