# NINA Integration Guide

This guide explains how ArmillaryLab integrates with [N.I.N.A. (Nighttime Imaging 'N' Astronomy)](https://nighttime-imaging.eu/) to export fully configured Advanced Sequencer sequences.

---

## Table of Contents

1. [Overview](#overview)
2. [What the V2 Export Produces](#what-the-v2-export-produces)
3. [Setting Up Filter Wheel Configuration](#setting-up-filter-wheel-configuration)
4. [Exporting a Sequence](#exporting-a-sequence)
5. [Export Dialog Reference](#export-dialog-reference)
6. [Importing into NINA](#importing-into-nina)
7. [Template Reference](#template-reference)
8. [Custom Filters and NINA Export](#custom-filters-and-nina-export)
9. [Troubleshooting](#troubleshooting)

---

## Overview

ArmillaryLab exports remaining imaging exposures directly to NINA's **Advanced Sequencer** JSON format. The workflow is:

```
Plan in ArmillaryLab  →  Export NINA Sequence…  →  Configure dialog  →  Download .json / .zip
                                                                              ↓
                                                             Import in NINA Advanced Sequencer
```

Only channels with remaining frames are included. All `$id`/`$ref` references are correctly renumbered so the sequence is immediately importable.

---

## What the V2 Export Produces

The exported sequence (`nina_template_v2.json` base) contains a complete session setup:

| Section | Content |
|---------|---------|
| **Start area** | `CoolCamera` (−10 °C, configurable duration), `StartGuider` |
| **Target area** | `SetTracking` → `CenterAndRotate` (with RA/Dec + position angle) → `AutofocusAfterSetTime` → one **`SequentialContainer`** per channel |
| **Per-channel block** | `SwitchFilter`, `TakeExposure` (loop × remaining frames, with your gain), `Dither` trigger after N exposures |
| **Global triggers** | `TimeCondition` stop guard keyed to tonight's imaging window end time |
| **End area** | Park telescope, warm camera |

The sequence name, DSO container name, and all numeric parameters are set before download — no manual editing required in NINA.

---

## Setting Up Filter Wheel Configuration

---

## Setting Up Filter Wheel Configuration

For positions and NINA filter names to export correctly your ArmillaryLab filter wheel must mirror your physical NINA configuration.

### Step 1: Configure your filter wheel

1. Go to **Settings → Filter Wheels**
2. Click **New Filter Wheel**
3. Set:
   - **Name** — e.g. "ZWO 8-Slot EFW"
   - **Slot Count** — number of positions (typically 5, 7, or 8)
   - **Filter Size** — 1.25", 2", 36 mm, etc.

### Step 2: Assign filters to slots

Each slot needs:
- **Position** — 0-based wheel position matching NINA's numbering
- **Filter** — the ArmillaryLab filter assigned to that slot
- **NINA Name** — the exact filter name as it appears in your NINA profile

Example 8-slot configuration:

| Position | ArmillaryLab Filter | NINA Name |
|----------|---------------------|-----------|
| 0 | LP | LP |
| 1 | L | L |
| 2 | R | R |
| 3 | G | G |
| 4 | B | B |
| 5 | H | Ha |
| 6 | S | SII |
| 7 | O | OIII |

### Step 3: Activate the filter wheel

1. Go to **Settings → Filter Wheels**
2. Find your wheel and click **Set as Active**

> ⚠️ Only one filter wheel can be active at a time. The active wheel is used for all NINA exports.

### NINA Name mapping reference

| ArmillaryLab Code | Common NINA Names |
|-------------------|-------------------|
| H | Ha, H-Alpha, Halpha |
| O | OIII, O-III, O3 |
| S | SII, S-II, S2 |
| L | L, Lum, Luminance |
| R | R, Red |
| G | G, Green |
| B | B, Blue |
| LP | LP, L-Pro, Light Pollution |

Check **NINA → Equipment → Filter Wheel** for the exact names used in your profile (case-sensitive).

---

## Exporting a Sequence

1. Open the target detail page
2. In the **Plan** section, click **Export NINA Sequence…**
3. The export dialog opens — fill in the options (see [Export Dialog Reference](#export-dialog-reference))
4. Click **Export Sequence** to download the file

> The button is only shown when a plan with at least one channel having remaining frames exists.

---

## Export Dialog Reference

### Sequence Info

| Field | Default | Description |
|-------|---------|-------------|
| **Sequence Name** | Target name | Top-level name shown in NINA |
| **DSO Container Name** | `"<target> Capture"` | Name of the `DeepSkyObjectContainer` |

### Sequence Setup

| Field | Default | Description |
|-------|---------|-------------|
| **Position Angle (°)** | `0` | Rotation for `CenterAndRotate`. Verify in the NINA Framing Assistant first. |
| **Cooldown (min)** | `10` | `CoolCamera` duration in minutes |
| **Dither After N** | `3` | Fire the `Dither` trigger every N exposures |
| **Force Guider Cal** | off | If checked, forces a new guide-star calibration at sequence start |

### Export Mode

| Mode | Output |
|------|--------|
| **All channels** | Single `.json` containing all channels with remaining frames |
| **Single channel** | Single `.json` for one selected channel |
| **Separate files (ZIP)** | `.zip` archive with one `.json` per channel |

### Channels & Gain

The table is auto-populated from your plan. Each row shows:

- **Channel** — display name (e.g. "Ha")
- **Filter** — NINA filter name
- **Remaining** — frames still to capture
- **Exp (s)** — sub-exposure seconds
- **Gain** — per-channel gain (editable)

Use **Global Gain** + **Apply** to set the same value across all channels, then override individual rows as needed.

### Stop Time

Displays tonight's imaging window end time. The `TimeCondition` in the exported sequence is pre-set to this time so NINA stops gracefully when the window closes.

### Experimental: ExposureCount offset

When checked, `TakeExposure.ExposureCount` is set to the number of already-captured frames for each channel. This tests whether NINA uses `ExposureCount` as a completed-frames offset. Leave unchecked unless experimenting.

---

## Importing into NINA

1. Open NINA
2. Go to **Sequencer → Advanced Sequencer**
3. Click **Load Sequence** (folder icon)
4. Select the downloaded `.json` file
5. Review — target coordinates, position angle, filter slots, and gain are pre-filled
6. Connect your equipment and run

> If you exported a ZIP, extract it first and import each channel's file separately.

---

## Template Reference

The V2 export is based on `nina_template_v2.json` in the project root.

```
armillarylab/
├── nina_template_v2.json   ← V2 template (Advanced Sequencer, full session)
├── nina_template.json      ← Legacy V1 template (kept for reference)
└── nina_integration.py     ← Export builder
```

### Key template structure

```
Root sequence
├── StartAreaContainer
│   ├── CoolCamera            ← Temperature: -10 °C  Duration: patched from dialog
│   └── StartGuider
├── TargetAreaContainer
│   ├── INIT block (SetTracking, WaitForAltitude …)
│   └── DeepSkyObjectContainer  ← Name + Target (RA/Dec/PA) patched
│       ├── CenterAndRotate     ← Coords + PA patched
│       ├── AutofocusAfterSetTime
│       ├── TimeCondition       ← Stop time patched from window end
│       └── [SequentialContainer × N channels]   ← Replicated + renumbered
│           ├── SwitchFilter    ← Name + position patched
│           ├── TakeExposure    ← ExposureTime + Gain + LoopCondition patched
│           └── Trigger: Dither ← AfterExposures patched
└── EndAreaContainer
    └── Park, WarmCamera …
```

### Camera cooling temperature

The template hardcodes −10 °C as the `CoolCamera` target temperature. Adjust in NINA at runtime if your conditions require a different setpoint.

---

## Custom Filters and NINA Export

When you create custom filters (e.g. separate channels for different exposure lengths), map them to the same physical NINA filter.

### Example: dual-exposure Ha channels

| ArmillaryLab channel | NINA Filter | Notes |
|----------------------|-------------|-------|
| `H_short` | Ha | 120 s sub-exposures |
| `H_long` | Ha | 300 s sub-exposures |

Both generate a `SwitchFilter → Ha` step with different `TakeExposure` durations.

### Setting the mapping

1. Go to **Settings → Filters**
2. Edit the custom filter
3. Set the **NINA Filter** field to the exact physical filter name

---

## Troubleshooting

### "No remaining subs to export"

All planned exposures are complete, or no plan exists.
- Check your plan has planned minutes > 0 for at least one channel
- Confirm progress hasn't already reached 100 %

### Export dialog channel table is empty

The plan has no channels with remaining frames, or no plan exists.
- Verify the preferred palette and plan are saved
- Add more planned time to channels still in progress

### Filter positions wrong in NINA

NINA uses 0-based indexing (first slot = position 0).
- Verify ArmillaryLab slot positions match NINA's Equipment → Filter Wheel panel exactly

### Wrong filter names in sequence

The NINA Name in the wheel slot doesn't match your NINA profile.
- Open NINA → Equipment → Filter Wheel and note exact names (case-sensitive)
- Edit the active wheel's slot NINA Names to match

### Sequence won't import in NINA

The V2 template was built and tested against NINA 3.x.
- Try re-exporting; if the problem persists open an issue and attach the exported `.json`

---

## Related Documentation

- [Equipment Presets Guide](PRESETS_GUIDE.md) — Filter and wheel configuration
- [AstroBin Export Guide](ASTROBIN_EXPORT.md) — CSV export for AstroBin uploads
- [Database Guide](DATABASE_GUIDE.md) — Database setup and migration
- [Calibration Guide](CALIBRATION_GUIDE.md) — Tracking darks, flats, and bias
