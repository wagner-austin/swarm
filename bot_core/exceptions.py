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

class VolunteerError(DomainError):
    """
    Raised when user input fails validation in volunteer-related flows.
    """
    pass