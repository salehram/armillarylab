"""
Night-conditions helper: moon phase, weather (Open-Meteo), astronomical
seeing (7Timer), and weighted channel-suggestion logic.

Three-tier fallback:
  1. Online  – fetch live data, cache 5-day forecast
  2. Cached  – serve from local JSON cache when offline
  3. Offline – compute moon phase via astroplan (no weather)
  4. (last)  – return an "offline / no data" status message
"""

from __future__ import annotations

import datetime
import json
import math
import os
import urllib.request
import urllib.error
from pathlib import Path
from zoneinfo import ZoneInfo

CACHE_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / "cache" / "conditions"
CACHE_MAX_AGE_HOURS = 6

# ---------------------------------------------------------------------------
# Moon suitability weights at *full* moon (illumination = 100%).
# At new moon every channel scores 1.0; values are linearly interpolated.
# ---------------------------------------------------------------------------
MOON_WEIGHT_FULL: dict[str, float] = {
    "H":  1.0,   # Ha — strongest NB, tolerates full moon
    "S":  0.7,   # SII — mid-strength NB
    "O":  0.3,   # OIII — weakest NB, most moon-sensitive
    "L":  0.2,   # Luminance — broadband
    "R":  0.2,
    "G":  0.2,
    "B":  0.2,
}

# 7Timer seeing scale → arcsec label + quality label
_SEEING_MAP = {
    1: ("<0.5\"",   "Excellent"),
    2: ("0.5-0.75\"", "Excellent"),
    3: ("0.75-1\"",  "Good"),
    4: ("1-1.25\"",  "Good"),
    5: ("1.25-1.5\"", "Average"),
    6: ("1.5-2\"",   "Below Average"),
    7: ("2-2.5\"",   "Poor"),
    8: (">2.5\"",    "Poor"),
}

_TRANSPARENCY_MAP = {
    1: "Excellent",
    2: "Above Average",
    3: "Average",
    4: "Below Average",
    5: "Below Average",
    6: "Poor",
    7: "Very Poor",
    8: "Very Poor",
}

# ---------------------------------------------------------------------------
# 1. Moon info  (fully offline via astroplan)
# ---------------------------------------------------------------------------

def compute_moon_info(tz_name: str = "Asia/Riyadh") -> dict | None:
    """Return moon phase, illumination %, phase name, and next full moon."""
    try:
        from astroplan import moon_illumination, moon_phase_angle
        from astropy.time import Time
    except ImportError:
        return None

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = datetime.timezone(datetime.timedelta(hours=3))

    now = Time(datetime.datetime.now(datetime.timezone.utc))
    illum = float(moon_illumination(now))
    import astropy.units as u
    phase_angle = float(moon_phase_angle(now).to(u.rad).value)

    phase_name, emoji = _phase_name(illum, phase_angle)

    next_full, days_to_full = _find_next_full_moon(now)

    now_local = datetime.datetime.now(datetime.timezone.utc).astimezone(tz)

    return {
        "phase_name": phase_name,
        "illumination_pct": round(illum * 100, 1),
        "emoji": emoji,
        "next_full_moon": next_full,
        "days_to_full": days_to_full,
        "as_of": now_local.strftime("%Y-%m-%d %H:%M"),
    }


def _phase_name(illum: float, phase_angle_rad: float) -> tuple[str, str]:
    """Derive human-readable phase name + emoji from illumination and phase angle."""
    waxing = phase_angle_rad < math.pi

    if illum < 0.02:
        return "New Moon", "\U0001F311"
    elif illum < 0.35:
        return ("Waxing Crescent", "\U0001F312") if waxing else ("Waning Crescent", "\U0001F318")
    elif illum < 0.65:
        return ("First Quarter", "\U0001F313") if waxing else ("Last Quarter", "\U0001F317")
    elif illum < 0.97:
        return ("Waxing Gibbous", "\U0001F314") if waxing else ("Waning Gibbous", "\U0001F316")
    else:
        return "Full Moon", "\U0001F315"


def _find_next_full_moon(now_time) -> tuple[str, int]:
    """Scan forward up to 30 days to find the next full-moon peak."""
    from astroplan import moon_illumination
    from astropy.time import Time, TimeDelta
    import astropy.units as u

    best_illum = 0.0
    best_day = 0
    prev_illum = float(moon_illumination(now_time))
    passed_peak = False

    for day_offset in range(1, 31):
        t = now_time + TimeDelta(day_offset * u.day)
        illum = float(moon_illumination(t))
        if illum >= best_illum:
            best_illum = illum
            best_day = day_offset
        if illum < prev_illum and prev_illum > 0.97:
            passed_peak = True
        if passed_peak and illum > prev_illum and best_illum > 0.97:
            break
        prev_illum = illum

    full_dt = (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(days=best_day)
    )
    return full_dt.strftime("%Y-%m-%d"), best_day


