"""
Plan duration prediction.

Two layers:
  1. Slot grids (expensive, cached in-process): every night is split into
     fixed slots; each slot records darkness, target altitude/pack-up validity,
     moon altitude, moon-target separation, plus per-night moon illumination.
  2. Simulator (cheap, deterministic): allocates per-filter integration into
     usable slots night by night for four scenarios
     (baseline / moon / weather / combined).

Weather: Open-Meteo hourly forecast (16 d) + 7Timer seeing (~72 h); after the
forecast horizon a monthly usable-night probability from the Open-Meteo
historical archive is used, falling back to a configured percentage.
"""

from __future__ import annotations

import datetime
import json
import time as _time
import urllib.request
from zoneinfo import ZoneInfo

import numpy as np

import conditions_utils
from conditions_utils import CACHE_DIR

SLOT_MINUTES = 10
# Sub-samples per slot for darkness/altitude/pack-up, so partial slots count fractionally.
SLOT_SUBSAMPLES = 5
HORIZON_NIGHTS = 365
NIGHT_START_HOUR = 15
NIGHT_SPAN_HOURS = 18
# Nautical darkness, same rule as compute_target_window().
DARK_SUN_ALT_DEG = -12.0

GRID_TTL_SECONDS = 6 * 3600
FORECAST_DAYS = 16
FORECAST_TTL_SECONDS = 3600
FORECAST_FILE_MAX_AGE_HOURS = 72
SEEING_MAX_DISTANCE_HOURS = 1.5

CLIMATOLOGY_YEARS = 3
CLIMATOLOGY_MAX_AGE_DAYS = 30
CLIMATOLOGY_EVENING_HOURS = (20, 21, 22, 23)
CLIMATOLOGY_MORNING_HOURS = (0, 1, 2, 3)
CLIMATOLOGY_USABLE_HOUR_FRACTION = 0.7

SCENARIOS = ("baseline", "moon", "weather", "combined")

_EPS = 1e-6

# (max moon illumination %, min moon separation deg)
_MOON_LIMITS_BY_CODE = {
    "H": (100, 25.0),
    "S": (75, 25.0),
    "O": (50, 35.0),
}
_MOON_LIMITS_BY_TYPE = {
    "narrowband": (75, 25.0),
    "broadband": (25, 40.0),
    "other": (50, 35.0),
}
_BROADBAND_CODES = {"L", "R", "G", "B"}

_sky_cache: dict = {}
_target_cache: dict = {}
_forecast_cache: dict = {}


def astro_deps_available() -> bool:
    try:
        import astropy  # noqa: F401
        import astroplan  # noqa: F401
    except ImportError:
        return False
    return True


def default_moon_limits(code: str, filter_type: str | None = None) -> tuple[int, float]:
    if code in _MOON_LIMITS_BY_CODE:
        return _MOON_LIMITS_BY_CODE[code]
    if filter_type in _MOON_LIMITS_BY_TYPE:
        return _MOON_LIMITS_BY_TYPE[filter_type]
    if code in _BROADBAND_CODES:
        return _MOON_LIMITS_BY_TYPE["broadband"]
    return _MOON_LIMITS_BY_TYPE["other"]


def _tz(tz_name: str):
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return datetime.timezone(datetime.timedelta(hours=3))


