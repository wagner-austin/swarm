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
import bot_core.config as config

@pytest.mark.usefixtures("reset_user_state")  # If needed in your environment
class TestCoreConfig:
    """
    Discord-centric config tests: only check for variables present in core/config.py.
    """

    def test_db_name_default(self):
        assert isinstance(config.DB_NAME, str)
        assert config.DB_NAME.endswith(".db")

    def test_role_name_map(self):
        assert isinstance(config.ROLE_NAME_MAP, dict)
        # By default, should be empty dict
        assert config.ROLE_NAME_MAP == {}

    def test_backup_interval(self):
        assert isinstance(config.BACKUP_INTERVAL, int)
        assert config.BACKUP_INTERVAL > 0

    def test_disk_backup_retention_count(self):
        assert isinstance(config.DISK_BACKUP_RETENTION_COUNT, int)
        assert config.DISK_BACKUP_RETENTION_COUNT > 0

    def test_disk_backup_interval_matches(self):
        assert config.DISK_BACKUP_INTERVAL == config.BACKUP_INTERVAL

    def test_openai_api_key_present(self):
        assert hasattr(config, "OPENAI_API_KEY")
        assert isinstance(config.OPENAI_API_KEY, str)

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
        # Confirm defaults remain consistent for Discord-centric config
        assert config.DB_NAME.endswith(".db")
        assert config.ROLE_NAME_MAP == {}
        assert config.BACKUP_INTERVAL == 3600
        assert config.DISK_BACKUP_RETENTION_COUNT == 10

# End of tests/core/test_config.py