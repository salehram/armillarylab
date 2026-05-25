"""VizierResolver — best-effort catalog-table lookup via astroquery VizieR.

VizieR doesn't have a single "resolve any name" endpoint like SIMBAD.
Instead it serves thousands of catalog tables. We use it as a thin
last-mile fallback (before Sesame) for a couple of specific catalogs
that SIMBAD/NED frequently miss:

    * Sharpless (Sh 2-N)  — VII/20 catalog
    * vdB (van den Bergh) — VII/21
    * LBN / LDN           — VII/9 / VII/7

Implementation is intentionally conservative: if anything looks off,
return None and let Sesame have the final word.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from resolver.base import Resolver
from resolver.types import ResolvedObject

logger = logging.getLogger(__name__)


# Map of input pattern → (VizieR catalog id, target_type, object_type label)
_CATALOG_RULES = [
    (re.compile(r"^(?:sh\s*2[\s-]*|sharpless\s*)(\d+)$", re.I), "VII/20", "emission", "Sharpless"),
    (re.compile(r"^vdb\s*(\d+)$", re.I),                       "VII/21", "reflection", "vdB"),
    (re.compile(r"^lbn\s*(\d+)$", re.I),                       "VII/9",  "emission", "LBN"),
    (re.compile(r"^ldn\s*(\d+)$", re.I),                       "VII/7",  "diffuse", "LDN"),
]


class VizierResolver(Resolver):
    name = "vizier"
    requires_network = True
    default_confidence = 0.8

    def is_available(self) -> bool:
        try:
            from astroquery.vizier import Vizier  # noqa: F401
            return True
        except Exception:
            return False

    def resolve(self, query: str) -> Optional[ResolvedObject]:
        if not query:
            return None
        q = query.strip()
        # Only attempt for catalogs we know how to handle
        matched_rule = None
        catalog_num = None
        for pat, cat_id, ttype, label in _CATALOG_RULES:
            m = pat.match(q)
            if m:
                matched_rule = (cat_id, ttype, label)
                catalog_num = m.group(1)
                break
        if matched_rule is None:
            return None

        cat_id, ttype, label = matched_rule

        try:
            from astroquery.vizier import Vizier
            from astropy.coordinates import SkyCoord
            import astropy.units as u
        except Exception as exc:
            logger.warning("VizieR: import failed: %s", exc)
            return None

        try:
            v = Vizier(columns=["**"], row_limit=1)
            v.TIMEOUT = 10
            # query_constraints is unreliable across catalogs; fall back to
            # query_object which performs name resolution against the catalog.
            result = v.query_object(q, catalog=[cat_id])
        except Exception as exc:
            logger.debug("VizieR: query failed for %r in %s: %s", q, cat_id, exc)
            return None

        if not result or len(result) == 0:
            return None
        try:
            table = result[0]
        except Exception:
            return None
        if table is None or len(table) == 0:
            return None

        row = table[0]
        # Locate RA / Dec columns heuristically (catalog-specific).
        ra_val = dec_val = None
        for col in table.colnames:
            cl = col.lower()
            if ra_val is None and cl in ("raj2000", "_raj2000", "ra", "ra2000"):
                ra_val = row[col]
            if dec_val is None and cl in ("dej2000", "_dej2000", "dec", "de2000"):
                dec_val = row[col]
        if ra_val is None or dec_val is None:
            return None

        try:
            coord = SkyCoord(str(ra_val), str(dec_val), unit=(u.hourangle, u.deg))
            ra_hours = float(coord.ra.hour)
            dec_deg = float(coord.dec.degree)
        except Exception:
            try:
                ra_hours = float(ra_val) / 15.0
                dec_deg = float(dec_val)
            except Exception as exc:
                logger.debug("VizieR: coord parse failed: %s", exc)
                return None

        canonical = f"{label} {catalog_num}"
        return ResolvedObject(
            canonical_name=canonical,
            ra_hours=ra_hours,
            dec_deg=dec_deg,
            object_type=label,
            target_type=ttype,
            common_names=[],
            magnitude=None,
            source=self.name,
            confidence=self.default_confidence,
            matched_variant=q,
        )
