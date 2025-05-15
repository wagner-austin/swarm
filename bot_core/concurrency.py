#!/usr/bin/env python
"""
concurrency.py - Provides application-level concurrency utilities.
Defines a context manager for per-phone locking to serialize operations on the same record.
This ensures that concurrent volunteer sign-ups for the same phone are handled sequentially.
"""
import threading
from contextlib import contextmanager

# Global dictionary for per-phone locks.
_per_phone_locks = {}
_global_lock = threading.Lock()

@contextmanager
def per_phone_lock(phone: str):
    """
    per_phone_lock - Context manager that acquires a lock specific to a phone number.
    
    Args:
        phone (str): The phone number used as a key for locking.
    
    Yields:
        None: The caller executes while holding the lock.
    """
    with _global_lock:
        if phone not in _per_phone_locks:
            _per_phone_locks[phone] = threading.Lock()
        lock = _per_phone_locks[phone]
    with lock:
        yield

# End of core/concurrency.py