# Resolver Data

Static reference catalogs bundled with ArmillaryLab. These files are produced
by `scripts/build_resolver_catalogs.py` (run during development, **not** at
runtime by the Flask app) and are committed to the repository as shipped
data.

## Files

| File              | Source                                     | Entries (typ.) |
|-------------------|--------------------------------------------|----------------|
| `ngc_ic.json`     | OpenNGC (mattiaverga/OpenNGC, CC-BY-SA 4.0) | ~13,000        |
| `messier.json`    | Derived from OpenNGC `M` column            | 110            |
| `caldwell.json`   | Sir Patrick Moore's Caldwell Catalogue (public domain) joined with OpenNGC coords | ~106 |
| `nicknames.json`  | Flattened common-name → catalog-id map     | varies         |

## Schema (per entry)

```jsonc
{
  "catalog_id":   "NGC 6992",          // canonical primary name
  "ra_hours":     20.946667,           // decimal hours (J2000)
  "dec_deg":      31.716667,           // decimal degrees (J2000)
  "object_type":  "SNR",               // raw upstream type code
  "target_type":  "supernova_remnant", // ArmillaryLab canonical (one of 8)
  "common_names": ["Eastern Veil Nebula"],
  "magnitude":    7.0,                 // V-mag if known, else B-mag, else null
  "aliases":      ["M 31", "Caldwell 33"] // catalog-style alternate IDs
}
```

## Regenerating

```bash
python scripts/build_resolver_catalogs.py            # downloads upstream
python scripts/build_resolver_catalogs.py --offline  # uses scripts/_catalog_cache/
```

## Licensing & Attribution

OpenNGC data is CC-BY-SA 4.0. Attribution must remain in
`docs/THIRD_PARTY_LICENSES.md`.
