"""Diagnose armillarylab.db problems without modifying or restoring the file."""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from config.database import get_database_config  # noqa: E402
from config.sqlite_health import (  # noqa: E402
    classify_sqlite_problem,
    describe_sqlite_problem,
    find_best_sqlite_backup,
    sqlite_db_info,
)


def main() -> int:
    db_config = get_database_config(BASE)
    if db_config.db_type != "sqlite":
        print("Only supported for SQLite.")
        return 1

    db_path = db_config.sqlite_file_path()
    if not db_path:
        print("Could not resolve database path.")
        return 1

    onedrive = "onedrive" in str(db_path).lower()
    info = sqlite_db_info(db_path) or {}
    kind = classify_sqlite_problem(db_path)

    print("=" * 60)
    print("ArmillaryLab SQLite diagnosis")
    print("=" * 60)
    print(f"Path:       {db_path}")
    print(f"OneDrive:   {'yes — high risk for sync conflicts' if onedrive else 'no'}")
    print(f"Size:       {info.get('size', '—')} bytes")
    print(f"Tables:     {info.get('tables', '—')}")
    print(f"Targets:    {info.get('targets', '—')}")
    print(f"Sessions:   {info.get('imaging_sessions', '—')}")
    print(f"Cal logs:   {info.get('calibration_captures', '—')}")
    print(f"Integrity:  {info.get('integrity', '—')}")
    print(f"Status:     {kind}")
    print()
    print(describe_sqlite_problem(db_path))

    if kind == "empty_shell":
        print()
        print("Likely causes (in order):")
        print("  1. flask init-db --force or flask db reset (now blocked unless")
        print("     ARMILLARYLAB_CONFIRM_DESTRUCTIVE=1 is set).")
        print("  2. OneDrive replaced armillarylab.db with a stale empty copy from sync.")
        print("  3. A helper script ran while Flask was already open (e.g. python -c")
        print('     "from app import ...") — fixed: import app no longer opens the DB.')
        print()
        print("Prevention (DB stays in project folder, auto-reload stays on):")
        print("  - Only Flask's worker process opens armillarylab.db for writes.")
        print("  - Use scripts that read SQLite directly, or flask CLI — not bare import app.")
        print("  - Right-click armillarylab.db -> Always keep on this device (OneDrive).")
        print("  - Stop Flask before flask migrate-db or manually copying the .db file.")
        print("  - Never set ARMILLARYLAB_CONFIRM_DESTRUCTIVE=1 unless you mean to wipe data.")

    backup = find_best_sqlite_backup(BASE)
    if backup:
        bi = sqlite_db_info(backup) or {}
        print()
        print(f"Richest manual backup: {backup.name}")
        print(
            f"  targets={bi.get('targets')} sessions={bi.get('imaging_sessions')} "
            f"cal={bi.get('calibration_captures')}"
        )
        print("  Restore only if you choose: python scripts/restore_db.py")

    return 0 if kind == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
