"""SesameResolver — legacy network fallback via astropy's CDS Sesame client.

This is the lowest-priority source in the chain. Its sole virtue is broad
catalog coverage (any name CDS Sesame indexes); its downsides are network
dependency, latency, no extra metadata (no object_type, no magnitude),
and patchy support for some catalogs (notoriously: ``C 33`` short form for
Caldwell — which is why we have higher-priority resolvers in front).
"""
from __future__ import annotations

import logging
from typing import Optional

from resolver.base import Resolver
from resolver.types import ResolvedObject

logger = logging.getLogger(__name__)


class SesameResolver(Resolver):
    name = "sesame"
    requires_network = True
    default_confidence = 0.7  # network lookups are less trusted than local catalogs

    def is_available(self) -> bool:
        try:
            from astropy.coordinates import SkyCoord  # noqa: F401
            return True
        except Exception:
            return False

    def resolve(self, query: str) -> Optional[ResolvedObject]:
        if not query:
            return None
        try:
            from astropy.coordinates import SkyCoord
        except Exception as exc:
            logger.warning("Sesame: astropy unavailable: %s", exc)
            return None

        try:
            coord = SkyCoord.from_name(query)
        except Exception as exc:
            # Clean miss — Sesame doesn't know this name. Return None per
            # Resolver protocol; the chain will keep walking or surface
            # ResolverError if every source misses.
            logger.debug("Sesame miss for %r: %s", query, exc)
            return None

        return ResolvedObject(
            canonical_name=query,  # Sesame doesn't tell us a canonical form
            ra_hours=float(coord.ra.hour),
            dec_deg=float(coord.dec.degree),
            object_type="",
            target_type="other",
            common_names=[],
            magnitude=None,
            source=self.name,
            confidence=self.default_confidence,
            matched_variant=query,
        )