# ---------------------------------------------------------------------------
# 2. Open-Meteo  (weather: temp, humidity, clouds, wind)
# ---------------------------------------------------------------------------

def fetch_openmeteo(lat: float, lon: float) -> dict | None:
    """Fetch 5-day hourly forecast from Open-Meteo (no API key)."""
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&hourly=temperature_2m,relative_humidity_2m,cloud_cover,"
        f"wind_speed_10m,wind_gusts_10m"
        f"&forecast_days=5&timezone=auto"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ArmillaryLab/2.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return data
    except Exception:
        return None


def _pick_current_hour(hourly: dict, tz_name: str = "Asia/Riyadh") -> dict | None:
    """Extract the row closest to the current local hour from Open-Meteo hourly data.

    Open-Meteo returns times in the local timezone (we pass timezone=auto),
    so we must compare against local time, not UTC.
    """
    times = hourly.get("time", [])
    if not times:
        return None

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = datetime.timezone(datetime.timedelta(hours=3))
    now_str = datetime.datetime.now(tz).strftime("%Y-%m-%dT%H:00")

    idx = None
    for i, t in enumerate(times):
        if t <= now_str:
            idx = i
        else:
            break
    if idx is None:
        idx = 0

    return {
        "temperature_c": hourly["temperature_2m"][idx],
        "humidity_pct": hourly["relative_humidity_2m"][idx],
        "cloud_cover_pct": hourly["cloud_cover"][idx],
        "wind_speed_kmh": hourly["wind_speed_10m"][idx],
        "wind_gusts_kmh": hourly["wind_gusts_10m"][idx],
    }


def _aggregate_window_hours(
    hourly: dict,
    window_start: str,
    window_end: str,
) -> dict | None:
    """Aggregate weather over the imaging window (start_time_local..end_time_local).

    window_start / window_end are "YYYY-MM-DD HH:MM:SS" strings in local time
    (matching the Open-Meteo timezone=auto output).
    """
    times = hourly.get("time", [])
    if not times or not window_start or not window_end:
        return None

    ws = window_start[:13].replace(" ", "T")  # "YYYY-MM-DDTHH"
    we = window_end[:13].replace(" ", "T")

    indices = [i for i, t in enumerate(times) if ws <= t <= we]
    if not indices:
        return None

    def _avg(key: str) -> float:
        vals = [hourly[key][i] for i in indices if hourly[key][i] is not None]
        return round(sum(vals) / len(vals), 1) if vals else 0

    def _max(key: str) -> float:
        vals = [hourly[key][i] for i in indices if hourly[key][i] is not None]
        return round(max(vals), 1) if vals else 0

    def _min(key: str) -> float:
        vals = [hourly[key][i] for i in indices if hourly[key][i] is not None]
        return round(min(vals), 1) if vals else 0

    return {
        "temp_min_c": _min("temperature_2m"),
        "temp_max_c": _max("temperature_2m"),
        "humidity_avg_pct": _avg("relative_humidity_2m"),
        "cloud_cover_avg_pct": _avg("cloud_cover"),
        "cloud_cover_max_pct": _max("cloud_cover"),
        "wind_avg_kmh": _avg("wind_speed_10m"),
        "wind_max_kmh": _max("wind_speed_10m"),
        "gusts_max_kmh": _max("wind_gusts_10m"),
        "hours": len(indices),
    }


# ---------------------------------------------------------------------------
# 3. 7Timer  (seeing, transparency)
# ---------------------------------------------------------------------------

