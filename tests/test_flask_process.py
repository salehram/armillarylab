"""Tests for Flask reloader process detection."""
import sys

from config.flask_process import (
    is_flask_serving_process,
    is_testing_process,
    should_open_live_sqlite,
    sqlite_auto_restore_enabled,
)


def test_bare_python_import_is_not_serving(monkeypatch):
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)
    monkeypatch.delenv("FLASK_RUN_FROM_CLI", raising=False)
    monkeypatch.delenv("ARMILLARYLAB_SERVE", raising=False)
    monkeypatch.setattr(sys, "argv", ["python", "-c", "from app import app"])
    assert is_flask_serving_process() is False
    assert should_open_live_sqlite() is False


def test_flask_cli_is_serving(monkeypatch):
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)
    monkeypatch.setenv("FLASK_RUN_FROM_CLI", "true")
    assert is_flask_serving_process() is True


def test_gunicorn_entrypoint_is_serving(monkeypatch):
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)
    monkeypatch.delenv("FLASK_RUN_FROM_CLI", raising=False)
    monkeypatch.setenv("SERVER_SOFTWARE", "gunicorn/21.2")
    assert is_flask_serving_process() is True


def test_python_app_py_is_serving(monkeypatch):
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)
    monkeypatch.delenv("FLASK_RUN_FROM_CLI", raising=False)
    monkeypatch.delenv("SERVER_SOFTWARE", raising=False)
    monkeypatch.setenv("ARMILLARYLAB_SERVE", "1")
    assert is_flask_serving_process() is True


def test_reloader_parent_is_not_serving(monkeypatch):
    monkeypatch.setenv("WERKZEUG_RUN_MAIN", "false")
    assert is_flask_serving_process() is False


def test_reloader_child_is_serving(monkeypatch):
    monkeypatch.setenv("WERKZEUG_RUN_MAIN", "true")
    assert is_flask_serving_process() is True


def test_pytest_never_opens_live_sqlite(monkeypatch):
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)
    monkeypatch.delenv("FLASK_RUN_FROM_CLI", raising=False)
    import sys

    sys.modules["pytest"] = True  # simulate pytest import
    try:
        assert should_open_live_sqlite() is False
    finally:
        del sys.modules["pytest"]


def test_testing_env_never_opens_live_sqlite(monkeypatch):
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("WERKZEUG_RUN_MAIN", "true")
    assert should_open_live_sqlite() is False


def test_auto_restore_always_disabled():
    assert sqlite_auto_restore_enabled() is False
