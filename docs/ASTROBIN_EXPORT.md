# AstroBin Export Guide

This guide explains how to export your imaging sessions from ArmillaryLab in a format compatible with [AstroBin](https://www.astrobin.com/), the premier astrophotography image hosting platform.

---

## Table of Contents

1. [Overview](#overview)
2. [Understanding AstroBin CSV Format](#understanding-astrobin-csv-format)
3. [Setting Up Filter IDs](#setting-up-filter-ids)
4. [Exporting Sessions](#exporting-sessions)
5. [Uploading to AstroBin](#uploading-to-astrbin)
6. [Custom Filters and Channel Mapping](#custom-filters-and-channel-mapping)
7. [Troubleshooting](#troubleshooting)

---

## Overview

ArmillaryLab can export your imaging sessions as CSV files that can be directly imported into AstroBin's acquisition data system. This provides:

- **Accurate Equipment Tracking**: Filter IDs link to AstroBin's equipment database
- **Session Consolidation**: Multiple sessions with the same filter are combined
- **Complete Metadata**: Exposure times, dates, binning, gain, and more
- **Time Savings**: No manual data entry on AstroBin

### What Gets Exported?

| Field | Description |
|-------|-------------|
| `date` | Imaging date (YYYY-MM-DD) |
| `filter` | AstroBin filter ID or filter name |
| `number` | Total sub count |
| `duration` | Sub exposure time in seconds |
| `binning` | Sensor binning (e.g., 1, 2) |
| `gain` | Camera gain setting |
| `sensorCooling` | Sensor temperature in °C |
| `darks` | Number of dark frames (optional) |
| `flats` | Number of flat frames (optional) |
| `flatDarks` | Number of flat-dark frames (optional) |
| `bias` | Number of bias frames (optional) |
| `bortle` | Bortle sky quality scale (optional) |

---

## Understanding AstroBin CSV Format

AstroBin accepts acquisition data in CSV format with specific column requirements.

### Required Columns

```csv
date,filter,number,duration,binning,gain,sensorCooling
2026-01-15,1955,20,300,1,100,-10
2026-01-15,2707,15,300,1,100,-10
```

### Column Descriptions

| Column | Type | Description |
|--------|------|-------------|
| `date` | Date | Imaging date in ISO format (YYYY-MM-DD) |
| `filter` | Integer/String | AstroBin filter ID (preferred) or filter name |
| `number` | Integer | Number of sub-exposures |
| `duration` | Integer | Sub-exposure duration in seconds |
| `binning` | Integer | Sensor binning level (1, 2, etc.) |
| `gain` | Integer | Camera gain/ISO setting |
| `sensorCooling` | Integer | Sensor cooling temperature in °C |

### Optional Columns

| Column | Type | Description |
|--------|------|-------------|
| `darks` | Integer | Number of dark calibration frames |
| `flats` | Integer | Number of flat calibration frames |
| `flatDarks` | Integer | Number of flat-dark frames |
| `bias` | Integer | Number of bias frames |
| `bortle` | Integer | Bortle scale (1-9) for sky quality |

---

## Setting Up Filter IDs

For best results, configure AstroBin Equipment IDs for your filters. This ensures proper equipment tracking on AstroBin.

### Finding Your Filter's AstroBin ID

1. Go to [AstroBin Equipment Database](https://www.astrobin.com/equipment/)
2. Search for your filter (e.g., "ZWO H-Alpha")
3. Click on the matching result
4. Look at the URL: `https://www.astrobin.com/equipment/filter/1955/`
5. The ID is the number at the end: **1955**

### Configuring Filter IDs in ArmillaryLab

#### Method 1: Apply from Preset

If using common equipment:

1. Go to **Settings** → **Filters**
2. Find "Apply AstroBin IDs from Preset"
3. Select preset (e.g., "zwo" for ZWO filters)
4. Click **Apply**

#### Method 2: Manual Configuration

1. Go to **Settings** → **Filters**
2. Click **Edit** next to a filter
3. Enter the AstroBin ID in the designated field
4. Click **Save**

### Common AstroBin Filter IDs

| Filter | Brand | AstroBin ID |
|--------|-------|-------------|
| H-Alpha 7nm | ZWO | 1955 |
| OIII 7nm | ZWO | 2707 |
| SII 7nm | ZWO | 2260 |
| Luminance | ZWO | 1958 |
| Red | ZWO | 1956 |
| Green | ZWO | 1954 |
| Blue | ZWO | 1957 |
| L-Pro | Optolong | 5501 |
| L-eXtreme | Optolong | 6391 |

> 💡 **Tip**: Search AstroBin's equipment database for your exact filter model to get the correct ID.

---

## Exporting Sessions

### Prerequisites

- Target must have recorded imaging sessions
- For best results, configure AstroBin filter IDs

### Export Process

1. Navigate to your target's detail page
2. Scroll to the **Export** section
3. Click **Export to AstroBin**
4. Configure export settings:

   | Setting | Default | Description |
   |---------|---------|-------------|
   | Binning | 1 | Your sensor binning level |
   | Gain | 100 | Camera gain setting used |
   | Sensor Cooling | -10 | Sensor temperature in °C |
   | Bortle | (empty) | Sky quality (1-9, optional) |
   | Darks | (empty) | Dark frame count (optional) |
   | Flats | (empty) | Flat frame count (optional) |
   | Flat Darks | (empty) | Flat-dark count (optional) |
   | Bias | (empty) | Bias frame count (optional) |

5. Click **Download CSV**

### Export Example

For a target with these sessions:
- Jan 15: 20× Ha 300s
- Jan 15: 15× OIII 300s
- Jan 16: 25× Ha 300s

The CSV output:
```csv
date,filter,number,duration,binning,gain,sensorCooling
2026-01-15,1955,20,300,1,100,-10
2026-01-15,2707,15,300,1,100,-10
2026-01-16,1955,25,300,1,100,-10
```

---

## Uploading to AstroBin

### Step 1: Upload Your Image

1. Log into [AstroBin](https://www.astrobin.com/)
2. Click **Upload** 
3. Select your processed image
4. Fill in basic image details

### Step 2: Import Acquisition Data

1. After upload, go to the image's edit page
2. Find **Acquisition** section
3. Look for **Import CSV** or **Import acquisition data**
4. Select the CSV file exported from ArmillaryLab
5. Click **Import**

### Step 3: Verify Data

Review the imported acquisition data:
- Check filter assignments are correct
- Verify exposure counts and durations
- Confirm dates match your sessions

### Step 4: Complete Equipment Profile

The imported data links to your equipment profile:
- Filter IDs connect to AstroBin's equipment database
- This enables equipment-based search and statistics
- Other users can see what filters you used

---

## Custom Filters and Channel Mapping

### Understanding Channel Mapping

When you create custom filter channels (like separate HDR channels), ArmillaryLab intelligently maps them to base filters for export.

### Example: HDR Workflow

You might have:
| Channel | Description | Base Filter | AstroBin ID |
|---------|-------------|-------------|-------------|
| H_1 | Ha standard | H | 1955 |
| H_2 | Ha long | H | 1955 |
| O_1 | OIII standard | O | 2707 |
| O_2 | OIII long | O | 2707 |

ArmillaryLab automatically:
1. Maps H_1 and H_2 sessions to filter "H"
2. Uses AstroBin ID 1955 for H
3. Consolidates sessions by date and base filter

### How Mapping Works

1. When you create a custom channel, you assign a "NINA Filter"
2. This NINA Filter links to your base filter
3. During export:
   - ArmillaryLab reads the channel → NINA Filter mapping
   - Looks up the AstroBin ID for that filter
   - Exports with the correct ID

### Verifying Mappings

To check your channel mappings:
1. View your target's plan
2. Note each channel and its associated filter
3. Confirm filters have AstroBin IDs configured

---

## Best Practices

### Before Imaging

1. **Configure Filter IDs**: Set up AstroBin IDs before starting a project
2. **Use Presets**: Apply brand presets for automatic ID configuration
3. **Verify Equipment**: Ensure AstroBin IDs match your exact equipment

### During Imaging

1. **Log All Sessions**: Record every imaging session in ArmillaryLab
2. **Be Consistent**: Use the same gain/cooling settings when possible
3. **Track Calibration**: Note dark/flat/bias counts for complete data

### Before Export

1. **Review Sessions**: Check all sessions are logged correctly
2. **Check Mappings**: Verify custom channels map to correct base filters
3. **Note Settings**: Have your imaging settings ready (binning, gain, etc.)

### After Export

1. **Verify CSV**: Open the CSV to confirm data looks correct
2. **Import Promptly**: Import while session details are fresh
3. **Review on AstroBin**: Check imported data for accuracy

---

## Troubleshooting

### "No imaging sessions to export"

**Cause**: The target has no recorded sessions.

**Solution**: Log your imaging sessions on the target detail page before exporting.

### Filter shows name instead of ID in CSV

**Cause**: No AstroBin ID configured for that filter.

**Solution**: 
1. Go to **Settings** → **Filters**
2. Edit the filter
3. Add the AstroBin ID
4. Re-export

### Sessions not consolidating properly

**Cause**: Channel names differ between sessions.

**Solution**: 
- Ensure consistent channel naming in your plan
- Verify NINA Filter mappings are correct for custom channels

### Wrong filter ID in export

**Cause**: Incorrect AstroBin ID in filter configuration.

**Solution**:
1. Look up the correct ID on AstroBin's equipment database
2. Update the filter configuration
3. Re-export

### AstroBin import fails

**Cause**: CSV format incompatibility.

**Solution**:
- Check for special characters in data
- Verify date format is YYYY-MM-DD
- Ensure all required columns are present
- Try importing a smaller subset first

### Missing filters warning

**Cause**: Some filters in your sessions don't have AstroBin IDs.

**Solution**: The export will continue using filter names, but for proper equipment tracking:
1. Note which filters are flagged
2. Configure AstroBin IDs for those filters
3. Re-export if desired

---

## Related Documentation

- [Equipment Presets Guide](PRESETS_GUIDE.md) - Configure filters and AstroBin IDs
- [NINA Integration Guide](NINA_INTEGRATION.md) - Export to NINA Advanced Sequencer
- [Database Guide](DATABASE_GUIDE.md) - Database setup and configuration
