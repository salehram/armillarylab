"""Inspect a SQLite database file for key row counts."""
import sqlite3
import sys
from pathlib import Path


def full(path: str) -> None:
    p = Path(path)
    if not p.is_file():
        print(path, "MISSING")
        return
    c = sqlite3.connect(p)
    cur = c.cursor()
    cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
    print("===", p.name, "tables", cur.fetchone()[0], "size", p.stat().st_size)
    for t in ("targets", "imaging_sessions", "calibration_captures"):
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            print(t, cur.fetchone()[0])
        except sqlite3.Error as e:
            print(t, "ERR", e)
    try:
        cur.execute("SELECT id, name FROM targets")
        print("targets:", cur.fetchall())
        cur.execute(
            "SELECT target_id, date, channel, sub_count, sub_exposure_seconds "
            "FROM imaging_sessions WHERE target_id=8 ORDER BY date"
        )
        print("t8 sessions:", cur.fetchall())
        cur.execute(
            "SELECT target_id, date, frame_type, channel, frame_count, sub_exposure_seconds "
            "FROM calibration_captures WHERE target_id=8"
        )
        print("t8 cal:", cur.fetchall())
    except sqlite3.Error as e:
        print("detail err", e)
    c.close()


if __name__ == "__main__":
    base = Path(__file__).resolve().parent.parent
    files = sys.argv[1:] or [
        "armillarylab copy 2.db",
        "armillarylab.db.corrupt_20260521_160423",
        "armillarylab.db.corrupt_20260521_160351",
        "armillarylab.db",
    ]
    for f in files:
        full(str(base / f) if not Path(f).is_absolute() else f)
        print()
