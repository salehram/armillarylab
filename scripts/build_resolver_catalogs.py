"""Build local resolver catalog JSON files from authoritative public sources.

Run once (or after upstream data updates) to (re)generate:

    resolver/data/ngc_ic.json     — full NGC + IC catalog (~13,000 entries)
    resolver/data/messier.json    — 110 Messier objects (derived)
    resolver/data/caldwell.json   — 109 Caldwell objects (mapped to NGC/IC)
    resolver/data/nicknames.json  — common names → catalog ID

Data sources (public domain / open):
    * OpenNGC (mattiaverga/OpenNGC, CC-BY-SA 4.0) — NGC + IC primary table
      https://github.com/mattiaverga/OpenNGC

The script uses ``urllib.request`` (stdlib only) so it has no extra deps.
It is *not* invoked at runtime by the Flask app — it produces shipped
reference data that lives in the repo.

Usage:
    python scripts/build_resolver_catalogs.py
    python scripts/build_resolver_catalogs.py --offline   # use cached CSV only
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "resolver" / "data"
CACHE_DIR = REPO_ROOT / "scripts" / "_catalog_cache"

OPENNGC_CSV_URL = (
    "https://raw.githubusercontent.com/mattiaverga/OpenNGC/master/"
    "database_files/NGC.csv"
)


# Caldwell catalog → NGC/IC mapping (public-domain Sir Patrick Moore list).
# Format: caldwell_number -> (ngc_or_ic_id, common_name).
# Source: Moore, P., Caldwell Catalogue (1995), public domain.
CALDWELL_TO_NGC = {
    1:   ("NGC 188",  "Caldwell 1"),
    2:   ("NGC 40",   "Bow-Tie Nebula"),
    3:   ("NGC 4236", "Caldwell 3"),
    4:   ("NGC 7023", "Iris Nebula"),
    5:   ("IC 342",   "Hidden Galaxy"),
    6:   ("NGC 6543", "Cat's Eye Nebula"),
    7:   ("NGC 2403", "Caldwell 7"),
    8:   ("NGC 559",  "Caldwell 8"),
    9:   ("Sh2-155",  "Cave Nebula"),
    10:  ("NGC 663",  "Caldwell 10"),
    11:  ("NGC 7635", "Bubble Nebula"),
    12:  ("NGC 6946", "Fireworks Galaxy"),
    13:  ("NGC 457",  "Owl Cluster"),
    14:  ("NGC 869",  "Double Cluster (h Persei)"),
    15:  ("NGC 6826", "Blinking Planetary"),
    16:  ("NGC 7243", "Caldwell 16"),
    17:  ("NGC 147",  "Caldwell 17"),
    18:  ("NGC 185",  "Caldwell 18"),
    19:  ("IC 5146",  "Cocoon Nebula"),
    20:  ("NGC 7000", "North America Nebula"),
    21:  ("NGC 4449", "Caldwell 21"),
    22:  ("NGC 7662", "Blue Snowball"),
    23:  ("NGC 891",  "Caldwell 23"),
    24:  ("NGC 1275", "Perseus A"),
    25:  ("NGC 2419", "Intergalactic Wanderer"),
    26:  ("NGC 4244", "Silver Needle Galaxy"),
    27:  ("NGC 6888", "Crescent Nebula"),
    28:  ("NGC 752",  "Caldwell 28"),
    29:  ("NGC 5005", "Caldwell 29"),
    30:  ("NGC 7331", "Caldwell 30"),
    31:  ("IC 405",   "Flaming Star Nebula"),
    32:  ("NGC 4631", "Whale Galaxy"),
    33:  ("NGC 6992", "Eastern Veil Nebula"),
    34:  ("NGC 6960", "Western Veil Nebula"),
    35:  ("NGC 4889", "Caldwell 35"),
    36:  ("NGC 4559", "Caldwell 36"),
    37:  ("NGC 6885", "Caldwell 37"),
    38:  ("NGC 4565", "Needle Galaxy"),
    39:  ("NGC 2392", "Lion Nebula (Eskimo)"),
    40:  ("NGC 3626", "Caldwell 40"),
    41:  ("Mel 25",   "Hyades"),
    42:  ("NGC 7006", "Caldwell 42"),
    43:  ("NGC 7814", "Little Sombrero"),
    44:  ("NGC 7479", "Superman Galaxy"),
    45:  ("NGC 5248", "Caldwell 45"),
    46:  ("NGC 2261", "Hubble's Variable Nebula"),
    47:  ("NGC 6934", "Caldwell 47"),
    48:  ("NGC 2775", "Caldwell 48"),
    49:  ("NGC 2237", "Rosette Nebula"),
    50:  ("NGC 2244", "Rosette Cluster"),
    51:  ("IC 1613",  "Caldwell 51"),
    52:  ("NGC 4697", "Caldwell 52"),
    53:  ("NGC 3115", "Spindle Galaxy"),
    54:  ("NGC 2506", "Caldwell 54"),
    55:  ("NGC 7009", "Saturn Nebula"),
    56:  ("NGC 246",  "Skull Nebula"),
    57:  ("NGC 6822", "Barnard's Galaxy"),
    58:  ("NGC 2360", "Caroline's Cluster"),
    59:  ("NGC 3242", "Ghost of Jupiter"),
    60:  ("NGC 4038", "Antennae Galaxies"),
    61:  ("NGC 4039", "Antennae Galaxies"),
    62:  ("NGC 247",  "Caldwell 62"),
    63:  ("NGC 7293", "Helix Nebula"),
    64:  ("NGC 2362", "Tau Canis Majoris Cluster"),
    65:  ("NGC 253",  "Sculptor Galaxy"),
    66:  ("NGC 5694", "Caldwell 66"),
    67:  ("NGC 1097", "Caldwell 67"),
    68:  ("NGC 6729", "Caldwell 68"),
    69:  ("NGC 6302", "Bug Nebula"),
    70:  ("NGC 300",  "Caldwell 70"),
    71:  ("NGC 2477", "Caldwell 71"),
    72:  ("NGC 55",   "Caldwell 72"),
    73:  ("NGC 1851", "Caldwell 73"),
    74:  ("NGC 3132", "Eight-Burst Nebula"),
    75:  ("NGC 6124", "Caldwell 75"),
    76:  ("NGC 6231", "Caldwell 76"),
    77:  ("NGC 5128", "Centaurus A"),
    78:  ("NGC 6541", "Caldwell 78"),
    79:  ("NGC 3201", "Caldwell 79"),
    80:  ("NGC 5139", "Omega Centauri"),
    81:  ("NGC 6352", "Caldwell 81"),
    82:  ("NGC 6193", "Caldwell 82"),
    83:  ("NGC 4945", "Caldwell 83"),
    84:  ("NGC 5286", "Caldwell 84"),
    85:  ("IC 2391",  "Omicron Velorum Cluster"),
    86:  ("NGC 6397", "Caldwell 86"),
    87:  ("NGC 1261", "Caldwell 87"),
    88:  ("NGC 5823", "Caldwell 88"),
    89:  ("NGC 6087", "S Normae Cluster"),
    90:  ("NGC 2867", "Caldwell 90"),
    91:  ("NGC 3532", "Wishing Well Cluster"),
    92:  ("NGC 3372", "Carina Nebula"),
    93:  ("NGC 6752", "Caldwell 93"),
    94:  ("NGC 4755", "Jewel Box"),
    95:  ("NGC 6025", "Caldwell 95"),
    96:  ("NGC 2516", "Caldwell 96"),
    97:  ("NGC 3766", "Pearl Cluster"),
    98:  ("NGC 4609", "Caldwell 98"),
    99:  ("Coalsack", "Coalsack Nebula"),
    100: ("IC 2944",  "Lambda Centauri Cluster"),
    101: ("NGC 6744", "Caldwell 101"),
    102: ("IC 2602",  "Southern Pleiades"),
    103: ("NGC 2070", "Tarantula Nebula"),
    104: ("NGC 362",  "Caldwell 104"),
    105: ("NGC 4833", "Caldwell 105"),
    106: ("NGC 104",  "47 Tucanae"),
    107: ("NGC 6101", "Caldwell 107"),
    108: ("NGC 4372", "Caldwell 108"),
    109: ("NGC 3195", "Caldwell 109"),
}


# Map OpenNGC "Type" column → ArmillaryLab canonical target_type.
# OpenNGC type codes documented at https://github.com/mattiaverga/OpenNGC#type
TYPE_MAP = {
    "G":    "galaxy",      # Galaxy
    "GPair":"galaxy",
    "GTrpl":"galaxy",
    "GGroup":"galaxy",
    "PN":   "planetary",   # Planetary Nebula
    "SNR":  "supernova_remnant",
    "HII":  "emission",    # HII Ionized region
    "EmN":  "emission",    # Emission Nebula
    "RfN":  "reflection",  # Reflection Nebula
    "Cl+N": "emission",    # Cluster + Nebulosity (usually emission)
    "Neb":  "emission",    # Generic nebula → emission default
    "DrkN": "diffuse",     # Dark nebula
    "OCl":  "cluster",     # Open Cluster
    "GCl":  "cluster",     # Globular Cluster
    "*":    "other",       # Single star
    "**":   "other",       # Double star
    "*Ass": "other",       # Stellar association
    "Other":"other",
    "NonEx":"other",
    "Dup":  "other",
}


def _http_get(url: str) -> bytes:
    print(f"  Downloading: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "ArmillaryLab-resolver-build/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # nosec - trusted source
        return resp.read()


def _fetch_openngc_csv(offline: bool) -> str:
    """Return the OpenNGC CSV text, using a local cache when possible."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / "openngc_NGC.csv"

    if cache_path.exists():
        print(f"  Using cached CSV: {cache_path}")
        return cache_path.read_text(encoding="utf-8")

    if offline:
        sys.exit(f"ERROR: --offline set but no cache at {cache_path}")

    raw = _http_get(OPENNGC_CSV_URL)
    text = raw.decode("utf-8", errors="replace")
    cache_path.write_text(text, encoding="utf-8")
    return text


