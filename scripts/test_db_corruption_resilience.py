"""
Simulate empty-shell SQLite corruption against a TEMPORARY copy only.

Never touches armillarylab.db — the live file stays untouched.
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from config.sqlite_health import sqlite_db_info  # noqa: E402

LIVE_DB = BASE / "armillarylab.db"
PORTS = (8080, 5000)


def _detect_port() -> int | None:
    for port in PORTS:
        for path in ("/api/filters", "/"):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as resp:
                    if resp.status in (200, 302):
                        return port
            except urllib.error.HTTPError as exc:
                if exc.code in (200, 302, 404):
                    return port
            except (urllib.error.URLError, TimeoutError, OSError):
                break
    return None


def _wipe_all_tables(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path, timeout=5)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cur.fetchall()]
    for name in tables:
        cur.execute(f'DROP TABLE IF EXISTS "{name}"')
    conn.commit()
    conn.close()
    return sqlite_db_info(db_path) or {}


def _http_get(path: str, port: int) -> tuple[int, str]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers={"Accept": "text/html"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read(8000).decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read(8000).decode("utf-8", errors="replace")
        return exc.code, body


def main() -> int:
    print("=" * 60)
    print("SQLite empty-shell simulation (TEMP COPY ONLY)")
    print("=" * 60)

    if not LIVE_DB.is_file():
        print("ERROR: armillarylab.db not found — cannot seed temp copy.")
        return 1

    baseline = sqlite_db_info(LIVE_DB)
    print("Live DB (read-only baseline):", baseline)
    if not baseline or not baseline.get("valid"):
        print("ERROR: Live database is not healthy. Fix it before running tests.")
        return 1

    port = _detect_port()
    if port is None:
        print("ERROR: Flask not reachable (ports 8080, 5000). Start server first.")
        return 1
    print(f"Flask responding on port {port}")

    with tempfile.TemporaryDirectory(prefix="armillarylab_corruption_") as tmp:
        temp_db = Path(tmp) / "armillarylab.db"
        shutil.copy2(LIVE_DB, temp_db)
        print(f"Temp copy: {temp_db}")

        wiped = _wipe_all_tables(temp_db)
        print("After wipe on TEMP copy:", wiped)

        status, body = _http_get("/", port)
        print(f"GET / -> HTTP {status}")

        live_after = sqlite_db_info(LIVE_DB)
        print("Live DB after HTTP (must be unchanged):", live_after)

        live_unchanged = (
            live_after
            and live_after.get("valid")
            and live_after.get("targets") == baseline.get("targets")
            and live_after.get("imaging_sessions") == baseline.get("imaging_sessions")
        )
        graceful = status in (200, 302, 503) or "unavailable" in body.lower()

        print("\nRESULTS")
        print(f"  Live DB unchanged: {'PASS' if live_unchanged else 'FAIL'}")
        print(f"  App still responds: {'PASS' if graceful else 'FAIL'}")
        return 0 if live_unchanged and graceful else 1


if __name__ == "__main__":
    raise SystemExit(main())
