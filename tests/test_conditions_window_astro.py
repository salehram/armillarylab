"""Regression tests for `_aggregate_window_astro` nearest-neighbor fallback.

7Timer publishes seeing/transparency on a 3-hour UTC grid. Short imaging
windows (heavy packup-time clipping) can land entirely between two grid
points and produce zero hits, which previously caused the Night Conditions
panel to silently drop the entire "Seeing (imaging window)" block.

v2.4.2 falls back to the single 7Timer point closest to the window midpoint
when no points fall strictly inside the window.
"""

from conditions_utils import _aggregate_window_astro


def _fake_7timer(init="2026052512"):
    """Mimic a real 7Timer payload: 3-hour grid, timepoints 3..24."""
    return {
        "init": init,
        "dataseries": [
            {"timepoint": tp, "seeing": 3, "transparency": 2}
            for tp in range(3, 25, 3)
        ],
    }


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
    # Window 21:06 -> 22:30 UTC: the 21:00 point is 6 min before the window
    # and the 00:00 point is 90 min after — both *outside*. Without the
    # fallback this would return None and the UI would drop the block.
    data = _fake_7timer()
    result = _aggregate_window_astro(
        data, "2026-05-25 21:06:00", "2026-05-25 22:30:00"
    )
    assert result is not None
    assert result["points"] == 1
    assert result["nearest_fallback"] is True
    # Closest point to midpoint 21:48 UTC is the 21:00 grid point.
    assert result["seeing_avg"] is not None


def test_window_astro_returns_none_when_dataseries_empty():
    result = _aggregate_window_astro(
        {"init": "2026052512", "dataseries": []},
        "2026-05-25 21:06:00",
        "2026-05-25 22:30:00",
    )
    assert result is None