def current_night_date(tz_name: str, now: datetime.datetime | None = None) -> datetime.date:
    """Evening date of the night in progress (before local noon it is still last night)."""
    local = (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(_tz(tz_name))
    if local.hour < 12:
        return local.date() - datetime.timedelta(days=1)
    return local.date()


def _cache_get(cache: dict, key, ttl: float):
    hit = cache.get(key)
    if hit and _time.monotonic() - hit[1] < ttl:
        return hit[0]
    return None


def _cache_put(cache: dict, key, value):
    if len(cache) > 64:
        cache.clear()
    cache[key] = (value, _time.monotonic())


# ---------------------------------------------------------------------------
# 1. Slot grids
# ---------------------------------------------------------------------------

def build_sky_grid(
    lat: float,
    lon: float,
    elev: float,
    tz_name: str,
    start_date: datetime.date,
    n_nights: int = HORIZON_NIGHTS,
    slot_minutes: int = SLOT_MINUTES,
) -> dict:
    """Sun/moon state for every slot of every night (target independent)."""
    key = (round(lat, 4), round(lon, 4), round(elev, -1), tz_name,
           start_date.isoformat(), n_nights, slot_minutes)
    cached = _cache_get(_sky_cache, key, GRID_TTL_SECONDS)
    if cached is not None:
        return cached

    import astropy.units as u
    from astropy.coordinates import EarthLocation, get_body, get_sun
    from astropy.time import Time
    from astroplan import moon_illumination

    tz = _tz(tz_name)
    slot_sec = slot_minutes * 60
    n_slots = int(NIGHT_SPAN_HOURS * 60 // slot_minutes)
    night_dates = [start_date + datetime.timedelta(days=i) for i in range(n_nights)]
    night_starts = np.array([
        datetime.datetime.combine(d, datetime.time(NIGHT_START_HOUR), tzinfo=tz).timestamp()
        for d in night_dates
    ])
    epochs = night_starts[:, None] + np.arange(n_slots)[None, :] * slot_sec
    mid = epochs + slot_sec / 2
    sub_times = epochs[..., None] + (np.arange(SLOT_SUBSAMPLES) + 0.5) * slot_sec / SLOT_SUBSAMPLES

    # Ephemerides are sampled every 2 h and interpolated; per-slot get_body is too slow.
    sample_step = 2 * 3600
    n_samples = int(NIGHT_SPAN_HOURS * 3600 // sample_step) + 2
    sample_ep = night_starts[:, None] + np.arange(n_samples)[None, :] * sample_step
    t_samples = Time(sample_ep.ravel(), format="unix")
    location = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=elev * u.m)
    sun = get_sun(t_samples)
    moon = get_body("moon", t_samples, location)
    precess = precession_matrix(start_date)

    def _interp_radec(coord, times):
        ra = np.radians(coord.ra.deg).reshape(sample_ep.shape)
        dec = np.radians(coord.dec.deg).reshape(sample_ep.shape)
        xyz = _unit_vectors(ra, dec) @ precess.T
        lead = (len(night_dates),) + (1,) * (times.ndim - 1)
        frac = (times - night_starts.reshape(lead)) / sample_step
        i0 = np.clip(np.floor(frac).astype(int), 0, n_samples - 2)
        w = (frac - i0)[..., None]
        rows = np.arange(len(night_dates)).reshape(lead)
        v = xyz[rows, i0] * (1 - w) + xyz[rows, i0 + 1] * w
        v /= np.linalg.norm(v, axis=-1, keepdims=True)
        return np.arctan2(v[..., 1], v[..., 0]), np.arcsin(np.clip(v[..., 2], -1, 1))

    lat_rad = np.radians(lat)
    sun_ra, sun_dec = _interp_radec(sun, sub_times)
    lst_sub = local_sidereal_rad(sub_times, lon)
    dark_sub = altitude_deg(lat_rad, lst_sub, sun_ra, sun_dec) < DARK_SUN_ALT_DEG
    moon_ra, moon_dec = _interp_radec(moon, mid)
    moon_alt = altitude_deg(lat_rad, local_sidereal_rad(mid, lon), moon_ra, moon_dec)

    local_midnights = night_starts + (24 - NIGHT_START_HOUR) * 3600
    illum = np.asarray(moon_illumination(Time(local_midnights, format="unix")), dtype=float) * 100.0

    sky = {
        "key": key,
        "tz_name": tz_name,
        "lat": lat,
        "night_dates": night_dates,
        "slot_minutes": slot_minutes,
        "epochs": epochs,
        "sub_times": sub_times,
        "lst_sub": lst_sub,
        "dark_sub": dark_sub,
        "precession": precess,
        "moon_alt": moon_alt,
        "moon_ra": moon_ra,
        "moon_dec": moon_dec,
        "moon_illum_pct": illum,
    }
    _cache_put(_sky_cache, key, sky)
    return sky


def _unit_vectors(ra_rad, dec_rad):
    return np.stack([np.cos(dec_rad) * np.cos(ra_rad), np.cos(dec_rad) * np.sin(ra_rad), np.sin(dec_rad)], axis=-1)


def precession_matrix(on_date: datetime.date):
    """GCRS/J2000 -> mean equator/equinox of ``on_date`` (GMST hour angles need RA of date)."""
    import erfa
    from astropy.time import Time

    tt = Time(on_date.isoformat()).tt
    return np.asarray(erfa.pmat06(tt.jd1, tt.jd2))


def local_sidereal_rad(unix_seconds, lon_deg: float):
    """Local mean sidereal time in radians (IAU 1982 GMST approximation)."""
    d = np.asarray(unix_seconds) / 86400.0 + 2440587.5 - 2451545.0
    gmst_h = 18.697374558 + 24.06570982441908 * d
    return np.radians((gmst_h * 15.0 + lon_deg) % 360.0)


def altitude_deg(lat_rad: float, lst_rad, ra_rad, dec_rad):
    """Geometric altitude (no refraction) from hour angle."""
    sin_alt = (np.sin(lat_rad) * np.sin(dec_rad)
               + np.cos(lat_rad) * np.cos(dec_rad) * np.cos(lst_rad - ra_rad))
    return np.degrees(np.arcsin(np.clip(sin_alt, -1.0, 1.0)))


def build_target_grid(
    sky: dict,
    ra_hours: float,
    dec_deg: float,
    min_alt_deg: float,
    packup_time: datetime.time | None,
) -> dict:
    """Usable fraction of each slot (dark + altitude + pack-up) and moon separation for one target."""
    key = (sky["key"], round(ra_hours, 4), round(dec_deg, 4),
           round(float(min_alt_deg), 1), str(packup_time))
    cached = _cache_get(_target_cache, key, GRID_TTL_SECONDS)
    if cached is not None:
        return cached

    v = _unit_vectors(np.radians(ra_hours * 15.0), np.radians(dec_deg)) @ sky["precession"].T
    ra = float(np.arctan2(v[1], v[0]))
    dec = float(np.arcsin(np.clip(v[2], -1.0, 1.0)))
    alt_sub = altitude_deg(np.radians(sky["lat"]), sky["lst_sub"], ra, dec)
    cos_sep = (np.sin(dec) * np.sin(sky["moon_dec"])
               + np.cos(dec) * np.cos(sky["moon_dec"]) * np.cos(ra - sky["moon_ra"]))
    sep = np.degrees(np.arccos(np.clip(cos_sep, -1.0, 1.0)))
    usable_sub = sky["dark_sub"] & (alt_sub >= float(min_alt_deg))

    if packup_time is not None:
        tz = _tz(sky["tz_name"])
        sub_times = sky["sub_times"]
        half_sub = sky["slot_minutes"] * 30 / SLOT_SUBSAMPLES
        for n, night_date in enumerate(sky["night_dates"]):
            dark_idx = np.flatnonzero(sky["dark_sub"][n].ravel())
            if not dark_idx.size:
                continue
            dark_start = sub_times[n].ravel()[dark_idx[0]] - half_sub
            pack = datetime.datetime.combine(night_date, packup_time, tzinfo=tz)
            if pack.timestamp() <= dark_start:
                pack = datetime.datetime.combine(
                    night_date + datetime.timedelta(days=1), packup_time, tzinfo=tz
                )
            usable_sub[n] &= (sub_times[n] + half_sub) <= pack.timestamp()

    frac = usable_sub.mean(axis=-1)
    grid = {
        "night_dates": sky["night_dates"],
        "slot_minutes": sky["slot_minutes"],
        "epochs": sky["epochs"],
        "sub_times": sky["sub_times"],
        "usable_sub": usable_sub,
        "frac": frac,
        "ok": frac > 0,
        "target_alt": alt_sub[..., SLOT_SUBSAMPLES // 2],
        "moon_alt": sky["moon_alt"],
        "moon_sep": sep,
        "moon_illum_pct": sky["moon_illum_pct"],
    }
    _cache_put(_target_cache, key, grid)
    return grid


def night_window(grid: dict, n: int, tz_name: str) -> dict:
    """Usable minutes and first/last usable time for night ``n`` of a target grid."""
    tz = _tz(tz_name)
    slot_min = grid["slot_minutes"]
    minutes = float(_frac(grid)[n].sum() * slot_min)
    out = {"date": grid["night_dates"][n].isoformat(), "window_minutes": int(round(minutes)),
           "start_local": None, "end_local": None}
    usable = grid.get("usable_sub")
    if usable is None or not usable[n].any():
        return out
    times = grid["sub_times"][n].ravel()[usable[n].ravel()]
    half_sub = slot_min * 30 / SLOT_SUBSAMPLES
    out["start_local"] = datetime.datetime.fromtimestamp(times[0] - half_sub, tz).strftime("%Y-%m-%d %H:%M")
    out["end_local"] = datetime.datetime.fromtimestamp(times[-1] + half_sub, tz).strftime("%Y-%m-%d %H:%M")
    return out


def tonight_summary(grid: dict, tz_name: str) -> dict:
    """First night's usable window derived from the grid."""
    night = night_window(grid, 0, tz_name)
    night["moon_illum_pct"] = round(float(grid["moon_illum_pct"][0]), 1)
    return night


def compute_rise_set(
    ra_hours: float,
    dec_deg: float,
    lat: float,
    lon: float,
    elev: float,
    tz_name: str,
    min_alt_deg: float,
) -> dict:
    """Next rise/set at the horizon and at the minimum altitude, plus transit (local strings)."""
    import astropy.units as u
    from astropy.coordinates import EarthLocation, SkyCoord
    from astropy.time import Time
    from astroplan import Observer

    tz = _tz(tz_name)
    observer = Observer(location=EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=elev * u.m))
    coord = SkyCoord(ra=ra_hours * u.hourangle, dec=dec_deg * u.deg)
    now = Time(datetime.datetime.now(datetime.timezone.utc))

    def _fmt(fn, **kwargs):
        try:
            t = fn(now, coord, which="next", **kwargs)
            if getattr(t, "masked", False):
                return None
            dt = t.to_datetime(timezone=datetime.timezone.utc)
            if not hasattr(dt, "astimezone"):
                return None
            return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return None

    return {
        "rise_local": _fmt(observer.target_rise_time, horizon=0 * u.deg),
        "set_local": _fmt(observer.target_set_time, horizon=0 * u.deg),
        "rise_min_alt_local": _fmt(observer.target_rise_time, horizon=float(min_alt_deg) * u.deg),
        "set_min_alt_local": _fmt(observer.target_set_time, horizon=float(min_alt_deg) * u.deg),
        "transit_local": _fmt(observer.target_meridian_transit_time),
        "min_alt_deg": float(min_alt_deg),
    }


# ---------------------------------------------------------------------------
# 2. Weather: forecast masks + climatology
# ---------------------------------------------------------------------------

def _forecast_cache_path(lat: float, lon: float):
    return CACHE_DIR / f"prediction_forecast_{round(lat, 2)}_{round(lon, 2)}.json"


def get_forecast_bundle(lat: float, lon: float) -> dict:
    """16-day Open-Meteo + 7Timer data; memory TTL, file fallback when offline."""
    key = (round(lat, 2), round(lon, 2))
    cached = _cache_get(_forecast_cache, key, FORECAST_TTL_SECONDS)
    if cached is not None:
        return cached

    weather_raw = conditions_utils.fetch_openmeteo(lat, lon, forecast_days=FORECAST_DAYS)
    astro_raw = conditions_utils.fetch_7timer(lat, lon)
    path = _forecast_cache_path(lat, lon)
    if weather_raw or astro_raw:
        bundle = {"weather_raw": weather_raw, "astro_raw": astro_raw, "source": "online"}
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            payload = dict(bundle, _cached_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
            path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            pass
    else:
        bundle = {"weather_raw": None, "astro_raw": None, "source": "none"}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            age = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(data["_cached_at"])
            if age <= datetime.timedelta(hours=FORECAST_FILE_MAX_AGE_HOURS):
                bundle = {"weather_raw": data.get("weather_raw"), "astro_raw": data.get("astro_raw"),
                          "source": "cache"}
        except (OSError, ValueError, KeyError, TypeError):
            pass
    _cache_put(_forecast_cache, key, bundle)
    return bundle


def _num(v):
    return np.nan if v is None else float(v)


def build_weather_mask(
    epochs: np.ndarray,
    slot_minutes: int,
    bundle: dict | None,
    max_cloud_pct: float,
    max_gust_kmh: float,
    max_seeing_raw: int,
) -> dict:
    """Per-slot weather verdicts where a forecast exists.

    ``covered`` marks slots with an Open-Meteo hour; ``ok`` is False only for
    covered slots failing cloud/gust, or slots with 7Timer seeing worse than
    the limit. Slots without data stay ok (handled by climatology per night).
    """
    shape = epochs.shape
    ok = np.ones(shape, dtype=bool)
    covered = np.zeros(shape, dtype=bool)
    seeing_covered = np.zeros(shape, dtype=bool)
    mid = epochs + slot_minutes * 30
    bundle = bundle or {}

    weather_raw = bundle.get("weather_raw") or {}
    hourly = weather_raw.get("hourly") or {}
    times = hourly.get("time") or []
    if times:
        offset = int(weather_raw.get("utc_offset_seconds") or 0)
        hour_ep = np.array([
            datetime.datetime.strptime(t[:16], "%Y-%m-%dT%H:%M")
            .replace(tzinfo=datetime.timezone.utc).timestamp() - offset
            for t in times
        ])
        cloud = np.array([_num(v) for v in hourly.get("cloud_cover") or [None] * len(times)])
        gust = np.array([_num(v) for v in hourly.get("wind_gusts_10m") or [None] * len(times)])
        order = np.argsort(hour_ep)
        hour_ep, cloud, gust = hour_ep[order], cloud[order], gust[order]
        slot_hour = np.floor(mid / 3600.0) * 3600.0
        pos = np.clip(np.searchsorted(hour_ep, slot_hour), 0, len(hour_ep) - 1)
        hit = hour_ep[pos] == slot_hour
        covered |= hit
        with np.errstate(invalid="ignore"):
            bad = (cloud[pos] > max_cloud_pct) | (gust[pos] > max_gust_kmh)
        ok &= ~(hit & bad)

    astro_raw = bundle.get("astro_raw") or {}
    series = astro_raw.get("dataseries") or []
    init_str = str(astro_raw.get("init") or "")
    if series and len(init_str) >= 10:
        try:
            init_ep = datetime.datetime.strptime(init_str[:10], "%Y%m%d%H").replace(
                tzinfo=datetime.timezone.utc).timestamp()
        except ValueError:
            init_ep = None
        if init_ep is not None:
            pt_ep = np.array([init_ep + p.get("timepoint", 0) * 3600 for p in series], dtype=float)
            seeing = np.array([_num(p.get("seeing")) for p in series])
            order = np.argsort(pt_ep)
            pt_ep, seeing = pt_ep[order], seeing[order]
            right = np.clip(np.searchsorted(pt_ep, mid), 0, len(pt_ep) - 1)
            left = np.clip(right - 1, 0, len(pt_ep) - 1)
            use_left = np.abs(mid - pt_ep[left]) < np.abs(mid - pt_ep[right])
            nearest = np.where(use_left, left, right)
            near = np.abs(mid - pt_ep[nearest]) <= SEEING_MAX_DISTANCE_HOURS * 3600
            seeing_covered |= near
            with np.errstate(invalid="ignore"):
                ok &= ~(near & (seeing[nearest] > max_seeing_raw))

    return {"ok": ok, "covered": covered, "seeing_covered": seeing_covered}


def _climatology_path(lat: float, lon: float):
    return CACHE_DIR / f"climatology_{round(lat, 2)}_{round(lon, 2)}.json"


def _fetch_climatology(lat: float, lon: float, today: datetime.date) -> dict | None:
    start = datetime.date(today.year - CLIMATOLOGY_YEARS, 1, 1)
    end = datetime.date(today.year - 1, 12, 31)
    url = (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={start.isoformat()}&end_date={end.isoformat()}"
        "&hourly=cloud_cover,wind_gusts_10m&timezone=auto"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ArmillaryLab/2.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return None
    return reduce_climatology(data)


def reduce_climatology(archive: dict) -> dict | None:
    """Compact per-night [cloud, gust] hour lists keyed by evening date."""
    hourly = (archive or {}).get("hourly") or {}
    times = hourly.get("time") or []
    clouds = hourly.get("cloud_cover") or []
    gusts = hourly.get("wind_gusts_10m") or []
    nights: dict[str, list] = {}
    for i, t in enumerate(times):
        try:
            hour = int(t[11:13])
            day = datetime.date.fromisoformat(t[:10])
        except (ValueError, TypeError):
            continue
        if hour in CLIMATOLOGY_EVENING_HOURS:
            night = day
        elif hour in CLIMATOLOGY_MORNING_HOURS:
            night = day - datetime.timedelta(days=1)
        else:
            continue
        c = clouds[i] if i < len(clouds) else None
        g = gusts[i] if i < len(gusts) else None
        if c is None and g is None:
            continue
        nights.setdefault(night.isoformat(), []).append([c, g])
    return {"nights": nights} if nights else None


def get_climatology(lat: float, lon: float, today: datetime.date) -> tuple[dict | None, str | None]:
    """Return (climatology, source) where source is 'archive', 'stale_cache' or None."""
    path = _climatology_path(lat, lon)
    cached = None
    fresh = False
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        age = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(cached["_cached_at"])
        fresh = age <= datetime.timedelta(days=CLIMATOLOGY_MAX_AGE_DAYS)
    except (OSError, ValueError, KeyError, TypeError):
        cached = None
    if cached and fresh:
        return cached, "archive"

    data = _fetch_climatology(lat, lon, today)
    if data:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            data["_cached_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            path.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass
        return data, "archive"
    if cached:
        return cached, "stale_cache"
    return None, None


def monthly_usable_probability(
    climatology: dict | None,
    max_cloud_pct: float,
    max_gust_kmh: float,
) -> dict[int, float]:
    """Fraction of nights per month where enough core-night hours pass cloud/gust limits."""
    totals: dict[int, int] = {}
    usable: dict[int, int] = {}
    for night, hours in ((climatology or {}).get("nights") or {}).items():
        try:
            month = int(night[5:7])
        except (ValueError, TypeError):
            continue
        valid = [h for h in hours if h and len(h) >= 2]
        if not valid:
            continue
        good = sum(
            1 for c, g in valid
            if (c is None or c <= max_cloud_pct) and (g is None or g <= max_gust_kmh)
        )
        totals[month] = totals.get(month, 0) + 1
        if good / len(valid) >= CLIMATOLOGY_USABLE_HOUR_FRACTION:
            usable[month] = usable.get(month, 0) + 1
    return {m: round(usable.get(m, 0) / n, 3) for m, n in totals.items() if n}


# ---------------------------------------------------------------------------
# 3. Simulator
# ---------------------------------------------------------------------------

def _frac(grid: dict) -> np.ndarray:
    frac = grid.get("frac")
    return frac if frac is not None else grid["ok"].astype(float)


def _moon_ok(grid: dict, n: int, j: int, limits: tuple[int, float]) -> bool:
    alt = grid["moon_alt"][n, j]
    if np.isnan(alt) or alt < 0:
        return True
    max_illum, min_sep = limits
    if grid["moon_illum_pct"][n] > max_illum:
        return False
    sep = grid["moon_sep"][n, j]
    return np.isnan(sep) or sep >= min_sep


def simulate(
    panels: list[dict],
    scenario: str,
    minutes_per_night: float | None,
    efficiency_pct: float,
    filter_limits: dict[str, tuple[int, float]],
    weather: dict | None = None,
    climatology_p: dict[int, float] | None = None,
    default_usable_pct: float = 50.0,
    now_epoch: float | None = None,
) -> dict:
    """Allocate integration night by night.

    ``panels``: ordered list of {"name", "grid", "channels": [{"key", "name",
    "label", "filter_code", "minutes"}]}. Panels are completed in order and
    share one nightly budget. ``minutes_per_night`` caps wall-clock imaging
    time; integration per slot is slot length x efficiency.
    """
    use_moon = scenario in ("moon", "combined")
    use_weather = scenario in ("weather", "combined") and weather is not None
    first_grid = panels[0]["grid"]
    night_dates = first_grid["night_dates"]
    slot_min = first_grid["slot_minutes"]
    slot_sec = slot_min * 60
    n_slots = first_grid["epochs"].shape[1]
    eff = max(min(efficiency_pct, 100.0), 1.0) / 100.0
    cap = float(minutes_per_night) if minutes_per_night else None

    jobs = []
    for pi, panel in enumerate(panels):
        for ch in panel["channels"]:
            minutes = max(float(ch.get("minutes") or 0.0), 0.0)
            code = ch.get("filter_code") or ch["name"]
            jobs.append({
                "panel_index": pi,
                "panel": panel.get("name"),
                "key": ch.get("key") or ch["name"],
                "name": ch["name"],
                "label": ch.get("label") or ch["name"],
                "filter_code": code,
                "minutes": round(minutes, 1),
                "remaining": minutes,
                "limits": filter_limits.get(code) or default_moon_limits(code),
                "nights_used": 0,
                "finish_date": None,
            })
    total_needed = sum(j["remaining"] for j in jobs)
    panel_jobs = [[j for j in jobs if j["panel_index"] == pi] for pi in range(len(panels))]

    credit = 0.0
    nights = []
    finish_index = None
    lost_weather = lost_moon = no_window = 0
    pi = 0

    def _panel_done(idx):
        return all(j["remaining"] <= _EPS for j in panel_jobs[idx])

    if total_needed <= _EPS:
        finish_index = -1

    for n, night_date in enumerate(night_dates):
        if finish_index is not None:
            break
        while pi < len(panels) and _panel_done(pi):
            pi += 1
        if pi >= len(panels):
            break
        grid = panels[pi]["grid"]
        frac_n = _frac(grid)[n].copy()
        if now_epoch is not None:
            frac_n[(grid["epochs"][n] + slot_sec) <= now_epoch] = 0.0
        valid = frac_n > 0
        window_minutes = int(round(frac_n.sum() * slot_min))
        rec = {"date": night_date.isoformat(), "window_minutes": window_minutes,
               "session_minutes": 0, "minutes": 0.0, "status": "", "by_channel": {}}
        if window_minutes == 0:
            no_window += 1
            rec["status"] = "no_window"
            nights.append(rec)
            continue

        forecast_night = use_weather and bool(weather["covered"][n][valid].any())
        if use_weather and not forecast_night:
            p = (climatology_p or {}).get(night_date.month)
            if p is None:
                p = default_usable_pct / 100.0
            credit += p
            if credit < 1.0 - _EPS:
                lost_weather += 1
                rec["status"] = "weather"
                nights.append(rec)
                continue
            credit -= 1.0

        used = 0.0
        weather_blocked = moon_blocked = 0
        for j in range(n_slots):
            if cap is not None and used >= cap - _EPS:
                break
            while pi < len(panels) and _panel_done(pi):
                pi += 1
            if pi >= len(panels):
                break
            grid = panels[pi]["grid"]
            slot_frac = _frac(grid)[n, j]
            if slot_frac <= 0:
                continue
            if now_epoch is not None and grid["epochs"][n, j] + slot_sec <= now_epoch:
                continue
            if forecast_night and not weather["ok"][n, j]:
                weather_blocked += 1
                continue
            wall = slot_frac * slot_min
            if cap is not None:
                wall = min(wall, cap - used)
            capacity = wall * eff
            spent = 0.0
            while capacity - spent > _EPS:
                candidates = [
                    job for job in panel_jobs[pi]
                    if job["remaining"] > _EPS and (not use_moon or _moon_ok(grid, n, j, job["limits"]))
                ]
                if not candidates:
                    break
                job = min(candidates, key=lambda c: (
                    c["limits"][0] if use_moon else 0,
                    -(c["remaining"] / c["minutes"]) if c["minutes"] else 0,
                ))
                take = min(capacity - spent, job["remaining"])
                job["remaining"] -= take
                spent += take
                rec["minutes"] += take
                rec["by_channel"][job["key"]] = rec["by_channel"].get(job["key"], 0.0) + take
                if job["remaining"] <= _EPS:
                    job["remaining"] = 0.0
                    job["finish_date"] = night_date.isoformat()
            if spent <= _EPS:
                moon_blocked += 1
                continue
            used += wall * spent / capacity

        rec["session_minutes"] = int(round(used))
        rec["minutes"] = round(rec["minutes"], 1)
        rec["by_channel"] = {k: round(v, 1) for k, v in rec["by_channel"].items()}
        for key in rec["by_channel"]:
            for job in jobs:
                if job["key"] == key:
                    job["nights_used"] += 1
        if used > _EPS:
            rec["status"] = "imaged"
        elif moon_blocked and moon_blocked >= weather_blocked:
            rec["status"] = "moon"
            lost_moon += 1
        elif weather_blocked:
            rec["status"] = "weather"
            lost_weather += 1
        else:
            rec["status"] = "idle"
        nights.append(rec)
        if all(job["remaining"] <= _EPS for job in jobs):
            finish_index = n

    remaining = sum(j["remaining"] for j in jobs)
    completed = remaining <= _EPS
    imaged = [r for r in nights if r["status"] == "imaged"]
    scheduled = total_needed - remaining
    result = {
        "scenario": scenario,
        "completed": completed,
        "start_date": night_dates[0].isoformat() if night_dates else None,
        "finish_date": night_dates[finish_index].isoformat() if completed and finish_index is not None and finish_index >= 0 else None,
        "imaging_nights": len(imaged),
        "calendar_nights": (finish_index + 1) if completed and finish_index is not None else len(nights),
        "total_minutes": round(total_needed, 1),
        "scheduled_minutes": round(scheduled, 1),
        "remaining_minutes": round(remaining, 1),
        "completion_pct": round(100.0 * scheduled / total_needed, 1) if total_needed > _EPS else 100.0,
        "avg_minutes_per_imaging_night": round(sum(r["minutes"] for r in imaged) / len(imaged), 1) if imaged else 0.0,
        "avg_session_minutes": round(sum(r["session_minutes"] for r in imaged) / len(imaged), 1) if imaged else 0.0,
        "max_session_minutes": max((r["session_minutes"] for r in imaged), default=0),
        "nights_without_window": no_window,
        "nights_lost_weather": lost_weather,
        "nights_lost_moon": lost_moon,
        "channels": [
            {
                "panel": j["panel"],
                "key": j["key"],
                "name": j["name"],
                "label": j["label"],
                "filter_code": j["filter_code"],
                "minutes": j["minutes"],
                "remaining_minutes": round(j["remaining"], 1),
                "finish_date": j["finish_date"],
                "nights_used": j["nights_used"],
            }
            for j in jobs
        ],
        "nights": nights,
    }
    return result


# ---------------------------------------------------------------------------
# 4. Orchestrator
# ---------------------------------------------------------------------------

def run_prediction(
    panels: list[dict],
    *,
    lat: float,
    lon: float,
    elev: float,
    tz_name: str,
    minutes_per_night: float | None,
    efficiency_pct: float,
    filter_limits: dict[str, tuple[int, float]],
    max_cloud_pct: float,
    max_gust_kmh: float,
    max_seeing_raw: int,
    default_usable_pct: float,
    now: datetime.datetime | None = None,
) -> dict:
    """Build grids for each panel and run all four scenarios.

    ``panels``: ordered list of {"name", "ra_hours", "dec_deg", "min_alt_deg",
    "packup_time", "channels": [...]} (see ``simulate``).
    """
    if not astro_deps_available():
        return {"deps_available": False, "note": "Astropy/astroplan not installed."}

    now = now or datetime.datetime.now(datetime.timezone.utc)
    start_date = current_night_date(tz_name, now)
    sky = build_sky_grid(lat, lon, elev, tz_name, start_date)
    sim_panels = []
    for p in panels:
        grid = build_target_grid(sky, p["ra_hours"], p["dec_deg"], p["min_alt_deg"], p.get("packup_time"))
        sim_panels.append({"name": p.get("name"), "grid": grid, "channels": p["channels"]})

    bundle = get_forecast_bundle(lat, lon)
    weather = build_weather_mask(sky["epochs"], sky["slot_minutes"], bundle,
                                 max_cloud_pct, max_gust_kmh, max_seeing_raw)
    climatology, clim_source = get_climatology(lat, lon, start_date)
    clim_p = monthly_usable_probability(climatology, max_cloud_pct, max_gust_kmh) if climatology else {}

    now_epoch = now.timestamp()
    scenarios = {
        s: simulate(sim_panels, s, minutes_per_night, efficiency_pct, filter_limits,
                    weather=weather, climatology_p=clim_p,
                    default_usable_pct=default_usable_pct, now_epoch=now_epoch)
        for s in SCENARIOS
    }

    def _last_covered(mask):
        rows = np.flatnonzero(mask.any(axis=1))
        return sky["night_dates"][rows[-1]].isoformat() if rows.size else None

    return {
        "deps_available": True,
        "start_date": start_date.isoformat(),
        "slot_minutes": sky["slot_minutes"],
        "horizon_nights": len(sky["night_dates"]),
        "tonight": [tonight_summary(p["grid"], tz_name) for p in sim_panels],
        "sources": {
            "forecast": bundle.get("source"),
            "forecast_until": _last_covered(weather["covered"]),
            "seeing_until": _last_covered(weather["seeing_covered"]),
            "climatology": "archive" if clim_source == "archive" and clim_p else (
                "stale_cache" if clim_source == "stale_cache" and clim_p else "default"),
            "climatology_monthly_pct": {str(m): round(p * 100) for m, p in sorted(clim_p.items())},
            "default_usable_night_pct": default_usable_pct,
        },
        "scenarios": scenarios,
    }


# ---------------------------------------------------------------------------
# 5. Validation against an independent astroplan reference
# ---------------------------------------------------------------------------

def reference_night_window(
    lat: float,
    lon: float,
    elev: float,
    tz_name: str,
    night_date: datetime.date,
    ra_hours: float,
    dec_deg: float,
    min_alt_deg: float,
    packup_time: datetime.time | None,
    step_seconds: int = 30,
) -> dict:
    """Usable window for one night using astroplan twilight events and full AltAz transforms."""
    import astropy.units as u
    from astropy.coordinates import EarthLocation, SkyCoord
    from astropy.time import Time
    from astroplan import Observer

    tz = _tz(tz_name)
    observer = Observer(location=EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=elev * u.m))
    coord = SkyCoord(ra=ra_hours * u.hourangle, dec=dec_deg * u.deg)
    noon = Time(datetime.datetime.combine(night_date, datetime.time(12), tzinfo=tz))
    out = {"date": night_date.isoformat(), "window_minutes": 0, "start_local": None, "end_local": None}
    try:
        dark_start = observer.twilight_evening_nautical(noon, which="next").to_datetime(datetime.timezone.utc)
        dark_end = observer.twilight_morning_nautical(noon, which="next").to_datetime(datetime.timezone.utc)
    except (ValueError, TypeError, AttributeError):
        return out
    end = dark_end
    if packup_time is not None:
        pack = datetime.datetime.combine(night_date, packup_time, tzinfo=tz)
        if pack <= dark_start:
            pack = datetime.datetime.combine(night_date + datetime.timedelta(days=1), packup_time, tzinfo=tz)
        end = min(end, pack)
    if end <= dark_start:
        return out
    ts = np.arange(dark_start.timestamp(), end.timestamp(), step_seconds) + step_seconds / 2
    alt = observer.altaz(Time(ts, format="unix"), coord).alt.deg
    ok = ts[alt >= min_alt_deg]
    if not ok.size:
        return out
    half = step_seconds / 2
    out["window_minutes"] = int(round(ok.size * step_seconds / 60))
    out["start_local"] = datetime.datetime.fromtimestamp(ok[0] - half, tz).strftime("%Y-%m-%d %H:%M")
    out["end_local"] = datetime.datetime.fromtimestamp(ok[-1] + half, tz).strftime("%Y-%m-%d %H:%M")
    return out


def validate_target_windows(
    lat: float,
    lon: float,
    elev: float,
    tz_name: str,
    ra_hours: float,
    dec_deg: float,
    min_alt_deg: float,
    packup_time: datetime.time | None,
    start_date: datetime.date,
    n_nights: int = 60,
    every: int = 3,
) -> dict:
    """Compare engine windows and moon geometry with the astroplan reference on sampled nights."""
    import astropy.units as u
    from astropy.coordinates import EarthLocation, SkyCoord
    from astropy.time import Time
    from astroplan import Observer, moon_illumination

    sky = build_sky_grid(lat, lon, elev, tz_name, start_date, n_nights=n_nights)
    grid = build_target_grid(sky, ra_hours, dec_deg, min_alt_deg, packup_time)
    rows = []
    for n in range(0, n_nights, max(1, every)):
        eng = night_window(grid, n, tz_name)
        ref = reference_night_window(lat, lon, elev, tz_name, sky["night_dates"][n],
                                     ra_hours, dec_deg, min_alt_deg, packup_time)
        rows.append({
            "date": eng["date"],
            "engine_minutes": eng["window_minutes"],
            "reference_minutes": ref["window_minutes"],
            "diff_minutes": eng["window_minutes"] - ref["window_minutes"],
            "engine_span": (eng["start_local"], eng["end_local"]),
            "reference_span": (ref["start_local"], ref["end_local"]),
        })

    # Moon: compare a few slot midpoints per sampled night with full astropy positions.
    observer = Observer(location=EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=elev * u.m))
    coord = SkyCoord(ra=ra_hours * u.hourangle, dec=dec_deg * u.deg)
    idx = [(n, j) for n in range(0, n_nights, max(1, every))
           for j in np.flatnonzero(sky["dark_sub"][n].all(axis=-1))[::6]]
    moon = {"samples": len(idx), "max_alt_err_deg": None, "max_sep_err_deg": None, "max_illum_err_pct": None}
    if idx:
        ns, js = np.array(idx).T
        t = Time(sky["epochs"][ns, js] + sky["slot_minutes"] * 30, format="unix")
        moon_altaz = observer.moon_altaz(t)
        tgt_altaz = observer.altaz(t, coord)
        moon["max_alt_err_deg"] = round(float(np.max(np.abs(moon_altaz.alt.deg - grid["moon_alt"][ns, js]))), 2)
        moon["max_sep_err_deg"] = round(float(np.max(np.abs(
            moon_altaz.separation(tgt_altaz).deg - grid["moon_sep"][ns, js]))), 2)
        moon["max_illum_err_pct"] = round(float(np.max(np.abs(
            np.asarray(moon_illumination(t)) * 100 - grid["moon_illum_pct"][ns]))), 1)

    diffs = [abs(r["diff_minutes"]) for r in rows]
    return {
        "nights": rows,
        "max_abs_diff_minutes": max(diffs) if diffs else 0,
        "mean_abs_diff_minutes": round(sum(diffs) / len(diffs), 1) if diffs else 0.0,
        "moon": moon,
    }


def check_simulation_invariants(
    result: dict,
    minutes_per_night: float | None,
    efficiency_pct: float,
) -> list[str]:
    """Bookkeeping checks that must hold for any scenario; returns human-readable violations."""
    problems = []
    eff = max(min(efficiency_pct, 100.0), 1.0) / 100.0
    per_channel: dict[str, float] = {}
    for night in result["nights"]:
        date = night["date"]
        if night["session_minutes"] > night["window_minutes"] + 1:
            problems.append(f"{date}: session {night['session_minutes']} min exceeds window {night['window_minutes']} min")
        if minutes_per_night and night["session_minutes"] > minutes_per_night + 1:
            problems.append(f"{date}: session {night['session_minutes']} min exceeds cap {minutes_per_night} min")
        if night["minutes"] > night["session_minutes"] * eff + 1:
            problems.append(f"{date}: {night['minutes']} min of subs exceeds session x efficiency")
        if abs(sum(night["by_channel"].values()) - night["minutes"]) > 0.1 * max(1, len(night["by_channel"])):
            problems.append(f"{date}: per-channel minutes do not add up to the night total")
        if night["status"] != "imaged" and night["minutes"] > 0:
            problems.append(f"{date}: status {night['status']} but {night['minutes']} min scheduled")
        for key, minutes in night["by_channel"].items():
            per_channel[key] = per_channel.get(key, 0.0) + minutes
    for ch in result["channels"]:
        scheduled = ch["minutes"] - ch["remaining_minutes"]
        if abs(per_channel.get(ch["key"], 0.0) - scheduled) > 0.1 * max(1, ch["nights_used"]) + 0.1:
            problems.append(f"{ch['key']}: nightly totals {per_channel.get(ch['key'], 0.0):.1f} != scheduled {scheduled:.1f}")
        if ch["minutes"] > 0 and ch["remaining_minutes"] == 0 and not ch["finish_date"]:
            problems.append(f"{ch['key']}: finished but no finish date")
    imaged = sum(1 for n in result["nights"] if n["status"] == "imaged")
    if imaged != result["imaging_nights"]:
        problems.append(f"imaging_nights {result['imaging_nights']} != imaged nights {imaged}")
    if result["completed"] and result["nights"] and result["finish_date"] != result["nights"][-1]["date"]:
        problems.append("finish date is not the last simulated night")
    return problems
