# Palette & Filter Management Guide

This guide explains the comprehensive palette and filter management system in ArmillaryLab. Understanding these concepts is essential for effectively planning your astrophotography sessions.

---

## Table of Contents

1. [Core Concepts](#core-concepts)
2. [The Big Picture: How Everything Connects](#the-big-picture-how-everything-connects)
3. [Palettes](#palettes)
4. [Filters](#filters)
5. [Filter Wheels](#filter-wheels)
6. [Target Plans](#target-plans)
7. [Custom Channels](#custom-channels)
8. [Workflow Examples](#workflow-examples)
9. [Troubleshooting](#troubleshooting)

---

## Core Concepts

Before diving in, let's clarify the terminology:

| Concept | What It Is | Example |
|---------|------------|---------|
| **Filter** | A physical piece of glass that passes specific wavelengths | ZWO H-Alpha 7nm filter |
| **Palette** | A combination of filters used together for a color image | SHO (Sulfur, Hydrogen, Oxygen) |
| **Filter Wheel** | Hardware that holds multiple filters | ZWO 8-slot 1.25" EFW |
| **Channel** | A single data stream in your final image | The "H" channel in SHO |
| **Target Plan** | Your exposure strategy for a specific target | 3 hours Ha, 2 hours OIII, 1 hour SII |

### The Relationship

```
                          ┌─────────────────┐
                          │   TARGET TYPE   │
                          │   (emission)    │
                          └────────┬────────┘
                                   │ recommends
                                   ▼
┌─────────────┐           ┌─────────────────┐
│   FILTER    │◄─────────►│    PALETTE      │
│   (H, O, S) │  defines  │     (SHO)       │
└──────┬──────┘  channels │                 │
       │                  └────────┬────────┘
       │                           │ used in
       │                           ▼
       │                  ┌─────────────────┐
       │                  │  TARGET PLAN    │
       │                  │  (exposures)    │
       │                  └────────┬────────┘
       │                           │ exports to
       │                           ▼
       │                  ┌─────────────────┐
       └─────────────────►│  FILTER WHEEL   │
           maps to        │  (positions)    │
                          └─────────────────┘
```

---

## The Big Picture: How Everything Connects

### 1. You Have Physical Filters

These are the actual glass filters you own:
- H-Alpha (narrowband, passes 656nm)
- OIII (narrowband, passes 496nm/501nm)
- SII (narrowband, passes 672nm)
- Luminance, Red, Green, Blue (broadband)

### 2. Filters Are Defined in the App

ArmillaryLab stores filter definitions with:
- **Short code** (H, O, S, L, R, G, B)
- **Display name** (Hydrogen Alpha, Oxygen III)
- **Type** (narrowband, broadband)
- **Default exposure** (300s for narrowband, 180s for broadband)
- **AstroBin ID** (for equipment tracking)

### 3. Filters Combine into Palettes

Palettes define which filters work together:
- **SHO**: S + H + O mapped to Red, Green, Blue
- **HOO**: H + O (with synthetic green)
- **LRGB**: L + R + G + B (natural colors)

### 4. Target Types Recommend Palettes

| Target Type | Recommended Palette | Why |
|-------------|---------------------|-----|
| Emission Nebula | SHO | Strong emission lines |
| Galaxy | LRGB | Natural star colors |
| Reflection Nebula | LRGB | Shows dust colors |
| Planetary Nebula | SHO | Strong OIII emission |

### 5. Target Plans Use Palettes

When you create a target and choose a palette, a **plan** is generated:
- Calculates total imaging time based on target type
- Distributes time across channels based on weights
- Sets default sub-exposure lengths

### 6. Filter Wheels Map to NINA

For export to work, your physical filter wheel positions must match:
- Position 0 → LP filter
- Position 5 → H filter (NINA name: "Ha")
- etc.

---

## Palettes

### What Is a Palette?

A palette defines:
1. **Which filters** are used together
2. **What RGB channel** each filter maps to
3. **Relative weights** for exposure distribution
4. **Default exposures** per filter

### Built-in System Palettes

| Palette | Channels | Best For |
|---------|----------|----------|
| **SHO** | S→Red, H→Green, O→Blue | Emission nebulae, SNR |
| **HOO** | H→Red, O→Blue | Simpler emission imaging |
| **LRGB** | L→Lum, R→Red, G→Green, B→Blue | Galaxies, clusters |
| **LRGBNB** | LRGB + H + O | Galaxies with nebulosity |

### Palette Structure (JSON)

```json
{
  "channels": [
    {
      "name": "H",           // Short code (links to Filter)
      "label": "Ha",         // Display label
      "filter": "Hydrogen Alpha",  // Full filter name
      "rgb_channel": "green",      // Color mapping (red/green/blue/luminance)
      "default_exposure": 300,     // Seconds
      "default_weight": 1.0        // Relative importance
    }
  ]
}
```

### Creating Custom Palettes

1. Go to **Settings** → **Palettes**
2. Click **New Palette**
3. Enter:
   - **Name**: Short code (e.g., `CUSTOM_HOO`)
   - **Display Name**: Human-readable (e.g., "My Custom HOO Blend")
   - **Description**: When to use this palette
4. Add channels:
   - Select filter (H, O, S, etc.)
   - Set RGB mapping (which color channel)
   - Set weight (relative exposure time)
   - Set default exposure (seconds)
5. Save

### RGB Channel Mapping

The `rgb_channel` determines how the filter data is used in the final image:

| RGB Channel | Purpose | Typical Filters |
|-------------|---------|-----------------|
| `red` | Red color channel | S (SHO), H (HOO), R (LRGB) |
| `green` | Green color channel | H (SHO), G (LRGB) |
| `blue` | Blue color channel | O (SHO/HOO), B (LRGB) |
| `luminance` | Detail/brightness layer | L (LRGB) |

### Weight System

Weights control how imaging time is distributed:

**Example: SHO with weights 0.5, 0.3, 0.2**
- Total planned time: 6 hours (360 minutes)
- H (0.5): 180 minutes
- O (0.3): 108 minutes
- S (0.2): 72 minutes

Weights are **relative**, not absolute—they're normalized to sum to 1.0.

---

## Filters

### Filter Definition

Each filter in ArmillaryLab has:

| Field | Description | Example |
|-------|-------------|---------|
| `name` | Short code (unique) | `H` |
| `display_name` | Full name | `ZWO H-Alpha 7nm 1.25"` |
| `filter_type` | Classification | `narrowband` |
| `default_exposure` | Suggested sub length | `300` (seconds) |
| `astrobin_id` | Equipment database ID | `1955` |
| `is_system` | Built-in vs custom | `true` |
| `is_active` | Currently usable | `true` |

### Built-in Filters

ArmillaryLab includes these default filters:

| Code | Display Name | Type | Default Exposure |
|------|--------------|------|------------------|
| H | Hydrogen Alpha | narrowband | 300s |
| O | Oxygen III | narrowband | 300s |
| S | Sulfur II | narrowband | 300s |
| L | Luminance | broadband | 180s |
| R | Red | broadband | 180s |
| G | Green | broadband | 180s |
| B | Blue | broadband | 180s |
| LP | Light Pollution | other | 300s |

### Creating Custom Filters

1. Go to **Settings** → **Filters**
2. Click **New Filter**
3. Enter:
   - **Name**: Short code (e.g., `UV`)
   - **Display Name**: Full description
   - **Filter Type**: narrowband/broadband/other
   - **Default Exposure**: Suggested sub length
   - **AstroBin ID**: (optional) for export tracking
4. Save

### When to Create Custom Filters

- You have a filter not in the defaults (UV, IR, Duo-band)
- You want different default exposures
- You need specific AstroBin tracking

---

## Filter Wheels

### What Is a Filter Wheel Profile?

A filter wheel profile maps your **physical hardware** to ArmillaryLab:
- Which filter is in which position
- What NINA calls each filter
- Only **one wheel can be active** at a time

### Why Filter Wheels Matter

For NINA export to work correctly:
1. ArmillaryLab needs to know filter positions
2. Filter names must match NINA's expectations
3. Positions must be 0-indexed (matching NINA)

### Creating a Filter Wheel

1. Go to **Settings** → **Filter Wheels**
2. Click **New Filter Wheel**
3. Enter:
   - **Name**: Descriptive (e.g., "ZWO 8-Slot EFW")
   - **Slot Count**: Number of positions (5, 7, 8)
   - **Filter Size**: Physical size (1.25", 2", 36mm)
4. For each slot:
   - **Position**: 0-indexed number
   - **Filter**: Select from your filters
   - **NINA Name**: What NINA expects (Ha, OIII, SII, L, R, G, B)
5. Save

### Slot Configuration

| Position | Filter | NINA Name | Notes |
|----------|--------|-----------|-------|
| 0 | LP | LP | Light pollution |
| 1 | L | L | Luminance |
| 2 | R | R | Red |
| 3 | G | G | Green |
| 4 | B | B | Blue |
| 5 | H | Ha | Note: "Ha" not "H" |
| 6 | S | SII | Note: "SII" not "S" |
| 7 | O | OIII | Note: "OIII" not "O" |

### NINA Name Mapping

NINA uses specific filter names. Common mappings:

| ArmillaryLab | NINA Name |
|--------------|-----------|
| H | Ha, H-Alpha |
| O | OIII, O-III |
| S | SII, S-II |
| L | L, Lum |
| R | R, Red |
| G | G, Green |
| B | B, Blue |

> ⚠️ **Important**: The NINA Name must **exactly match** your NINA profile!

### Activating a Filter Wheel

Only one filter wheel can be active at a time:

1. Go to **Settings** → **Filter Wheels**
2. Find your wheel
3. Click **Set as Active**
4. Confirm the change

The active wheel is used for:
- NINA sequence exports
- Filter position display
- Equipment tracking

---

## Target Plans

### What Is a Target Plan?

A target plan specifies exactly how you'll image a specific target:

```json
{
  "channels": [
    {
      "name": "H",
      "label": "Ha",
      "planned_minutes": 180,
      "sub_exposure_seconds": 300,
      "weight": 0.5,
      "weight_fraction": 0.5
    },
    {
      "name": "O",
      "label": "OIII", 
      "planned_minutes": 108,
      "sub_exposure_seconds": 300,
      "weight": 0.3,
      "weight_fraction": 0.3
    }
  ],
  "total_planned_minutes": 360,
  "palette": "SHO"
}
```

### How Plans Are Generated

1. **Target type** determines base total time:
   - Emission: 360 min
   - Galaxy: 420 min
   - Cluster: 300 min

2. **Bortle scale** adjusts total:
   - Bortle 8-9: +30% more time
   - Bortle 6-7: +10% more time

3. **Palette weights** distribute time across channels

### Editing Plans

On the target detail page, you can:

1. **Change Total Time**: Rescales all channels proportionally
2. **Adjust Individual Channels**: Override specific channel minutes
3. **Change Sub-Exposure**: Modify exposure length per channel
4. **Add Custom Channels**: Add filters not in the original palette

### Plan vs Progress

- **Plan**: What you intend to capture
- **Progress**: What you've actually captured (from sessions)
- **Remaining**: Plan minus Progress (exported to NINA)

---

## Custom Channels

### What Are Custom Channels?

Sometimes you need channels beyond the standard palette:

- **HDR imaging**: Multiple exposure lengths for the same filter
- **Special filters**: UV, IR, or duo-band filters
- **Experimentation**: Testing different approaches

### Adding Custom Channels

On the target edit page:

1. Scroll to "Add Custom Channel"
2. Enter:
   - **Name**: Unique identifier (e.g., `H_HDR_1`)
   - **Label**: Display name (e.g., "Ha HDR Long")
   - **NINA Filter**: Base filter for export (e.g., `H`)
   - **Minutes**: Planned time
   - **Exposure**: Sub length in seconds
   - **Weight**: Relative importance
3. Save the plan

### NINA Filter Mapping for Custom Channels

Custom channels need to map to real filters for NINA export:

| Custom Channel | NINA Filter | Physical Filter |
|----------------|-------------|-----------------|
| H_HDR_1 | H | Ha (short exp) |
| H_HDR_2 | H | Ha (long exp) |
| O_HDR_1 | O | OIII (short exp) |

This ensures NINA uses the correct filter wheel position.

### HDR Workflow Example

For capturing the Orion Nebula (bright core + faint nebulosity):

| Channel | Label | NINA Filter | Exposure | Minutes |
|---------|-------|-------------|----------|---------|
| H_1 | Ha Short | H | 60s | 60 |
| H_2 | Ha Medium | H | 180s | 90 |
| H_3 | Ha Long | H | 300s | 120 |
| O_1 | OIII Short | O | 60s | 45 |
| O_2 | OIII Long | O | 300s | 90 |

All "H" variants map to the same physical Ha filter.

---

## Workflow Examples

### Example 1: New Emission Nebula Project

1. **Create Target**
   - Name: "IC 1805 - Heart Nebula"
   - Type: Emission
   - (Automatically recommends SHO palette)

2. **Review Generated Plan**
   - Total: ~470 min (Bortle 8 adjustment)
   - H: 235 min (50%)
   - O: 141 min (30%)
   - S: 94 min (20%)

3. **Customize if Needed**
   - Maybe increase S time for more red detail
   - Adjust sub-exposures based on your seeing

4. **Start Imaging**
   - Log sessions as you capture data
   - Progress updates automatically

5. **Export to NINA**
   - Exports only remaining subs
   - Uses correct filter positions

### Example 2: Galaxy with LRGB

1. **Create Target**
   - Name: "M81 - Bode's Galaxy"
   - Type: Galaxy
   - Select LRGB palette

2. **Review Plan**
   - L: Heavy weighting (50%)
   - RGB: Equal weighting

3. **Configure for Good Seeing**
   - Maybe reduce L sub-exposure to 120s
   - RGB can stay at 180s

### Example 3: Custom HDR Palette

1. **Create Custom Palette**
   - Name: `SHO_HDR`
   - Add channels with multiple exposure lengths

2. **Assign to Target**
   - Select your custom palette
   - Plan generates with your channels

3. **Image and Track**
   - Log sessions per channel
   - Each custom channel tracked separately

---

## Troubleshooting

### "Palette not found for target"

**Cause**: Target references a palette that was deleted.

**Solution**: Edit the target and select an existing palette.

### "Filter X not in filter wheel"

**Cause**: Your plan includes a filter not assigned to any wheel slot.

**Solution**: 
1. Go to Settings → Filter Wheels
2. Edit the active wheel
3. Assign the missing filter to a slot

### "NINA export has wrong filter positions"

**Cause**: Filter wheel positions don't match NINA.

**Solution**:
1. Check your NINA profile filter assignments
2. Update ArmillaryLab wheel to match
3. Verify NINA Names are correct

### "Custom channel not exporting correctly"

**Cause**: Missing NINA Filter mapping.

**Solution**:
1. Edit the target plan
2. Set the NINA Filter field for custom channels
3. Re-export

### "Weights don't add up to 100%"

**Cause**: Weights are relative, not percentages.

**Solution**: Weights are normalized automatically. `0.5, 0.3, 0.2` becomes `50%, 30%, 20%`.

### "Plan shows 0 minutes for a channel"

**Cause**: Channel weight is 0 or total time is 0.

**Solution**: 
1. Edit the plan
2. Set proper weight or minutes for the channel

---

## Quick Reference

### Palette Types

| Palette | Filters | Use Case |
|---------|---------|----------|
| SHO | S, H, O | Emission nebulae |
| HOO | H, O | Quick narrowband |
| LRGB | L, R, G, B | Galaxies, clusters |
| LRGBNB | L, R, G, B, H, O | Galaxies + nebulosity |

### Filter Types

| Type | Examples | Typical Exposure |
|------|----------|------------------|
| Narrowband | H, O, S | 300-600s |
| Broadband | L, R, G, B | 60-180s |
| Other | LP, UV, IR | Varies |

### Target Type Recommendations

| Type | Palette | Total Time |
|------|---------|------------|
| Emission | SHO | 6+ hours |
| Galaxy | LRGB | 7+ hours |
| Cluster | LRGB | 5+ hours |
| Reflection | LRGB | 6+ hours |
| Planetary | SHO | 6+ hours |

---

## Related Documentation

- [Equipment Presets Guide](PRESETS_GUIDE.md) - Configure filters and presets
- [NINA Integration Guide](NINA_INTEGRATION.md) - Export to NINA
- [AstroBin Export Guide](ASTROBIN_EXPORT.md) - Export for AstroBin
