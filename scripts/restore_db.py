"""Restore armillarylab.db from the best local .backup_* copy (manual only)."""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from config.sqlite_health import (  # noqa: E402
    check_sqlite_database,
    find_best_sqlite_backup,
    restore_sqlite_from_backup,
    sqlite_db_info,
)
from config.database import get_database_config  # noqa: E402


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Manually restore armillarylab.db from the best .backup_* file."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Restore even if the current database has more data than the backup.",
    )
    args = parser.parse_args()

    db_config = get_database_config(BASE)
    if db_config.db_type != "sqlite":
        print("Only supported for SQLite.")
        return 1

    db_path = db_config.sqlite_file_path()
    if not db_path:
        print("Could not resolve database path.")
        return 1

    print("Database path:", db_path)
    ok, msg, _info = check_sqlite_database(db_path)
    print("Before:", msg)
    print(sqlite_db_info(db_path))
    backup = find_best_sqlite_backup(BASE)
    print("Best backup:", backup.name if backup else None, sqlite_db_info(backup) if backup else None)

    if not backup:
        print("No valid backup found.")
        return 1

    restored, message = restore_sqlite_from_backup(
        db_path,
        BASE,
        allow_downgrade=args.force,
    )
    print(message)
    print("After:", sqlite_db_info(db_path))

    if restored:
        print(
            "Next: restart Flask. Run `flask migrate-db` only if you pulled/upgraded ArmillaryLab "
            "since that backup was made, or Flask errors with missing tables/columns — "
            "otherwise the restored file already matches this checkout."
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
