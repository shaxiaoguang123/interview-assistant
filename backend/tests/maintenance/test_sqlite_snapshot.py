import sqlite3
from pathlib import Path

from app.maintenance.__main__ import _snapshot_sqlite


def test_migration_snapshot_includes_uncheckpointed_wal_data(tmp_path):
    database = tmp_path / "live.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute("INSERT INTO sample(value) VALUES ('committed in WAL')")
    connection.commit()
    wal = Path(f"{database}-wal")
    assert wal.is_file()

    snapshot = _snapshot_sqlite(database, tmp_path / "app-data")

    with sqlite3.connect(snapshot) as restored:
        assert restored.execute("SELECT value FROM sample").fetchone() == ("committed in WAL",)
        assert restored.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert snapshot.stat().st_mode & 0o777 == 0o600
    connection.close()
