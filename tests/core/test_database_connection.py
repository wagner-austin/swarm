"""
tests/core/test_database_connection.py - Tests for the database connection module.
Verifies that get_connection returns a valid SQLite connection, and handles errors properly.
"""

import sqlite3
import pytest
from unittest.mock import patch
import logging
# Obsolete: sync connection layer removed. Tests disabled.

# def test_get_connection():
#     pass  # Obsolete: sync connection layer removed.

# @pytest.mark.parametrize("error_class", [sqlite3.OperationalError, OSError])
# def test_get_connection_raises_and_logs(error_class, caplog):
#     pass  # Obsolete: sync connection layer removed.

# End of tests/core/test_database_connection.py