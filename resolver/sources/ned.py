"""NedResolver — astroquery NED (NASA/IPAC Extragalactic Database) lookup.

NED is the authoritative source for extragalactic objects (galaxies,
quasars, clusters of galaxies). We use it as a fallback when SIMBAD
fails to resolve a name — particularly useful for catalog IDs like
"UGC 12158", "MCG +05-31-145", "ESO 137-G006".
"""
from __future__ import annotations

import logging
from typing import Optional

from resolver.base import Resolver
from resolver.types import ResolvedObject

logger = logging.getLogger(__name__)


# NED's `Type` column → ArmillaryLab canonical target_type.
_NED_TYPE_MAP: dict[str, str] = {
    "G":    "galaxy",
    "GPair":"galaxy",
    "GTrpl":"galaxy",
    "GGroup":"galaxy",
    "GClstr":"galaxy",
    "QSO":  "galaxy",
    "AbLS": "galaxy",
    "EmLS": "galaxy",
    "RadioS":"other",
    "IrS":  "other",
    "UvS":  "other",
    "XrayS":"other",
    "PofG": "galaxy",
    "HII":  "emission",
    "PN":   "planetary",
    "SNR":  "supernova_remnant",
    "*Cl":  "cluster",
    "GClstr":"galaxy",
    "Neb":  "emission",
    "RfN":  "reflection",
    "*":    "other",
}


def _map_ned_type(t: str | None) -> str:
    if not t:
        return "other"
    t = t.strip()
    return _NED_TYPE_MAP.get(t, "other")


class NedResolver(Resolver):
    name = "ned"
    requires_network = True
    default_confidence = 0.9

    def is_available(self) -> bool:
        try:
            from astroquery.ipac.ned import Ned  # noqa: F401
            return True
        except Exception:
            try:
                from astroquery.ned import Ned  # noqa: F401  (older path)
                return True
            except Exception:
                return False

    def _get_ned(self):
        try:
            from astroquery.ipac.ned import Ned
        except Exception:
            from astroquery.ned import Ned
        return Ned

    def resolve(self, query: str) -> Optional[ResolvedObject]:
        if not query:
            return None
        try:
            Ned = self._get_ned()
        except Exception as exc:
            logger.warning("NED: import failed: %s", exc)
            return None

        try:
            table = Ned.query_object(query)
        except Exception as exc:
            logger.debug("NED: transport error on %r: %s", query, exc)
            return None

        if table is None or len(table) == 0:
            return None

        row = table[0]
        try:
            ra_deg = float(row["RA"])
            dec_deg = float(row["DEC"])
        except Exception:
            try:
                ra_deg = float(row["RA(deg)"])
                dec_deg = float(row["DEC(deg)"])
            except Exception as exc:
                logger.debug("NED: coord parse failed: %s", exc)
                return None

        try:
            main_id = str(row["Object Name"]).strip()
        except Exception:
            main_id = query

        try:
            ned_type = str(row["Type"]).strip()
        except Exception:
            ned_type = ""

        ra_hours = ra_deg / 15.0
        target_type = _map_ned_type(ned_type)

        return ResolvedObject(
            canonical_name=main_id,
            ra_hours=ra_hours,
            dec_deg=dec_deg,
            object_type=ned_type,
            target_type=target_type,
            common_names=[],
            magnitude=None,
            source=self.name,
            confidence=self.default_confidence,
            matched_variant=query,
        )
