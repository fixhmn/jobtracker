import sqlite3

import pytest

from app.database import Database
from scripts.backup import backup


def test_backup_and_restore_include_wal(tmp_path):
    original = tmp_path / "original.db"
    copy = tmp_path / "copy.db"
    Database(original).initialize()
    with sqlite3.connect(original) as connection:
        connection.execute("CREATE TABLE backup_test (value TEXT)")
        connection.execute("INSERT INTO backup_test VALUES ('keep this')")
        connection.commit()
        backup(original, copy)
        with sqlite3.connect(copy) as restored:
            assert restored.execute("SELECT value FROM backup_test").fetchone()[0] == "keep this"
        with pytest.raises(ValueError, match="already exists"):
            backup(original, copy)


def test_missing_backup_source(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        backup(tmp_path / "missing.db", tmp_path / "copy.db")
