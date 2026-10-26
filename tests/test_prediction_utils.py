"""Unit tests for the plan duration prediction engine (synthetic grids, no network)."""

from datetime import date, timedelta

import numpy as np
import pytest

import prediction_utils as pu


START = date(2026, 1, 1)


def make_grid(n_nights=30, n_slots=12, slot=10, ok=None, moon_alt=-10.0, illum=0.0, sep=180.0):
    shape = (n_nights, n_slots)
    epochs = (1.7e9 + np.arange(n_nights)[:, None] * 86400.0
              + np.arange(n_slots)[None, :] * slot * 60.0)
    return {
        "night_dates": [START + timedelta(days=i) for i in range(n_nights)],
        "slot_minutes": slot,
        "epochs": epochs,
        "ok": np.ones(shape, dtype=bool) if ok is None else ok,
        "target_alt": np.full(shape, 60.0),
        "moon_alt": np.full(shape, moon_alt) if np.isscalar(moon_alt) else moon_alt,
        "moon_sep": np.full(shape, sep),
        "moon_illum_pct": np.full(n_nights, illum),
    }


def ch(name, minutes, code=None, key=None):
    return {"key": key or name, "name": name, "label": name, "filter_code": code or name, "minutes": minutes}


LIMITS = {"H": (100, 25.0), "O": (50, 35.0), "L": (25, 40.0)}


def run(panels, scenario="baseline", mpn=None, eff=100, **kw):
    return pu.simulate(panels, scenario, mpn, eff, LIMITS, **kw)


def test_baseline_full_window_cap_and_efficiency():
    grid = make_grid()
    panel = [{"name": "T", "grid": grid, "channels": [ch("H", 600)]}]

    r = run(panel)
    assert r["completed"] and r["imaging_nights"] == 5 and r["calendar_nights"] == 5
    assert r["finish_date"] == (START + timedelta(days=4)).isoformat()
    assert r["avg_session_minutes"] == 120

    r = run([{"name": "T", "grid": make_grid(), "channels": [ch("H", 600)]}], mpn=60)
    assert r["imaging_nights"] == 10 and r["max_session_minutes"] == 60

    r = run([{"name": "T", "grid": make_grid(), "channels": [ch("H", 600)]}], eff=50)
    assert r["imaging_nights"] == 10
    assert r["avg_minutes_per_imaging_night"] == 60


def test_nothing_to_schedule():
    r = run([{"name": "T", "grid": make_grid(), "channels": [ch("H", 0)]}])
    assert r["completed"] and r["imaging_nights"] == 0 and r["completion_pct"] == 100.0


def test_moon_blocks_broadband_but_not_ha():
    grid = make_grid(n_nights=10, moon_alt=30.0, illum=100.0, sep=90.0)
    panels = [{"name": "T", "grid": grid, "channels": [ch("H", 120), ch("L", 120)]}]

    assert run(panels, "baseline")["completed"]
    r = run([{"name": "T", "grid": grid, "channels": [ch("H", 120), ch("L", 120)]}], "moon")
    assert not r["completed"]
    by_name = {c["name"]: c for c in r["channels"]}
    assert by_name["H"]["remaining_minutes"] == 0
    assert by_name["L"]["remaining_minutes"] == 120
    assert r["nights_lost_moon"] > 0


def test_moon_separation_limit():
    grid = make_grid(n_nights=3, moon_alt=30.0, illum=10.0, sep=20.0)
    r = run([{"name": "T", "grid": grid, "channels": [ch("L", 60)]}], "moon")
    assert not r["completed"]
    grid = make_grid(n_nights=3, moon_alt=30.0, illum=10.0, sep=60.0)
    assert run([{"name": "T", "grid": grid, "channels": [ch("L", 60)]}], "moon")["completed"]


def test_dark_slots_go_to_most_moon_sensitive_filter():
    moon_alt = np.full((5, 12), -5.0)
    moon_alt[:, :6] = 40.0
    grid = make_grid(n_nights=5, moon_alt=moon_alt, illum=90.0)
    r = run([{"name": "T", "grid": grid, "channels": [ch("H", 60), ch("O", 60)]}], "moon")
    assert r["imaging_nights"] == 1
    assert r["nights"][0]["by_channel"] == {"H": 60.0, "O": 60.0}


