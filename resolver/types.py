"""Resolver result types and exceptions."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


class ResolverError(RuntimeError):
    """Raised when no resolver in the chain can resolve a name.

    Carries a list of (variant, resolver_name, error_message) attempts for
    diagnostics. The string form is suitable for displaying to end users.
    """

    def __init__(self, query: str, attempts: list[tuple[str, str, str]] | None = None):
        self.query = query
        self.attempts = attempts or []
        super().__init__(self._format())

    def _format(self) -> str:
        if not self.attempts:
            return f"Could not resolve '{self.query}'."
        tried = ", ".join(sorted({v for v, _, _ in self.attempts}))
        return (
            f"Could not resolve '{self.query}'. Tried variants: {tried}. "
            f"No resolver in the chain returned a match."
        )


@dataclass
class ResolvedObject:
    """Canonical resolved astronomical object.

    Fields:
        canonical_name: Authoritative catalog name (e.g. 'NGC 6992').
        ra_hours: Right ascension in decimal hours.
        dec_deg: Declination in decimal degrees.
        object_type: Raw upstream object type string (e.g. SIMBAD 'SNR',
            local-catalog 'supernova_remnant', or '' if unknown).
        target_type: ArmillaryLab canonical target type, one of:
            emission, diffuse, reflection, galaxy, cluster, planetary,
            supernova_remnant, other.
        common_names: Human-readable nicknames (e.g. ['Eastern Veil
            Nebula', 'Network Nebula']).
        catalog_aliases: Cross-catalog designations for the same object
            (e.g. ['NGC 6992', 'Caldwell 33']). Separate from
            ``common_names`` so the UI can display them differently.
        magnitude: Visual magnitude if known.
        source: Name of the resolver that produced this result
            (e.g. 'local_catalog', 'simbad', 'sesame').
        confidence: 0.0..1.0; 1.0 for trusted local catalog matches, lower
            for fuzzy / network fallbacks.
        input_name: The original user-supplied name (pre-normalization).
        matched_variant: The normalized variant that resolved.
        cached: True if served from cache.
    """

    canonical_name: str
    ra_hours: float
    dec_deg: float
    object_type: str = ""
    target_type: str = "other"
    common_names: list[str] = field(default_factory=list)
    catalog_aliases: list[str] = field(default_factory=list)
    magnitude: Optional[float] = None
    source: str = "unknown"
    confidence: float = 1.0
    input_name: str = ""
    matched_variant: str = ""
    cached: bool = False

    def differs_from_input(self) -> bool:
        """True if the canonical name is meaningfully different from the
        user's typed input (after whitespace/case normalization)."""
        a = (self.input_name or "").replace(" ", "").upper()
        b = (self.canonical_name or "").replace(" ", "").upper()
        return bool(a) and bool(b) and a != b

    def to_api_dict(self) -> dict:
        """Render as the dict returned by GET /api/resolve.

        Backwards compatible: includes legacy fields (name, ra_hours,
        dec_deg, suggested_type) consumed by templates/target_form.html.
        """
        return {
            # Legacy fields (do not remove)
            "name": self.input_name or self.canonical_name,
            "ra_hours": self.ra_hours,
            "dec_deg": self.dec_deg,
            "suggested_type": self.target_type,
            # Enriched fields (added in Phase 7)
            "canonical_name": self.canonical_name,
            "object_type": self.object_type,
            "common_names": list(self.common_names),
            "catalog_aliases": list(self.catalog_aliases),
            "magnitude": self.magnitude,
            "source": self.source,
            "confidence": self.confidence,
            "matched_variant": self.matched_variant,
            "cached": self.cached,
            "differs_from_input": self.differs_from_input(),
        }

    def as_dict(self) -> dict:
        return asdict(self)
