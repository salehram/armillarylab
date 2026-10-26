# Plan Duration Prediction Guide

Estimate how many nights a target's plan will take, how long you will image each night, and when you will finish — taking into account the target's position in the sky, the moon and the weather.
*Available since v2.9.0.*
---

## Table of Contents

- [Where to find it](#where-to-find-it)
- [The four views](#the-four-views)
- [Controls](#controls)
- [Reading the results](#reading-the-results)
- [Settings](#settings)
- [Moon limits per filter](#moon-limits-per-filter)
- [Weather data](#weather-data)
- [Mosaics](#mosaics)
- [How the engine works](#how-the-engine-works)
- [Validating the calculations](#validating-the-calculations)
- [API reference](#api-reference)
- [Database fields](#database-fields)
- [Limitations](#limitations)

---

## Where to find it

- **Target page** — a *Plan Duration Prediction* card under *Plan & Palette* (shown when the target has a plan).
- **Mosaic page** — a *Mosaic Duration Prediction* card above the panel list, covering all non-archived panels.

The first calculation for a target can take a few seconds (the year-long sky grid is built and, the first time, three years of historical weather are downloaded for your location). After that, changes are near-instant.

---

## The four views

| Tab | What limits imaging |
|-----|---------------------|
| **Baseline** | Darkness (nautical, sun below −12°), the target being above your minimum altitude, your pack-up time and your nightly time cap. Every night is assumed clear. |
| **Moon** | Baseline + per-filter moon limits. A filter is only scheduled while the moon is below the horizon, or when the moon is dim enough **and** far enough from the target for that filter. Dark time goes to the most moon-sensitive filter first, so moonlit time is left for tolerant filters such as Ha. |
| **Weather** | Baseline + cloud cover, wind gusts and seeing (see [Weather data](#weather-data)). |
| **Moon + Weather** | Both together — the most realistic estimate. |

---

## Controls

| Control | Meaning |
|---------|---------|
| **Basis** | *Remaining time* (planned minus already-logged sessions) or *Full plan*. |
| **Hours per night** | The most time you want to spend imaging per night. Blank = the whole usable window. Example: the window is 6 h but you only want 4 h → enter `4`. |
| **Efficiency %** | Share of imaging time that becomes subs (dithering, downloads, autofocus, meridian flips, filter changes). 85% means 4 h of imaging yields 3 h 24 m of subs. |
| **Recalculate** | Re-runs the prediction (it also re-runs automatically when you change a value). |
| **Save for this target** | Stores the hours per night and efficiency as this target's defaults (target page only). |

---

## Reading the results

**Visibility** (top left): next rise/set at the horizon, when the target is above your minimum altitude, meridian transit, tonight's usable window and tonight's moon illumination.

**Integration per filter** (top right): planned, done and still-to-schedule time per channel, the number of frames left at the plan's sub length, and the moon limit used for that filter.

**Per view:**

| Tile | Meaning |
|------|---------|
| **Imaging nights** | Nights on which something is captured. |
| **…over N calendar nights** | Elapsed nights from tonight until the plan is done, including nights lost to moon or weather. |
| **Estimated finish** | Date of the last imaging night. "Not within a year" means the plan cannot be completed in the next 365 nights (target out of season or limits too strict); the warning shows how much cannot be scheduled. |
| **Avg per imaging night** | Average time at the telescope, with the resulting sub time underneath. |
| **Nights lost** | Nights with no usable window (out of season), lost to weather, or lost to the moon. |

The per-filter table shows how many nights each channel uses and when it finishes.

**Chart:** stacked bars are minutes of subs per night by channel; the line is the usable window. Nights skipped because of the moon are shaded light blue (click *Skipped (moon)* in the legend to hide the shading). Hover over a night to see its date and why it was or wasn't used.

> The usable window naturally changes from night to night: a target that has already transited at dusk sets about 4 minutes earlier each night, so its window shrinks; a target that rises during the night gets a longer window as the season advances.

---

## Settings

**Global** (*Settings → Plan Duration Prediction*):

| Setting | Default | Notes |
|---------|---------|-------|
| Imaging Time per Night (min) | blank (full window) | Default nightly cap. |
| Imaging Efficiency (%) | 85 | |
| Max Wind Gust (km/h) | 35 | Forecast hours with stronger gusts are unusable. |
| Worst Acceptable Seeing | 6 (1.5–2″) | 7Timer scale 1–8; 8 effectively ignores seeing. |
| Fallback Usable Nights (%) | 50 | Used after the forecast when no historical data is available. |
| Max Cloud Cover Tolerance (%) | 25 | Existing Night Conditions setting, reused for the prediction. |

**Per target** (*Target → Settings → Plan Duration Prediction*): imaging time per night and efficiency. Blank uses the global value; `0` minutes means "use the full window" even if a global cap is set. The *Save for this target* button on the card writes the same fields.

---

## Moon limits per filter

Each filter has two optional limits (*Filters → Edit*):

- **Max Moon Illumination (%)** — the filter is not used while the moon is up and brighter than this.
- **Min Moon Separation (°)** — the filter is not used while the moon is up and closer to the target than this.

Both only apply while the moon is above the horizon. Blank uses the default:

| Filter | Max illumination | Min separation |
|--------|------------------|----------------|
| H (Ha) | 100% | 25° |
| S (SII) | 75% | 25° |
| O (OIII) | 50% | 35° |
| L, R, G, B / broadband | 25% | 40° |
| Other narrowband | 75% | 25° |
| Other | 50% | 35° |

Custom plan channels (e.g. `O_HDR_4`) use the limits of the filter they map to. The limits are included in preset export/import.

---

## Weather data

| Period | Source | Applied |
|--------|--------|---------|
| Next ~16 days | Open-Meteo hourly forecast | Each hour with cloud above your tolerance or gusts above the limit is unusable. |
| Next ~3 days | 7Timer seeing | Hours with seeing worse than your limit are unusable. |
| After the forecast | Open-Meteo historical archive (last 3 full years) | Monthly probability that a night is usable (≥70% of 20:00–04:00 hours within the cloud and gust limits). |
| No archive data (offline, first run) | *Fallback Usable Nights (%)* | Same monthly mechanism with your fixed percentage. |

Climatology is applied deterministically: each night adds that month's probability to a running credit, and a night is imaged when the credit reaches 1. With a 60% month, 3 of every 5 nights are imaging nights. Results are therefore repeatable.

The card header shows which sources were used (e.g. *Forecast until 2026-11-10 · seeing until 2026-10-29 · then historical climate*). Forecasts are cached for an hour and on disk for offline use; climatology is cached for 30 days under `cache/conditions/`.

Seeing has no historical equivalent, so seeing is only applied while 7Timer has data.

---

## Mosaics

The mosaic card treats all non-archived panels as one project:

- Panels are completed **in panel-number order** (panel 1 before panel 2).
- All panels share **one nightly time budget**; each panel uses its own visibility window.
- Channels are labelled with the panel, e.g. `P1 H`, `P2 O`.
- The nightly cap and efficiency come from the global settings (or the values typed into the card).

---

## How the engine works

Implemented in `prediction_utils.py`.

1. **Sky grid** (cached per location and start date for 6 hours): the next 365 nights are split into 10-minute slots from 15:00 to 09:00 local. Each slot is sampled at 5 points (every 2 minutes) for sun altitude, so partly usable slots count only their usable minutes. Sun and moon positions come from astropy every 2 hours and are interpolated; altitudes are computed from local sidereal time with positions precessed to the current date. Moon illumination is evaluated per night.
2. **Target grid** (cached per target settings): target altitude at each sub-sample, the minimum-altitude and pack-up limits, and moon–target separation per slot.
3. **Weather masks**: forecast hours and seeing points mapped onto slots.
4. **Simulator**: walks night by night and slot by slot, filling each usable slot (up to your nightly cap) with the remaining channel that has the highest priority — most moon-sensitive first in the moon views, otherwise the channel with the largest share of its time still remaining. If a channel finishes partway through a slot, the next channel uses the rest. Integration per slot = usable minutes × efficiency.
5. **Scenarios**: the same simulator runs four times with moon and/or weather constraints switched on.

---

## Validating the calculations

Run the validator for any target (from the project folder with the virtual environment active):

```bash
flask validate-prediction 22
flask validate-prediction 22 --nights 120 --every 3 --tolerance 3
```

It performs three independent checks:

1. **Usable window** — compares the engine's window night by night with an exact astroplan reference (nautical twilight events plus a full altitude/azimuth transform every 30 seconds).
2. **Moon geometry** — compares moon altitude, moon–target separation and illumination with astropy at sampled times.
3. **Simulator bookkeeping** — for all four views: nightly session ≤ usable window and ≤ your cap, subs ≤ session × efficiency, per-channel nightly totals add up to what was scheduled, finish dates and night counts are consistent.

Example output:

```
Night        Engine  Reference  Diff   Engine span     Reference span
2026-10-26     290        290    +0   18:08-22:58     18:07-22:58
2026-11-09     244        244    +0   18:00-22:04     17:59-22:03
...
Window: max |diff| 2 min, mean 0.3 min
Moon (284 samples): altitude err 0.04°, separation err 0.03°, illumination err 2.4%

Simulation (cap full window min, efficiency 85%):
  baseline  imaging nights   6, calendar   6, finish 2026-10-31: invariants ok
  ...
Validation passed.
```

The command exits with an error if any window differs by more than `--tolerance` minutes (default 5) or a bookkeeping check fails. The same checks run in the test suite (`tests/test_prediction_utils.py`) for several latitudes and targets with a 3-minute tolerance.

> The *Tonight's Window* card and the Night Conditions popup use the older `compute_target_window()` with coarser sampling, so their window can be up to ~30 minutes shorter than the prediction's.

---

## API reference

| Endpoint | Description |
|----------|-------------|
| `GET /api/target/<id>/duration-prediction` | All four views for one target. |
| `GET /api/mosaic/<id>/duration-prediction` | All four views for a mosaic (non-archived panels in order). |
| `POST /target/<id>/prediction-settings` | JSON `{"minutes_per_night": 240, "efficiency_pct": 85}`; blank clears an override, `0` minutes = full window. |

Query parameters for the GET endpoints (all optional; omitted values use the saved settings):

| Parameter | Values |
|-----------|--------|
| `basis` | `remaining` (default) or `full` |
| `minutes_per_night` | 0–1440; empty or `0` = full window |
| `efficiency_pct` | 10–100 |

The response contains `inputs`, `sources`, `panels` (per-channel minutes and moon limits), `tonight`, `rise_set` and `scenarios.{baseline,moon,weather,combined}` with summary fields and a `nights` list (`date`, `window_minutes`, `session_minutes`, `minutes`, `status`, `by_channel`).

---

## Database fields

Added automatically on startup (additive migrations; identical behaviour on SQLite and PostgreSQL — Float columns are `REAL` on SQLite and `DOUBLE PRECISION` on PostgreSQL):

| Table | Column | Type |
|-------|--------|------|
| `global_config` | `prediction_minutes_per_night` | Integer, nullable |
| `global_config` | `prediction_efficiency_pct` | Integer, default 85 |
| `global_config` | `prediction_max_gust_kmh` | Float, default 35 |
| `global_config` | `prediction_max_seeing_raw` | Integer, default 6 |
| `global_config` | `prediction_default_usable_night_pct` | Integer, default 50 |
| `targets` | `override_prediction_minutes_per_night` | Integer, nullable |
| `targets` | `override_prediction_efficiency_pct` | Integer, nullable |
| `filters` | `moon_max_illumination_pct` | Integer, nullable |
| `filters` | `moon_min_separation_deg` | Float, nullable |

Predictions themselves are computed on demand and never stored.

---

## Limitations

- A capped night uses the **earliest** usable time in the window, not the time around transit.
- Altitudes are geometric (no atmospheric refraction), matching the rest of the app.
- Seeing is only applied within 7Timer's ~3-day horizon.
- Climatology looks at 20:00–04:00 local hours, independent of the target.
- Other targets competing for the same nights are not considered.
