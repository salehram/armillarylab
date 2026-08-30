"""
One-shot fix: rename channel 'L' -> 'LP' for target_id=9
in both imaging_sessions and calibration_captures tables.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "armillarylab.db"

OLD = "L"
NEW = "LP"
TARGET_ID = 9


def main() -> int:
    if not DB.is_file():
        print(f"ERROR: database not found at {DB}")
        return 1

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # --- Preview ---
    cur.execute(
        "SELECT id, date, channel, sub_count, sub_exposure_seconds "
        "FROM imaging_sessions WHERE target_id=? AND channel=?",
        (TARGET_ID, OLD),
    )
    light_rows = cur.fetchall()
    print(f"imaging_sessions rows to update: {len(light_rows)}")
    for row in light_rows:
        print("  ", row)

    cur.execute(
        "SELECT id, date, frame_type, channel, frame_count, checkpoint "
        "FROM calibration_captures WHERE target_id=? AND channel=?",
        (TARGET_ID, OLD),
    )
    cal_rows = cur.fetchall()
    print(f"\ncalibration_captures rows to update: {len(cal_rows)}")
    for row in cal_rows:
        print("  ", row)

    if not light_rows and not cal_rows:
        print("\nNothing to update.")
        conn.close()
        return 0

    confirm = input(f"\nProceed to rename '{OLD}' -> '{NEW}' for target {TARGET_ID}? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        conn.close()
        return 0

    # --- Update ---
    cur.execute(
        "UPDATE imaging_sessions SET channel=? WHERE target_id=? AND channel=?",
        (NEW, TARGET_ID, OLD),
    )
    sessions_updated = cur.rowcount

    cur.execute(
        "UPDATE calibration_captures SET channel=? WHERE target_id=? AND channel=?",
        (NEW, TARGET_ID, OLD),
    )
    cal_updated = cur.rowcount

    conn.commit()
    conn.close()

    print(f"\nDone. Updated {sessions_updated} imaging_sessions row(s) and {cal_updated} calibration_captures row(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
