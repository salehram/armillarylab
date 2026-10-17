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
    Filter,
    FilterWheel,
    FilterWheelSlot,
    get_effective_calibration_config,
    latest_plan,
    apply_destructive_schema_cleanup,
    stamp_unassigned_filter_wheels,
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
        assert "midpoint_missed" not in flat[0]


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


def test_manual_flat_counts_toward_channel_total(client):
    """Manual bulk logs complete the per-channel flat/dark-flat totals."""
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
        assert "mid_complete" not in r_flat
        assert r_flat["end_complete"] is True
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


# ---------------------------------------------------------------------------
# v2.8.0: session-form flats, mosaic backfill, per-project filter wheels, parity
# ---------------------------------------------------------------------------

SHO_PLAN = {
    "palette": "SHO",
    "total_planned_minutes": 300,
    "channels": [
        {"name": "H", "label": "Ha", "planned_minutes": 100, "sub_exposure_seconds": 300},
        {"name": "O", "label": "OIII", "planned_minutes": 100, "sub_exposure_seconds": 300},
        {"name": "S", "label": "SII", "planned_minutes": 100, "sub_exposure_seconds": 300},
    ],
}


def _make_filters():
    codes = ["L", "R", "G", "B", "S", "H", "O", "LP"]
    filters = {}
    for code in codes:
        f = Filter(name=code, display_name=code, astrobin_id=1000 + codes.index(code))
        db.session.add(f)
        filters[code] = f
    db.session.flush()
    return filters


def _make_wheel(name, codes, filters, active=False, astrobin_ids=None):
    wheel = FilterWheel(name=name, slot_count=len(codes), is_active=active)
    db.session.add(wheel)
    db.session.flush()
    for pos, code in enumerate(codes):
        db.session.add(FilterWheelSlot(
            filter_wheel_id=wheel.id,
            filter_id=filters[code].id,
            position=pos,
            astrobin_id=(astrobin_ids or {}).get(code),
        ))
    db.session.flush()
    return wheel


def _make_project(name, plan, wheel=None, mosaic=None, panel=None, tracking=False):
    t = Target(
        name=name, ra_hours=20.8, dec_deg=31.0, preferred_palette=plan["palette"],
        filter_wheel_id=wheel.id if wheel else None,
        mosaic_group_id=mosaic.id if mosaic else None, mosaic_panel_number=panel,
        calibration_tracking_enabled=tracking,
    )
    db.session.add(t)
    db.session.flush()
    db.session.add(TargetPlan(target_id=t.id, palette_name=plan["palette"], plan_json=json.dumps(plan)))
    db.session.flush()
    return t


def test_session_form_logs_flats_and_dark_flats_without_tracking(client):
    with app.app_context():
        filters = _make_filters()
        wheel = _make_wheel("ZWO 7x2", ["L", "R", "G", "B", "S", "H", "O"], filters, active=True)
        t = _make_project("Flats Target", SHO_PLAN, wheel=wheel, tracking=False)
        db.session.commit()
        target_id, wheel_id = t.id, wheel.id

    resp = client.post(f"/target/{target_id}/progress/add", data={
        "imaging_date": "2026-08-01", "channel": "H", "sub_exposure_seconds": "300",
        "sub_count": "12", "log_flats": "1", "flat_count": "30", "log_dark_flats": "1",
    })
    assert resp.status_code == 302

    with app.app_context():
        session = ImagingSession.query.filter_by(target_id=target_id).one()
        assert session.filter_wheel_id == wheel_id
        caps = CalibrationCapture.query.filter_by(target_id=target_id).all()
        assert sorted(c.frame_type for c in caps) == ["dark_flat", "flat"]
        assert all(c.channel == "H" and c.frame_count == 30 for c in caps)
        assert all(c.date == date(2026, 8, 1) for c in caps)


def test_session_form_flats_only(client):
    with app.app_context():
        t = _make_project("Flats Only", SHO_PLAN)
        db.session.commit()
        target_id = t.id

    client.post(f"/target/{target_id}/progress/add", data={
        "imaging_date": "2026-08-02", "channel": "O", "sub_exposure_seconds": "300",
        "sub_count": "5", "log_flats": "1", "flat_count": "20",
    })
    with app.app_context():
        caps = CalibrationCapture.query.filter_by(target_id=target_id).all()
        assert [(c.frame_type, c.frame_count) for c in caps] == [("flat", 20)]


