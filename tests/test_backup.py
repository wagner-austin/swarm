from pathlib import Path
import tempfile
from bot_core.settings import Settings
from db.backup import create_backup, list_backups


def test_create_backup_happy_path() -> None:
    # Create a temp directory for the test DB and backups
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test.db"
        # Write a dummy SQLite file
        with db_path.open("wb") as f:
            f.write(b"SQLite format 3\x00dummy data\n")
        # Create a Settings instance pointing to this DB
        cfg = Settings(db_name=str(db_path), discord_token="test_token")
        # Run the backup
        backup_path = create_backup(cfg)
        assert backup_path, "Backup path should not be empty"
        assert backup_path.exists(), f"Backup file should exist: {backup_path}"
        # It should appear in list_backups
        backups = list_backups(cfg)
        assert any(backup_path.name == b.name for b in backups), (
            "Backup should be listed by list_backups()"
        )
        # Optionally: check backup file content matches (not strictly required)
        with backup_path.open("rb") as f:
            data = f.read()
        assert b"SQLite format 3" in data, "Backup file should contain SQLite header"
