"""One-shot restore: copy legacy astroplanner SQLite data into armillarylab.db."""

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
TARGET_DB = BASE / "armillarylab.db"
LEGACY_DB = BASE / "old-astroplanner.db"


def backup_db(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = path.with_name(f"{path.name}.backup_{stamp}")
    shutil.copy2(path, dest)
    return dest


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]


def restore():
    if not LEGACY_DB.exists():
        raise SystemExit(f"Legacy database not found: {LEGACY_DB}")
    if not TARGET_DB.exists():
        raise SystemExit(f"Target database not found: {TARGET_DB}")

    pre_backup = backup_db(TARGET_DB)
    print(f"Pre-restore backup: {pre_backup}")

    tgt = sqlite3.connect(TARGET_DB)
    tgt.row_factory = sqlite3.Row
    legacy = sqlite3.connect(LEGACY_DB)
    legacy.row_factory = sqlite3.Row

    for table in ("imaging_sessions", "target_plans", "targets"):
        tgt.execute(f"DELETE FROM [{table}]")

    legacy_targets = legacy.execute("SELECT * FROM targets ORDER BY id").fetchall()
    for row in legacy_targets:
        tgt.execute(
            """
            INSERT INTO targets (
                id, name, catalog_id, target_type, target_type_id,
                ra_hours, dec_deg, notes, pixinsight_workflow, preferred_palette,
                palette_id, packup_time_local, override_packup_time, override_min_altitude,
                calibration_tracking_enabled,
                override_calibration_darks, override_calibration_flats_per_channel,
                override_calibration_dark_flats_per_channel, override_calibration_bias,
                override_calibration_two_point,
                final_image_filename, created_at, is_archived, archived_at, completion_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["name"],
                row["catalog_id"],
                row["target_type"],
                None,
                row["ra_hours"],
                row["dec_deg"],
                row["notes"],
                row["pixinsight_workflow"],
                row["preferred_palette"],
                None,
                row["packup_time_local"] or "01:00",
                None,
                None,
                0,
                None,
                None,
                None,
                None,
                None,
                row["final_image_filename"],
                None,
                0,
                None,
                None,
            ),
        )

    legacy_plans = legacy.execute("SELECT * FROM target_plans ORDER BY id").fetchall()
    for row in legacy_plans:
        tgt.execute(
            """
            INSERT INTO target_plans (id, target_id, palette_name, palette_id, plan_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (row["id"], row["target_id"], row["palette_name"], None, row["plan_json"], row["created_at"]),
        )

    legacy_sessions = legacy.execute("SELECT * FROM imaging_sessions ORDER BY id").fetchall()
    for row in legacy_sessions:
        tgt.execute(
            """
            INSERT INTO imaging_sessions (id, target_id, date, channel, sub_exposure_seconds, sub_count, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["target_id"],
                row["date"],
                row["channel"],
                row["sub_exposure_seconds"],
                row["sub_count"],
                row["notes"],
            ),
        )

    tgt.commit()
    legacy.close()
    tgt.close()

    verify = sqlite3.connect(TARGET_DB)
    print("Restored row counts:")
    for table in ("targets", "target_plans", "imaging_sessions"):
        print(f"  {table}: {count_rows(verify, table)}")
    verify.close()
    print("Restore complete. Run: flask init-db  (without --force) to seed filters/palettes if needed.")


if __name__ == "__main__":
    restore()
