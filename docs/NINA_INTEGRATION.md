# NINA Integration Guide

This guide explains how AstroPlanner integrates with [N.I.N.A. (Nighttime Imaging 'N' Astronomy)](https://nighttime-imaging.eu/), the popular open-source astrophotography software, to export imaging sequences directly to NINA's Advanced Sequencer.

---

## Table of Contents

1. [Overview](#overview)
2. [How It Works](#how-it-works)
3. [Setting Up Filter Wheel Configuration](#setting-up-filter-wheel-configuration)
4. [Exporting Sequences](#exporting-sequences)
5. [Template Customization](#template-customization)
6. [Troubleshooting](#troubleshooting)

---

## Overview

AstroPlanner can export your remaining imaging exposures directly to NINA's Advanced Sequencer format. This allows you to:

- **Seamless Workflow**: Plan in AstroPlanner → Export → Import in NINA → Image
- **Accurate Progress Tracking**: Only export remaining subs, not the full plan
- **Proper Filter Mapping**: AstroPlanner filter names map to your actual NINA filter wheel positions
- **Time Savings**: No manual sequence creation needed

### What Gets Exported?

| Component | Description |
|-----------|-------------|
| **Target Name** | Sequence named "AstroPlanner – [Target Name]" |
| **Camera Cooling** | Set to -10°C (default, template-configurable) |
| **Filter Changes** | Proper filter wheel position switching |
| **Exposures** | Remaining frames at specified exposure times |
| **Waits** | 3-second delays between filter changes |

---

## How It Works

### Export Flow

```
┌─────────────────────┐
│   AstroPlanner      │
│   Target Plan       │
│   (channels +       │
│   progress data)    │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Calculate          │
│  Remaining Subs     │
│  per Channel        │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Map to Active      │
│  Filter Wheel       │
│  (positions + names)│
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Generate NINA      │
│  Sequence JSON      │
│  from Template      │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Download           │
│  AstroPlanner_      │
│  [Target].json      │
└─────────────────────┘
```

### Remaining Subs Calculation

For each channel in your target plan:

```
Planned Time = planned_minutes × 60 (seconds)
Completed Time = sum of all session sub_exposure_seconds × sub_count
Remaining Time = max(Planned - Completed, 0)
Remaining Frames = round(Remaining Time / sub_exposure_seconds)
```

Only channels with `Remaining Frames > 0` are included in the export.

---

## Setting Up Filter Wheel Configuration

For NINA export to work correctly, your AstroPlanner filter wheel must match your physical equipment configuration in NINA.

### Step 1: Configure Your Filter Wheel

1. Navigate to **Settings** → **Filter Wheels**
2. Click **New Filter Wheel**
3. Enter your wheel specifications:
   - **Name**: e.g., "ZWO 8-Slot EFW"
   - **Slot Count**: Number of positions (typically 5, 7, or 8)
   - **Filter Size**: 1.25", 2", 36mm, etc.

### Step 2: Assign Filters to Slots

Each slot must have:
- **Position**: Wheel position (0-based, matching NINA)
- **Filter**: The AstroPlanner filter to assign
- **NINA Name**: The exact filter name as it appears in NINA

Example 8-Slot Configuration:

| Position | AstroPlanner Filter | NINA Name |
|----------|---------------------|-----------|
| 0 | LP | LP |
| 1 | L | L |
| 2 | R | R |
| 3 | G | G |
| 4 | B | B |
| 5 | H | Ha |
| 6 | S | SII |
| 7 | O | OIII |

### Step 3: Activate the Filter Wheel

1. Go to **Settings** → **Filter Wheels**
2. Find your configured wheel
3. Click **Set as Active**
4. Confirm the activation

> ⚠️ **Important**: Only one filter wheel can be active at a time. The active wheel is used for all NINA exports.

### NINA Name Mapping

The **NINA Name** field is crucial—it must match exactly what NINA expects:

| AstroPlanner Code | Common NINA Names |
|-------------------|-------------------|
| H | Ha, H-Alpha, Halpha |
| O | OIII, O-III, O3 |
| S | SII, S-II, S2 |
| L | L, Lum, Luminance |
| R | R, Red |
| G | G, Green |
| B | B, Blue |
| LP | LP, L-Pro, Light Pollution |

Check your NINA profile settings to verify the exact filter names.

---

## Exporting Sequences

### From Target Detail Page

1. Navigate to your target's detail page
2. Scroll to the **Export** section
3. Click **Export to NINA**
4. The JSON file downloads automatically

### Export Contents

The exported file contains a complete NINA Advanced Sequencer sequence:

```json
{
  "Name": "AstroPlanner – M31",
  "Items": {
    "$values": [
      // Start: Camera cooling to -10°C
      // Target: Set tracking, then for each channel:
      //   - Wait 3s
      //   - Switch to filter
      //   - Wait 3s  
      //   - Take N exposures at X seconds
      // End: Park telescope
    ]
  }
}
```

### Importing into NINA

1. Open NINA
2. Go to **Sequencer** (Advanced Sequencer)
3. Click **Load Sequence** or **Import**
4. Select the downloaded JSON file
5. Review the sequence
6. Modify camera temperature, target coordinates as needed
7. Run the sequence

---

## Template Customization

AstroPlanner uses a template file (`nina_template.json`) to generate exports. You can customize this template for your specific setup.

### Template Location

```
astroplanner/
├── nina_template.json    ← Main template file
├── nina_integration.py   ← Export logic
└── ...
```

### Template Structure

The template defines the sequence structure with placeholder values:

```json
{
  "Name": "Template",
  "Items": {
    "$values": [
      // StartAreaContainer - Camera cooling, etc.
      {
        "Items": {
          "$values": [
            {
              "$type": "NINA.Sequencer.SequenceItem.Camera.CoolCamera...",
              "Temperature": -10.0  // ← Modified during export
            }
          ]
        }
      },
      // TargetAreaContainer - Tracking, filters, exposures
      {
        "Items": {
          "$values": [
            // SetTracking
            // Wait 3s
            // SwitchFilter (cloned per channel)
            // Wait 3s
            // TakeManyExposures (cloned per channel)
          ]
        }
      },
      // EndAreaContainer - Park telescope, warm camera
      { ... }
    ]
  }
}
```

### Creating a Custom Template

1. **Export from NINA**: Create your ideal sequence in NINA, then save it
2. **Copy to AstroPlanner**: Replace `nina_template.json` with your exported file
3. **Preserve Structure**: Ensure these elements exist:
   - StartAreaContainer (first item)
   - TargetAreaContainer (second item) with:
     - SetTracking at position 0
     - Wait template at position 1
     - SwitchFilter template at position 2
     - Wait template at position 3
     - TakeManyExposures template at position 4
   - EndAreaContainer (third item)

### Customizable Elements

| Element | How to Customize |
|---------|------------------|
| Camera cooling temp | Edit `Temperature` in CoolCamera item |
| Wait duration | Edit `Time` in Wait items |
| End sequence actions | Modify EndAreaContainer items |
| Dithering | Add dither instructions to template |

---

## Custom Filters and NINA Export

When you create custom filters in AstroPlanner (like separate HDR channels), you can map them to standard NINA filters.

### Example: HDR Channels

If you have:
- `H_1` - H-Alpha standard (120s)
- `H_2` - H-Alpha long (300s)
- `H_3` - H-Alpha extra-long (600s)

All three should map to the same NINA filter (`Ha`) since they use the same physical filter.

### Setting the Mapping

When creating or editing a filter:
1. Go to **Settings** → **Filters**
2. Edit the custom filter
3. Set the **NINA Filter** field to the standard filter name

This ensures the export uses the correct filter wheel position.

---

## Troubleshooting

### "No remaining subs to export"

**Cause**: All planned exposures are complete, or no plan exists.

**Solution**: 
- Check your target plan has planned minutes > 0
- Verify progress hasn't already reached 100%
- Ensure a plan exists for the target's preferred palette

### "Unknown channel 'X' - skipping in NINA export"

**Cause**: A filter in your plan isn't configured in the active filter wheel.

**Solution**:
1. Go to **Settings** → **Filter Wheels**
2. Edit the active wheel
3. Add the missing filter to a slot
4. Set the correct NINA name

### Filter positions wrong in NINA

**Cause**: Filter wheel position numbers don't match NINA configuration.

**Solution**:
- Verify positions are 0-based (first slot = position 0)
- Check NINA's filter wheel settings match AstroPlanner positions
- Use the same position numbering scheme in both applications

### Export file won't import in NINA

**Cause**: Template structure mismatch or NINA version incompatibility.

**Solution**:
1. Export a fresh template from your current NINA version
2. Replace `nina_template.json` with the new template
3. Restart AstroPlanner
4. Try exporting again

### Wrong filter names in exported sequence

**Cause**: NINA Name in filter wheel slot doesn't match NINA profile.

**Solution**:
1. Open NINA → Equipment → Filter Wheel
2. Note the exact filter names shown
3. In AstroPlanner, edit filter wheel slots
4. Set NINA Name to match exactly (case-sensitive)

---

## Best Practices

### Keep Configurations Synchronized

- When you change filters in NINA, update AstroPlanner
- When adding new filters, configure both systems

### Use Descriptive NINA Names

- Consistent naming prevents confusion
- Document your naming convention

### Test Before Imaging Nights

- Export a test sequence
- Import into NINA and verify structure
- Run a short test to confirm filter switching

### Backup Your Template

```powershell
copy nina_template.json nina_template_backup.json
```

---

## Related Documentation

- [Equipment Presets Guide](PRESETS_GUIDE.md) - Filter and wheel configuration
- [AstroBin Export Guide](ASTROBIN_EXPORT.md) - CSV export for AstroBin uploads
- [Database Guide](DATABASE_GUIDE.md) - Database setup and migration
