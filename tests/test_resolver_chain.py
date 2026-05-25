"""ResolverChain orchestration tests.

These tests use fake in-memory resolvers and never touch the network or
the bundled JSON catalogs (those are covered by test_resolver_local.py).
"""
from __future__ import annotations

from typing import Optional

import pytest

from resolver.base import Resolver
from resolver.chain import ResolverChain
from resolver.types import ResolvedObject, ResolverError


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeResolver(Resolver):
    def __init__(self, name: str, hits: dict[str, ResolvedObject] | None = None,
                 available: bool = True, raise_on: set[str] | None = None):
        self.name = name
        self._hits = hits or {}
        self._available = available
        self._raise_on = raise_on or set()
        self.calls: list[str] = []

    def is_available(self) -> bool:
        return self._available

    def resolve(self, query: str) -> Optional[ResolvedObject]:
        self.calls.append(query)
        if query in self._raise_on:
            raise RuntimeError(f"boom on {query}")
        return self._hits.get(query)


def _obj(canon: str, source: str = "fake") -> ResolvedObject:
    return ResolvedObject(
        canonical_name=canon, ra_hours=1.0, dec_deg=2.0, source=source,
    )


# ---------------------------------------------------------------------------
# Core behavior
# ---------------------------------------------------------------------------

class TestChainCore:
    def test_first_hit_wins(self):
        a = _FakeResolver("a", {"M 31": _obj("M 31", "a")})
        b = _FakeResolver("b", {"M 31": _obj("M 31", "b")})
        chain = ResolverChain([a, b])
        result = chain.resolve("M 31")
        assert result.source == "a"
        # b must not even be called since a hit on the first variant
        assert b.calls == []

    def test_falls_through_to_next_resolver_on_miss(self):
        a = _FakeResolver("a", {})  # always misses
        b = _FakeResolver("b", {"M 31": _obj("M 31", "b")})
        chain = ResolverChain([a, b])
        result = chain.resolve("M 31")
        assert result.source == "b"
        assert a.calls == ["M 31"]

    def test_normalizer_emits_variants(self):
        # "C 33" must produce "Caldwell 33" via the real normalizer.
        a = _FakeResolver("a", {"Caldwell 33": _obj("Caldwell 33", "a")})
        chain = ResolverChain([a])
        result = chain.resolve("C 33")
        assert result.canonical_name == "Caldwell 33"
        assert "Caldwell 33" in a.calls
        assert result.input_name == "C 33"

    def test_all_miss_raises_resolver_error(self):
        a = _FakeResolver("a", {})
        b = _FakeResolver("b", {})
        chain = ResolverChain([a, b])
        with pytest.raises(ResolverError) as exc_info:
            chain.resolve("definitely_nothing_xyz")
        # Error message should mention the input
        assert "definitely_nothing_xyz" in str(exc_info.value)
        # attempts list should be populated
        assert len(exc_info.value.attempts) >= 1

    def test_empty_input_raises(self):
        chain = ResolverChain([_FakeResolver("a", {})])
        with pytest.raises(ResolverError):
            chain.resolve("")
        with pytest.raises(ResolverError):
            chain.resolve("   ")

    def test_unavailable_resolver_skipped(self):
        a = _FakeResolver("a", {"M 31": _obj("M 31", "a")}, available=False)
        b = _FakeResolver("b", {"M 31": _obj("M 31", "b")})
        chain = ResolverChain([a, b])
        result = chain.resolve("M 31")
        assert result.source == "b"
        assert a.calls == []  # never called

    def test_resolver_exception_does_not_abort_chain(self):
        # A crashing resolver must be logged and the chain must move on.
        a = _FakeResolver("a", {}, raise_on={"M 31"})
        b = _FakeResolver("b", {"M 31": _obj("M 31", "b")})
        chain = ResolverChain([a, b])
        result = chain.resolve("M 31")
        assert result.source == "b"

    def test_empty_chain_rejected(self):
        with pytest.raises(ValueError):
            ResolverChain([])


# ---------------------------------------------------------------------------
# Provenance stamping
# ---------------------------------------------------------------------------

class TestProvenance:
    def test_input_name_recorded(self):
        a = _FakeResolver("a", {"M 31": _obj("M 31", "a")})
        chain = ResolverChain([a])
        result = chain.resolve("  M31  ")  # whitespace + compact form
        assert result.input_name == "M31"  # stripped, otherwise unchanged

    def test_matched_variant_recorded(self):
        a = _FakeResolver("a", {"Caldwell 33": _obj("Caldwell 33", "a")})
        chain = ResolverChain([a])
        result = chain.resolve("C 33")
        assert result.matched_variant == "Caldwell 33"

    def test_source_overrides_blank(self):
        # Resolver returns ResolvedObject with empty source — chain fills it.
        a = _FakeResolver("a", {"M 31": ResolvedObject(
            canonical_name="M 31", ra_hours=0, dec_deg=0, source="",
        )})
        chain = ResolverChain([a])
        result = chain.resolve("M 31")
        assert result.source == "a"


# ---------------------------------------------------------------------------
# End-to-end with the real LocalCatalogResolver (the actual bug fix)
# ---------------------------------------------------------------------------

class TestRealLocalCatalogE2E:
    """Sanity check the chain with the real LocalCatalogResolver. Skipped
    if catalogs haven't been built yet."""

    @pytest.fixture(scope="class")
    def chain(self):
        from pathlib import Path
        data = Path(__file__).resolve().parent.parent / "resolver" / "data"
        if not (data / "ngc_ic.json").exists():
            pytest.skip("Local catalog JSON not built")
        from resolver.sources.local_catalog import LocalCatalogResolver
        # Reset singleton cache for determinism
        LocalCatalogResolver._index = None
        LocalCatalogResolver._nicknames = None
        LocalCatalogResolver._load_failed = False
        return ResolverChain([LocalCatalogResolver()])

    @pytest.mark.parametrize("query", ["C 33", "c33", "Caldwell 33"])
    def test_caldwell_33_end_to_end(self, chain, query):
        """The original reported bug: GET /api/resolve?name=C%2033 must
        succeed without hitting the network."""
        result = chain.resolve(query)
        assert result.source == "local_catalog"
        assert result.target_type == "supernova_remnant"
        assert any("Veil" in cn for cn in result.common_names)
