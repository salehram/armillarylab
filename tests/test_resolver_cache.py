"""Tests for the DB-backed ResolverCache.

Covers:
    * positive cache: store → lookup returns cached=True
    * negative cache: store_negative → lookup raises ResolverError
    * expiry: stale rows are ignored
    * resolve_with_cache: chain called once, second call served from cache
    * no app context: cache silently no-ops (does not crash)
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

import pytest

from resolver.base import Resolver
from resolver.chain import ResolverChain
from resolver.types import ResolvedObject, ResolverError


@pytest.fixture
def app_ctx():
    """Fresh in-memory DB with an active Flask app context."""
    from app import app, db
    app.config["TESTING"] = True
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _CountingResolver(Resolver):
    name = "counting"
    requires_network = False

    def __init__(self, payload: Optional[ResolvedObject] = None):
        self._payload = payload
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def resolve(self, query: str) -> Optional[ResolvedObject]:
        self.calls += 1
        return self._payload


def _veil_obj() -> ResolvedObject:
    return ResolvedObject(
        canonical_name="Caldwell 33",
        ra_hours=20.95, dec_deg=31.7,
        object_type="SNR", target_type="supernova_remnant",
        common_names=["Eastern Veil Nebula"],
        magnitude=7.0, source="local_catalog", confidence=1.0,
    )


# ---------------------------------------------------------------------------
# Direct API
# ---------------------------------------------------------------------------

class TestStoreLookup:
    def test_store_then_lookup_marks_cached(self, app_ctx):
        from resolver import cache
        cache.store("C 33", _veil_obj())
        hit = cache.lookup("C 33")
        assert hit is not None
        assert hit.cached is True
        assert hit.canonical_name == "Caldwell 33"
        assert hit.target_type == "supernova_remnant"
        assert hit.common_names == ["Eastern Veil Nebula"]
        assert hit.ra_hours == pytest.approx(20.95)

    def test_lookup_is_case_insensitive(self, app_ctx):
        from resolver import cache
        cache.store("c 33", _veil_obj())
        # Different case + extra whitespace must hit the same row
        assert cache.lookup("C 33") is not None
        assert cache.lookup("  C   33  ") is not None

    def test_miss_returns_none(self, app_ctx):
        from resolver import cache
        assert cache.lookup("not in cache") is None

    def test_empty_input_returns_none(self, app_ctx):
        from resolver import cache
        assert cache.lookup("") is None
        assert cache.lookup("   ") is None

    def test_update_existing_row(self, app_ctx):
        from resolver import cache
        cache.store("M 31", _veil_obj())  # wrong data on purpose
        new = ResolvedObject(canonical_name="M 31", ra_hours=0.71,
                             dec_deg=41.27, target_type="galaxy",
                             source="local_catalog")
        cache.store("M 31", new)
        hit = cache.lookup("M 31")
        assert hit.canonical_name == "M 31"
        assert hit.target_type == "galaxy"
        assert hit.ra_hours == pytest.approx(0.71)


# ---------------------------------------------------------------------------
# Negative caching
# ---------------------------------------------------------------------------

class TestNegativeCache:
    def test_negative_lookup_raises(self, app_ctx):
        from resolver import cache
        cache.store_negative("bogus_xyz", attempts=[("bogus_xyz", "sesame", "miss")])
        with pytest.raises(ResolverError) as ei:
            cache.lookup("bogus_xyz")
        assert "bogus_xyz" in str(ei.value)

    def test_positive_overrides_negative(self, app_ctx):
        from resolver import cache
        cache.store_negative("M 31")
        cache.store("M 31", _veil_obj())  # later positive
        hit = cache.lookup("M 31")
        assert hit is not None and hit.cached is True


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------

class TestExpiry:
    def test_expired_positive_returns_none(self, app_ctx):
        from app import db, ResolverCache
        from resolver import cache
        cache.store("M 42", _veil_obj(), ttl_days=30)
        row = ResolverCache.query.filter_by(input_key="m 42").first()
        # Force expiry by backdating
        row.resolved_at = _dt.datetime.utcnow() - _dt.timedelta(days=31)
        db.session.commit()
        assert cache.lookup("M 42") is None

    def test_expired_negative_returns_none(self, app_ctx):
        from app import db, ResolverCache
        from resolver import cache
        cache.store_negative("bogus", ttl_days=1)
        row = ResolverCache.query.filter_by(input_key="bogus").first()
        row.resolved_at = _dt.datetime.utcnow() - _dt.timedelta(days=2)
        db.session.commit()
        # Expired negative no longer raises
        assert cache.lookup("bogus") is None

    def test_purge_expired_removes_rows(self, app_ctx):
        from app import db, ResolverCache
        from resolver import cache
        cache.store("alpha", _veil_obj())
        cache.store("beta", _veil_obj())
        beta = ResolverCache.query.filter_by(input_key="beta").first()
        beta.resolved_at = _dt.datetime.utcnow() - _dt.timedelta(days=999)
        db.session.commit()

        removed = cache.purge_expired()
        assert removed == 1
        assert ResolverCache.query.filter_by(input_key="alpha").first() is not None
        assert ResolverCache.query.filter_by(input_key="beta").first() is None


# ---------------------------------------------------------------------------
# resolve_with_cache integration
# ---------------------------------------------------------------------------

class TestResolveWithCache:
    def test_chain_called_once_then_cached(self, app_ctx):
        from resolver import cache
        r = _CountingResolver(_veil_obj())
        chain = ResolverChain([r])

        first = cache.resolve_with_cache("C 33", chain)
        assert first.cached is False
        assert r.calls == 1

        second = cache.resolve_with_cache("C 33", chain)
        assert second.cached is True
        # Critical: chain must NOT have been called again
        assert r.calls == 1

    def test_chain_failure_caches_negative(self, app_ctx):
        from resolver import cache
        r = _CountingResolver(None)  # always misses
        chain = ResolverChain([r])

        with pytest.raises(ResolverError):
            cache.resolve_with_cache("nothing_here", chain)
        # Second attempt should be served by negative cache without
        # calling the chain again
        with pytest.raises(ResolverError):
            cache.resolve_with_cache("nothing_here", chain)
        assert r.calls == 1


# ---------------------------------------------------------------------------
# No app context = silent no-op
# ---------------------------------------------------------------------------

class TestNoAppContext:
    """Caller may use the resolver from a CLI / test with no Flask app
    available. The cache must silently degrade rather than crashing."""

    def test_lookup_returns_none_with_no_context(self):
        from resolver import cache
        # We are outside the app_ctx fixture, so no Flask context.
        assert cache.lookup("anything") is None

    def test_store_is_silent_no_op(self):
        from resolver import cache
        # Must not raise
        cache.store("anything", _veil_obj())
