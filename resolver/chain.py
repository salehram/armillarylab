"""ResolverChain — orchestrates input normalization and the source pipeline.

Pipeline per resolve() call:

    1. Normalize raw input → ordered list of variants (e.g. "C 33" →
       ["C 33", "Caldwell 33", "c33"]).
    2. For each variant, walk the configured resolvers in priority order.
    3. First resolver to return a non-None ResolvedObject wins.
    4. If every (variant, resolver) pair misses → raise ResolverError
       carrying the diagnostic attempt list.

The chain itself is stateless and cheap to construct; resolvers may hold
lazy caches (LocalCatalogResolver does). Network resolvers (Sesame and
later SIMBAD/NED/VizieR) are expected to silently return None on miss
and only log on transport-level errors.
"""
from __future__ import annotations

import logging
import time
from typing import Iterable, Optional

from resolver.base import Resolver
from resolver.normalizer import normalize
from resolver.types import ResolvedObject, ResolverError

logger = logging.getLogger(__name__)


class ResolverChain:
    def __init__(self, resolvers: Iterable[Resolver]):
        self._resolvers: list[Resolver] = list(resolvers)
        if not self._resolvers:
            raise ValueError("ResolverChain requires at least one resolver")

    @property
    def resolvers(self) -> list[Resolver]:
        return list(self._resolvers)

    def resolve(self, raw_name: str) -> ResolvedObject:
        """Resolve ``raw_name`` through the configured chain.

        Returns the first successful ``ResolvedObject``. Raises
        ``ResolverError`` if no (variant, resolver) pair matched.
        """
        input_name = (raw_name or "").strip()
        if not input_name:
            raise ResolverError(query=raw_name or "", attempts=[])

        variants = normalize(input_name)
        if not variants:
            variants = [input_name]

        attempts: list[tuple[str, str, str]] = []

        for variant in variants:
            for resolver in self._resolvers:
                if not resolver.is_available():
                    attempts.append((variant, resolver.name, "unavailable"))
                    continue
                t0 = time.monotonic()
                try:
                    result = resolver.resolve(variant)
                except Exception as exc:  # defensive: resolver bug should not abort chain
                    elapsed = (time.monotonic() - t0) * 1000
                    logger.exception(
                        "Resolver %s crashed on %r after %.1fms",
                        resolver.name, variant, elapsed,
                    )
                    attempts.append((variant, resolver.name, f"error: {exc}"))
                    continue
                elapsed = (time.monotonic() - t0) * 1000

                if result is None:
                    attempts.append((variant, resolver.name, "miss"))
                    logger.debug(
                        "Resolver %s missed %r in %.1fms", resolver.name, variant, elapsed,
                    )
                    continue

                # Hit. Stamp provenance fields the source may have left blank.
                result.input_name = input_name
                if not result.matched_variant:
                    result.matched_variant = variant
                if not result.source:
                    result.source = resolver.name
                logger.info(
                    "Resolver %s resolved %r→%r in %.1fms (via variant %r)",
                    resolver.name, input_name, result.canonical_name, elapsed, variant,
                )
                return result

        raise ResolverError(query=input_name, attempts=attempts)


# ---------------------------------------------------------------------------
# Default chain construction
# ---------------------------------------------------------------------------

_default_chain: Optional[ResolverChain] = None


def get_default_chain() -> ResolverChain:
    """Return the process-wide default chain.

    Honors runtime ``GlobalConfig`` toggles when a Flask app context is
    available (``resolver_enable_simbad``, ``resolver_offline_mode``,
    etc.); otherwise builds a permissive default chain.

    The chain is rebuilt only when no cached chain exists. Use
    :func:`reset_default_chain` from the settings save path to pick up
    toggled flags.
    """
    global _default_chain
    if _default_chain is not None:
        return _default_chain

    from resolver.sources.local_catalog import LocalCatalogResolver
    from resolver.sources.simbad import SimbadResolver
    from resolver.sources.ned import NedResolver
    from resolver.sources.vizier import VizierResolver
    from resolver.sources.sesame import SesameResolver

    cfg = _load_resolver_config()
    sources: list[Resolver] = [LocalCatalogResolver()]
    if not cfg["offline_mode"]:
        if cfg["enable_simbad"]:
            sources.append(SimbadResolver())
        if cfg["enable_ned"]:
            sources.append(NedResolver())
        if cfg["enable_vizier"]:
            sources.append(VizierResolver())
        if cfg["enable_sesame"]:
            sources.append(SesameResolver())
    _default_chain = ResolverChain(sources)
    return _default_chain


def _load_resolver_config() -> dict:
    """Read resolver toggles from GlobalConfig if available."""
    defaults = {
        "enable_simbad": True,
        "enable_ned": True,
        "enable_vizier": True,
        "enable_sesame": True,
        "offline_mode": False,
    }
    try:
        from flask import has_app_context
        if not has_app_context():
            return defaults
        from app import GlobalConfig
        cfg = GlobalConfig.query.first()
        if cfg is None:
            return defaults
        return {
            "enable_simbad": bool(getattr(cfg, "resolver_enable_simbad", True)),
            "enable_ned":    bool(getattr(cfg, "resolver_enable_ned", True)),
            "enable_vizier": bool(getattr(cfg, "resolver_enable_vizier", True)),
            "enable_sesame": bool(getattr(cfg, "resolver_enable_sesame", True)),
            "offline_mode":  bool(getattr(cfg, "resolver_offline_mode", False)),
        }
    except Exception:
        return defaults


def reset_default_chain() -> None:
    """Clear the cached default chain. For tests only."""
    global _default_chain
    _default_chain = None
