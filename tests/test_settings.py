import tempfile
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from bot.core.settings import Settings


def test_settings_reads_env(monkeypatch: Any) -> None:
    # Create a temp .env file in a temporary directory
    with tempfile.TemporaryDirectory() as tmpdir:
        env_path = Path(tmpdir) / ".env"
        with open(env_path, "w") as f:
            f.write(
                """
                discord_token = "test_token_from_file"
                gemini_api_key = "test-gemini-from-file"
                openai_api_key = "test-openai-from-file"
                """
            )

        # Remove any relevant environment variables to ensure test isolation
        monkeypatch.delenv("DISCORD_TOKEN", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        # Instantiate settings, telling it explicitly to use our .env file
        s = Settings(_env_file=env_path)

        assert s.discord_token == "test_token_from_file"
        assert s.gemini_api_key == "test-gemini-from-file"
        assert s.openai_api_key == "test-openai-from-file"


def test_settings_missing_mandatory(monkeypatch: Any) -> None:
    # Ensure no env vars are set that could satisfy the model
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)

    # An empty token should raise a validation error
    with pytest.raises(ValidationError):
        Settings(discord_token="")