def fetch_7timer(lat: float, lon: float) -> dict | None:
    """Fetch astronomical forecast from 7Timer (no API key)."""
    url = (
        f"http://www.7timer.info/bin/api.pl"
        f"?lon={lon}&lat={lat}&product=astro&output=json"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ArmillaryLab/2.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return data
    except Exception:
        return None


def _pick_current_astro(data: dict) -> dict | None:
    """Pick the 7Timer datapoint closest to now."""
    series = data.get("dataseries", [])
    if not series:
        return None

    init_str = data.get("init", "")
    if len(init_str) < 10:
        return series[0] if series else None

    init_dt = datetime.datetime.strptime(init_str, "%Y%m%d%H").replace(
        tzinfo=datetime.timezone.utc
    )
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    best = series[0]
    best_diff = float("inf")
    for point in series:
        tp_dt = init_dt + datetime.timedelta(hours=point["timepoint"])
        diff = abs((tp_dt - now_utc).total_seconds())
        if diff < best_diff:
            best_diff = diff
            best = point

    seeing_val = best.get("seeing", 5)
    transp_val = best.get("transparency", 3)
    arcsec, quality = _SEEING_MAP.get(seeing_val, ("?", "Unknown"))

    return {
        "seeing_arcsec": arcsec,
        "seeing_label": quality,
        "seeing_raw": seeing_val,
        "transparency_label": _TRANSPARENCY_MAP.get(transp_val, "Unknown"),
        "transparency_raw": transp_val,
        "cloud_cover_7t": best.get("cloudcover", None),
        "temp_2m_7t": best.get("temp2m", None),
        "wind_direction": best.get("wind10m", {}).get("direction", ""),
    }


def _aggregate_window_astro(
    data: dict,
    window_start_utc: str,
    window_end_utc: str,
) -> dict | None:
    """Aggregate 7Timer seeing/transparency over the imaging window.

    window_start_utc / window_end_utc are "YYYY-MM-DD HH:MM:SS" UTC strings.
    7Timer timepoints are hours-offset from init (UTC).
    """
    series = data.get("dataseries", [])
    init_str = data.get("init", "")
    if not series or len(init_str) < 10 or not window_start_utc or not window_end_utc:
        return None

    init_dt = datetime.datetime.strptime(init_str, "%Y%m%d%H").replace(
        tzinfo=datetime.timezone.utc
    )

    try:
        ws = datetime.datetime.strptime(window_start_utc[:19], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=datetime.timezone.utc
        )
        we = datetime.datetime.strptime(window_end_utc[:19], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=datetime.timezone.utc
        )
    except (ValueError, TypeError):
        return None

    window_points = []
    for point in series:
        tp_dt = init_dt + datetime.timedelta(hours=point["timepoint"])
        if ws <= tp_dt <= we:
            window_points.append(point)

    if not window_points:
        return None

    seeing_vals = [p.get("seeing", 5) for p in window_points]
    transp_vals = [p.get("transparency", 3) for p in window_points]
    avg_seeing = round(sum(seeing_vals) / len(seeing_vals))
    worst_seeing = max(seeing_vals)
    avg_transp = round(sum(transp_vals) / len(transp_vals))

    avg_arc, avg_lbl = _SEEING_MAP.get(avg_seeing, ("?", "Unknown"))
    worst_arc, worst_lbl = _SEEING_MAP.get(worst_seeing, ("?", "Unknown"))

    return {
        "seeing_avg": avg_arc,
        "seeing_avg_label": avg_lbl,
        "seeing_worst": worst_arc,
        "seeing_worst_label": worst_lbl,
        "transparency_avg_label": _TRANSPARENCY_MAP.get(avg_transp, "Unknown"),
        "points": len(window_points),
    }


# ---------------------------------------------------------------------------
# 4. Channel suggestion  (weighted scoring)
# ---------------------------------------------------------------------------

def suggest_tonight_channel(
    plan_data: dict | None,
    moon_illumination_pct: float,
    progress_by_channel: dict[str, float] | None,
) -> dict | None:
    """Score each plan channel and suggest the best one for tonight.

    score = moon_suitability_weight(channel, illumination) * remaining_ratio
    """
    if not plan_data or "channels" not in plan_data:
        return None

    channels = plan_data["channels"]
    if not channels:
        return None

    progress = progress_by_channel or {}
    illum_frac = moon_illumination_pct / 100.0  # 0..1

    scored: list[tuple[float, str, str, float, float]] = []
    for ch in channels:
        name = ch.get("name", "")
        planned = ch.get("planned_minutes", 0)
        if planned <= 0:
            continue

        captured = progress.get(name, 0.0)
        remaining_ratio = max((planned - captured) / planned, 0.0)

        weight_at_full = MOON_WEIGHT_FULL.get(name, 0.5)
        moon_weight = 1.0 - illum_frac * (1.0 - weight_at_full)

        score = moon_weight * remaining_ratio
        scored.append((score, name, ch.get("label", name), moon_weight, remaining_ratio))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_name, best_label, best_mw, best_rr = scored[0]

    remaining_pct = round(best_rr * 100)
    moon_note = f"moon tolerance {round(best_mw * 100)}%"
    reason = (
        f"{best_label} scores highest: {moon_note} at "
        f"{round(moon_illumination_pct)}% illumination"
        f" + {remaining_pct}% of planned subs remaining"
    )

    return {
        "channel": best_name,
        "channel_label": best_label,
        "score": round(best_score, 3),
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# 5. Cache management
# ---------------------------------------------------------------------------

def _cache_path(lat: float, lon: float) -> Path:
    lat_r = round(lat, 2)
    lon_r = round(lon, 2)
    return CACHE_DIR / f"conditions_{lat_r}_{lon_r}.json"


def _write_cache(lat: float, lon: float, payload: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload["_cached_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        _cache_path(lat, lon).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass


def _read_cache(lat: float, lon: float) -> dict | None:
    p = _cache_path(lat, lon)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

    cached_at_str = data.get("_cached_at")
    if not cached_at_str:
        return None

    cached_at = datetime.datetime.fromisoformat(cached_at_str)
    age = datetime.datetime.now(datetime.timezone.utc) - cached_at
    if age > datetime.timedelta(hours=CACHE_MAX_AGE_HOURS * 20):
        return None

    data["_age_hours"] = round(age.total_seconds() / 3600, 1)
    return data


# ---------------------------------------------------------------------------
# 6. Orchestrator
# ---------------------------------------------------------------------------

def get_tonight_conditions(
    lat: float,
    lon: float,
    elev: float,
    tz_name: str,
    plan_data: dict | None = None,
    progress_by_channel: dict[str, float] | None = None,
    window_start_local: str | None = None,
    window_end_local: str | None = None,
    window_start_utc: str | None = None,
    window_end_utc: str | None = None,
) -> dict:
    """Main entry point. Returns a dict ready for JSON serialization."""

    moon = compute_moon_info(tz_name)

    weather_raw = fetch_openmeteo(lat, lon)
    astro_raw = fetch_7timer(lat, lon)
    online = weather_raw is not None or astro_raw is not None

    weather = None
    astro = None
    window_weather = None
    window_astro = None

    if online:
        if weather_raw and "hourly" in weather_raw:
            weather = _pick_current_hour(weather_raw["hourly"], tz_name)
            if window_start_local and window_end_local:
                window_weather = _aggregate_window_hours(
                    weather_raw["hourly"], window_start_local, window_end_local
                )
        if astro_raw:
            astro = _pick_current_astro(astro_raw)
            if window_start_utc and window_end_utc:
                window_astro = _aggregate_window_astro(
                    astro_raw, window_start_utc, window_end_utc
                )

        cache_payload = {
            "weather_raw": weather_raw,
            "astro_raw": astro_raw,
        }
        _write_cache(lat, lon, cache_payload)
        status = "online"
    else:
        cached = _read_cache(lat, lon)
        if cached:
            cw = cached.get("weather_raw")
            if cw and "hourly" in cw:
                weather = _pick_current_hour(cw["hourly"], tz_name)
                if window_start_local and window_end_local:
                    window_weather = _aggregate_window_hours(
                        cw["hourly"], window_start_local, window_end_local
                    )
            ca = cached.get("astro_raw")
            if ca:
                astro = _pick_current_astro(ca)
                if window_start_utc and window_end_utc:
                    window_astro = _aggregate_window_astro(
                        ca, window_start_utc, window_end_utc
                    )
            status = "cached"
        elif moon:
            status = "offline_moon"
        else:
            status = "offline"

    moon_illum = moon["illumination_pct"] if moon else 50.0
    suggestion = suggest_tonight_channel(plan_data, moon_illum, progress_by_channel)

    message = None
    if status == "offline":
        message = "You are offline and no cached data is available. Connect to the internet to retrieve conditions."
    elif status == "offline_moon":
        message = "You are offline. Showing moon data only (computed locally). Weather and seeing require an internet connection."
    elif status == "cached":
        message = "Showing cached data (you appear to be offline)."

    return {
        "status": status,
        "location": {"lat": round(lat, 4), "lon": round(lon, 4)},
        "moon": moon,
        "weather": weather,
        "astro": astro,
        "window_weather": window_weather,
        "window_astro": window_astro,
        "suggestion": suggestion,
        "message": message,
    }
