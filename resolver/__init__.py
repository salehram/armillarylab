"""
Astronomical object name resolution package.

Public entry points:
    resolve(name)            -> ResolvedObject
    resolve_coords(name)     -> (ra_hours, dec_deg)   [back-compat shim]
    normalize(raw)           -> list[str]             [candidate query variants]

Architecture (layered, first hit wins):
    1. Input normalizer            (resolver.normalizer)
    2. Cache lookup                (resolver.cache, added in Phase 4)
    3. Resolver chain              (resolver.chain)
         a. LocalCatalogResolver       offline bundled JSON
         b. ObjectMappingResolver      user overrides / aliases (Phase 6)
         c. SimbadResolver             astroquery SIMBAD (Phase 5)
         d. NedResolver                astroquery NED   (Phase 5)
         e. VizierResolver             astroquery VizieR (Phase 5)
         f. SesameResolver             astropy SkyCoord.from_name (legacy fallback)
    4. Result enricher (target_type mapping)
    5. Cache store
"""
from __future__ import annotations

from resolver.types import ResolvedObject, ResolverError
from resolver.normalizer import normalize
from resolver.chain import ResolverChain, get_default_chain, reset_default_chain


def resolve(name: str) -> ResolvedObject:
    """Resolve ``name`` via the process-wide default chain.

    Raises ``ResolverError`` if no source could match the name.
    """
    return get_default_chain().resolve(name)


def resolve_coords(name: str) -> tuple[float, float]:
    """Back-compat shim: ``(ra_hours, dec_deg)`` like the original
    ``astro_utils.resolve_target_name``."""
    obj = resolve(name)
    return obj.ra_hours, obj.dec_deg


__all__ = [
    "ResolvedObject",
    "ResolverError",
    "ResolverChain",
    "normalize",
    "resolve",
    "resolve_coords",
    "get_default_chain",
    "reset_default_chain",
]
