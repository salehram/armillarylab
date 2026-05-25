"""Tests for LocalCatalogResolver against the bundled JSON catalogs.

These tests rely on the JSON files produced by
``scripts/build_resolver_catalogs.py``. They are read-only — no DB, no Flask,
no network.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from resolver.sources.local_catalog import LocalCatalogResolver

DATA_DIR = Path(__file__).resolve().parent.parent / "resolver" / "data"


@pytest.fixture(scope="module")
def resolver():
    if not (DATA_DIR / "ngc_ic.json").exists():
        pytest.skip(
            "Local catalog JSON not built. Run: "
            "python scripts/build_resolver_catalogs.py"
        )
    # Reset class-level cache so tests are deterministic across modules.
    LocalCatalogResolver._index = None
    LocalCatalogResolver._nicknames = None
    LocalCatalogResolver._load_failed = False
    r = LocalCatalogResolver()
    assert r.is_available(), "LocalCatalogResolver failed to load"
    return r


# ---------------------------------------------------------------------------
# Anti-regression: the specific bug reported by the user.
# ---------------------------------------------------------------------------

class TestCaldwell33Regression:
    """The 'C 33' / 'Caldwell 33' resolution bug must stay fixed."""

    @pytest.mark.parametrize("query", ["Caldwell 33", "C 33", "C33", "c33"])
    def test_caldwell_33_resolves_to_ngc_6992(self, resolver, query):
        result = resolver.resolve(query)
        assert result is not None, f"Local catalog failed to resolve {query!r}"
        # Caldwell 33's primary canonical_id in our local store is "Caldwell 33";
        # what matters is that we recognize all four input forms.
        assert result.canonical_name in ("Caldwell 33", "NGC 6992")
        # And the coordinates must point to the Eastern Veil Nebula
        # (RA ~20h56m, Dec ~+31°43′; allow generous tolerance for both
        # OpenNGC's center-of-bbox and catalog mid-point variations).
        assert 20.5 < result.ra_hours < 21.2
        assert 30.0 < result.dec_deg < 33.0
        assert result.target_type == "supernova_remnant"
        assert any("Veil" in cn for cn in result.common_names)


# ---------------------------------------------------------------------------
# Messier coverage
# ---------------------------------------------------------------------------

class TestMessier:
    def test_m31_andromeda(self, resolver):
        result = resolver.resolve("M 31")
        assert result is not None
        assert result.canonical_name == "M 31"
        assert result.target_type == "galaxy"
        # Andromeda Galaxy: RA ~0h42m, Dec ~+41°16′
        assert 0.5 < result.ra_hours < 0.9
        assert 40.0 < result.dec_deg < 42.5

    def test_m31_compact_form(self, resolver):
        # User types "M31" with no space; LocalCatalogResolver indexes
        # compact form too.
        result = resolver.resolve("M31")
        assert result is not None
        assert result.canonical_name == "M 31"

    def test_m42_orion_nebula(self, resolver):
        result = resolver.resolve("M 42")
        assert result is not None
        assert result.target_type in ("emission", "diffuse")


# ---------------------------------------------------------------------------
# NGC / IC coverage
# ---------------------------------------------------------------------------

class TestNGC_IC:
    def test_ngc_6992_directly(self, resolver):
        result = resolver.resolve("NGC 6992")
        assert result is not None
        assert result.canonical_name == "NGC 6992"
        assert result.target_type == "supernova_remnant"

    def test_ngc_compact(self, resolver):
        result = resolver.resolve("NGC6992")
        assert result is not None
        assert result.canonical_name == "NGC 6992"

    def test_ic_1805_heart_nebula(self, resolver):
        result = resolver.resolve("IC 1805")
        assert result is not None
        assert result.canonical_name == "IC 1805"

    def test_ngc_224_is_messier_31(self, resolver):
        result = resolver.resolve("NGC 224")
        assert result is not None
        # NGC 224 entry may have target_type=galaxy
        assert result.target_type == "galaxy"


# ---------------------------------------------------------------------------
# Misses
# ---------------------------------------------------------------------------

class TestMisses:
    def test_garbage_returns_none(self, resolver):
        assert resolver.resolve("not_a_real_object_xyz123") is None

    def test_empty_returns_none(self, resolver):
        assert resolver.resolve("") is None

    def test_unsupported_catalog_returns_none(self, resolver):
        # Sharpless is not in the bundled local catalogs (only NGC/IC/M/C);
        # chain will fall back to SIMBAD in Phase 5.
        assert resolver.resolve("Sh2-155") is None


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------

class TestResultShape:
    def test_source_is_local_catalog(self, resolver):
        r = resolver.resolve("M 31")
        assert r.source == "local_catalog"

    def test_confidence_is_high(self, resolver):
        r = resolver.resolve("M 31")
        assert r.confidence == 1.0

    def test_matched_variant_recorded(self, resolver):
        r = resolver.resolve("M 31")
        assert r.matched_variant == "M 31"

    def test_common_names_list(self, resolver):
        r = resolver.resolve("M 31")
        assert isinstance(r.common_names, list)
