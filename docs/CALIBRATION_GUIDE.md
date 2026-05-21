# Calibration Frames Guide

Track darks, flats, dark flats, and bias per imaging target—with optional two-point flat capture suggestions tied to your light frame progress.

---

## Overview

Calibration tracking is **opt-in per target**. When enabled:

| Frame type | Scope | Suggestions |
|------------|-------|-------------|
| Darks | Whole target | Manual logging only |
| Bias | Whole target | Manual logging only |
| Flats | Per channel (same count for every channel) | Midpoint + end (if two-point enabled) |
| Dark flats | Per channel | Midpoint + end (if two-point enabled) |

---

## Setup

### 1. Global defaults

Open **Settings** → **Default Calibration Frames**:

- Set counts for darks, flats per channel, dark flats per channel, and optional bias
- Enable **Use two-point flat capture by default** to split flats/dark-flats at channel midpoint and end

Use `0` to disable a frame type.

### 2. Enable on a target

Open **Target → Settings** → **Calibration Tracking**:

- Check **Enable calibration frame tracking for this target**
- Optionally override any count or two-point behavior (blank = global default)

---

## Two-point workflow (example: R channel)

Suppose you set **100 flats** and **100 dark flats per channel**, with two-point enabled, and your R channel plan is **20×300s** light frames.

| Milestone | Light progress | Suggestion |
|-----------|----------------|------------|
| Midpoint | 10 frames logged (50%) | Capture **50 flats** + **50 dark flats** for R |
| End | 20 frames logged (100%) | Capture **remaining 50** of each (or full 100 if midpoint was skipped) |

### Skip for now

- **Skip midpoint**: obligation moves to the end checkpoint when R channel completes
- **Skip end**: no further prompts; log manually whenever you want

---

## Logging captures

On the target detail page, use the **Calibration Frames** card:

1. Choose date, frame type, count, channel (for flats/dark flats), checkpoint, optional notes
2. Click **Log Calibration**

From **action item** banners (when a threshold is crossed):

- **Log capture** — prefills the form
- **Skip for now** — defers that checkpoint

You can also log darks in small batches across sessions (e.g. 2–3 at the start/end of a night) to chip away at the total.

---

## Reading progress

- **Darks / Bias**: target-level progress bars (`captured / planned`)
- **Per-channel table**: flats and dark flats with midpoint status (✓, pending, or — if skipped)
- **Plan table**: **Cal** column badges when a suggestion is active
- **History**: captures grouped by date with edit/delete

---

## AstroBin export

When tracking is enabled, the **Export to AstroBin** modal prefills calibration fields from your logged totals. Flats and dark flats are **summed across all channels**. You can still override values before download.

See [AstroBin Export Guide](ASTROBIN_EXPORT.md).

---

## API

`GET /api/target/<id>/calibration` returns JSON with `summary` and `suggestions` (same data as the target detail UI).

---

## Database migration

After upgrading to v2.2.0 on an existing database, run:

```bash
flask migrate-db
```

This adds calibration columns and creates `calibration_captures` / `calibration_checkpoint_skips` tables.
