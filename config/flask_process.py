"""Helpers for Flask dev-server / reloader process detection."""
import os
import sys
from pathlib import Path


def _is_truthy_env(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")


def _is_server_entrypoint() -> bool:
    """
    True when this process was started as a web server, not a one-off script.

    ``python -c "from app import ..."`` and helper scripts must NOT open the
    live SQLite file — especially while Flask is already running on OneDrive.
    """
    if _is_truthy_env("ARMILLARYLAB_SERVE"):
        return True

    server_software = os.environ.get("SERVER_SOFTWARE", "").lower()
    if any(name in server_software for name in ("gunicorn", "waitress", "werkzeug")):
        return True

    argv = sys.argv
    if not argv:
        return False

    prog = Path(argv[0]).stem.lower()
    joined = " ".join(argv).lower()

    if prog in ("gunicorn", "waitress-serve", "flask"):
        return True
    if "gunicorn" in joined:
        return True
    if prog == "app" and any("app.py" in arg for arg in argv):
        return True
    return False


def is_flask_serving_process() -> bool:
    """
    True when this process should open SQLite and serve requests.

    With ``flask run`` + auto-reload, Werkzeug starts a watcher parent and a
    worker child. Only the child sets WERKZEUG_RUN_MAIN=true. The parent must
    NOT hold database connections — that was causing SQLite corruption on reload.
    """
    werkzeug_main = os.environ.get("WERKZEUG_RUN_MAIN")
    if werkzeug_main is not None:
        return werkzeug_main == "true"

    # Flask CLI (`flask run`, `flask migrate-db`, …) — not bare ``import app``.
    if _is_truthy_env("FLASK_RUN_FROM_CLI"):
        return True

    return _is_server_entrypoint()


def is_testing_process() -> bool:
    """True during pytest or when TESTING=1 is set in the environment."""
    if _is_truthy_env("TESTING"):
        return True
    return "pytest" in sys.modules


def should_open_live_sqlite() -> bool:
    """Only the Flask worker / explicit CLI should touch armillarylab.db."""
    if is_testing_process():
        return False
    return is_flask_serving_process()


def sqlite_auto_restore_enabled() -> bool:
    """Deprecated — automatic restore was removed. Always returns False."""
    return False
