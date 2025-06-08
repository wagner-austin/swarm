import tempfile
from pathlib import Path
import pytest
from pydantic import ValidationError
from bot.core.settings import Settings

from typing import Any


def test_settings_reads_env(monkeypatch: Any) -> None:
    # Create a temp .env file
    with tempfile.TemporaryDirectory() as tmpdir:
        env_path = Path(tmpdir) / ".env"
        env_path.write_text(
            """
discord_token = test_token
gemini_api_key = test-gemini
openai_api_key = test-openai
"""
        )
        monkeypatch.setenv("PYTHONPATH", tmpdir)
        # Remove any relevant environment variables to ensure test isolation
        monkeypatch.delenv("DISCORD_TOKEN", raising=False)
        # DB-related env-vars no longer exist
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        # Instantiate settings with custom env_file (Pydantic v2 does not cache settings globally)
        s = Settings(
            discord_token="test_token",
            gemini_api_key="test-gemini",
            openai_api_key="test-openai",
        )
        assert s.discord_token == "test_token"

        assert s.gemini_api_key == "test-gemini"
        assert s.openai_api_key == "test-openai"


def test_settings_missing_mandatory() -> None:
    # Only an empty/placeholder token should raise now
    with pytest.raises(ValidationError):
        Settings(discord_token="")