def _parse_ra_hours(ra_str: str) -> float | None:
    """OpenNGC RA is 'HH:MM:SS.ss'. Returns decimal hours, or None."""
    if not ra_str or ra_str.strip() == "":
        return None
    try:
        h, m, s = ra_str.split(":")
        return float(h) + float(m) / 60.0 + float(s) / 3600.0
    except (ValueError, IndexError):
        return None


def _parse_dec_deg(dec_str: str) -> float | None:
    """OpenNGC Dec is '+DD:MM:SS.ss' or '-DD:MM:SS.ss'."""
    if not dec_str or dec_str.strip() == "":
        return None
    try:
        sign = -1.0 if dec_str.lstrip().startswith("-") else 1.0
        clean = dec_str.lstrip("+-").strip()
        d, m, s = clean.split(":")
        return sign * (float(d) + float(m) / 60.0 + float(s) / 3600.0)
    except (ValueError, IndexError):
        return None


def _safe_float(s: str) -> float | None:
    if not s or s.strip() == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _split_names(s: str) -> list[str]:
    """OpenNGC 'Common names' is comma-separated."""
    if not s:
        return []
    return [n.strip() for n in s.split(",") if n.strip()]


def build_ngc_ic_messier(csv_text: str) -> tuple[list[dict], list[dict]]:
    """Parse OpenNGC CSV → (ngc_ic_entries, messier_entries).

    Each entry dict has the schema consumed by LocalCatalogResolver:
        catalog_id:    canonical primary name (e.g. "NGC 6992")
        ra_hours:      float
        dec_deg:       float
        object_type:   raw OpenNGC type (e.g. "SNR")
        target_type:   canonical 8 (e.g. "supernova_remnant")
        common_names:  list[str] (free-form aliases)
        magnitude:     float | None (V-mag if available, else B-mag)
        aliases:       list[str] (catalog-style aliases, e.g. ["M 31", "Caldwell 33"])
    """
    reader = csv.DictReader(io.StringIO(csv_text), delimiter=";")
    ngc_ic: list[dict] = []
    messier: list[dict] = []

    for row in reader:
        name = (row.get("Name") or "").strip()
        if not name:
            continue
        # Skip duplicate / non-existent entries
        otype_raw = (row.get("Type") or "").strip()
        if otype_raw in ("Dup", "NonEx"):
            continue

        ra = _parse_ra_hours(row.get("RA", ""))
        dec = _parse_dec_deg(row.get("Dec", ""))
        if ra is None or dec is None:
            continue

        # Canonicalize primary name: "NGC0224" → "NGC 224", "IC1805" → "IC 1805"
        m = re.match(r"^(NGC|IC)(\d+)([A-Z]?)$", name)
        if m:
            canonical = f"{m.group(1)} {int(m.group(2))}{m.group(3)}"
        else:
            canonical = name

        vmag = _safe_float(row.get("V-Mag", ""))
        bmag = _safe_float(row.get("B-Mag", ""))
        magnitude = vmag if vmag is not None else bmag

        common = _split_names(row.get("Common names", ""))

        messier_num = (row.get("M") or "").strip().lstrip("0")
        aliases: list[str] = []
        if messier_num:
            aliases.append(f"M {messier_num}")

        target_type = TYPE_MAP.get(otype_raw, "other")

        entry = {
            "catalog_id": canonical,
            "ra_hours": round(ra, 6),
            "dec_deg": round(dec, 6),
            "object_type": otype_raw,
            "target_type": target_type,
            "common_names": common,
            "magnitude": magnitude,
            "aliases": aliases,
        }
        ngc_ic.append(entry)

        if messier_num:
            messier_entry = dict(entry)
            messier_entry["catalog_id"] = f"M {messier_num}"
            messier_entry["aliases"] = [canonical] + [a for a in aliases if a != f"M {messier_num}"]
            messier.append(messier_entry)

    # Sort for deterministic output
    def _sort_key(e):
        return e["catalog_id"]
    ngc_ic.sort(key=_sort_key)

    def _messier_sort(e):
        try:
            return int(e["catalog_id"].split()[1])
        except (IndexError, ValueError):
            return 9999
    messier.sort(key=_messier_sort)
    return ngc_ic, messier


