#!/usr/bin/env python
"""
tests/core/test_config.py - Tests for core/config.py.
Verifies environment variables for BOT_NUMBER, SIGNAL_CLI_COMMAND, backup intervals,
retention counts, and also checks behavior when .env is missing or values are invalid.
"""

import os
import importlib
import pytest
import logging
from unittest.mock import patch
import core.config as config

@pytest.mark.usefixtures("clear_database_tables")  # If needed in your environment
class TestCoreConfig:
    """
    TestCoreConfig - Grouped tests for verifying environment variable fallback, overrides,
    invalid numeric values, and missing .env file scenarios.
    """

    @patch.dict(os.environ, {}, clear=True)
    @patch("dotenv.load_dotenv", lambda *args, **kwargs: None)
    def test_bot_number_default(self):
        """
        Test that BOT_NUMBER defaults to 'YOUR_SIGNAL_NUMBER' if not in environment or .env.
        """
        importlib.reload(config)
        assert isinstance(config.BOT_NUMBER, str)
        assert config.BOT_NUMBER == "YOUR_SIGNAL_NUMBER"

    @patch.dict(os.environ, {}, clear=True)
    @patch("dotenv.load_dotenv", lambda *args, **kwargs: None)
    def test_signal_cli_command_default(self):
        """
        Test that SIGNAL_CLI_COMMAND defaults to 'signal-cli.bat' if not in environment or .env.
        """
        importlib.reload(config)
        assert isinstance(config.SIGNAL_CLI_COMMAND, str)
        assert config.SIGNAL_CLI_COMMAND == "signal-cli.bat"

    @patch("dotenv.load_dotenv", lambda *args, **kwargs: None)
    def test_bot_number_override(self):
        """
        Test that BOT_NUMBER is set to the environment override if present.
        """
        original_value = os.environ.get("BOT_NUMBER", None)
        os.environ["BOT_NUMBER"] = "+19876543210"
        importlib.reload(config)
        assert config.BOT_NUMBER == "+19876543210"
        # Cleanup
        if original_value is None:
            del os.environ["BOT_NUMBER"]
        else:
            os.environ["BOT_NUMBER"] = original_value
        importlib.reload(config)

    @patch("dotenv.load_dotenv", lambda *args, **kwargs: None)
    def test_signal_cli_command_override(self):
        """
        Test that SIGNAL_CLI_COMMAND is set to the environment override if present.
        """
        original_value = os.environ.get("SIGNAL_CLI_COMMAND", None)
        os.environ["SIGNAL_CLI_COMMAND"] = "mysignalcli"
        importlib.reload(config)
        assert config.SIGNAL_CLI_COMMAND == "mysignalcli"
        # Cleanup
        if original_value is None:
            del os.environ["SIGNAL_CLI_COMMAND"]
        else:
            os.environ["SIGNAL_CLI_COMMAND"] = original_value
        importlib.reload(config)

    def test_polling_interval_default(self):
        # Check that POLLING_INTERVAL is an int and is at least 1.
        assert isinstance(config.POLLING_INTERVAL, int)
        assert config.POLLING_INTERVAL >= 1

    def test_backup_interval_and_retention(self):
        # Verify that backup interval and retention count are valid integers.
        assert isinstance(config.BACKUP_INTERVAL, int)
        assert config.BACKUP_INTERVAL > 0
        assert isinstance(config.BACKUP_RETENTION_COUNT, int)
        assert config.BACKUP_RETENTION_COUNT > 0

    @patch.dict(os.environ, {"BACKUP_INTERVAL": "notanumber"}, clear=True)
    def test_backup_interval_invalid_value(self, caplog):
        """
        Test that an invalid BACKUP_INTERVAL logs a warning and uses default (3600).
        """
        caplog.set_level(logging.WARNING)
        importlib.reload(config)
        assert any("Invalid integer value for BACKUP_INTERVAL" in rec.message for rec in caplog.records), \
            "Should log a warning for invalid BACKUP_INTERVAL"
        assert config.BACKUP_INTERVAL == 3600

    @patch.dict(os.environ, {"BACKUP_RETENTION_COUNT": "abc"}, clear=True)
    def test_backup_retention_count_invalid_value(self, caplog):
        """
        Test that an invalid BACKUP_RETENTION_COUNT logs a warning and uses default (5).
        """
        caplog.set_level(logging.WARNING)
        importlib.reload(config)
        assert any("Invalid integer value for BACKUP_RETENTION_COUNT" in rec.message for rec in caplog.records), \
            "Should log a warning for invalid BACKUP_RETENTION_COUNT"
        assert config.BACKUP_RETENTION_COUNT == 5

    # ADDED patch.dict BELOW for clearing environment so BOT_NUMBER is NOT set at OS level
    @patch.dict(os.environ, {}, clear=True)
    @patch("os.path.exists", return_value=False)
    @patch("dotenv.load_dotenv")
    def test_missing_env_file(self, mock_load_dotenv, mock_path_exists, caplog):
        """
        Test that if .env file is missing, an info log is written and environment is still loaded from OS or defaults,
        specifically we expect BOT_NUMBER to remain 'YOUR_SIGNAL_NUMBER' if the OS-level variable is not set.
        """
        caplog.set_level(logging.INFO)
        importlib.reload(config)
        # load_dotenv should NOT be called, because we patched exists() to False.
        mock_load_dotenv.assert_not_called()
        assert any("No .env found" in rec.message for rec in caplog.records), \
            "Should log an info message about missing .env file"
        # Confirm defaults remain consistent
        assert config.BOT_NUMBER == "YOUR_SIGNAL_NUMBER"
        assert config.BACKUP_INTERVAL == 3600
        assert config.BACKUP_RETENTION_COUNT == 10

# End of tests/core/test_config.py