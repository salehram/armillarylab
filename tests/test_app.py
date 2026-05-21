"""Application tests for calibration frame tracking."""

import json
from datetime import date

import pytest

from app import (
    app,
    db,
    Target,
    TargetPlan,
    ImagingSession,
    GlobalConfig,
    CalibrationCapture,
    CalibrationCheckpointSkip,
    get_effective_calibration_config,
)
from calibration_utils import (
    get_calibration_payload,
    get_calibration_suggestions,
    resolve_astrobin_calibration_columns,
    build_target_imaging_log_days,
    build_astrobin_export_rows,
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

    with app.app_context():
        db.engine.dispose()
        db.drop_all()
        db.create_all()
        config = GlobalConfig(
            default_calibration_darks=50,
            default_calibration_flats_per_channel=100,
            default_calibration_dark_flats_per_channel=100,
            default_calibration_bias=30,
            default_calibration_two_point=True,
        )
        db.session.add(config)
        db.session.commit()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def _seed_target(enabled=True):
    target = Target(
        name="Test Nebula",
        ra_hours=12.0,
        dec_deg=45.0,
        calibration_tracking_enabled=enabled,
        override_calibration_darks=40,
    )
    db.session.add(target)
    db.session.flush()
    plan_json = json.dumps(
        {
            "channels": [
                {
                    "name": "R",
                    "label": "Red",
                    "planned_minutes": 100,
                    "sub_exposure_seconds": 300,
                    "weight": 1.0,
                    "weight_fraction": 1.0,
                }
            ],
            "total_planned_minutes": 100,
            "palette": "LRGB",
        }
    )
    db.session.add(
        TargetPlan(target_id=target.id, palette_name="LRGB", plan_json=plan_json)
    )
    db.session.commit()
    return target


def test_effective_calibration_config_uses_target_override(client):
    with app.app_context():
        target = _seed_target()
        cfg = get_effective_calibration_config(target)
        assert cfg["enabled"] is True
        assert cfg["darks"] == 40
        assert cfg["flats_per_channel"] == 100
        assert cfg["two_point"] is True


def test_global_settings_saves_max_cloud_cover_pct(client):
    response = client.post(
        "/settings",
        data={
            "observer_lat": "24.7136",
            "observer_lon": "46.6753",
            "observer_elev_m": "600",
            "default_packup_time": "01:00",
            "default_min_altitude": "30",
            "timezone_name": "Asia/Riyadh",
            "max_cloud_cover_pct": "15",
            "default_calibration_darks": "0",
            "default_calibration_flats_per_channel": "0",
            "default_calibration_dark_flats_per_channel": "0",
            "default_calibration_bias": "0",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'value="15"' in response.data
    with app.app_context():
        assert GlobalConfig.query.first().max_cloud_cover_pct == 15


def test_midpoint_suggestion_at_half_light_frames(client):
    with app.app_context():
        target = _seed_target()
        plan = TargetPlan.query.filter_by(target_id=target.id).first()
        plan_data = json.loads(plan.plan_json)
        # 100 min / 300s = 20 frames; 10 frames = 50%
        db.session.add(
            ImagingSession(
                target_id=target.id,
                date=date.today(),
                channel="R",
                sub_exposure_seconds=300,
                sub_count=10,
            )
        )
        db.session.commit()
        progress_seconds = {"R": 3000.0}
        cfg = get_effective_calibration_config(target)
        suggestions = get_calibration_suggestions(
            cfg, plan_data, progress_seconds, [], []
        )
        flat_mid = [s for s in suggestions if s["frame_type"] == "flat" and s["checkpoint"] == "midpoint"]
        assert len(flat_mid) == 1
        assert flat_mid[0]["suggested_count"] == 50
        assert flat_mid[0]["planned_total"] == 100
        assert flat_mid[0]["title"] == "Log 50 flat at midpoint"


def test_lights_complete_shows_only_end_not_midpoint(client):
    with app.app_context():
        target = _seed_target()
        plan = TargetPlan.query.filter_by(target_id=target.id).first()
        plan_data = json.loads(plan.plan_json)
        db.session.add(
            ImagingSession(
                target_id=target.id,
                date=date.today(),
                channel="R",
                sub_exposure_seconds=300,
                sub_count=20,
            )
        )
        db.session.commit()
        progress_seconds = {"R": 6000.0}
        cfg = get_effective_calibration_config(target)
        suggestions = get_calibration_suggestions(cfg, plan_data, progress_seconds, [], [])
        flat = [s for s in suggestions if s["frame_type"] == "flat"]
        assert len(flat) == 1
        assert flat[0]["checkpoint"] == "end"
        assert flat[0]["suggested_count"] == 100
        assert flat[0]["planned_total"] == 100
        assert flat[0]["midpoint_missed"] is True


def test_skip_midpoint_end_includes_full_remainder(client):
    with app.app_context():
        target = _seed_target()
        plan = TargetPlan.query.filter_by(target_id=target.id).first()
        plan_data = json.loads(plan.plan_json)
        db.session.add(
            ImagingSession(
                target_id=target.id,
                date=date.today(),
                channel="R",
                sub_exposure_seconds=300,
                sub_count=20,
            )
        )
        skip = CalibrationCheckpointSkip(
            target_id=target.id,
            channel="R",
            frame_type="flat",
            checkpoint="midpoint",
        )
        db.session.add(skip)
        db.session.commit()
        progress_seconds = {"R": 6000.0}
        cfg = get_effective_calibration_config(target)
        suggestions = get_calibration_suggestions(
            cfg, plan_data, progress_seconds, [], [skip]
        )
        end_flat = [s for s in suggestions if s["frame_type"] == "flat" and s["checkpoint"] == "end"]
        assert len(end_flat) == 1
        assert end_flat[0]["suggested_count"] == 100


def test_partial_midpoint_capture_reduces_end_suggestion(client):
    with app.app_context():
        target = _seed_target()
        plan = TargetPlan.query.filter_by(target_id=target.id).first()
        plan_data = json.loads(plan.plan_json)
        db.session.add(
            ImagingSession(
                target_id=target.id,
                date=date.today(),
                channel="R",
                sub_exposure_seconds=300,
                sub_count=20,
            )
        )
        db.session.add(
            CalibrationCapture(
                target_id=target.id,
                date=date.today(),
                frame_type="flat",
                channel="R",
                checkpoint="midpoint",
                frame_count=30,
            )
        )
        db.session.commit()
        progress_seconds = {"R": 6000.0}
        cfg = get_effective_calibration_config(target)
        suggestions = get_calibration_suggestions(
            cfg, plan_data, progress_seconds, target.calibration_captures, []
        )
        end_flat = [s for s in suggestions if s["frame_type"] == "flat" and s["checkpoint"] == "end"]
        assert end_flat[0]["suggested_count"] == 70


def test_manual_flat_counts_toward_midpoint(client):
    """Manual bulk logs satisfy midpoint when total reaches mid_target."""
    with app.app_context():
        target = _seed_target()
        plan = TargetPlan.query.filter_by(target_id=target.id).first()
        plan_data = json.loads(plan.plan_json)
        db.session.add(
            CalibrationCapture(
                target_id=target.id,
                date=date.today(),
                frame_type="flat",
                channel="R",
                frame_count=100,
                checkpoint="manual",
            )
        )
        db.session.add(
            CalibrationCapture(
                target_id=target.id,
                date=date.today(),
                frame_type="dark_flat",
                channel="R",
                frame_count=100,
                checkpoint="manual",
            )
        )
        db.session.commit()
        cfg = get_effective_calibration_config(target)
        payload = get_calibration_payload(cfg, plan_data, {}, target.calibration_captures, [])
        r_flat = payload["summary"]["channels"]["R"]["flat"]
        r_df = payload["summary"]["channels"]["R"]["dark_flat"]
        assert r_flat["captured"] == 100
        assert r_flat["mid_complete"] is True
        assert r_flat["end_complete"] is True
        assert r_df["mid_complete"] is True
        assert r_df["end_complete"] is True


def test_manual_dark_logging_increments_summary(client):
    with app.app_context():
        target = _seed_target()
        plan = TargetPlan.query.filter_by(target_id=target.id).first()
        plan_data = json.loads(plan.plan_json)
        db.session.add(
            CalibrationCapture(
                target_id=target.id,
                date=date.today(),
                frame_type="dark",
                sub_exposure_seconds=300,
                frame_count=6,
                checkpoint="manual",
            )
        )
        db.session.commit()
        cfg = get_effective_calibration_config(target)
        payload = get_calibration_payload(cfg, plan_data, {}, target.calibration_captures, [])
        assert payload["summary"]["darks"]["captured"] == 6
        assert payload["summary"]["darks"]["exposures"][0]["captured"] == 6


def test_darks_tracked_per_sub_exposure(client):
    with app.app_context():
        target = _seed_target()
        plan_json = json.dumps(
            {
                "channels": [
                    {"name": "H", "planned_minutes": 60, "sub_exposure_seconds": 60, "weight": 1.0},
                    {"name": "O", "planned_minutes": 60, "sub_exposure_seconds": 120, "weight": 1.0},
                ],
                "total_planned_minutes": 120,
                "palette": "SHO",
            }
        )
        plan = TargetPlan.query.filter_by(target_id=target.id).first()
        plan.plan_json = plan_json
        plan_data = json.loads(plan_json)
        db.session.add(
            CalibrationCapture(
                target_id=target.id,
                date=date.today(),
                frame_type="dark",
                sub_exposure_seconds=60,
                frame_count=10,
                checkpoint="manual",
            )
        )
        db.session.add(
            CalibrationCapture(
                target_id=target.id,
                date=date.today(),
                frame_type="dark",
                sub_exposure_seconds=120,
                frame_count=5,
                checkpoint="manual",
            )
        )
        db.session.commit()
        cfg = get_effective_calibration_config(target)
        payload = get_calibration_payload(cfg, plan_data, {}, target.calibration_captures, [])
        by_sub = {row["sub_exposure_seconds"]: row for row in payload["summary"]["darks"]["exposures"]}
        assert by_sub[60]["captured"] == 10
        assert by_sub[60]["planned"] == 40
        assert by_sub[120]["captured"] == 5
        assert payload["summary"]["darks"]["captured"] == 15
        assert payload["summary"]["darks"]["planned"] == 80


def test_disabled_tracking_returns_no_suggestions(client):
    with app.app_context():
        target = _seed_target(enabled=False)
        plan = TargetPlan.query.filter_by(target_id=target.id).first()
        plan_data = json.loads(plan.plan_json)
        cfg = get_effective_calibration_config(target)
        suggestions = get_calibration_suggestions(cfg, plan_data, {"R": 9999}, [], [])
        assert suggestions == []


def test_calibration_log_route(client):
    with app.app_context():
        target = _seed_target()
        tid = target.id
    resp = client.post(
        f"/target/{tid}/calibration/log",
        data={
            "frame_type": "dark",
            "frame_count": "5",
            "sub_exposure_seconds": "300",
            "imaging_date": "2026-05-21",
            "checkpoint": "manual",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        assert CalibrationCapture.query.filter_by(target_id=tid, frame_type="dark").count() == 1


def test_skip_calibration_json(client):
    with app.app_context():
        target = _seed_target()
        tid = target.id
    resp = client.post(
        f"/target/{tid}/calibration/skip",
        data={
            "channel": "R",
            "frame_type": "flat",
            "checkpoint": "midpoint",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "calibration" in data
    assert any(s["checkpoint"] == "midpoint" for s in data["calibration"]["skips"])


def test_restore_calibration_skip_route(client):
    with app.app_context():
        target = _seed_target()
        skip = CalibrationCheckpointSkip(
            target_id=target.id,
            channel="R",
            frame_type="flat",
            checkpoint="midpoint",
        )
        db.session.add(skip)
        db.session.commit()
        skip_id = skip.id
        tid = target.id
    resp = client.post(
        f"/calibration/skip/{skip_id}/restore",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Restored calibration suggestion" in resp.data
    with app.app_context():
        assert CalibrationCheckpointSkip.query.filter_by(target_id=tid).count() == 0


def test_build_astrobin_export_rows_per_session_calibration(client):
    """Calibration is allocated per row, not duplicated on every light session."""
    with app.app_context():
        target = _seed_target()
        plan_json = json.dumps(
            {
                "channels": [
                    {"name": "G", "planned_minutes": 60, "sub_exposure_seconds": 60, "weight": 1.0},
                    {"name": "R", "planned_minutes": 60, "sub_exposure_seconds": 60, "weight": 1.0},
                    {"name": "H", "planned_minutes": 60, "sub_exposure_seconds": 300, "weight": 1.0},
                    {"name": "L", "planned_minutes": 60, "sub_exposure_seconds": 60, "weight": 1.0},
                    {"name": "B", "planned_minutes": 60, "sub_exposure_seconds": 60, "weight": 1.0},
                ],
                "dominant_channel": "H",
                "total_planned_minutes": 300,
                "palette": "LRGBNB",
            }
        )
        plan = TargetPlan.query.filter_by(target_id=target.id).first()
        plan.plan_json = plan_json
        plan_data = json.loads(plan_json)
        filter_map = {ch["name"]: ch["name"] for ch in plan_data["channels"]}

        sessions = [
            ImagingSession(
                target_id=target.id, date=date(2026, 5, 20), channel="G",
                sub_exposure_seconds=60, sub_count=300,
            ),
            ImagingSession(
                target_id=target.id, date=date(2026, 5, 20), channel="R",
                sub_exposure_seconds=60, sub_count=150,
            ),
            ImagingSession(
                target_id=target.id, date=date(2026, 5, 21), channel="H",
                sub_exposure_seconds=300, sub_count=90,
            ),
            ImagingSession(
                target_id=target.id, date=date(2026, 5, 21), channel="L",
                sub_exposure_seconds=60, sub_count=100,
            ),
            ImagingSession(
                target_id=target.id, date=date(2026, 5, 22), channel="B",
                sub_exposure_seconds=60, sub_count=100,
            ),
        ]
        for s in sessions:
            db.session.add(s)

        captures = [
            CalibrationCapture(
                target_id=target.id, date=date(2026, 5, 21), frame_type="dark",
                sub_exposure_seconds=300, frame_count=100, checkpoint="manual",
            ),
            CalibrationCapture(
                target_id=target.id, date=date(2026, 5, 21), frame_type="flat",
                channel="G", frame_count=100, checkpoint="manual",
            ),
            CalibrationCapture(
                target_id=target.id, date=date(2026, 5, 22), frame_type="flat",
                channel="L", frame_count=100, checkpoint="manual",
            ),
        ]
        for c in captures:
            db.session.add(c)
        db.session.commit()

        rows = build_astrobin_export_rows(sessions, captures, filter_map, plan_data)
        by_key = {(r["date"], r["filter_name"], r["duration"]): r for r in rows}

        assert by_key[("2026-05-20", "G", 60)]["darks"] == 0
        assert by_key[("2026-05-20", "G", 60)]["flats"] == 0
        assert by_key[("2026-05-21", "H", 300)]["darks"] == 100
        assert by_key[("2026-05-21", "H", 300)]["flats"] == 0
        assert by_key[("2026-05-21", "G", 60)]["number"] == 0
        assert by_key[("2026-05-21", "G", 60)]["flats"] == 100
        assert by_key[("2026-05-22", "L", 60)]["number"] == 0
        assert by_key[("2026-05-22", "L", 60)]["flats"] == 100
        assert sum(r["darks"] for r in rows) == 100
        assert sum(r["flats"] for r in rows) == 200


def test_astrobin_export_route_uses_per_row_calibration(client):
    with app.app_context():
        target = _seed_target()
        tid = target.id
        db.session.add(
            ImagingSession(
                target_id=tid, date=date(2026, 5, 21), channel="R",
                sub_exposure_seconds=300, sub_count=10,
            )
        )
        db.session.add(
            ImagingSession(
                target_id=tid, date=date(2026, 5, 22), channel="R",
                sub_exposure_seconds=300, sub_count=5,
            )
        )
        db.session.add(
            CalibrationCapture(
                target_id=tid, date=date(2026, 5, 21), frame_type="dark",
                sub_exposure_seconds=300, frame_count=100, checkpoint="manual",
            )
        )
        db.session.commit()

    resp = client.post(
        f"/target/{tid}/export_astrobin",
        data={
            "use_tracked_calibration": "on",
            "binning": "1",
            "gain": "100",
            "sensor_cooling": "-10",
            "bortle": "8",
        },
    )
    assert resp.status_code == 200
    import csv
    rows = list(csv.reader(resp.data.decode("utf-8").strip().splitlines()))
    header = rows[0]
    data_rows = {r[0]: dict(zip(header, r)) for r in rows[1:]}
    assert data_rows["2026-05-21"]["darks"] == "100"
    assert data_rows["2026-05-22"]["darks"] in ("", "0")


def test_resolve_astrobin_calibration_columns(client):
    with app.app_context():
        target = _seed_target()
        db.session.add(
            CalibrationCapture(
                target_id=target.id,
                date=date.today(),
                frame_type="dark",
                frame_count=10,
                checkpoint="manual",
            )
        )
        db.session.add(
            CalibrationCapture(
                target_id=target.id,
                date=date.today(),
                frame_type="flat",
                channel="R",
                frame_count=20,
                checkpoint="midpoint",
            )
        )
        db.session.commit()
        captures = target.calibration_captures
        tracked = resolve_astrobin_calibration_columns({}, captures, use_tracked=True)
        assert tracked["darks"] == "10"
        assert tracked["flats"] == "20"
        override = resolve_astrobin_calibration_columns({"darks": "5"}, captures, use_tracked=True)
        assert override["darks"] == "5"
        assert override["flats"] == "20"
        off = resolve_astrobin_calibration_columns({}, captures, use_tracked=False)
        assert off["darks"] == ""


def test_build_target_imaging_log_days(client):
    with app.app_context():
        target = _seed_target()
        db.session.add(
            ImagingSession(
                target_id=target.id,
                date=date.today(),
                channel="R",
                sub_exposure_seconds=300,
                sub_count=5,
            )
        )
        db.session.add(
            CalibrationCapture(
                target_id=target.id,
                date=date.today(),
                frame_type="bias",
                frame_count=30,
                checkpoint="manual",
            )
        )
        db.session.commit()
        days = build_target_imaging_log_days(target.sessions, target.calibration_captures)
        assert len(days) == 1
        assert len(days[0][1]) == 2
        kinds = {e["kind"] for e in days[0][1]}
        assert kinds == {"light", "calibration"}