def build_caldwell(ngc_ic: list[dict]) -> list[dict]:
    """Build Caldwell entries by joining the Moore mapping with NGC/IC coords.

    Side effect: appends the Caldwell designation to the source NGC/IC
    entry's ``aliases`` list so reverse lookups ("NGC 6992 is also
    Caldwell 33") surface in the API response.
    """
    index = {e["catalog_id"]: e for e in ngc_ic}
    caldwell: list[dict] = []
    missing: list[int] = []
    for num in sorted(CALDWELL_TO_NGC):
        ngc_id, common_name = CALDWELL_TO_NGC[num]
        src = index.get(ngc_id)
        if src is None:
            missing.append(num)
            continue
        entry = {
            "catalog_id": f"Caldwell {num}",
            "ra_hours": src["ra_hours"],
            "dec_deg": src["dec_deg"],
            "object_type": src["object_type"],
            "target_type": src["target_type"],
            "common_names": [common_name] + [c for c in src["common_names"] if c != common_name],
            "magnitude": src["magnitude"],
            "aliases": [ngc_id, f"C {num}", f"C{num}"],
        }
        caldwell.append(entry)
        # Reverse alias: NGC X also catalogued as Caldwell N.
        for back in (f"Caldwell {num}", f"C {num}"):
            if back not in src["aliases"]:
                src["aliases"].append(back)
    if missing:
        print(f"  Note: {len(missing)} Caldwell entries skipped (non-NGC/IC primary): {missing}")
    return caldwell


