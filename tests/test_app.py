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
    MosaicGroup,
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

    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        config = GlobalConfig(
            default_calibration_darks=50,
            default_calibration_flats_per_channel=100,
            default_calibration_dark_flats_per_channel=100,
            default_calibration_bias=30,
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
        # v2.5.0: two_point dropped from effective config payload.
        assert "two_point" not in cfg


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


def test_no_midpoint_suggestion_at_half_light_frames(client):
    """v2.5.0: the midpoint nudge is gone — no suggestion fires mid-channel."""
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
                sub_count=10,
            )
        )
        db.session.commit()
        progress_seconds = {"R": 3000.0}
        cfg = get_effective_calibration_config(target)
        suggestions = get_calibration_suggestions(
            cfg, plan_data, progress_seconds, [], []
        )
        assert suggestions == []


def test_calibration_suggestion_fires_only_at_channel_end(client):
    """Suggestion appears only once lights for the channel are complete."""
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
        # midpoint_missed retained as False for response-shape stability.
        assert flat[0]["midpoint_missed"] is False


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
            "checkpoint": "end",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "calibration" in data
    assert any(s["checkpoint"] == "end" for s in data["calibration"]["skips"])


def test_skip_calibration_rejects_midpoint(client):
    """v2.5.0: only end-of-channel skips are accepted."""
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
    assert resp.status_code == 400


