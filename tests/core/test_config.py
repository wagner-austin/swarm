#!/usr/bin/env python
"""
tests/core/test_config.py - Tests for core/config.py.
Verifies environment variables for BOT_NUMBER, SIGNAL_CLI_COMMAND, backup intervals,
retention counts, and also checks behavior when .env is missing or values are invalid.
"""

import os
import os
import importlib
import logging
from unittest.mock import patch
import pytest
import bot_core.settings as config

@pytest.mark.usefixtures("reset_user_state")

class TestCoreConfig:
    """
    Discord-centric config tests: only check for variables present in core/config.py.
    """

    @pytest.mark.asyncio
    async def test_db_name_default(self):
        assert isinstance(config.settings.db_name, str)
        if "memdb" in config.settings.db_name:
            pytest.skip("Skipping default db_name test because we are using an in-memory DB.")
        assert config.settings.db_name.endswith(".db")

    @pytest.mark.asyncio
    async def test_role_name_map(self):
        assert isinstance(config.settings.role_name_map, dict)
        # By default, should be empty dict
        assert config.settings.role_name_map == {}

    @pytest.mark.asyncio
    async def test_backup_interval(self):
        assert isinstance(config.settings.backup_interval, int)
        assert config.settings.backup_interval > 0

    @pytest.mark.asyncio
    async def test_backup_retention(self):
        assert isinstance(config.settings.backup_retention, int)
        assert config.settings.backup_retention > 0

    @pytest.mark.asyncio
    async def test_openai_api_key_present(self):
        # Should be present (can be None or a string)
        assert hasattr(config.settings, "openai_api_key")

    @patch.dict(os.environ, {"DISCORD_TOKEN": "dummy-token"}, clear=True)
    @pytest.mark.asyncio
    async def test_missing_env_file(self):
        # Should fall back to defaults if .env is missing, but DISCORD_TOKEN is required
        from bot_core.settings import Settings
        s = Settings(_env_file=None)
        assert s.db_name.endswith(".db")
        assert s.role_name_map == {}
        assert s.backup_interval == 3600
        assert s.backup_retention == 10

# End of tests/core/test_config.py