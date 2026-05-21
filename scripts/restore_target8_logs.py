"""One-shot restore of target 8 imaging + calibration logs from conversation screenshots."""
from __future__ import annotations

import sqlite3
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "armillarylab.db"
TARGET_ID = 8

LIGHT_SESSIONS = [
    # date, channel, sub_count, sub_exposure_seconds
    (date(2026, 5, 20), "G", 300, 60.0),
    (date(2026, 5, 20), "R", 150, 60.0),
    (date(2026, 5, 21), "H", 90, 300.0),
    (date(2026, 5, 21), "L", 100, 60.0),
    (date(2026, 5, 22), "B", 100, 60.0),
]

CAL_CAPTURES = [
    # date, frame_type, channel, sub_exposure_seconds, frame_count, checkpoint
    (date(2026, 5, 21), "dark", None, 300.0, 100, "manual"),
    (date(2026, 5, 21), "flat", "G", None, 100, "manual"),
    (date(2026, 5, 21), "dark_flat", "G", None, 100, "manual"),
    (date(2026, 5, 22), "flat", "L", None, 100, "manual"),
]


def main() -> int:
    if not DB.is_file():
        print("armillarylab.db not found")
        return 1

    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM targets WHERE id=?", (TARGET_ID,))
    row = cur.fetchone()
    if not row:
        print(f"Target {TARGET_ID} not found")
        conn.close()
        return 1

    cur.execute("SELECT COUNT(*) FROM imaging_sessions WHERE target_id=?", (TARGET_ID,))
    existing_sessions = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM calibration_captures WHERE target_id=?", (TARGET_ID,))
    existing_cal = cur.fetchone()[0]

    if existing_sessions or existing_cal:
        print(
            f"Target {TARGET_ID} ({row[1]}) already has "
            f"{existing_sessions} sessions and {existing_cal} calibration logs."
        )
        print("Skipping restore to avoid duplicates. Delete existing rows first if you want to re-run.")
        conn.close()
        return 0

    for d, channel, sub_count, sub_exp in LIGHT_SESSIONS:
        cur.execute(
            "INSERT INTO imaging_sessions "
            "(target_id, date, channel, sub_exposure_seconds, sub_count, notes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (TARGET_ID, d.isoformat(), channel, sub_exp, sub_count, None),
        )

    for d, frame_type, channel, sub_exp, count, checkpoint in CAL_CAPTURES:
        cur.execute(
            "INSERT INTO calibration_captures "
            "(target_id, date, frame_type, channel, sub_exposure_seconds, "
            "checkpoint, frame_count, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (TARGET_ID, d.isoformat(), frame_type, channel, sub_exp, checkpoint, count, None),
        )

    conn.commit()
    cur.execute("SELECT COUNT(*) FROM imaging_sessions WHERE target_id=?", (TARGET_ID,))
    sessions = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM calibration_captures WHERE target_id=?", (TARGET_ID,))
    cal = cur.fetchone()[0]
    conn.close()

    print(f"Restored target {TARGET_ID} ({row[1]}): {sessions} light sessions, {cal} calibration logs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
