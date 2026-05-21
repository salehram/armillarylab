"""Scan all armillarylab.db* files for row counts."""
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

def stats(path: Path):
    try:
        conn = sqlite3.connect(path, timeout=3)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        if cur.fetchone()[0] == 0:
            conn.close()
            return None
        out = {"file": path.name, "size": path.stat().st_size}
        for table in ("targets", "imaging_sessions", "calibration_captures"):
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                out[table] = cur.fetchone()[0]
            except sqlite3.Error:
                out[table] = -1
        try:
            cur.execute("SELECT COUNT(*) FROM imaging_sessions WHERE target_id=8")
            out["t8_sessions"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM calibration_captures WHERE target_id=8")
            out["t8_cal"] = cur.fetchone()[0]
        except sqlite3.Error:
            pass
        conn.close()
        return out
    except sqlite3.Error as e:
        return {"file": path.name, "error": str(e)}


def main():
    rows = []
    for p in sorted(BASE.glob("armillarylab.db*")):
        if p.is_file():
            s = stats(p)
            if s:
                rows.append(s)
    rows.sort(key=lambda r: (
        r.get("calibration_captures", 0),
        r.get("imaging_sessions", 0),
        r.get("t8_sessions", 0),
        r.get("targets", 0),
    ), reverse=True)
    for r in rows:
        print(r)


if __name__ == "__main__":
    main()