def test_forecast_weather_mask_skips_night():
    grid = make_grid(n_nights=10)
    weather = {
        "ok": np.ones((10, 12), dtype=bool),
        "covered": np.ones((10, 12), dtype=bool),
        "seeing_covered": np.zeros((10, 12), dtype=bool),
    }
    weather["ok"][0] = False
    weather["ok"][1, :6] = False
    r = run([{"name": "T", "grid": grid, "channels": [ch("H", 240)]}], "weather", weather=weather)
    assert [n["status"] for n in r["nights"][:2]] == ["weather", "imaged"]
    assert r["nights"][1]["session_minutes"] == 60
    assert r["calendar_nights"] == 4 and r["nights_lost_weather"] == 1


def test_climatology_credit_is_deterministic():
    grid = make_grid(n_nights=40)
    weather = {"ok": np.ones((40, 12), bool), "covered": np.zeros((40, 12), bool),
               "seeing_covered": np.zeros((40, 12), bool)}
    panels = lambda: [{"name": "T", "grid": grid, "channels": [ch("H", 600)]}]
    r = run(panels(), "weather", weather=weather, climatology_p={1: 0.5})
    assert r["imaging_nights"] == 5 and r["calendar_nights"] == 10
    assert r == run(panels(), "weather", weather=weather, climatology_p={1: 0.5})

    r = run(panels(), "weather", weather=weather, climatology_p={}, default_usable_pct=25)
    assert r["imaging_nights"] == 5 and r["calendar_nights"] == 20


def test_out_of_season_nights_and_horizon():
    ok = np.zeros((10, 12), dtype=bool)
    ok[5:] = True
    r = run([{"name": "T", "grid": make_grid(n_nights=10, ok=ok), "channels": [ch("H", 120)]}])
    assert r["nights_without_window"] == 5 and r["calendar_nights"] == 6

    r = run([{"name": "T", "grid": make_grid(n_nights=3), "channels": [ch("H", 1000)]}])
    assert not r["completed"] and r["finish_date"] is None
    assert r["scheduled_minutes"] == 360 and r["completion_pct"] == 36.0


def test_now_epoch_excludes_past_slots():
    grid = make_grid(n_nights=3)
    now = grid["epochs"][0, 6]
    r = run([{"name": "T", "grid": grid, "channels": [ch("H", 120)]}], now_epoch=now)
    assert r["nights"][0]["session_minutes"] == 60


def test_mosaic_panels_completed_in_order_with_shared_budget():
    panels = [
        {"name": "P1", "grid": make_grid(), "channels": [ch("H", 120, key="P1 H")]},
        {"name": "P2", "grid": make_grid(), "channels": [ch("H", 120, key="P2 H")]},
    ]
    r = run(panels)
    assert r["nights"][0]["by_channel"] == {"P1 H": 120.0}
    assert r["nights"][1]["by_channel"] == {"P2 H": 120.0}
    finish = {c["key"]: c["finish_date"] for c in r["channels"]}
    assert finish == {"P1 H": "2026-01-01", "P2 H": "2026-01-02"}


def test_build_weather_mask_from_forecast_payloads():
    slot = 10
    base = 1767225600.0  # 2026-01-01T00:00Z
    epochs = base + np.arange(2)[:, None] * 86400.0 + np.arange(12)[None, :] * slot * 60.0
    bundle = {
        "weather_raw": {
            "utc_offset_seconds": 0,
            "hourly": {
                "time": ["2026-01-01T00:00", "2026-01-01T01:00"],
                "cloud_cover": [10, 90],
                "wind_gusts_10m": [20, 20],
            },
        },
        "astro_raw": {"init": "2026010100", "dataseries": [{"timepoint": 0, "seeing": 8}]},
    }
    mask = pu.build_weather_mask(epochs, slot, bundle, max_cloud_pct=25, max_gust_kmh=35, max_seeing_raw=6)
    assert mask["covered"][0].all() and not mask["covered"][1].any()
    assert mask["seeing_covered"][0, :9].all() and not mask["seeing_covered"][0, 9:].any()
    # Hour 0 is clear but seeing 8 is too poor; hour 1 is cloudy.
    assert not mask["ok"][0].any()
    assert mask["ok"][1].all()


def test_climatology_reduce_and_monthly_probability():
    times, clouds, gusts = [], [], []
    for day in range(1, 5):
        for hour in (20, 21, 22, 23):
            times.append(f"2025-01-{day:02d}T{hour:02d}:00")
            clouds.append(0 if day % 2 else 100)
            gusts.append(10)
        for hour in (0, 1, 2, 3):
            times.append(f"2025-01-{day + 1:02d}T{hour:02d}:00")
            clouds.append(0 if day % 2 else 100)
            gusts.append(10)
    clim = pu.reduce_climatology({"hourly": {"time": times, "cloud_cover": clouds, "wind_gusts_10m": gusts}})
    assert len(clim["nights"]["2025-01-01"]) == 8
    probs = pu.monthly_usable_probability(clim, max_cloud_pct=25, max_gust_kmh=35)
    assert probs[1] == 0.5