def test_calibration_log_allowed_without_tracking(client):
    with app.app_context():
        t = _make_project("No Tracking", SHO_PLAN, tracking=False)
        db.session.commit()
        target_id = t.id

    client.post(f"/target/{target_id}/calibration/log", data={
        "frame_type": "flat", "channel": "S", "frame_count": "15",
        "imaging_date": "2026-08-03", "also_log_counterpart": "1",
    })
    with app.app_context():
        caps = CalibrationCapture.query.filter_by(target_id=target_id).all()
        assert sorted(c.frame_type for c in caps) == ["dark_flat", "flat"]


def test_mosaic_backfill_logs_missing_rows_and_is_idempotent(client):
    with app.app_context():
        group = MosaicGroup(name="Cygnus Loop")
        db.session.add(group)
        db.session.flush()
        p1 = _make_project("CL P1", SHO_PLAN, mosaic=group, panel=1)
        p2 = _make_project("CL P2", SHO_PLAN, mosaic=group, panel=2)
        night = date(2026, 7, 10)
        for t, ch in ((p1, "H"), (p1, "O"), (p2, "H")):
            db.session.add(ImagingSession(target_id=t.id, date=night, channel=ch,
                                          sub_exposure_seconds=300, sub_count=10))
        db.session.add(CalibrationCapture(target_id=p1.id, date=night, frame_type="flat",
                                          channel="O", frame_count=25, checkpoint="manual"))
        db.session.commit()
        group_id, p1_id, p2_id = group.id, p1.id, p2.id

    page = client.get(f"/mosaic/{group_id}/calibration/backfill")
    assert page.status_code == 200
    assert b"CL P2" in page.data

    rows = [f"2026-07-10|{p1_id}|H", f"2026-07-10|{p1_id}|O", f"2026-07-10|{p2_id}|H",
            "2026-07-10|99999|H"]
    data = {"flat_count": "30", "log_dark_flats": "1", "rows": rows}
    resp = client.post(f"/mosaic/{group_id}/calibration/backfill", data=data)
    assert resp.status_code == 302

    with app.app_context():
        def counts(tid, ch):
            caps = CalibrationCapture.query.filter_by(target_id=tid, channel=ch).all()
            return sorted((c.frame_type, c.frame_count) for c in caps)
        assert counts(p1_id, "H") == [("dark_flat", 30), ("flat", 30)]
        # Existing flats kept; only the missing dark flats were added
        assert counts(p1_id, "O") == [("dark_flat", 30), ("flat", 25)]
        assert counts(p2_id, "H") == [("dark_flat", 30), ("flat", 30)]
        assert CalibrationCapture.query.filter_by(target_id=99999).count() == 0
        total = CalibrationCapture.query.count()

    client.post(f"/mosaic/{group_id}/calibration/backfill", data=data)
    with app.app_context():
        assert CalibrationCapture.query.count() == total


def test_wheel_switch_blocked_when_project_uses_filter_new_wheel_lacks(client):
    with app.app_context():
        filters = _make_filters()
        eight = _make_wheel("ZWO 8x1.25", ["L", "R", "G", "B", "S", "H", "O", "LP"], filters, active=True)
        seven = _make_wheel("Optolong 7x2", ["L", "R", "G", "B", "S", "H", "O"], filters)
        t = _make_project("LP Project", SHO_PLAN, wheel=eight)
        db.session.add(ImagingSession(target_id=t.id, date=date.today(), channel="LP",
                                      sub_exposure_seconds=300, sub_count=5, filter_wheel_id=eight.id))
        db.session.commit()
        target_id, eight_id, seven_id = t.id, eight.id, seven.id

    page = client.get(f"/target/{target_id}/filter-wheel/switch")
    assert page.status_code == 200
    assert b"LP" in page.data

    client.post(f"/target/{target_id}/filter-wheel/switch", data={"wheel_id": seven_id})
    with app.app_context():
        assert db.session.get(Target, target_id).filter_wheel_id == eight_id


def test_wheel_switch_allowed_and_remaps_sessions(client):
    with app.app_context():
        filters = _make_filters()
        eight = _make_wheel("ZWO 8x1.25", ["L", "R", "G", "B", "S", "H", "O", "LP"], filters, active=True)
        seven = _make_wheel("Optolong 7x2", ["L", "R", "G", "B", "S", "H", "O"], filters)
        t = _make_project("SHO Project", SHO_PLAN, wheel=eight)
        db.session.add(ImagingSession(target_id=t.id, date=date.today(), channel="H",
                                      sub_exposure_seconds=300, sub_count=5, filter_wheel_id=eight.id))
        db.session.commit()
        target_id, seven_id = t.id, seven.id

    resp = client.post(f"/target/{target_id}/filter-wheel/switch",
                       data={"wheel_id": seven_id, "remap_sessions": "1"})
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(Target, target_id).filter_wheel_id == seven_id
        assert {s.filter_wheel_id for s in ImagingSession.query.filter_by(target_id=target_id)} == {seven_id}


