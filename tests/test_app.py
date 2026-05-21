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
from calibration_utils import get_calibration_payload, get_calibration_suggestions


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
                frame_count=6,
                checkpoint="manual",
            )
        )
        db.session.commit()
        cfg = get_effective_calibration_config(target)
        payload = get_calibration_payload(cfg, plan_data, {}, target.calibration_captures, [])
        assert payload["summary"]["darks"]["captured"] == 6


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
            "imaging_date": "2026-05-21",
            "checkpoint": "manual",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        assert CalibrationCapture.query.filter_by(target_id=tid, frame_type="dark").count() == 1
