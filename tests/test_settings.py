import os
import tempfile
import shutil
from pathlib import Path
import pytest
from pydantic import ValidationError
from bot_core.settings import Settings

def test_settings_reads_env(monkeypatch):
    # Create a temp .env file
    with tempfile.TemporaryDirectory() as tmpdir:
        env_path = Path(tmpdir) / ".env"
        env_path.write_text("""
discord_token = test_token
db_name = test.db
backup_interval = 123
backup_retention = 3
gemini_api_key = test-gemini
openai_api_key = test-openai
""")
        monkeypatch.setenv("PYTHONPATH", tmpdir)
        # Remove any relevant environment variables to ensure test isolation
        monkeypatch.delenv("DISCORD_TOKEN", raising=False)
        monkeypatch.delenv("DB_NAME", raising=False)
        monkeypatch.delenv("BACKUP_INTERVAL", raising=False)
        monkeypatch.delenv("BACKUP_RETENTION", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        # Instantiate settings with custom env_file (Pydantic v2 does not cache settings globally)
        s = Settings(_env_file=str(env_path))
        assert s.discord_token == "test_token"
        assert s.db_name == "test.db"
        assert s.backup_interval == 123
        assert s.backup_retention == 3
        assert s.gemini_api_key == "test-gemini"
        assert s.openai_api_key == "test-openai"

def test_settings_missing_mandatory():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, discord_token=None)
