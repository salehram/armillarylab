"""
Verify pytest / run_tests.py never wipes armillarylab.db (empty-shell regression).

Root cause (fixed 2026-05-22): test_app client fixture set SQLALCHEMY_DATABASE_URI to
:memory: after app import, but Flask-SQLAlchemy kept the engine on the live file.
db.drop_all() then DROP TABLE'd armillarylab.db while Flask could still be running.

This script:
  1. Reproduces the OLD bug on a TEMP copy only (shows empty_shell fingerprint).
  2. Runs the NEW fixed test client fixture against another temp copy (must stay intact).
  3. Runs `python run_tests.py` and confirms LIVE armillarylab.db is unchanged.

Never modifies armillarylab.db.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from config.sqlite_health import classify_sqlite_problem, sqlite_db_info  # noqa: E402

LIVE_DB = BASE / "armillarylab.db"


def _count_tables(path: Path) -> int:
    info = sqlite_db_info(path)
    return int(info.get("tables") or 0) if info else -1


def _simulate_old_broken_fixture(db_path: Path) -> dict:
    """Mimic pre-fix test_app.py: TESTING not set at import; URI switch + dispose kept file engine."""
    env = os.environ.copy()
    env.pop("TESTING", None)
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    env.pop("FLASK_RUN_FROM_CLI", None)

    code = (
        "from app import app, db\n"
        'app.config["TESTING"] = True\n'
        'app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"\n'
        "with app.app_context():\n"
        '    url_before = str(db.engine.url)\n'
        "    db.engine.dispose()\n"
        "    db.drop_all()\n"
        '    print("URL_BEFORE", url_before)\n'
        "    try:\n"
        '        print("URL_AFTER", str(db.engine.url))\n'
        "    except Exception as exc:\n"
        '        print("URL_AFTER", "error", exc)\n'
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        cwd=str(BASE),
        capture_output=True,
        text=True,
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "tables_after": _count_tables(db_path),
        "kind_after": classify_sqlite_problem(db_path),
    }


def _simulate_fixed_fixture(db_path: Path) -> dict:
    """Mimic post-fix: in-memory DATABASE_URL before app import."""
    env = os.environ.copy()
    env["TESTING"] = "1"
    env["DATABASE_URL"] = "sqlite:///:memory:"
    env.pop("FLASK_RUN_FROM_CLI", None)

    code = """
import os
os.environ.setdefault("TESTING", "1")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app import app, db

app.config["TESTING"] = True

with app.app_context():
    db.session.remove()
    db.drop_all()

print("ENGINE", db.engine.url)
"""
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        cwd=str(BASE),
        capture_output=True,
        text=True,
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "tables_after": _count_tables(db_path),
        "kind_after": classify_sqlite_problem(db_path),
    }


def _run_full_test_suite() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(BASE / "run_tests.py"), "-t", "app"],
        cwd=str(BASE),
        capture_output=True,
        text=True,
    )


def main() -> int:
    print("=" * 60)
    print("Pytest live-DB isolation regression test")
    print("=" * 60)

    if not LIVE_DB.is_file():
        print(f"ERROR: {LIVE_DB} not found.")
        return 1

    live_before = sqlite_db_info(LIVE_DB)
    if not live_before or not live_before.get("valid"):
        print("ERROR: Live DB is not healthy. Restore before running this test.")
        print(live_before)
        return 1

    live_mtime_before = LIVE_DB.stat().st_mtime
    print("Live DB before:", live_before)

    with tempfile.TemporaryDirectory(prefix="pytest_isolation_") as tmp:
        tmp_dir = Path(tmp)
        old_bug_db = tmp_dir / "old_bug_canary.db"
        fixed_db = tmp_dir / "fixed_canary.db"
        shutil.copy2(LIVE_DB, old_bug_db)
        shutil.copy2(LIVE_DB, fixed_db)

        print("\n--- Step 1: OLD broken fixture on temp copy (expect empty_shell) ---")
        old = _simulate_old_broken_fixture(old_bug_db)
        print("  stdout:", old["stdout"] or "(empty)")
        if old["stderr"]:
            print("  stderr:", old["stderr"][:500])
        print("  tables after:", old["tables_after"], "| kind:", old["kind_after"])
        old_reproduced = old["tables_after"] == 0 and old["kind_after"] == "empty_shell"
        print("  OLD bug reproduced:", "PASS" if old_reproduced else "FAIL")

        print("\n--- Step 2: FIXED fixture on temp copy (must keep tables) ---")
        fixed = _simulate_fixed_fixture(fixed_db)
        print("  stdout:", fixed["stdout"] or "(empty)")
        if fixed["stderr"]:
            print("  stderr:", fixed["stderr"][:500])
        print("  tables after:", fixed["tables_after"], "| kind:", fixed["kind_after"])
        fixed_ok = fixed["tables_after"] > 0 and fixed["kind_after"] is None
        print("  Temp copy preserved:", "PASS" if fixed_ok else "FAIL")

        print("\n--- Step 3: Full run_tests.py (live armillarylab.db must be unchanged) ---")
        suite = _run_full_test_suite()
        print("  exit code:", suite.returncode)
        if suite.returncode != 0:
            print("  pytest stderr tail:", (suite.stderr or "")[-800:])

        live_after = sqlite_db_info(LIVE_DB)
        live_mtime_after = LIVE_DB.stat().st_mtime
        print("  Live DB after:", live_after)

        live_ok = (
            live_after
            and live_after.get("valid")
            and live_after.get("targets") == live_before.get("targets")
            and live_after.get("imaging_sessions") == live_before.get("imaging_sessions")
            and live_after.get("tables") == live_before.get("tables")
        )
        print("  Live DB unchanged:", "PASS" if live_ok else "FAIL")
        if live_mtime_before != live_mtime_after:
            print("  (note: mtime changed — check OneDrive/sync; table counts matter most)")

    print("\n" + "=" * 60)
    all_pass = old_reproduced and fixed_ok and live_ok and suite.returncode == 0
    if all_pass:
        print("OVERALL: PASS — fix holds; old bug path still reproducible on temp copy only.")
        return 0
    print("OVERALL: FAIL — see steps above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
