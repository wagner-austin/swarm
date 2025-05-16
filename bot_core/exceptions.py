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


class BotError(DomainError):
    """Generic, non-domain-specific error raised by core helpers."""

    pass
