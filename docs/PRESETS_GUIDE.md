# AstroPlanner Equipment Presets Guide

This guide explains the Equipment Preset System in AstroPlanner, which allows you to save, share, and reuse filter configurations and filter wheel setups across different installations or with other users.

---

## Table of Contents

1. [Overview](#overview)
2. [Built-in Presets](#built-in-presets)
3. [Preset File Format](#preset-file-format)
4. [Using Presets via CLI](#using-presets-via-cli)
5. [Using Presets via Web UI](#using-presets-via-web-ui)
6. [Creating Custom Presets](#creating-custom-presets)
7. [Sharing Presets](#sharing-presets)
8. [Best Practices](#best-practices)

---

## Overview

The preset system solves several common problems:

- **Initial Setup**: Quickly configure filters with correct AstroBin IDs
- **Equipment Sharing**: Share your filter configuration with imaging partners
- **Backup**: Export your current setup before making changes
- **Brand-Specific Configs**: Use manufacturer-specific presets (e.g., ZWO filters)

### What's Included in a Preset?

| Component | Description |
|-----------|-------------|
| **Filters** | Filter definitions (name, display name, type, exposure, AstroBin ID) |
| **Filter Wheels** | Hardware profiles with slot assignments (optional) |
| **Target Types** | Classification system with recommended palettes (base preset only) |
| **Palettes** | Color palette definitions like SHO, HOO, LRGB (base preset only) |

---

## Built-in Presets

AstroPlanner includes several built-in presets in the `config/presets/` directory:

### Base Preset (`config/presets/base.json`)

The foundational preset loaded during database initialization. Contains:

- **8 Target Types**: emission, diffuse, reflection, galaxy, cluster, planetary, supernova_remnant, other
- **4 Palettes**: SHO, HOO, LRGB, LRGBNB
- **Default Filter Wheel**: 8-slot 1.25" configuration

### Filter Presets (`config/presets/filters/`)

| Preset | Description | AstroBin IDs |
|--------|-------------|--------------|
| `generic.json` | Standard filters with generic names | ❌ None (configure manually) |
| `zwo.json` | ZWO 1.25" narrowband (7nm) and LRGB | ✅ Included |

---

## Preset File Format

### Filter Preset Structure

```json
{
  "version": "1.0",
  "brand": "Your Brand Name",
  "description": "Description of this filter set",
  
  "filters": [
    {
      "name": "H",
      "display_name": "Hydrogen Alpha 7nm",
      "filter_type": "narrowband",
      "default_exposure": 300,
      "astrobin_id": 1955
    }
  ]
}
```

### Field Reference

| Field | Required | Description |
|-------|----------|-------------|
| `version` | Yes | Preset format version (currently "1.0") |
| `brand` | No | Manufacturer or brand name |
| `description` | Yes | Human-readable description |
| `filters` | Yes | Array of filter definitions |
| `filter_wheels` | No | Array of filter wheel configurations |

### Filter Object Fields

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `name` | Yes | String | Short code (H, O, S, L, R, G, B, LP) |
| `display_name` | Yes | String | Full descriptive name |
| `filter_type` | Yes | String | `narrowband`, `broadband`, or `other` |
| `default_exposure` | Yes | Integer | Default exposure time in seconds |
| `astrobin_id` | No | Integer | AstroBin equipment database ID |

### Filter Wheel Object Fields (Optional)

```json
{
  "filter_wheels": [
    {
      "name": "ZWO 8-Slot EFW",
      "slot_count": 8,
      "filter_size": "1.25\"",
      "is_default": true,
      "slots": [
        {"position": 0, "filter_code": "LP", "nina_name": "LP"},
        {"position": 1, "filter_code": "L", "nina_name": "L"},
        {"position": 2, "filter_code": "R", "nina_name": "R"}
      ]
    }
  ]
}
```

---

## Using Presets via CLI

### List Available Presets

```powershell
flask list-presets
```

**Output:**
```
Available filter presets:
--------------------------------------------------

  generic
    Name: Generic Filters
    Filters: 8
    AstroBin: ✗ No AstroBin IDs
    Description: Standard filter set with generic names

  zwo
    Name: ZWO Filters
    Filters: 8
    AstroBin: ✓ AstroBin IDs
    Description: ZWO 1.25" narrowband (7nm) and LRGB filters

--------------------------------------------------
Usage: flask init-db --filter-preset <preset_name>
```

### Initialize Database with a Preset

```powershell
# Use the ZWO preset (includes AstroBin IDs)
flask init-db --filter-preset zwo

# Use generic filters
flask init-db --filter-preset generic

# Default (uses base.json)
flask init-db
```

### Export Current Configuration

```powershell
# Export filters only
flask export-preset my_filters.json

# Export filters AND filter wheels
flask export-preset my_complete_setup.json --include-wheels
```

### Import a Preset File

```powershell
# Replace all existing filters
flask import-preset my_filters.json

# Merge with existing filters (update existing, add new)
flask import-preset my_filters.json --merge

# Include filter wheel configurations
flask import-preset my_setup.json --include-wheels
```

---

## Using Presets via Web UI

### Accessing Preset Features

Navigate to **Settings** → **Filters** to access preset functionality.

### Apply AstroBin IDs from Preset

If you have existing filters but want to update their AstroBin IDs:

1. Go to **Settings** → **Filters**
2. Look for the "Apply AstroBin IDs" section
3. Select a preset (e.g., "zwo")
4. Click **Apply**

This will update AstroBin IDs for any filters that match the preset's filter names without changing your other filter settings.

### Export Configuration (Web)

1. Go to **Settings**
2. Click **Export Configuration**
3. Choose what to include:
   - ☑️ Filters
   - ☑️ Filter Wheels (optional)
4. Download the JSON file

### Import Configuration (Web)

1. Go to **Settings**
2. Click **Import Configuration**
3. Select your JSON preset file
4. Choose import mode:
   - **Replace**: Remove existing, import new
   - **Merge**: Update existing, add new
5. Click **Import**

---

## Creating Custom Presets

### Step 1: Export Your Current Setup

Start by exporting your working configuration:

```powershell
flask export-preset my_equipment.json --include-wheels
```

### Step 2: Edit the JSON File

Open `my_equipment.json` and customize:

```json
{
  "preset_name": "My Observatory Setup",
  "description": "Custom filter configuration for my imaging rig",
  
  "filters": [
    {
      "name": "H",
      "display_name": "Antlia H-Alpha Pro 3nm",
      "filter_type": "narrowband",
      "default_exposure": 600,
      "astrobin_id": 4523
    },
    {
      "name": "O",
      "display_name": "Antlia OIII Pro 3nm",
      "filter_type": "narrowband", 
      "default_exposure": 600,
      "astrobin_id": 4524
    }
  ],
  
  "filter_wheels": [
    {
      "name": "ZWO 7x36mm EFW",
      "slot_count": 7,
      "filter_size": "36mm",
      "is_default": true,
      "slots": [
        {"position": 0, "filter_code": "L", "nina_name": "L"},
        {"position": 1, "filter_code": "R", "nina_name": "R"},
        {"position": 2, "filter_code": "G", "nina_name": "G"},
        {"position": 3, "filter_code": "B", "nina_name": "B"},
        {"position": 4, "filter_code": "H", "nina_name": "Ha"},
        {"position": 5, "filter_code": "O", "nina_name": "OIII"},
        {"position": 6, "filter_code": "S", "nina_name": "SII"}
      ]
    }
  ]
}
```

### Step 3: Add to Presets Directory (Optional)

To make your preset appear in the CLI list:

```powershell
copy my_equipment.json config\presets\filters\my_equipment.json
```

Now you can use:
```powershell
flask init-db --filter-preset my_equipment
```

---

## Finding AstroBin Filter IDs

AstroBin uses numeric IDs to identify equipment. To find your filter's ID:

1. Go to [AstroBin Equipment Database](https://www.astrobin.com/equipment/)
2. Search for your filter
3. Open the filter page
4. Look at the URL: `https://www.astrobin.com/equipment/filter/1955/`
5. The ID is the number: **1955**

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

---

## Sharing Presets

### Sharing with Other Users

1. Export your configuration:
   ```powershell
   flask export-preset observatory_setup.json --include-wheels
   ```

2. Share the JSON file via:
   - Email
   - Cloud storage (Dropbox, Google Drive)
   - Git repository
   - Astronomy forums

3. Recipients can import:
   ```powershell
   flask import-preset observatory_setup.json --include-wheels
   ```

### Contributing to Built-in Presets

If you create a useful preset for common equipment:

1. Create a well-documented JSON file
2. Test it thoroughly
3. Submit a Pull Request to add it to `config/presets/filters/`

---

## Best Practices

### Naming Conventions

- Use **short codes** for filter names: `H`, `O`, `S`, `L`, `R`, `G`, `B`, `LP`
- Use **descriptive display names**: "ZWO H-Alpha 7nm 1.25\""
- Keep NINA names consistent with your NINA profile

### AstroBin IDs

- Always include AstroBin IDs for accurate equipment tracking
- Verify IDs match your exact filter model
- Different sizes (1.25" vs 2") have different IDs

### Backup Before Changes

Before importing or replacing:
```powershell
flask export-preset backup_$(Get-Date -Format "yyyyMMdd").json --include-wheels
```

### Version Your Presets

Include version information in your preset files:
```json
{
  "version": "1.0",
  "preset_name": "My Setup v2",
  "description": "Updated January 2026 with new filters"
}
```

---

## Troubleshooting

### "Preset not found"

Ensure the preset file is in the correct location:
- CLI presets: `config/presets/filters/<name>.json`
- Import files: Any accessible path

### "No filters found to update"

When applying AstroBin IDs, the preset's filter `name` fields must match your existing filter names (H, O, S, etc.).

### "Filter wheel slot assignment failed"

Ensure all filters referenced in wheel slots exist in your database. Import filters first, then filter wheels.

### Import Replaces Everything

By default, `import-preset` replaces all existing filters. Use `--merge` to preserve existing configurations:
```powershell
flask import-preset new_filters.json --merge
```

---

## Related Documentation

- [Database Configuration Guide](DATABASE_GUIDE.md) - Database setup and migration
- [NINA Integration Guide](NINA_INTEGRATION.md) - Telescope integration and exports
- [AstroBin Export Guide](ASTROBIN_EXPORT.md) - CSV export for AstroBin uploads