def _propagate_messier_reverse_aliases(ngc_ic: list[dict], messier: list[dict]) -> None:
    """Append 'M N' to each NGC/IC entry that has a Messier alias."""
    by_id = {e["catalog_id"]: e for e in ngc_ic}
    for m in messier:
        m_id = m["catalog_id"]  # e.g. "M 31"
        for ngc_id in m.get("aliases", []):
            src = by_id.get(ngc_id)
            if src is not None and m_id not in src["aliases"]:
                src["aliases"].append(m_id)


def build_nicknames(*catalogs: list[dict]) -> dict[str, str]:
    """Flatten common_names → primary catalog_id mapping for fast nickname lookup."""
    nicknames: dict[str, str] = {}
    for cat in catalogs:
        for entry in cat:
            for name in entry["common_names"]:
                # Use casefold key to allow case-insensitive lookup
                key = name.casefold()
                # Don't overwrite — first catalog wins (Messier > NGC/IC > Caldwell)
                nicknames.setdefault(key, entry["catalog_id"])
    return nicknames


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true",
                        help="Use cached CSV only; do not download.")
    args = parser.parse_args()

    print("Building local resolver catalogs...")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/4] Fetching OpenNGC...")
    csv_text = _fetch_openngc_csv(offline=args.offline)

    print("[2/4] Parsing NGC/IC + Messier...")
    ngc_ic, messier = build_ngc_ic_messier(csv_text)
    print(f"      NGC/IC entries: {len(ngc_ic)}")
    print(f"      Messier entries: {len(messier)}")

    print("[3/4] Building Caldwell from Moore mapping...")
    caldwell = build_caldwell(ngc_ic)
    print(f"      Caldwell entries: {len(caldwell)}")

    # Now that Caldwell entries have side-effected back-aliases into
    # ngc_ic, also propagate Messier reverse aliases.
    _propagate_messier_reverse_aliases(ngc_ic, messier)

    print("[4/4] Building nicknames index...")
    nicknames = build_nicknames(messier, caldwell, ngc_ic)
    print(f"      Nicknames: {len(nicknames)}")

    def _write(path: Path, data) -> None:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        size_kb = path.stat().st_size / 1024
        print(f"  Wrote {path.relative_to(REPO_ROOT)} ({size_kb:.1f} KB)")

    _write(DATA_DIR / "ngc_ic.json", ngc_ic)
    _write(DATA_DIR / "messier.json", messier)
    _write(DATA_DIR / "caldwell.json", caldwell)
    _write(DATA_DIR / "nicknames.json", nicknames)
    print("Done.")


if __name__ == "__main__":
    main()
