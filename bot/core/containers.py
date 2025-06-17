from dependency_injector import containers, providers
from pathlib import Path

from bot.core.settings import Settings
from bot.history.in_memory import MemoryBackend
from bot.history.redis_backend import RedisBackend

from bot.netproxy.service import ProxyService
from bot.browser.runtime import BrowserRuntime
from bot.infra.tankpit.proxy.ws_tankpit import TankPitWSAddon
from bot.ai import providers as _ai_providers


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
    history_backend = providers.Singleton(
        lambda cfg: (
            RedisBackend(cfg.redis_url, cfg.conversation_max_turns)
            if cfg.redis_enabled and cfg.redis_url
            else MemoryBackend(cfg.conversation_max_turns)
        ),
        config,
    )

    # Mapping of LLM provider singletons discovered in bot.ai.providers
    # Resolve the registry lazily so newly registered providers are seen.
    llm_providers = providers.Callable(lambda: _ai_providers.all())

    # Proxy service
    # The default_port and cert_dir for ProxyService can be sourced from config.
    # The 'addon' parameter defaults to None as per ProxyService.__init__ signature.
    # Proxy service
    proxy_service: providers.Singleton["ProxyService"] = providers.Singleton(
        ProxyService,
        port=providers.Callable(
            lambda cfg: cfg.proxy_port or 9000,  # Use OR for default
            config,
        ),
        certdir=providers.Callable(
            lambda cfg: Path(cfg.proxy_cert_dir),  # Path conversion is correct
            config,
        ),
        # Explicit list provider makes the "list-ness" clear and allows DI container
        # to resolve each element individually if they become providers themselves.
        addons=providers.List(
            providers.Object(TankPitWSAddon),
        ),
    )

    # Browser runtime – one process-wide instance wired through DI
    browser_runtime: providers.Singleton["BrowserRuntime"] = providers.Singleton(
        BrowserRuntime
    )


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
