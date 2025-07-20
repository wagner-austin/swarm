"""
core/logger_setup.py - Provides a reusable logging configuration setup with robust handling.
This module centralizes logging configuration and exposes a setup_logging() function
that can be used in both production and testing environments.
"""

import collections
import contextvars
import copy
import logging
import logging.config
import os
import platform
import socket
import warnings
from typing import Any

from pythonjsonlogger import json as jsonlogger

# ----------  New section: contextual metadata  ----------
# Core service context
_ctx_service: contextvars.ContextVar[str] = contextvars.ContextVar("service", default="unknown")
_ctx_worker_id: contextvars.ContextVar[str] = contextvars.ContextVar("worker_id", default="unknown")
_ctx_job_id: contextvars.ContextVar[str] = contextvars.ContextVar("job_id", default="-")

# Deployment/infrastructure context (set once at startup)
_ctx_hostname: contextvars.ContextVar[str] = contextvars.ContextVar("hostname", default="unknown")
_ctx_container_id: contextvars.ContextVar[str] = contextvars.ContextVar("container_id", default="-")
_ctx_deployment_env: contextvars.ContextVar[str] = contextvars.ContextVar(
    "deployment_env", default="local"
)
_ctx_region: contextvars.ContextVar[str] = contextvars.ContextVar("region", default="unknown")


def bind_log_context(
    *, service: str | None = None, worker_id: str | None = None, job_id: str | None = None
) -> None:
    """Bind service, worker_id, and job_id to the logging context."""
    if service is not None:
        _ctx_service.set(service)
    if worker_id is not None:
        _ctx_worker_id.set(worker_id)
    if job_id is not None:
        _ctx_job_id.set(job_id)


def bind_deployment_context(
    *,
    hostname: str | None = None,
    container_id: str | None = None,
    deployment_env: str | None = None,
    region: str | None = None,
    context: dict[str, str] | None = None,
) -> None:
    """Bind deployment/infrastructure metadata to logging context.

    Should be called once at service startup with deployment information.
    If context is provided, uses its values; otherwise uses the keyword args or auto-detects.
    """
    if context is not None:
        _ctx_hostname.set(context.get("hostname", "unknown"))
        _ctx_container_id.set(context.get("container_id", "-"))
        _ctx_deployment_env.set(context.get("deployment_env", "local"))
        _ctx_region.set(context.get("region", "unknown"))
        return
    if hostname is not None:
        _ctx_hostname.set(hostname)
    if container_id is not None:
        _ctx_container_id.set(container_id)
    if deployment_env is not None:
        _ctx_deployment_env.set(deployment_env)
    if region is not None:
        _ctx_region.set(region)


def auto_detect_deployment_context() -> dict[str, str]:
    """Auto-detect deployment context from environment variables and system info.

    Returns a dict of detected values that can be passed to bind_deployment_context.
    """
    context = {}

    # Hostname detection
    try:
        context["hostname"] = socket.getfqdn() or platform.node()
    except Exception:
        context["hostname"] = "unknown"

    # Container ID detection (Docker)
    container_id = os.getenv("HOSTNAME")  # Docker sets this to container ID
    if not container_id:
        try:
            # Alternative: read from /proc/self/cgroup (Linux containers)
            with open("/proc/self/cgroup") as f:
                for line in f:
                    if "docker" in line or "containerd" in line:
                        container_id = line.split("/")[-1].strip()[:12]  # First 12 chars
                        break
        except Exception:
            pass
    context["container_id"] = container_id or "-"

    # Environment detection
    context["deployment_env"] = os.getenv("DEPLOYMENT_ENV", "local")

    # Region detection (cloud providers)
    region = (
        os.getenv("FLY_REGION")  # Fly.io
        or os.getenv("AWS_REGION")  # AWS
        or os.getenv("GOOGLE_CLOUD_REGION")  # GCP
        or os.getenv("AZURE_REGION")  # Azure
        or "unknown"
    )
    context["region"] = region

    return context