def test_default_moon_limits():
    assert pu.default_moon_limits("H") == (100, 25.0)
    assert pu.default_moon_limits("R") == (25, 40.0)
    assert pu.default_moon_limits("X", "broadband") == (25, 40.0)
    assert pu.default_moon_limits("X") == (50, 35.0)


def test_altitude_helper_pole_and_sidereal_range():
    lat = np.radians(24.7)
    assert pu.altitude_deg(lat, 1.234, 0.0, np.radians(90.0)) == pytest.approx(24.7)
    lst = pu.local_sidereal_rad(np.array([0.0, 1.7e9]), 46.7)
    assert ((lst >= 0) & (lst < 2 * np.pi)).all()


@pytest.mark.skipif(not pu.astro_deps_available(), reason="astropy/astroplan not installed")
@pytest.mark.parametrize("lat, lon, tz, ra, dec, min_alt, packup", [
    (24.7136, 46.6753, "Asia/Riyadh", 20.82225, 31.99, 30.0, (2, 0)),   # Cygnus Loop, pack-up bound
    (24.7136, 46.6753, "Asia/Riyadh", 0.712, 41.27, 30.0, None),         # M31, full night
    (24.7136, 46.6753, "Asia/Riyadh", 17.76, -29.0, 20.0, (1, 30)),      # low southern target
    (51.5, -0.12, "Europe/London", 5.59, -5.39, 25.0, None),             # M42 from a high latitude
])
def test_engine_windows_match_astroplan_reference(lat, lon, tz, ra, dec, min_alt, packup):
    import datetime

    start = date(2026, 10, 1)
    pack = datetime.time(*packup) if packup else None
    report = pu.validate_target_windows(lat, lon, 100.0, tz, ra, dec, min_alt, pack, start,
                                        n_nights=200, every=40)
    assert report["max_abs_diff_minutes"] <= 3, report["nights"]
    assert report["moon"]["max_alt_err_deg"] < 0.2
    assert report["moon"]["max_sep_err_deg"] < 0.2
    assert report["moon"]["max_illum_err_pct"] < 5


def test_fractional_slots_count_partial_minutes():
    grid = make_grid(n_nights=3)
    grid["frac"] = np.full((3, 12), 0.5)
    r = run([{"name": "T", "grid": grid, "channels": [ch("H", 120)]}])
    assert r["nights"][0]["window_minutes"] == 60
    assert r["nights"][0]["session_minutes"] == 60
    assert r["imaging_nights"] == 2


def test_cap_in_wall_minutes_and_leftover_slot_goes_to_next_filter():
    grid = make_grid(n_nights=3)
    r = run([{"name": "T", "grid": grid, "channels": [ch("H", 5), ch("O", 100)]}], mpn=25)
    first = r["nights"][0]
    assert first["session_minutes"] == 25
    assert first["by_channel"] == {"O": 20.0, "H": 5.0}


def test_simulation_invariants_hold_and_detect_tampering():
    moon_alt = np.full((20, 12), -5.0)
    moon_alt[::2, :4] = 40.0
    grid = make_grid(n_nights=20, moon_alt=moon_alt, illum=80.0)
    grid["frac"] = np.where(np.arange(12) % 3 == 0, 0.4, 1.0)[None, :].repeat(20, axis=0)
    weather = {"ok": np.ones((20, 12), bool), "covered": np.zeros((20, 12), bool),
               "seeing_covered": np.zeros((20, 12), bool)}
    weather["covered"][:5] = True
    weather["ok"][1] = False
    for scenario in pu.SCENARIOS:
        panels = [{"name": "T", "grid": grid, "channels": [ch("H", 300), ch("O", 200), ch("L", 150)]}]
        r = run(panels, scenario, mpn=90, eff=85, weather=weather, climatology_p={1: 0.6})
        assert pu.check_simulation_invariants(r, 90, 85) == [], scenario

    r["nights"][0]["session_minutes"] = 500
    r["imaging_nights"] += 1
    problems = pu.check_simulation_invariants(r, 90, 85)
    assert any("exceeds window" in p for p in problems)
    assert any("imaging_nights" in p for p in problems)
