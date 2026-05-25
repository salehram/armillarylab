"""SimbadResolver — astroquery SIMBAD lookup.

SIMBAD has the most comprehensive name index for galactic + nearby
extragalactic objects: catalog IDs (NGC, IC, M, Sh2, vdB, LBN, …),
common names, and a stable object-type taxonomy we can map onto our
8 canonical target_type values.

This resolver:
    * lazy-imports astroquery so the package is optional;
    * requests extra fields (otype, flux_V, ids) to enrich the result;
    * silently returns None on miss / disambiguation / network error
      (the chain handles fallback to NED, VizieR, Sesame).
"""
from __future__ import annotations

import logging
from typing import Optional

from resolver.base import Resolver
from resolver.types import ResolvedObject

logger = logging.getLogger(__name__)


# SIMBAD's `otype` short codes → ArmillaryLab canonical target_type.
# References: http://simbad.u-strasbg.fr/simbad/sim-display?data=otypes
_SIMBAD_OTYPE_MAP: dict[str, str] = {
    # Emission / HII regions
    "HII": "emission", "EmO": "emission", "EmG": "emission",
    # Reflection
    "RNe": "reflection", "ISM": "diffuse",
    # Diffuse / dark
    "MoC": "diffuse", "DNe": "diffuse",
    # Planetary nebulae
    "PN":  "planetary", "PN?": "planetary",
    # Supernova remnants
    "SNR": "supernova_remnant", "SR?": "supernova_remnant", "sh":  "supernova_remnant",
    # Galaxies (and their many subtypes — collapsed to "galaxy")
    "G":   "galaxy", "Sy1": "galaxy", "Sy2": "galaxy", "AGN": "galaxy",
    "QSO": "galaxy", "GiG": "galaxy", "GiC": "galaxy", "GiP": "galaxy",
    "BiC": "galaxy", "rG":  "galaxy", "H2G": "galaxy", "LSB": "galaxy",
    "IG":  "galaxy", "PaG": "galaxy", "GrG": "galaxy", "CGG": "galaxy",
    "ClG": "galaxy", "SCG": "galaxy", "EmG": "galaxy",
    # Clusters
    "OpC": "cluster", "GlC": "cluster", "Cl*": "cluster", "As*": "cluster",
    # Generic nebula — default to emission (most common request type)
    "Cld": "emission", "GNe": "emission",
}


def _map_otype(otype: str | None) -> str:
    if not otype:
        return "other"
    t = otype.strip()
    if t in _SIMBAD_OTYPE_MAP:
        return _SIMBAD_OTYPE_MAP[t]
    # Heuristic suffix match (e.g. "GiCl" → galaxy)
    for key, val in _SIMBAD_OTYPE_MAP.items():
        if t.startswith(key):
            return val
    return "other"


class SimbadResolver(Resolver):
    name = "simbad"
    requires_network = True
    default_confidence = 0.95

    _client = None  # lazy-built astroquery Simbad instance

    def is_available(self) -> bool:
        try:
            from astroquery.simbad import Simbad  # noqa: F401
            return True
        except Exception:
            return False

    def _get_client(self):
        if self._client is not None:
            return self._client
        from astroquery.simbad import Simbad
        s = Simbad()
        s.TIMEOUT = 10
        # Newer (>=0.4.8) and older astroquery use different APIs for adding
        # extra columns; try the new one first.
        try:
            s.add_votable_fields("otype", "flux(V)", "ids")
        except Exception:
            try:
                s.add_votable_fields("otype", "flux(V)")
            except Exception as exc:
                logger.debug("SIMBAD: couldn't add votable fields: %s", exc)
        self._client = s
        return s

    def _extract_row_field(self, row, *candidates):
        """Return the first non-empty value from candidate column names."""
        for col in candidates:
            try:
                val = row[col]
            except Exception:
                continue
            if val is None:
                continue
            try:
                # astropy MaskedConstant ⇒ skip
                import numpy as _np
                if hasattr(val, "mask") and bool(getattr(val, "mask", False)):
                    continue
            except Exception:
                pass
            s = str(val).strip()
            if s and s.lower() != "nan" and s != "--":
                return s
        return None

    def resolve(self, query: str) -> Optional[ResolvedObject]:
        if not query:
            return None
        try:
            client = self._get_client()
        except Exception as exc:
            logger.warning("SIMBAD: client unavailable: %s", exc)
            return None

        try:
            table = client.query_object(query)
        except Exception as exc:
            logger.debug("SIMBAD: transport error on %r: %s", query, exc)
            return None

        if table is None or len(table) == 0:
            return None

        row = table[0]
        main_id = self._extract_row_field(row, "MAIN_ID", "main_id")
        ra_str = self._extract_row_field(row, "RA", "ra")
        dec_str = self._extract_row_field(row, "DEC", "dec")
        if not ra_str or not dec_str:
            return None

        # Parse coords via astropy (handles "00 42 44.330" sexagesimal).
        try:
            from astropy.coordinates import SkyCoord
            import astropy.units as u
            coord = SkyCoord(ra_str, dec_str, unit=(u.hourangle, u.deg))
            ra_hours = float(coord.ra.hour)
            dec_deg = float(coord.dec.degree)
        except Exception as exc:
            logger.debug("SIMBAD: coord parse failed for %r: %s", query, exc)
            return None

        otype = self._extract_row_field(row, "OTYPE", "otype")
        target_type = _map_otype(otype)

        vmag = self._extract_row_field(row, "FLUX_V", "flux_V", "V")
        try:
            magnitude = float(vmag) if vmag is not None else None
        except (TypeError, ValueError):
            magnitude = None

        # SIMBAD's IDS field is a pipe-separated list of cross-catalog
        # designations (NGC, M, IC, HD, 2MASS, ...). These are catalog
        # IDs, not human nicknames, so they go to catalog_aliases.
        aliases: list[str] = []
        ids_raw = self._extract_row_field(row, "IDS", "ids")
        if ids_raw:
            for piece in ids_raw.split("|"):
                p = piece.strip()
                if p and p != main_id:
                    aliases.append(p)
            aliases = aliases[:12]

        return ResolvedObject(
            canonical_name=main_id or query,
            ra_hours=ra_hours,
            dec_deg=dec_deg,
            object_type=otype or "",
            target_type=target_type,
            common_names=[],
            catalog_aliases=aliases,
            magnitude=magnitude,
            source=self.name,
            confidence=self.default_confidence,
            matched_variant=query,
        )
