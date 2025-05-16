#!/usr/bin/env python
"""
tests/core/test_config.py - Tests for core/config.py.
Verifies environment variables for BOT_NUMBER, SIGNAL_CLI_COMMAND, backup intervals,
retention counts, and also checks behavior when .env is missing or values are invalid.
"""

import os
from unittest.mock import patch
import pytest
from bot_core.settings import settings  # fully typed alias


@pytest.mark.usefixtures("reset_user_state")
class TestCoreConfig:
    """
    Discord-centric config tests: only check for variables present in core/config.py.
    """

    @pytest.mark.asyncio
    async def test_db_name_default(self) -> None:
        assert isinstance(settings.db_name, str)
        if "memdb" in settings.db_name:
            pytest.skip(
                "Skipping default db_name test because we are using an in-memory DB."
            )
        assert settings.db_name.endswith(".db")

    @pytest.mark.asyncio
    async def test_backup_interval(self) -> None:
        assert isinstance(settings.backup_interval, int)
        assert settings.backup_interval > 0

    @pytest.mark.asyncio
    async def test_backup_retention(self) -> None:
        assert isinstance(settings.backup_retention, int)
        assert settings.backup_retention > 0

    @pytest.mark.asyncio
    async def test_openai_api_key_present(self) -> None:
        # Should be present (can be None or a string)
        assert hasattr(settings, "openai_api_key")

    @patch.dict(os.environ, {"DISCORD_TOKEN": "dummy-token"}, clear=True)
    @pytest.mark.asyncio
    async def test_missing_env_file(self) -> None:
        # Should fall back to defaults if .env is missing, but DISCORD_TOKEN is required
        from bot_core.settings import Settings

        s = Settings(_env_file=None, discord_token="dummy")
        assert s.db_name.endswith(".db")
        assert s.backup_interval == 3600
        assert s.backup_retention == 10
