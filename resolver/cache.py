"""Persistent ResolverCache backed by the ``resolver_cache`` DB table.

Sits between the user-facing API entry point and the ResolverChain:

    cached = cache.get(input_name)
    if cached: return cached
    obj = chain.resolve(input_name)
    cache.put(input_name, obj)
    return obj

Negative caching: failed lookups are stored with ``negative=True`` and a
shorter TTL so repeated bad queries don't hammer the network. Re-raises
``ResolverError`` on read of a fresh negative entry.

Concurrency: writes are best-effort; race conditions on the unique
``input_key`` are caught with ``IntegrityError`` and treated as
"someone else cached it first, ignore".

Flask coupling: cache requires an active app context (to access the
``ResolverCache`` model). When no app context is available (e.g. pure
unit tests with no Flask), the cache silently degrades to a no-op so
that the rest of the chain still works.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
from typing import Optional

from resolver.types import ResolvedObject, ResolverError

logger = logging.getLogger(__name__)


# TTLs are intentionally short relative to catalog change cadence:
#   * Positive entries: 90 days (object coordinates / metadata are stable).
#   * Negative entries: 1 day (give upstream services a chance to recover).
DEFAULT_POSITIVE_TTL_DAYS = 90
DEFAULT_NEGATIVE_TTL_DAYS = 1


def _input_key(raw: str) -> str:
    """Stable cache key: stripped, whitespace-collapsed, casefolded."""
    if not raw:
        return ""
    return " ".join(raw.split()).casefold()


def _now() -> _dt.datetime:
    return _dt.datetime.utcnow()


def _is_expired(resolved_at: _dt.datetime, ttl_days: int) -> bool:
    if not resolved_at or ttl_days <= 0:
        return True
    return (_now() - resolved_at) > _dt.timedelta(days=ttl_days)


def _get_models():
    """Return (db, ResolverCache) if Flask app context is active; else None."""
    try:
        from flask import has_app_context
        if not has_app_context():
            return None
        from app import db, ResolverCache
        return db, ResolverCache
    except Exception as exc:  # pragma: no cover — only on import failure
        logger.debug("ResolverCache: app/db unavailable (%s); cache disabled", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lookup(raw_name: str) -> Optional[ResolvedObject]:
    """Return cached ``ResolvedObject`` for ``raw_name``, or None if missing
    or expired. Re-raises ``ResolverError`` if a *fresh* negative entry exists.
    """
    models = _get_models()
    if models is None:
        return None
    _, ResolverCache = models

    key = _input_key(raw_name)
    if not key:
        return None

    row = ResolverCache.query.filter_by(input_key=key).first()
    if row is None:
        return None
    if _is_expired(row.resolved_at, row.ttl_days):
        return None

    if row.negative:
        # Reproduce the original failure semantics
        raise ResolverError(query=raw_name, attempts=[
            (raw_name, row.source or "cache", "previously failed (negative-cached)"),
        ])

    try:
        common = json.loads(row.common_names_json) if row.common_names_json else []
    except Exception:
        common = []
    try:
        aliases = json.loads(row.catalog_aliases_json) if row.catalog_aliases_json else []
    except Exception:
        aliases = []

    return ResolvedObject(
        canonical_name=row.canonical_name or "",
        ra_hours=float(row.ra_hours) if row.ra_hours is not None else 0.0,
        dec_deg=float(row.dec_deg) if row.dec_deg is not None else 0.0,
        object_type=row.object_type or "",
        target_type=row.target_type or "other",
        common_names=common,
        catalog_aliases=aliases,
        magnitude=row.magnitude,
        source=row.source or "cache",
        confidence=1.0,
        input_name=raw_name.strip(),
        matched_variant=raw_name.strip(),
        cached=True,
    )


def store(raw_name: str, obj: ResolvedObject,
          ttl_days: int = DEFAULT_POSITIVE_TTL_DAYS) -> None:
    """Insert or update a positive cache row for ``raw_name``."""
    models = _get_models()
    if models is None:
        return
    db, ResolverCache = models

    key = _input_key(raw_name)
    if not key:
        return

    common_json = json.dumps(list(obj.common_names or []), ensure_ascii=False)
    aliases_json = json.dumps(list(obj.catalog_aliases or []), ensure_ascii=False)
    try:
        row = ResolverCache.query.filter_by(input_key=key).first()
        if row is None:
            row = ResolverCache(input_key=key)
            db.session.add(row)
        row.canonical_name = obj.canonical_name
        row.ra_hours = float(obj.ra_hours)
        row.dec_deg = float(obj.dec_deg)
        row.object_type = obj.object_type or ""
        row.target_type = obj.target_type or "other"
        row.common_names_json = common_json
        row.catalog_aliases_json = aliases_json
        row.magnitude = obj.magnitude
        row.source = obj.source or "unknown"
        row.negative = False
        row.resolved_at = _now()
        row.ttl_days = ttl_days
        db.session.commit()
    except Exception as exc:
        logger.warning("ResolverCache: failed to store %r: %s", key, exc)
        try:
            db.session.rollback()
        except Exception:
            pass


def store_negative(raw_name: str, attempts: list[tuple[str, str, str]] | None = None,
                   ttl_days: int = DEFAULT_NEGATIVE_TTL_DAYS) -> None:
    """Record a failed resolution so we don't repeatedly retry the same
    impossible query for ``ttl_days`` days."""
    models = _get_models()
    if models is None:
        return
    db, ResolverCache = models

    key = _input_key(raw_name)
    if not key:
        return

    try:
        row = ResolverCache.query.filter_by(input_key=key).first()
        if row is None:
            row = ResolverCache(input_key=key)
            db.session.add(row)
        row.canonical_name = None
        row.ra_hours = None
        row.dec_deg = None
        row.object_type = None
        row.target_type = None
        row.common_names_json = json.dumps(attempts or [])
        row.magnitude = None
        row.source = "negative"
        row.negative = True
        row.resolved_at = _now()
        row.ttl_days = ttl_days
        db.session.commit()
    except Exception as exc:
        logger.warning("ResolverCache: failed to store negative %r: %s", key, exc)
        try:
            db.session.rollback()
        except Exception:
            pass


def purge_expired() -> int:
    """Delete expired rows. Returns the number of rows removed.

    Called by the ``flask resolver-cache-purge`` CLI in Phase 8.
    """
    models = _get_models()
    if models is None:
        return 0
    db, ResolverCache = models

    now = _now()
    removed = 0
    try:
        for row in ResolverCache.query.all():
            if _is_expired(row.resolved_at, row.ttl_days):
                db.session.delete(row)
                removed += 1
        if removed:
            db.session.commit()
    except Exception as exc:
        logger.warning("ResolverCache: purge failed: %s", exc)
        try:
            db.session.rollback()
        except Exception:
            pass
    return removed


def clear_all() -> int:
    """Drop every row. For tests / admin reset."""
    models = _get_models()
    if models is None:
        return 0
    db, ResolverCache = models
    try:
        count = ResolverCache.query.delete()
        db.session.commit()
        return count
    except Exception as exc:
        logger.warning("ResolverCache: clear_all failed: %s", exc)
        try:
            db.session.rollback()
        except Exception:
            pass
        return 0


def resolve_with_cache(raw_name: str, chain) -> ResolvedObject:
    """Convenience: lookup → resolve → cache → apply ObjectMapping override.

    The chain argument is injected so tests can pass a fake chain.
    """
    from resolver.overrides import apply_override

    try:
        cached = lookup(raw_name)
        if cached is not None:
            return apply_override(cached)
    except ResolverError:
        # Fresh negative entry — re-raise without retrying the chain
        raise

    try:
        obj = chain.resolve(raw_name)
    except ResolverError as exc:
        store_negative(raw_name, attempts=exc.attempts)
        raise

    store(raw_name, obj)
    obj.cached = False
    return apply_override(obj)