# ----------  New section: context filter  ----------
class _ContextFilter(logging.Filter):
    """Adds service/worker_id/job_id and deployment metadata fields to every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Core service context
        record.service = _ctx_service.get()
        record.worker_id = _ctx_worker_id.get()
        record.job_id = _ctx_job_id.get()
        # Deployment/infrastructure context
        record.hostname = _ctx_hostname.get()
        record.container_id = _ctx_container_id.get()
        record.deployment_env = _ctx_deployment_env.get()
        record.region = _ctx_region.get()
        return True


def merge_dicts(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """
    Recursively merge *overrides* into *base*.

    * For nested dicts, values are merged depth-first.
    * If the types at the same key differ, the override value wins and a
      `warnings.warn()` is emitted (same behaviour the old copies had).

    Returns the modified *base* for convenience so callers can write
    `cfg = merge_dicts(cfg, overrides)`.
    """
    for key, value in overrides.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            merge_dicts(base[key], value)
        else:
            if key in base and not isinstance(base[key], type(value)):
                warnings.warn(
                    f"Type mismatch for key '{key}': "
                    f"{type(base[key]).__name__} vs {type(value).__name__}. "
                    "Using override value."
                )
            base[key] = value
    return base


DEFAULT_LOGGING_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        # Human-friendly for dev runs (`LOG_FORMAT=pretty`)
        "rich": {"datefmt": "%Y-%m-%d %H:%M:%S"},
        # Machine-friendly for Alloy/Loki (`LOG_FORMAT=json`, default in prod)
        "json": {
            "()": "pythonjsonlogger.json.JsonFormatter",
            "fmt": "%(asctime)s %(levelname)s %(service)s %(worker_id)s %(job_id)s %(hostname)s %(container_id)s %(deployment_env)s %(region)s %(name)s %(message)s",
            "datefmt": "%Y-%m-%dT%H:%M:%S%z",
        },
        # Fallback plain text (kept for unit-tests & legacy)
        "default": {"format": "%(asctime)s [%(levelname)s] %(message)s"},
    },
    "filters": {
        "dedupe": {"()": "swarm.core.logger_setup._DuplicateFilter"},
        # Inject ctx-vars into every record
        "context": {"()": "swarm.core.logger_setup._ContextFilter"},
    },
    "handlers": {
        # always present – goes to stdout so Alloy can scrape
        "stdout": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["dedupe", "context"],
            "stream": "ext://sys.stdout",
        },
        # pretty console for local hacking – enabled when LOG_FORMAT=pretty
        "rich": {
            "class": "rich.logging.RichHandler",
            "formatter": "rich",
            "filters": ["dedupe", "context"],
            "markup": True,
            "show_path": False,
            "rich_tracebacks": True,
        },
    },
    "root": {"handlers": ["stdout"], "level": "INFO"},
}


# Sentinel to avoid multiple configuration attempts
# Suppress duplicate exception log entries in quick succession (same message & traceback)
class _DuplicateFilter(logging.Filter):
    """Filter that drops consecutive duplicate (msg, exc_text) records."""

    def __init__(self, window: int = 20) -> None:
        super().__init__()
        self._recent: collections.deque[tuple[str, str]] = collections.deque(maxlen=window)

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        key = (record.getMessage(), getattr(record, "exc_text", ""))
        if key in self._recent:
            return False
        self._recent.append(key)
        return True


_CONFIGURED: bool = False


def setup_logging(config_overrides: dict[str, Any] | None = None) -> None:
    """
    setup_logging - Configures logging using a centralized configuration.

    Args:
        config_overrides (dict, optional): A dictionary with logging configuration overrides.
            This can be used to modify the default logging setup for different environments.

    Returns:
        None
    """
    global _CONFIGURED
    if _CONFIGURED:
        return  # already configured – avoid duplicate handlers

    config = copy.deepcopy(DEFAULT_LOGGING_CONFIG)

    # Honour LOG_LEVEL env variable (e.g. DEBUG, INFO, WARNING)
    env_level = os.getenv("LOG_LEVEL")
    if env_level:
        config.setdefault("root", {})["level"] = env_level.upper()
    config["force"] = True
    if config_overrides:
        merge_dicts(config, config_overrides)

    # Override default handler set selected via LOG_FORMAT/LOG_TO_FILE flags.
    log_format = os.getenv("LOG_FORMAT", "json").lower()
    if log_format == "pretty":
        config["root"]["handlers"] = ["rich"]
    if os.getenv("LOG_TO_FILE"):
        # Dynamically create file handler when requested
        log_file = os.getenv("LOG_FILE_PATH", "logs/swarm.log")
        log_dir = os.path.dirname(log_file)
        
        # Create directory if needed
        add_file_handler = True
        if log_dir:
            try:
                os.makedirs(log_dir, exist_ok=True)
            except (OSError, PermissionError) as e:
                warnings.warn(f"Cannot create log directory {log_dir}: {e}. File logging disabled.")
                add_file_handler = False
        
        # Add file handler configuration dynamically
        if add_file_handler:
            config["handlers"]["file"] = {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": log_file,
                "maxBytes": 20_000_000,
                "backupCount": 3,
                "formatter": "json",
                "filters": ["dedupe", "context"],
            }
            config["root"]["handlers"].append("file")

    # Check for empty or missing handlers in overall config or in the root logger.
    if (
        not config.get("handlers")
        or not config["handlers"]
        or not config.get("root", {}).get("handlers")
    ):
        warnings.warn("Logging configuration missing handlers; using fallback console handler.")
        config["handlers"] = {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
            },
        }
        if "root" in config:
            config["root"]["handlers"] = ["console"]

    logging.config.dictConfig(config)
    _CONFIGURED = True


# End of core/logger_setup.py
