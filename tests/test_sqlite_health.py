"""Tests for SQLite health checks (no automatic restore)."""
import shutil
import sqlite3
from pathlib import Path

import pytest

from config.sqlite_health import (
    check_sqlite_database,
    classify_sqlite_problem,
    find_best_sqlite_backup,
    remove_sqlite_sidecars,
    restore_sqlite_from_backup,
    sqlite_data_score,
    sqlite_db_info,
    sqlite_has_core_schema,
    sqlite_target_count,
)


def _make_minimal_db(path: Path, targets: int = 2) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE targets (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
    )
    for i in range(targets):
        conn.execute("INSERT INTO targets (name) VALUES (?)", (f"T{i}",))
    conn.commit()
    conn.close()


def test_sqlite_target_count_valid(tmp_path):
    db = tmp_path / "test.db"
    _make_minimal_db(db, targets=3)
    assert sqlite_target_count(db) == 3
    assert sqlite_has_core_schema(db) is True


def test_sqlite_target_count_empty_file(tmp_path):
    db = tmp_path / "empty.db"
    db.write_bytes(b"")
    assert sqlite_target_count(db) == -1
    assert sqlite_has_core_schema(db) is False


def test_sqlite_target_count_no_targets_table(tmp_path):
    db = tmp_path / "shell.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE foo (id INTEGER)")
    conn.commit()
    conn.close()
    assert sqlite_target_count(db) == -1


def test_find_best_backup_picks_richest_data(tmp_path):
    sparse = tmp_path / "armillarylab.db.backup_a"
    many_targets = tmp_path / "armillarylab.db.backup_b"
    rich = tmp_path / "armillarylab.db.backup_c"
    _make_minimal_db(sparse, targets=1)
    _make_minimal_db(many_targets, targets=5)
    conn = sqlite3.connect(rich)
    conn.execute("CREATE TABLE targets (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    conn.execute("CREATE TABLE imaging_sessions (id INTEGER PRIMARY KEY, target_id INTEGER)")
    conn.execute("CREATE TABLE calibration_captures (id INTEGER PRIMARY KEY, target_id INTEGER)")
    conn.execute("INSERT INTO targets (name) VALUES ('T')")
    for _ in range(10):
        conn.execute("INSERT INTO imaging_sessions (target_id) VALUES (1)")
    conn.execute("INSERT INTO calibration_captures (target_id) VALUES (1)")
    conn.commit()
    conn.close()
    assert find_best_sqlite_backup(tmp_path).name == "armillarylab.db.backup_c"


def test_refuse_restore_when_current_is_richer(tmp_path):
    db = tmp_path / "armillarylab.db"
    backup = tmp_path / "armillarylab.db.backup_x"
    _make_minimal_db(backup, targets=2)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE targets (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    conn.execute("CREATE TABLE imaging_sessions (id INTEGER PRIMARY KEY, target_id INTEGER)")
    conn.execute("INSERT INTO targets (name) VALUES ('T1')")
    conn.execute("INSERT INTO targets (name) VALUES ('T2')")
    for _ in range(5):
        conn.execute("INSERT INTO imaging_sessions (target_id) VALUES (1)")
    conn.commit()
    conn.close()

    ok, msg = restore_sqlite_from_backup(db, tmp_path)
    assert ok is False
    assert "Refusing to restore" in msg
    assert sqlite_data_score(db)["imaging_sessions"] == 5


def test_restore_from_backup(tmp_path):
    db = tmp_path / "armillarylab.db"
    backup = tmp_path / "armillarylab.db.backup_x"
    _make_minimal_db(backup, targets=4)
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    for (name,) in cur.fetchall():
        cur.execute(f'DROP TABLE IF EXISTS "{name}"')
    conn.commit()
    conn.close()

    ok, msg = restore_sqlite_from_backup(db, tmp_path)
    assert ok is True
    assert sqlite_target_count(db) == 4
    assert "Restored" in msg


def test_classify_empty_shell(tmp_path):
    db = tmp_path / "armillarylab.db"
    backup = tmp_path / "armillarylab.db.backup_x"
    _make_minimal_db(backup, targets=4)
    shutil.copy2(backup, db)
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    for (name,) in cur.fetchall():
        cur.execute(f'DROP TABLE IF EXISTS "{name}"')
    conn.commit()
    conn.close()
    # Match armillarylab.db post-wipe footprint (size unchanged, tables gone)
    with open(db, "ab") as fh:
        fh.truncate(114688)
    assert classify_sqlite_problem(db) == "empty_shell"


def test_check_never_restores(tmp_path):
    db = tmp_path / "armillarylab.db"
    backup = tmp_path / "armillarylab.db.backup_y"
    _make_minimal_db(backup, targets=2)
    conn = sqlite3.connect(db)
    conn.execute("VACUUM")
    conn.close()

    ok, msg, _info = check_sqlite_database(db)
    assert ok is False
    assert sqlite_target_count(db) < 0
    assert sqlite_target_count(backup) == 2


def test_remove_sqlite_sidecars(tmp_path):
    db = tmp_path / "armillarylab.db"
    db.write_text("x")
    for suffix in ("-wal", "-shm"):
        Path(str(db) + suffix).write_text("sidecar")
    removed = remove_sqlite_sidecars(db)
    assert len(removed) == 2
    assert sqlite_db_info(db) is not None
