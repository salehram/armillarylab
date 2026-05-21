"""SQLite database health checks for ArmillaryLab (no automatic restore)."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

# After DROP TABLE on a populated armillarylab.db the file keeps its size but
# has zero user tables — matches every corrupt_* snapshot we have inspected.
EMPTY_SHELL_SIZE_BYTES = 114688
EMPTY_SHELL_PAGE_COUNT = 28


def classify_sqlite_problem(db_path: Path) -> str:
    """
    Classify an unhealthy database file.

    Returns one of: ok, missing, empty_shell, no_schema, integrity_fail, unreadable
    """
    if not db_path.is_file():
        return "missing"
    if db_path.stat().st_size == 0:
        return "unreadable"
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        tables = cur.fetchone()[0]
        cur.execute("PRAGMA page_count")
        pages = cur.fetchone()[0]
        cur.execute("PRAGMA integrity_check")
        integrity = cur.fetchone()[0]
        conn.close()
    except sqlite3.Error:
        return "unreadable"

    if integrity != "ok":
        return "integrity_fail"
    if tables > 0 and sqlite_has_core_schema(db_path):
        return "ok"
    if tables == 0 and db_path.stat().st_size >= EMPTY_SHELL_SIZE_BYTES:
        return "empty_shell"
    return "no_schema"


def describe_sqlite_problem(db_path: Path) -> str:
    """Human-readable explanation for classify_sqlite_problem (not ok)."""
    kind = classify_sqlite_problem(db_path)
    if kind == "ok":
        return "Database schema looks healthy."

    if kind == "missing":
        return f"File not found: {db_path}"

    if kind == "empty_shell":
        return (
            "Empty SQLite shell: file size is unchanged (~114 KB) but all tables are gone. "
            "This matches DROP TABLE on a live database — caused by (1) the dev corruption "
            "test script wiping tables while Flask is running, or (2) OneDrive replacing the "
            "file with a stale/placeholder copy during sync while the app has it open. "
            "It is NOT random bit-rot; integrity check still passes."
        )

    if kind == "integrity_fail":
        info = sqlite_db_info(db_path) or {}
        return f"SQLite integrity check failed: {info.get('integrity', 'unknown')}."

    if kind == "unreadable":
        return "File exists but cannot be opened as SQLite."

    return "Core schema missing (no targets table)."


def sqlite_file_path_from_uri(connection_string: str) -> Path:
    return Path(connection_string.replace("sqlite:///", "")).resolve()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cur.fetchone() is not None


def sqlite_data_score(db_path: Path) -> dict:
    """Return row counts used to compare backups (manual restore only)."""
    score = {
        "targets": -1,
        "imaging_sessions": 0,
        "calibration_captures": 0,
        "valid": False,
        "richness": -1,
    }
    if not db_path.is_file() or db_path.stat().st_size == 0:
        return score
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        if cur.fetchone()[0] == 0:
            conn.close()
            return score
        if not _table_exists(conn, "targets"):
            conn.close()
            return score
        cur.execute("SELECT COUNT(*) FROM targets")
        score["targets"] = cur.fetchone()[0]
        for table in ("imaging_sessions", "calibration_captures"):
            if _table_exists(conn, table):
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                score[table] = cur.fetchone()[0]
        conn.close()
        score["valid"] = score["targets"] >= 0
        score["richness"] = (
            score["imaging_sessions"]
            + score["calibration_captures"] * 2
            + score["targets"]
        )
        return score
    except sqlite3.Error:
        return score


def sqlite_target_count(db_path: Path) -> int:
    """Return number of targets, or -1 if file/table is invalid."""
    return sqlite_data_score(db_path)["targets"]


def sqlite_has_core_schema(db_path: Path) -> bool:
    return sqlite_data_score(db_path)["valid"]


def sqlite_db_info(db_path: Path) -> dict | None:
    if not db_path.is_file():
        return None
    data = sqlite_data_score(db_path)
    if not data["valid"] and data["targets"] < 0:
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
            tables = cur.fetchone()[0]
            conn.close()
            return {
                "path": str(db_path),
                "size": db_path.stat().st_size,
                "tables": tables,
                "targets": -1,
                "valid": False,
            }
        except sqlite3.Error as exc:
            return {"path": str(db_path), "valid": False, "error": str(exc)}
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        tables = cur.fetchone()[0]
        cur.execute("PRAGMA integrity_check")
        integrity = cur.fetchone()[0]
        conn.close()
        return {
            "path": str(db_path),
            "size": db_path.stat().st_size,
            "tables": tables,
            "targets": data["targets"],
            "imaging_sessions": data["imaging_sessions"],
            "calibration_captures": data["calibration_captures"],
            "richness": data["richness"],
            "integrity": integrity,
            "valid": integrity == "ok" and data["valid"],
        }
    except sqlite3.Error as exc:
        return {"path": str(db_path), "valid": False, "error": str(exc)}


def remove_sqlite_sidecars(db_path: Path) -> list[str]:
    """Delete stale WAL/SHM files that break OneDrive-synced SQLite."""
    removed = []
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(db_path) + suffix)
        if sidecar.is_file():
            try:
                sidecar.unlink()
                removed.append(sidecar.name)
            except OSError:
                pass
    return removed


def find_best_sqlite_backup(project_dir: Path, min_richness: int = 0) -> Path | None:
    """Pick the backup with the most imaging/calibration data (manual restore only)."""
    best_path = None
    best_richness = min_richness - 1
    for path in project_dir.glob("armillarylab.db.backup_*"):
        data = sqlite_data_score(path)
        if not data["valid"]:
            continue
        if data["richness"] > best_richness:
            best_path = path
            best_richness = data["richness"]
    return best_path


def prepare_sqlite_file(db_path: Path) -> list[str]:
    """Remove stale sidecars once at startup. Does not modify table data."""
    return remove_sqlite_sidecars(db_path)


def check_sqlite_database(db_path: Path, *, clean_sidecars: bool = False) -> tuple[bool, str, dict | None]:
    """
    Validate SQLite file. Never replaces or restores the database.

    Sidecar cleanup runs only when clean_sidecars=True (worker startup), not per request.
    """
    removed = prepare_sqlite_file(db_path) if clean_sidecars else []
    info = sqlite_db_info(db_path)

    if info and info.get("valid"):
        msg = (
            f"Database OK ({info.get('targets', 0)} targets, "
            f"{info.get('imaging_sessions', 0)} sessions, "
            f"{info.get('calibration_captures', 0)} calibration logs)."
        )
        if removed:
            msg += f" Removed sidecars: {', '.join(removed)}."
        return True, msg, info

    if not db_path.is_file():
        return False, describe_sqlite_problem(db_path), info

    detail = describe_sqlite_problem(db_path)
    if classify_sqlite_problem(db_path) == "empty_shell":
        return False, detail + " Stop Flask, wait for OneDrive sync, then reload.", info

    return False, detail + " Run: python scripts/diagnose_db.py", info


def restore_sqlite_from_backup(
    db_path: Path,
    project_dir: Path,
    *,
    save_corrupt_as: str | None = "corrupt",
    allow_downgrade: bool = False,
) -> tuple[bool, str]:
    """
    Explicit manual restore: replace db_path with the best local backup copy.

    Only call from scripts/restore_db.py — never from Flask startup or requests.
    """
    backup = find_best_sqlite_backup(project_dir)
    if not backup:
        return False, "No valid backup found (need a .backup_* file with a targets table)."

    current = sqlite_data_score(db_path) if db_path.is_file() else None
    backup_data = sqlite_data_score(backup)

    if (
        current
        and current["valid"]
        and not allow_downgrade
        and current["richness"] > backup_data["richness"]
    ):
        return False, (
            f"Refusing to restore from {backup.name}: current database has more data "
            f"(sessions={current['imaging_sessions']}, cal={current['calibration_captures']}) "
            f"than backup (sessions={backup_data['imaging_sessions']}, "
            f"cal={backup_data['calibration_captures']}). "
            "Use --force on restore_db.py if you intend to downgrade."
        )

    if db_path.is_file() and save_corrupt_as:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        corrupt_copy = project_dir / f"armillarylab.db.{save_corrupt_as}_{stamp}"
        shutil.copy2(db_path, corrupt_copy)

    remove_sqlite_sidecars(db_path)
    shutil.copy2(backup, db_path)
    remove_sqlite_sidecars(db_path)

    restored = sqlite_data_score(db_path)
    if not restored["valid"]:
        return False, f"Restore from {backup.name} failed — file still has no targets table."

    return True, (
        f"Restored {db_path.name} from {backup.name} "
        f"({restored['targets']} targets, {restored['imaging_sessions']} sessions, "
        f"{restored['calibration_captures']} calibration logs)."
    )