def test_wheel_switch_without_remap_keeps_session_wheel(client):
    with app.app_context():
        filters = _make_filters()
        a = _make_wheel("A", ["S", "H", "O"], filters, active=True)
        b = _make_wheel("B", ["S", "H", "O"], filters)
        t = _make_project("Keep History", SHO_PLAN, wheel=a)
        db.session.add(ImagingSession(target_id=t.id, date=date.today(), channel="H",
                                      sub_exposure_seconds=300, sub_count=5, filter_wheel_id=a.id))
        db.session.commit()
        target_id, a_id, b_id = t.id, a.id, b.id

    client.post(f"/target/{target_id}/filter-wheel/switch", data={"wheel_id": b_id})
    with app.app_context():
        assert db.session.get(Target, target_id).filter_wheel_id == b_id
        assert ImagingSession.query.filter_by(target_id=target_id).one().filter_wheel_id == a_id


def test_mosaic_wheel_switch_validates_union_of_panels(client):
    with app.app_context():
        filters = _make_filters()
        eight = _make_wheel("ZWO 8", ["L", "R", "G", "B", "S", "H", "O", "LP"], filters, active=True)
        seven = _make_wheel("Opto 7", ["L", "R", "G", "B", "S", "H", "O"], filters)
        group = MosaicGroup(name="Mixed")
        db.session.add(group)
        db.session.flush()
        p1 = _make_project("M P1", SHO_PLAN, wheel=eight, mosaic=group, panel=1)
        p2 = _make_project("M P2", SHO_PLAN, wheel=eight, mosaic=group, panel=2)
        db.session.commit()
        group_id, seven_id, eight_id, p1_id, p2_id = group.id, seven.id, eight.id, p1.id, p2.id

    client.post(f"/mosaic/{group_id}/filter-wheel/switch", data={"wheel_id": seven_id})
    with app.app_context():
        assert {db.session.get(Target, i).filter_wheel_id for i in (p1_id, p2_id)} == {seven_id}

    with app.app_context():
        db.session.add(CalibrationCapture(target_id=p2_id, date=date.today(), frame_type="flat",
                                          channel="LP", frame_count=10, checkpoint="manual"))
        db.session.commit()
    client.post(f"/mosaic/{group_id}/filter-wheel/switch", data={"wheel_id": eight_id})
    client.post(f"/mosaic/{group_id}/filter-wheel/switch", data={"wheel_id": seven_id})
    with app.app_context():
        # LP calibration on panel 2 now blocks moving the mosaic back to the 7-slot wheel
        assert {db.session.get(Target, i).filter_wheel_id for i in (p1_id, p2_id)} == {eight_id}


def test_astrobin_export_uses_session_wheel_slot_ids(client):
    with app.app_context():
        filters = _make_filters()
        zwo = _make_wheel("ZWO", ["S", "H", "O"], filters, active=True, astrobin_ids={"H": 1955})
        opto = _make_wheel("Optolong", ["S", "H", "O"], filters, astrobin_ids={"H": 7777})
        t = _make_project("Export Project", SHO_PLAN, wheel=opto)
        db.session.add(ImagingSession(target_id=t.id, date=date(2026, 6, 1), channel="H",
                                      sub_exposure_seconds=300, sub_count=5, filter_wheel_id=zwo.id))
        db.session.add(ImagingSession(target_id=t.id, date=date(2026, 6, 2), channel="H",
                                      sub_exposure_seconds=300, sub_count=5, filter_wheel_id=opto.id))
        db.session.add(ImagingSession(target_id=t.id, date=date(2026, 6, 3), channel="O",
                                      sub_exposure_seconds=300, sub_count=5, filter_wheel_id=opto.id))
        db.session.commit()
        target_id = t.id
        global_o = filters["O"].astrobin_id

    resp = client.post(f"/target/{target_id}/export_astrobin", data={"binning": "1"})
    assert resp.status_code == 200
    lines = resp.data.decode().strip().splitlines()[1:]
    by_date = {line.split(",")[0]: line.split(",")[1] for line in lines}
    assert by_date["2026-06-01"] == "1955"
    assert by_date["2026-06-02"] == "7777"
    assert by_date["2026-06-03"] == str(global_o)


