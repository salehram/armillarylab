"""Tests for destructive database operation guards."""
from pathlib import Path

from config.destructive_db_guard import destructive_db_allowed, has_live_sqlite_data


def _seed_db(path: Path) -> None:
    import sqlite3

    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE targets (id INTEGER PRIMARY KEY, name TEXT)")
    cur.execute("INSERT INTO targets (name) VALUES ('M31')")
    conn.commit()
    conn.close()


def test_allows_destructive_on_empty_db(tmp_path):
    db = tmp_path / "armillarylab.db"
    db.write_bytes(b"")
    allowed, msg = destructive_db_allowed(db, "init-db --force")
    assert allowed is True
    assert msg == ""


def test_refuses_destructive_when_data_exists(tmp_path, monkeypatch):
    db = tmp_path / "armillarylab.db"
    _seed_db(db)
    assert has_live_sqlite_data(db) is True

    monkeypatch.delenv("ARMILLARYLAB_CONFIRM_DESTRUCTIVE", raising=False)
    allowed, msg = destructive_db_allowed(db, "init-db --force")
    assert allowed is False
    assert "Refusing" in msg


def test_allows_destructive_with_explicit_confirm(tmp_path, monkeypatch):
    db = tmp_path / "armillarylab.db"
    _seed_db(db)
    monkeypatch.setenv("ARMILLARYLAB_CONFIRM_DESTRUCTIVE", "1")
    allowed, msg = destructive_db_allowed(db, "init-db --force")
    assert allowed is True
