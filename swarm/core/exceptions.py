#!/usr/bin/env python
"""
core/exceptions.py - Central module for custom exception classes.
"""


class DomainError(Exception):
    """
    Base class for domain-specific exceptions with a unified error message format.
    """

    def __init__(self, message: str):
        super().__init__(f"[DomainError] {message}")


class ModelOverloaded(DomainError):
    """Raised when the selected LLM model is temporarily overloaded/unavailable."""

    pass


class BotError(DomainError):
    """Generic, non-domain-specific error raised by core helpers."""

    pass


class WorkerUnavailableError(BotError):
    """Raised when distributed workers are temporarily unavailable."""

    def __init__(self, component: str = "workers"):
        super().__init__(f"{component} temporarily unavailable")
        self.component = component


class OperationTimeoutError(BotError):
    """Raised when operations exceed expected duration."""

    def __init__(self, operation: str = "operation"):
        super().__init__(f"{operation} timed out")
        self.operation = operation


class RedisBackendError(BotError):
    """Base exception for Redis backend errors."""

    pass


class RedisConnectionError(RedisBackendError):
    """Raised when unable to connect to Redis."""

    def __init__(self, backend: str = "redis", reason: str = "connection failed"):
        super().__init__(f"{backend}: {reason}")
        self.backend = backend
        self.reason = reason


class RedisRateLimitError(RedisBackendError):
    """Raised when Redis rate limit is exceeded (Upstash specific)."""

    def __init__(self, limit: int, usage: int):
        super().__init__(f"Rate limit exceeded. Limit: {limit}, Usage: {usage}")
        self.limit = limit
        self.usage = usage
