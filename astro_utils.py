from __future__ import annotations

import json
import math
import os
import datetime
from zoneinfo import ZoneInfo

try:
    from astropy.coordinates import SkyCoord, EarthLocation, AltAz, get_sun
    from astropy.time import Time
    import astropy.units as u
    from astroplan import Observer
    ASTRO_DEPS_AVAILABLE = True
except Exception:
    ASTRO_DEPS_AVAILABLE = False


def _fallback_window(note: str):
    return {
        "deps_available": False,
        "note": note,
        "sunset": None,
        "dark_start": None,
        "dark_end": None,
        "meridian_time": None,
        "start_time": None,
        "end_time": None,
        "total_minutes": None,
        "min_altitude_deg": None,
    }


def compute_target_window(
    ra_hours: float,
    dec_deg: float,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float,
    packup_time_local: datetime.time | None,
    min_altitude_deg: float = 30.0,
):
    """
    Compute observing window information for tonight for a celestial target.

    Returned structure:
      deps_available: bool
      note: str
      timezone_name: str

      sunset_local / sunset_utc
      dark_start_local / dark_start_utc
      dark_end_local / dark_end_utc
      meridian_local / meridian_utc

      start_time_local / start_time_utc   (altitude-clipped + packup-validated window)
      end_time_local / end_time_utc
      total_minutes

      raw_start_local/raw_end_local/raw_total_minutes  (dark + packup window before altitude clipping)

      min_altitude_deg
      midpoint_altitude_deg
      altitude_profile: list of {time_label: HH:MM, alt_deg: float}
    """

    tz_name = os.environ.get("OBSERVER_TZ", "Asia/Riyadh")

    # Robust timezone loader for Windows
    try:
        local_tz = ZoneInfo(tz_name)
    except Exception:
        # if user wants KSA and system lacks tzdata → hardcode UTC+3
        if tz_name in ("Asia/Riyadh", "KSA", "UTC+3"):
            local_tz = datetime.timezone(datetime.timedelta(hours=3))
            tz_name = "UTC+3"
        else:
            local_tz = datetime.timezone.utc
            tz_name = "UTC"

    try:
        import astropy.units as u
        from astropy.time import Time
        from astropy.coordinates import SkyCoord, EarthLocation, AltAz
        from astroplan import Observer
    except ImportError:
        return {
            "deps_available": False,
            "note": "Astropy/astroplan not installed.",
            "total_minutes": None,
            "timezone_name": tz_name,
        }

    # Location
    location = EarthLocation(
        lat=latitude_deg * u.deg,
        lon=longitude_deg * u.deg,
        height=elevation_m * u.m,
    )

    # Now in UTC
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    t_now = Time(now_utc)

    observer = Observer(location=location, timezone=local_tz, name="LocalObserver")

    coord = SkyCoord(ra=ra_hours * u.hourangle, dec=dec_deg * u.deg)

    def fmt(dt: datetime.datetime | None) -> str:
        if not dt:
            return "N/A"
        return dt.strftime("%Y-%m-%d %H:%M:%S")  # precise to the second

    def fmt_short(dt: datetime.datetime | None) -> str:
        if not dt:
            return ""
        return dt.strftime("%H:%M")

    def tp(t_astropy: Time | None):
        if t_astropy is None:
            return None, None
        dt_utc = t_astropy.to_datetime(timezone=datetime.timezone.utc)
        dt_local = dt_utc.astimezone(local_tz)
        return dt_utc, dt_local

    # Twilight and sunset
    try:
        sunset = observer.sun_set_time(t_now, which="nearest")
        dark_start = observer.twilight_evening_nautical(t_now, which="nearest")
        dark_end = observer.twilight_morning_nautical(t_now, which="next")
    except Exception:
        return {
            "deps_available": False,
            "note": "Could not compute twilight times.",
            "total_minutes": None,
            "timezone_name": tz_name,
        }

    # Transit
    try:
        meridian = observer.target_meridian_transit_time(t_now, coord, which="nearest")
    except Exception:
        meridian = None

    # Moon rise and set times
    try:
        moon_rise = observer.moon_rise_time(t_now, which="nearest")
        moon_set = observer.moon_set_time(t_now, which="nearest")
    except Exception:
        moon_rise = None
        moon_set = None

    sunset_utc, sunset_local = tp(sunset)
    dark_start_utc, dark_start_local = tp(dark_start)
    dark_end_utc, dark_end_local = tp(dark_end)
    meridian_utc, meridian_local = tp(meridian) if meridian else (None, None)
    moon_rise_utc, moon_rise_local = tp(moon_rise) if moon_rise else (None, None)
    moon_set_utc, moon_set_local = tp(moon_set) if moon_set else (None, None)

    # Pack-up time (local)
    if packup_time_local:
        pack_local = datetime.datetime.combine(
            dark_start_local.date(), packup_time_local, tzinfo=local_tz
        )
        if pack_local <= dark_start_local:
            pack_local += datetime.timedelta(days=1)
    else:
        pack_local = dark_end_local

    base_start_local = dark_start_local
    base_end_local = min(dark_end_local, pack_local)

    if base_end_local <= base_start_local:
        raw_total = 0
    else:
        raw_total = int((base_end_local - base_start_local).total_seconds() // 60)

    # Altitude clipping
    from astropy.time import Time as ATime

    steps = 60
    sample_times = []
    altitudes = []
    above = []

    if base_end_local > base_start_local:
        delta = (base_end_local - base_start_local) / steps
        for i in range(steps + 1):
            t_loc = base_start_local + delta * i
            t_utc = t_loc.astimezone(datetime.timezone.utc)
            t_ast = ATime(t_utc)
            altaz = coord.transform_to(AltAz(obstime=t_ast, location=location))
            alt = float(altaz.alt.deg)
            sample_times.append(t_loc)
            altitudes.append(alt)
            above.append(alt >= min_altitude_deg)
    else:
        sample_times = []
        altitudes = []
        above = []

    valid_i = [i for i, ok in enumerate(above) if ok]

    if valid_i:
        start_local = sample_times[valid_i[0]]
        end_local = sample_times[valid_i[-1]]
    else:
        start_local = base_start_local
        end_local = base_start_local

    total_minutes = int(max((end_local - start_local).total_seconds() // 60, 0))

    # Midpoint altitude
    if end_local > start_local:
        mid_local = start_local + (end_local - start_local) / 2
        mid_utc = mid_local.astimezone(datetime.timezone.utc)
        t_mid = Time(mid_utc)
        alt_mid = coord.transform_to(AltAz(obstime=t_mid, location=location))
        midpoint_alt = round(float(alt_mid.alt.deg), 1)
    else:
        midpoint_alt = None

    start_utc = start_local.astimezone(datetime.timezone.utc)
    end_utc = end_local.astimezone(datetime.timezone.utc)
    raw_start_utc = base_start_local.astimezone(datetime.timezone.utc)
    raw_end_utc = base_end_local.astimezone(datetime.timezone.utc)

    altitude_profile = [
        {"time_label": fmt_short(t), "alt_deg": round(a, 1)}
        for t, a in zip(sample_times, altitudes)
    ]

    return {
        "deps_available": True,
        "note": "",
        "timezone_name": tz_name,

        "sunset_local": fmt(sunset_local),
        "sunset_utc": fmt(sunset_utc),

        "dark_start_local": fmt(dark_start_local),
        "dark_start_utc": fmt(dark_start_utc),

        "dark_end_local": fmt(dark_end_local),
        "dark_end_utc": fmt(dark_end_utc),

        "meridian_local": fmt(meridian_local),
        "meridian_utc": fmt(meridian_utc),

        "moon_rise_local": fmt(moon_rise_local),
        "moon_rise_utc": fmt(moon_rise_utc),
        "moon_set_local": fmt(moon_set_local),
        "moon_set_utc": fmt(moon_set_utc),

        "start_time_local": fmt(start_local),
        "start_time_utc": fmt(start_utc),
        "end_time_local": fmt(end_local),
        "end_time_utc": fmt(end_utc),
        "total_minutes": total_minutes,

        "raw_start_local": fmt(base_start_local),
        "raw_start_utc": fmt(raw_start_utc),
        "raw_end_local": fmt(base_end_local),
        "raw_end_utc": fmt(raw_end_utc),
        "raw_total_minutes": raw_total,

        "min_altitude_deg": float(min_altitude_deg),
        "midpoint_altitude_deg": midpoint_alt,

        "altitude_profile": altitude_profile,
    }


# ---------------------------------------------------------------------------
# Palette & exposure logic
# ---------------------------------------------------------------------------

# crude defaults you can tune later, in minutes of total integration
DEFAULT_TOTAL_MINUTES_BY_TYPE = {
    "emission": 600,   # 10h
    "diffuse": 480,
    "reflection": 420,
    "galaxy": 360,
    "cluster": 240,
}


def suggest_palette_and_exposures(target_type: str, palette: str, bortle: int = 9):
    """
    Heuristic exposure planner.

    Returns dict:
      {
        "channels": [
            {
              "name": "H", "label": "Ha",
              "weight": 0.5,
              "weight_fraction": 0.5,
              "planned_minutes": 180,
              "sub_exposure_seconds": 300
            },
            ...
        ],
        "dominant_channel": "H",
        "total_planned_minutes": 360,
        "per_channel_minutes": {"H": 180, "O": 110, ...},
        "palette": "SHO"
      }
    """
    ttype = (target_type or "").lower()
    base_total = DEFAULT_TOTAL_MINUTES_BY_TYPE.get(ttype, 420)

    # Bortle penalty – push longer total under bad skies
    if bortle >= 8:
        base_total *= 1.3
    elif bortle >= 6:
        base_total *= 1.1

    palette = (palette or "SHO").upper()

    if palette == "SHO":
        # Emission nebula – Ha usually king
        channels = [
            {"name": "H", "label": "Ha",   "weight": 0.5},
            {"name": "O", "label": "OIII", "weight": 0.3},
            {"name": "S", "label": "SII",  "weight": 0.2},
        ]
        dominant = "H"
    elif palette == "HOO":
        channels = [
            {"name": "H", "label": "Ha",   "weight": 0.6},
            {"name": "O", "label": "OIII", "weight": 0.4},
        ]
        dominant = "H"
    elif palette == "LRGB":
        channels = [
            {"name": "L", "label": "Luminance", "weight": 0.5},
            {"name": "R", "label": "Red",       "weight": 0.17},
            {"name": "G", "label": "Green",     "weight": 0.17},
            {"name": "B", "label": "Blue",      "weight": 0.16},
        ]
        dominant = "L"
    elif palette == "LRGBNB":
        # LRGB + a bit of Ha/OIII
        channels = [
            {"name": "L", "label": "Luminance", "weight": 0.4},
            {"name": "R", "label": "Red",       "weight": 0.12},
            {"name": "G", "label": "Green",     "weight": 0.12},
            {"name": "B", "label": "Blue",      "weight": 0.11},
            {"name": "H", "label": "Ha",        "weight": 0.15},
            {"name": "O", "label": "OIII",      "weight": 0.10},
        ]
        dominant = "L"
    else:
        # fallback – single luminance
        channels = [
            {"name": "L", "label": "Luminance", "weight": 1.0},
        ]
        dominant = "L"

    # Set default sub-exposures per channel (tuned for Bortle 9-ish)
    # Narrowband: 300s, LRGB: 180s (you can tweak later)
    for c in channels:
        n = c["name"]
        if n in ("H", "O", "S"):
            c["sub_exposure_seconds"] = 300
        elif n == "L":
            c["sub_exposure_seconds"] = 180
        else:  # R, G, B or others
            c["sub_exposure_seconds"] = 180

    total_minutes = round(base_total)
    weight_sum = sum(c["weight"] for c in channels)

    per_channel_minutes = {}
    for c in channels:
        c["weight_fraction"] = c["weight"] / weight_sum
        c["planned_minutes"] = round(total_minutes * c["weight_fraction"])
        per_channel_minutes[c["name"]] = c["planned_minutes"]

    return {
        "channels": channels,
        "dominant_channel": dominant,
        "total_planned_minutes": total_minutes,
        "per_channel_minutes": per_channel_minutes,
        "palette": palette,
    }



def build_default_plan_json(target_type: str, palette: str, bortle: int = 9) -> str:
    plan = suggest_palette_and_exposures(target_type, palette, bortle)
    return json.dumps(plan, indent=2)


def resolve_target_name(name: str):
    """
    Resolve an object name like 'NGC 6992', 'M31', 'IC 1805' using
    CDS name resolver via astropy.

    Returns:
      (ra_hours, dec_deg) as floats.

    Raises RuntimeError with a friendly message on failure.
    """
    if not ASTRO_DEPS_AVAILABLE:
        raise RuntimeError("Astropy/astroplan not installed; resolver unavailable.")

    name = (name or "").strip()
    if not name:
        raise RuntimeError("Empty name provided.")

    try:
        # Uses remote CDS service under the hood
        coord = SkyCoord.from_name(name)
    except Exception as exc:
        raise RuntimeError(f"Could not resolve '{name}': {exc}") from exc

    ra_hours = float(coord.ra.hour)
    dec_deg = float(coord.dec.degree)
    return ra_hours, dec_deg
