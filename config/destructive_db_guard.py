"""Refuse destructive SQLite operations unless explicitly confirmed."""
from __future__ import annotations

import os
from pathlib import Path

from config.sqlite_health import sqlite_data_score


def has_live_sqlite_data(db_path: Path | None) -> bool:
    if not db_path or not db_path.is_file():
        return False
    score = sqlite_data_score(db_path)
    return score["valid"] and score["richness"] > 0


def destructive_db_allowed(db_path: Path | None, action: str) -> tuple[bool, str]:
    """
    Return (allowed, message).

    Requires ARMILLARYLAB_CONFIRM_DESTRUCTIVE=1 when the database already
    contains targets, sessions, or calibration logs.
    """
    if not has_live_sqlite_data(db_path):
        return True, ""

    if os.environ.get("ARMILLARYLAB_CONFIRM_DESTRUCTIVE", "").strip() == "1":
        return True, ""

    score = sqlite_data_score(db_path) if db_path else {}
    return False, (
        f"Refusing {action}: armillarylab.db already has data "
        f"({score.get('targets', 0)} targets, "
        f"{score.get('imaging_sessions', 0)} sessions, "
        f"{score.get('calibration_captures', 0)} calibration logs). "
        "Set ARMILLARYLAB_CONFIRM_DESTRUCTIVE=1 only if you intend to wipe it."
    )
