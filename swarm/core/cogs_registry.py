from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Iterable

from swarm.core.settings import Settings

if TYPE_CHECKING:  # pragma: no cover
    from swarm.core.containers import Container


@dataclass(frozen=True)
class CogSpec:
    provider_attr: str
    display_name: str
    # Optional plugin module basename used to skip standard extension loading
    plugin_key: str | None = None
    # Feature gate for conditional cogs
    is_enabled: Callable[[Settings], bool] = lambda _s: True
    # Whether lifecycle must await Redis readiness prior to adding this cog
    requires_redis_ready: bool = False
    # Whether this cog factory expects the SwarmLifecycle to be passed
    needs_lifecycle: bool = False


# DI-managed cogs loaded unconditionally (no external feature gate)
REQUIRED_DI_COGS: tuple[CogSpec, ...] = (
    CogSpec("metrics_tracker_cog", "MetricsTracker", plugin_key="metrics_tracker"),
    CogSpec("logging_admin_cog", "LoggingAdmin", plugin_key="logging_admin"),
    CogSpec("persona_admin_cog", "PersonaAdmin", plugin_key="persona_admin"),
    CogSpec("about_cog", "About", plugin_key="about"),
    CogSpec("alert_pump_cog", "AlertPump", plugin_key="alert_pump", needs_lifecycle=True),
    CogSpec("status_cog", "Status", plugin_key="status"),
    CogSpec("chat_cog", "Chat", plugin_key="chat"),
    CogSpec("web_cog", "Web", plugin_key=None),
    CogSpec("shutdown_cog", "Shutdown", plugin_key="shutdown", needs_lifecycle=True),
)


# DI-managed cogs loaded conditionally
OPTIONAL_DI_COGS: tuple[CogSpec, ...] = (
    CogSpec(
        "browser_health_monitor_cog",
        "BrowserHealthMonitor",
        plugin_key=None,
        is_enabled=lambda s: s.redis.enabled,
        requires_redis_ready=True,
    ),
)


def iter_enabled_di_cog_specs(settings: Settings) -> Iterable[CogSpec]:
    for spec in REQUIRED_DI_COGS:
        yield spec
    for spec in OPTIONAL_DI_COGS:
        if spec.is_enabled(settings):
            yield spec


def required_cog_names(settings: Settings) -> set[str]:
    """Return the set of DI-managed cog display names expected for given settings."""
    return {spec.display_name for spec in iter_enabled_di_cog_specs(settings)}


def di_skip_plugin_keys(settings: Settings) -> set[str]:
    """Return plugin basenames for DI cogs to skip during extension discovery.

    This avoids double-loading standard extensions corresponding to DI-managed cogs.
    """
    out: set[str] = set()
    for spec in iter_enabled_di_cog_specs(settings):
        if spec.plugin_key:
            out.add(spec.plugin_key)
    return out


# Allow-list for standard extensions to load via discovery
STANDARD_EXTENSIONS: set[str] = {"browser", "chat", "help"}


__all__ = [
    "CogSpec",
    "REQUIRED_DI_COGS",
    "OPTIONAL_DI_COGS",
    "iter_enabled_di_cog_specs",
    "required_cog_names",
    "di_skip_plugin_keys",
    "STANDARD_EXTENSIONS",
]


def validate_registry(container: Container) -> None:
    """Validate that registry entries are consistent with the DI container.

    - Every provider_attr must exist on the container.
    - plugin_key values (when present) must be unique across all DI cogs.
    """
    all_specs: list[CogSpec] = list(REQUIRED_DI_COGS) + list(OPTIONAL_DI_COGS)

    seen_plugins: set[str] = set()
    for spec in all_specs:
        if not hasattr(container, spec.provider_attr):
            raise ValueError(
                f"Missing DI provider on container: {spec.provider_attr} for cog {spec.display_name}"
            )
        if spec.plugin_key:
            if spec.plugin_key in seen_plugins:
                raise ValueError(f"Duplicate plugin_key in cogs registry: {spec.plugin_key}")
            seen_plugins.add(spec.plugin_key)