def test_calibration_log_preserves_midpoint_checkpoint_tag(client):
    """checkpoint is free-form metadata — 'midpoint' is still a valid tag."""
    with app.app_context():
        target = _seed_target()
        tid = target.id
    resp = client.post(
        f"/target/{tid}/calibration/log",
        data={
            "frame_type": "flat",
            "channel": "R",
            "frame_count": "25",
            "checkpoint": "midpoint",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        cap = CalibrationCapture.query.filter_by(target_id=tid, frame_type="flat").one()
        assert cap.checkpoint == "midpoint"
        assert cap.frame_count == 25


def test_migration_clears_legacy_midpoint_skips(client):
    """apply_additive_schema_migrations sweeps stale midpoint skip rows."""
    from app import apply_additive_schema_migrations
    with app.app_context():
        target = _seed_target()
        db.session.add(CalibrationCheckpointSkip(
            target_id=target.id, channel="R", frame_type="flat", checkpoint="midpoint",
        ))
        db.session.add(CalibrationCheckpointSkip(
            target_id=target.id, channel="G", frame_type="flat", checkpoint="end",
        ))
        db.session.commit()
        apply_additive_schema_migrations(log=lambda *_a, **_k: None)
        remaining = CalibrationCheckpointSkip.query.filter_by(target_id=target.id).all()
        assert [s.checkpoint for s in remaining] == ["end"]


def test_restore_calibration_skip_route(client):
    with app.app_context():
        target = _seed_target()
        skip = CalibrationCheckpointSkip(
            target_id=target.id,
            channel="R",
            frame_type="flat",
            checkpoint="end",
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


def test_update_plan_per_channel_overrides_win_over_master_total(client):
    """Regression: manual per-channel minutes must persist even when the master
    total is changed in the same Save Plan submit (v2.4.1 fix)."""
    with app.app_context():
        target = Target(
            name="C 33 plan test",
            ra_hours=20.939,
            dec_deg=31.74,
            preferred_palette="SHO",
        )
        db.session.add(target)
        db.session.flush()
        plan = TargetPlan(
            target_id=target.id,
            palette_name="SHO",
            plan_json=json.dumps(
                {
                    "palette": "SHO",
                    "total_planned_minutes": 546,
                    "channels": [
                        {"name": "H", "label": "Halpha", "planned_minutes": 273,
                         "sub_exposure_seconds": 300, "weight": 0.5,
                         "weight_fraction": 0.5},
                        {"name": "O", "label": "OIII", "planned_minutes": 164,
                         "sub_exposure_seconds": 300, "weight": 0.3,
                         "weight_fraction": 0.3},
                        {"name": "S", "label": "SII", "planned_minutes": 109,
                         "sub_exposure_seconds": 300, "weight": 0.2,
                         "weight_fraction": 0.2},
                    ],
                }
            ),
        )
        db.session.add(plan)
        db.session.commit()
        target_id = target.id

    resp = client.post(
        f"/target/{target_id}/plan/update",
        data={
            "total_planned_minutes": "4200",
            "ch_H_minutes": "1200",
            "ch_O_minutes": "1200",
            "ch_S_minutes": "1800",
            "ch_H_subexp": "300",
            "ch_O_subexp": "300",
            "ch_S_subexp": "300",
        },
    )
    assert resp.status_code == 302

    with app.app_context():
        saved = (
            TargetPlan.query.filter_by(target_id=target_id)
            .order_by(TargetPlan.created_at.desc())
            .first()
        )
        data = json.loads(saved.plan_json)
        channels = {c["name"]: c["planned_minutes"] for c in data["channels"]}
        assert channels["H"] == pytest.approx(1200.0)
        assert channels["O"] == pytest.approx(1200.0)
        assert channels["S"] == pytest.approx(1800.0)
        assert data["total_planned_minutes"] == 4200


# ---------------------------------------------------------------------------
# Mosaic Group Tests
# ---------------------------------------------------------------------------

def test_mosaic_group_crud(client):
    """Create, list, edit, and delete a mosaic group via HTTP routes."""
    # Create
    resp = client.post("/mosaic/new", data={
        "name": "Cygnus Loop Mosaic",
        "description": "9-panel SHO mosaic",
        "panel_count_goal": "9",
        "notes": "Test notes",
    })
    assert resp.status_code == 302

    with app.app_context():
        g = MosaicGroup.query.filter_by(name="Cygnus Loop Mosaic").first()
        assert g is not None
        assert g.panel_count_goal == 9
        assert g.description == "9-panel SHO mosaic"
        group_id = g.id

    # List
    resp = client.get("/mosaics")
    assert resp.status_code == 200
    assert b"Cygnus Loop Mosaic" in resp.data

    # Detail (empty group)
    resp = client.get(f"/mosaic/{group_id}")
    assert resp.status_code == 200
    assert b"Cygnus Loop Mosaic" in resp.data

    # Edit
    resp = client.post(f"/mosaic/{group_id}/edit", data={
        "name": "Cygnus Loop Mosaic Updated",
        "description": "Updated description",
        "panel_count_goal": "9",
        "notes": "",
    })
    assert resp.status_code == 302

    with app.app_context():
        g = MosaicGroup.query.get(group_id)
        assert g.name == "Cygnus Loop Mosaic Updated"

    # Delete
    resp = client.post(f"/mosaic/{group_id}/delete")
    assert resp.status_code == 302

    with app.app_context():
        assert MosaicGroup.query.get(group_id) is None


def test_mosaic_detail_aggregation(client):
    """Panel targets assigned to a group appear in the detail view with correct aggregation."""
    with app.app_context():
        group = MosaicGroup(name="Test Mosaic", panel_count_goal=2)
        db.session.add(group)
        db.session.flush()

        plan_json = json.dumps({
            "palette": "SHO",
            "total_planned_minutes": 300,
            "channels": [
                {"name": "H", "label": "Ha", "planned_minutes": 180,
                 "sub_exposure_seconds": 300, "weight": 0.6, "weight_fraction": 0.6},
                {"name": "O", "label": "OIII", "planned_minutes": 120,
                 "sub_exposure_seconds": 300, "weight": 0.4, "weight_fraction": 0.4},
            ],
        })

        for i in range(1, 3):
            t = Target(
                name=f"Panel {i}",
                ra_hours=20.0 + i * 0.1,
                dec_deg=31.0,
                preferred_palette="SHO",
                mosaic_group_id=group.id,
                mosaic_panel_number=i,
            )
            db.session.add(t)
            db.session.flush()
            db.session.add(TargetPlan(
                target_id=t.id, palette_name="SHO", plan_json=plan_json
            ))
            # 60 min of Ha = 12 × 300s
            db.session.add(ImagingSession(
                target_id=t.id, date=date.today(), channel="H",
                sub_exposure_seconds=300, sub_count=12,
            ))
        db.session.commit()
        group_id = group.id

    resp = client.get(f"/mosaic/{group_id}")
    assert resp.status_code == 200
    assert b"Panel 1" in resp.data
    assert b"Panel 2" in resp.data

    # Both panels together: 2 × 60 min Ha done, 2 × 180 planned
    # The aggregation check is done via the response body (values rendered in template)
    assert b"120.0" in resp.data  # total Ha done (2 × 60 min)


def test_target_form_mosaic_group_assignment(client):
    """Creating a target with a mosaic_group_id links it to the group."""
    with app.app_context():
        group = MosaicGroup(name="My Mosaic")
        db.session.add(group)
        db.session.commit()
        group_id = group.id

    resp = client.post("/target/new", data={
        "name": "Panel A",
        "ra_hours": "20.5",
        "dec_deg": "31.0",
        "target_type": "emission",
        "preferred_palette": "SHO",
        "packup_time_local": "02:00",
        "mosaic_group_id": str(group_id),
        "mosaic_panel_number": "1",
    })
    assert resp.status_code == 302

    with app.app_context():
        t = Target.query.filter_by(name="Panel A").first()
        assert t is not None
        assert t.mosaic_group_id == group_id
        assert t.mosaic_panel_number == 1


def test_mosaic_delete_unlinks_targets(client):
    """Deleting a mosaic group sets mosaic_group_id to None on linked targets."""
    with app.app_context():
        group = MosaicGroup(name="Temp Mosaic")
        db.session.add(group)
        db.session.flush()
        t = Target(
            name="Temp Panel",
            ra_hours=20.0,
            dec_deg=31.0,
            mosaic_group_id=group.id,
            mosaic_panel_number=1,
        )
        db.session.add(t)
        db.session.commit()
        group_id = group.id
        target_id = t.id

    resp = client.post(f"/mosaic/{group_id}/delete")
    assert resp.status_code == 302

    with app.app_context():
        assert MosaicGroup.query.get(group_id) is None
        t = Target.query.get(target_id)
        assert t.mosaic_group_id is None
        assert t.mosaic_panel_number is None


def test_mosaic_update_notes_ajax(client):
    """AJAX inline notes update returns ok and persists the notes."""
    with app.app_context():
        group = MosaicGroup(name="Notes Mosaic")
        db.session.add(group)
        db.session.commit()
        group_id = group.id

    resp = client.post(
        f"/mosaic/{group_id}/update-notes",
        json={"notes": "Updated inline notes"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["notes"] == "Updated inline notes"

    with app.app_context():
        g = MosaicGroup.query.get(group_id)
        assert g.notes == "Updated inline notes"


def test_index_includes_mosaic_summaries(client):
    """Dashboard returns mosaic summary data when a group exists."""
    with app.app_context():
        group = MosaicGroup(name="Dashboard Mosaic", panel_count_goal=3)
        db.session.add(group)
        db.session.commit()

    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Dashboard Mosaic" in resp.data
