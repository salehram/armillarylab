# Calibration Frames Guide

Track darks, flats, dark flats, and bias per imaging target. ArmillaryLab is a
**tracker, not a stacker** — we record what you captured and remind you at the
end of each channel if you still owe frames. *When* and *how* you capture
(per-session, all at the end, or any mix) is entirely up to you.

> **v2.5.0 change:** the old "two-point" mid-channel nudge was dropped. Since
> ArmillaryLab never applies or averages flats, forcing a capture rhythm gained
> nothing. You now get one suggestion per channel — at the end — and the
> `checkpoint` field on each capture is free-form metadata. See the
> [features roadmap](FEATURES_ROADMAP.md) for the v2.6 column cleanup that
> follows.

---

## Overview

Calibration tracking is **opt-in per target**. When enabled:

| Frame type | Scope | Suggestion |
|------------|-------|------------|
| Darks | Whole target | None — log whenever you capture |
| Bias | Whole target | None — log whenever you capture |
| Flats | Per channel (same count for every channel) | One reminder when the channel's lights are complete |
| Dark flats | Per channel | One reminder when the channel's lights are complete |

---

## Setup

### 1. Global defaults

Open **Settings** → **Default Calibration Frames**:

- Set counts for darks, flats per channel, dark flats per channel, and optional bias
- Use `0` to disable a frame type

### 2. Enable on a target

Open **Target → Settings** → **Calibration Tracking**:

- Check **Enable calibration frame tracking for this target**
- Optionally override any count (blank = global default)

---

## End-of-channel workflow (example: R channel)

Suppose you set **100 flats** and **100 dark flats per channel**, and your R
channel plan is **20×300s** light frames.

| Moment | What you see |
|--------|--------------|
| Mid-channel (10/20 frames logged) | No nudge — capture flats now if you want, or wait |
| End of channel (20/20 frames logged) | One suggestion: *log remaining flats/dark flats for R* |

The banner shows **X / 100 captured** so totals never look additive. The
`checkpoint` tag you pick when logging (`midpoint`, `end`, `manual`, or any
text via the API) is preserved as-is — it's metadata, not workflow state.

### Skip for now

- **Skip end**: silence the channel's end-of-run reminder until you restore it

To bring a skipped suggestion back, open **Calibration Frames** → **Skipped
Suggestions** and click **Restore**.

---

## Logging captures

On the target detail page, use the **Calibration Frames** card:

1. Choose date, frame type, count, channel (for flats/dark flats), checkpoint tag, optional notes
2. Click **Log Calibration**

You can log captures at **any time** — before, during, or after lights for a
channel. The `checkpoint` field is a free-form tag for your own bookkeeping;
ArmillaryLab counts the frames toward the channel total regardless of tag.

From the **end-of-channel banner**:

- **Log capture** — prefills the form with the remaining count
- **Skip for now** — silences that channel's reminder

You can also log darks in small batches across sessions (e.g. 2–3 at the start/end of a night) to chip away at the total.

---

## Reading progress

- **Darks / Bias**: target-level progress bars (`captured / planned`)
- **Per-channel table**: flats and dark flats with end-of-channel status (✓ complete, pending, or — if skipped)
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

After upgrading, on **existing SQLite**:

```bash
flask db info
flask db backup      # optional; migrate-db auto-backs up SQLite
flask migrate-db
```

`migrate-db` is **additive only** (new columns/tables). It does not delete rows. Always confirm the database path with `flask db info` first.

**Never** run `flask init-db --force` unless you intend to wipe all data.
