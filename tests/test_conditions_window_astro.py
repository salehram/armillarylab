"""Regression tests for `_aggregate_window_astro` nearest-neighbor fallback.

7Timer publishes seeing/transparency on a 3-hour UTC grid. Short imaging
windows (heavy packup-time clipping) can land entirely between two grid
points and produce zero hits, which previously caused the Night Conditions
panel to silently drop the entire "Seeing (imaging window)" block.

v2.4.2 added the fallback for the right-now Overview tab. v2.4.4 extracts
it into `_collect_seeing_points_for_window` and reuses it from
`compute_forecast_days` so the 5-day Forecast tab no longer silently drops
the seeing column for short imaging windows. The helper also caps the
fallback distance to ~1.6 h so nights beyond 7Timer's ~72 h horizon
correctly remain empty.
"""

import datetime

from conditions_utils import (
    _aggregate_window_astro,
    _collect_seeing_points_for_window,
    compute_forecast_days,
)


def _fake_7timer(init="2026052512"):
    """Mimic a real 7Timer payload: 3-hour grid, timepoints 3..24."""
    return {
        "init": init,
        "dataseries": [
            {"timepoint": tp, "seeing": 3, "transparency": 2}
            for tp in range(3, 25, 3)
        ],
    }


def _fake_openmeteo_5d():
    """Mimic Open-Meteo hourly payload covering 5 days from 2026-05-25 12:00."""
    base = datetime.datetime(2026, 5, 25, 12, 0)
    times = [(base + datetime.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M")
             for h in range(0, 24 * 6)]
    n = len(times)
    return {
        "hourly": {
            "time": times,
            "cloud_cover": [0] * n,
            "wind_speed_10m": [5] * n,
            "wind_gusts_10m": [10] * n,
            "temperature_2m": [25] * n,
        }
    }


# ---------------------------------------------------------------------------
# _aggregate_window_astro (Overview tab "Imaging Window Seeing")
# ---------------------------------------------------------------------------

def test_window_astro_returns_data_when_points_fall_inside():
    # Window 17:30 -> 23:30 UTC includes the 18, 21 UTC points.
    data = _fake_7timer()
    result = _aggregate_window_astro(
        data, "2026-05-25 17:30:00", "2026-05-25 23:30:00"
    )
    assert result is not None
    assert result["points"] == 2
    assert result["nearest_fallback"] is False


def test_window_astro_falls_back_to_nearest_when_window_misses_grid():
    # Window 21:06 -> 22:30 UTC: 21:00 point is 6 min before window, 00:00
    # is 90 min after -- both outside. Midpoint 21:48 UTC, nearest 21:00
    # point sits 48 min away (within the 1.6 h fallback cap).
    data = _fake_7timer()
    result = _aggregate_window_astro(
        data, "2026-05-25 21:06:00", "2026-05-25 22:30:00"
    )
    assert result is not None
    assert result["points"] == 1
    assert result["nearest_fallback"] is True
    assert result["seeing_avg"] is not None


def test_window_astro_returns_none_when_dataseries_empty():
    result = _aggregate_window_astro(
        {"init": "2026052512", "dataseries": []},
        "2026-05-25 21:06:00",
        "2026-05-25 22:30:00",
    )
    assert result is None


# ---------------------------------------------------------------------------
# _collect_seeing_points_for_window (shared helper)
# ---------------------------------------------------------------------------

def test_collect_helper_returns_empty_when_nearest_point_outside_fallback_cap():
    # Series ends at timepoint 24 (2026-05-26 12:00 UTC). A window 4 days
    # later is 96 h past the last point -- well beyond the 1.6 h cap. Helper
    # must return empty so days 4-5 in the forecast legitimately show "--".
    data = _fake_7timer()
    init = datetime.datetime(2026, 5, 25, 12, 0, tzinfo=datetime.timezone.utc)
    ws = datetime.datetime(2026, 5, 30, 21, 0, tzinfo=datetime.timezone.utc)
    we = datetime.datetime(2026, 5, 30, 22, 30, tzinfo=datetime.timezone.utc)
    pts, used_fallback = _collect_seeing_points_for_window(
        data["dataseries"], init, ws, we
    )
    assert pts == []
    assert used_fallback is False


# ---------------------------------------------------------------------------
# compute_forecast_days (5-day Forecast tab Seeing column)
# ---------------------------------------------------------------------------

def test_forecast_seeing_populated_for_short_window_within_7timer_horizon(monkeypatch):
    # Freeze "today" to 2026-05-25 so the forecast computes for May 26-30.
    fixed_today = datetime.datetime(2026, 5, 25, 18, 0, tzinfo=datetime.timezone.utc)

    real_datetime = datetime.datetime

    class FrozenDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_today.astimezone(tz) if tz else fixed_today.replace(tzinfo=None)

    monkeypatch.setattr("conditions_utils.datetime.datetime", FrozenDateTime)

    weather_raw = _fake_openmeteo_5d()
    # Build a 7Timer payload that extends ~5 days so day 4-5 still have
    # points (so we can isolate just the "short-window misses grid" case).
    astro_raw = {
        "init": "2026052512",
        "dataseries": [
            {"timepoint": tp, "seeing": 3, "transparency": 2}
            for tp in range(3, 24 * 5 + 1, 3)
        ],
    }

    # C 33-style short window: 21:06 -> 22:30 LOCAL (Asia/Riyadh = UTC+3),
    # so in UTC the slot is 18:06 -> 19:30. 7Timer grid points 18:00 and
    # 21:00 UTC are both outside this slot -- without the fallback every
    # forecast night would show "--".
    days = compute_forecast_days(
        weather_raw, astro_raw,
        window_start_local="2026-05-25 21:06:00",
        window_end_local="2026-05-25 22:30:00",
        tz_name="Asia/Riyadh",
        max_cloud_pct=25,
        n_days=3,
    )
    assert days is not None
    assert len(days) >= 1
    # At least the first night (within 7Timer horizon) must now have seeing.
    assert days[0]["seeing_available"] is True
    assert days[0]["seeing_avg"] is not None