def test_delete_filter_wheel_refused_when_used_by_project(client):
    with app.app_context():
        filters = _make_filters()
        _make_wheel("Active", ["H"], filters, active=True)
        used = _make_wheel("Used", ["H"], filters)
        _make_project("Uses Wheel", SHO_PLAN, wheel=used)
        db.session.commit()
        used_id = used.id

    client.post(f"/filter-wheel/{used_id}/delete")
    with app.app_context():
        assert db.session.get(FilterWheel, used_id) is not None


def test_stamp_unassigned_filter_wheels(client):
    with app.app_context():
        filters = _make_filters()
        wheel = _make_wheel("Active", ["S", "H", "O"], filters, active=True)
        t = _make_project("Legacy", SHO_PLAN)
        db.session.add(ImagingSession(target_id=t.id, date=date.today(), channel="H",
                                      sub_exposure_seconds=300, sub_count=1))
        db.session.commit()
        assert stamp_unassigned_filter_wheels() == 2
        assert db.session.get(Target, t.id).filter_wheel_id == wheel.id
        assert ImagingSession.query.one().filter_wheel_id == wheel.id
        assert stamp_unassigned_filter_wheels() == 0


def test_latest_plan_prefers_dated_plan_over_null_created_at(client):
    from datetime import datetime as dt

    with app.app_context():
        t = Target(name="Plans", ra_hours=1.0, dec_deg=1.0, preferred_palette="SHO")
        db.session.add(t)
        db.session.flush()
        dated = TargetPlan(target_id=t.id, palette_name="SHO", plan_json="{}",
                           created_at=dt(2026, 1, 1))
        db.session.add(dated)
        db.session.flush()
        undated = TargetPlan(target_id=t.id, palette_name="SHO", plan_json="{}")
        db.session.add(undated)
        db.session.flush()
        undated.created_at = None
        db.session.commit()
        assert latest_plan(t.id, "SHO").id == dated.id


def test_destructive_cleanup_drops_retired_columns_idempotently(client):
    from sqlalchemy import inspect, text

    with app.app_context():
        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE targets ADD COLUMN override_calibration_two_point BOOLEAN"))
            conn.commit()
        assert apply_destructive_schema_cleanup(log=lambda *_: None) == [
            "targets.override_calibration_two_point"
        ]
        cols = {c["name"] for c in inspect(db.engine).get_columns("targets")}
        assert "override_calibration_two_point" not in cols
        assert apply_destructive_schema_cleanup(log=lambda *_: None) == []


def test_migration_table_order_respects_foreign_keys():
    from config.migration import DatabaseMigrator, REQUIRED_TABLES

    order = DatabaseMigrator._get_table_export_order(None, db.metadata)
    assert order.index("mosaic_groups") < order.index("targets")
    assert order.index("filter_wheels") < order.index("targets")
    assert order.index("filter_wheels") < order.index("imaging_sessions")
    assert order.index("targets") < order.index("calibration_captures")
    assert set(REQUIRED_TABLES) <= set(order)


def test_v280_pages_render(client):
    with app.app_context():
        filters = _make_filters()
        wheel = _make_wheel("ZWO", ["S", "H", "O"], filters, active=True, astrobin_ids={"H": 1955})
        group = MosaicGroup(name="Render Mosaic")
        db.session.add(group)
        db.session.flush()
        t = _make_project("Render Panel", SHO_PLAN, wheel=wheel, mosaic=group, panel=1, tracking=True)
        db.session.add(ImagingSession(target_id=t.id, date=date.today(), channel="H",
                                      sub_exposure_seconds=300, sub_count=5, filter_wheel_id=wheel.id))
        db.session.commit()
        ids = {"t": t.id, "g": group.id, "w": wheel.id}

    for url in (
        f"/target/{ids['t']}",
        f"/target/{ids['t']}/settings",
        f"/target/{ids['t']}/filter-wheel/switch",
        f"/mosaic/{ids['g']}",
        f"/mosaic/{ids['g']}/log",
        f"/mosaic/{ids['g']}/calibration/backfill",
        f"/mosaic/{ids['g']}/filter-wheel/switch",
        f"/filter-wheel/{ids['w']}/edit",
    ):
        resp = client.get(url)
        assert resp.status_code == 200, url
    detail = client.get(f"/target/{ids['t']}").data
    assert b'name="log_flats"' in detail
    assert b"Switch Wheel" in detail
    assert b'name="slot_0_astrobin_id"' in client.get(f"/filter-wheel/{ids['w']}/edit").data
