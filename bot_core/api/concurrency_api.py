#!/usr/bin/env python
"""
core/api/concurrency_api.py
---------------------------
Provides stable, high-level concurrency functions for plugins.
Re-exports locks and transaction handling from the internal concurrency and transaction modules.
"""

from bot_core.concurrency import per_phone_lock
from bot_core.transaction import atomic_transaction

def per_phone_lock_api(phone: str):
    """
    per_phone_lock_api(phone: str)
    --------------------------------
    Acquire an exclusive lock for the specified phone number.
    Use as a context manager to ensure that any database or domain operations
    for this phone are done atomically.

    Usage Example:
        from bot_core.api.concurrency_api import per_phone_lock_api

        with per_phone_lock_api("+15551234567"):
            # perform phone-specific operations
            pass
    """
    return per_phone_lock(phone)

def atomic_transaction_api(exclusive: bool = False):
    """
    atomic_transaction_api(exclusive: bool = False)
    ------------------------------------------------
    Provide an atomic database transaction context.
    If exclusive=True, acquires an exclusive lock on the database.

    Usage Example:
        from bot_core.api.concurrency_api import atomic_transaction_api

        with atomic_transaction_api(exclusive=True) as conn:
            # perform writes under an exclusive transaction
            pass
    """
    return atomic_transaction(exclusive=exclusive)

# End of core/api/concurrency_api.py