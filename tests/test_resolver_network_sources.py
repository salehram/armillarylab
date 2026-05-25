"""Tests for SIMBAD / NED / VizieR resolvers.

All network calls are mocked. These tests verify our parsing /
otype-mapping logic, not the underlying astroquery library.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from resolver.sources.simbad import SimbadResolver, _map_otype
from resolver.sources.ned import NedResolver, _map_ned_type
from resolver.sources.vizier import VizierResolver


# ---------------------------------------------------------------------------
# SIMBAD otype mapping
# ---------------------------------------------------------------------------

class TestSimbadOtypeMap:
    @pytest.mark.parametrize("code,expected", [
        ("HII", "emission"),
        ("PN",  "planetary"),
        ("SNR", "supernova_remnant"),
        ("G",   "galaxy"),
        ("Sy1", "galaxy"),
        ("OpC", "cluster"),
        ("GlC", "cluster"),
        ("RNe", "reflection"),
        ("", "other"),
        (None, "other"),
        ("UnknownXYZ", "other"),
    ])
    def test_otype_codes(self, code, expected):
        assert _map_otype(code) == expected

    def test_prefix_fallback(self):
        # Codes we don't list explicitly should still map sanely if they
        # start with a known prefix.
        assert _map_otype("GalSomething") == "galaxy"


# ---------------------------------------------------------------------------
# SIMBAD parsing (with mocked astroquery)
# ---------------------------------------------------------------------------

def _fake_simbad_row(**fields):
    """Build a mapping that quacks like an astropy Table row."""
    class _Row:
        def __init__(self, data):
            self._data = data
        def __getitem__(self, key):
            if key in self._data:
                return self._data[key]
            raise KeyError(key)
    return _Row(fields)


def _fake_simbad_table(rows):
    """Minimal stand-in for an astropy Table."""
    class _T:
        def __init__(self, rs):
            self._rs = rs
        def __len__(self):
            return len(self._rs)
        def __getitem__(self, i):
            return self._rs[i]
    return _T(rows)


class TestSimbadResolver:
    def test_resolves_m31(self):
        r = SimbadResolver()
        fake_client = MagicMock()
        fake_client.query_object.return_value = _fake_simbad_table([_fake_simbad_row(
            MAIN_ID="M  31",
            RA="00 42 44.3300",
            DEC="+41 16 09.000",
            OTYPE="G",
            FLUX_V=3.4,
            IDS="M 31|NGC 224|UGC 454|Andromeda Galaxy",
        )])
        with patch.object(SimbadResolver, "_get_client", return_value=fake_client):
            result = r.resolve("M31")
        assert result is not None
        assert result.canonical_name == "M  31"
        assert result.target_type == "galaxy"
        assert result.source == "simbad"
        assert 0.5 < result.ra_hours < 0.9
        assert 40.0 < result.dec_deg < 42.5
        assert result.magnitude == pytest.approx(3.4)
        # SIMBAD IDS are catalog designations → catalog_aliases.
        assert "NGC 224" in result.catalog_aliases
        assert any("Andromeda" in cn for cn in result.catalog_aliases)

    def test_empty_table_returns_none(self):
        r = SimbadResolver()
        fake_client = MagicMock()
        fake_client.query_object.return_value = _fake_simbad_table([])
        with patch.object(SimbadResolver, "_get_client", return_value=fake_client):
            assert r.resolve("not_an_object") is None

    def test_none_table_returns_none(self):
        r = SimbadResolver()
        fake_client = MagicMock()
        fake_client.query_object.return_value = None
        with patch.object(SimbadResolver, "_get_client", return_value=fake_client):
            assert r.resolve("anything") is None

    def test_transport_error_returns_none(self):
        r = SimbadResolver()
        fake_client = MagicMock()
        fake_client.query_object.side_effect = RuntimeError("ConnectionError")
        with patch.object(SimbadResolver, "_get_client", return_value=fake_client):
            assert r.resolve("anything") is None

    def test_empty_input(self):
        assert SimbadResolver().resolve("") is None


# ---------------------------------------------------------------------------
# NED parsing
# ---------------------------------------------------------------------------

class TestNedTypeMap:
    @pytest.mark.parametrize("code,expected", [
        ("G", "galaxy"),
        ("QSO", "galaxy"),
        ("HII", "emission"),
        ("PN", "planetary"),
        ("SNR", "supernova_remnant"),
        ("*Cl", "cluster"),
        ("", "other"),
        ("Wat?", "other"),
    ])
    def test_codes(self, code, expected):
        assert _map_ned_type(code) == expected


def _fake_ned_table(**fields):
    class _Row:
        def __init__(self, d):
            self._d = d
        def __getitem__(self, k):
            return self._d[k]
    class _T:
        def __init__(self, rs):
            self._rs = rs
        def __len__(self):
            return len(self._rs)
        def __getitem__(self, i):
            return self._rs[i]
    return _T([_Row(fields)])


class TestNedResolver:
    def test_resolves_ugc(self):
        r = NedResolver()
        fake_ned = MagicMock()
        fake_ned.query_object.return_value = _fake_ned_table(
            **{"Object Name": "UGC 12158", "RA": 340.86, "DEC": 4.27, "Type": "G"}
        )
        with patch.object(NedResolver, "_get_ned", return_value=fake_ned):
            result = r.resolve("UGC 12158")
        assert result is not None
        assert result.canonical_name == "UGC 12158"
        assert result.target_type == "galaxy"
        # 340.86 deg / 15 = 22.724 h
        assert result.ra_hours == pytest.approx(340.86 / 15.0, rel=1e-3)
        assert result.dec_deg == pytest.approx(4.27)
        assert result.source == "ned"

    def test_empty_returns_none(self):
        r = NedResolver()
        fake_ned = MagicMock()
        class _Empty:
            def __len__(self): return 0
        fake_ned.query_object.return_value = _Empty()
        with patch.object(NedResolver, "_get_ned", return_value=fake_ned):
            assert r.resolve("nothing") is None

    def test_transport_error_returns_none(self):
        r = NedResolver()
        fake_ned = MagicMock()
        fake_ned.query_object.side_effect = RuntimeError("offline")
        with patch.object(NedResolver, "_get_ned", return_value=fake_ned):
            assert r.resolve("anything") is None


# ---------------------------------------------------------------------------
# VizieR — pattern matching only (queries themselves are integration-tested)
# ---------------------------------------------------------------------------

class TestVizierPatterns:
    def test_non_matching_input_returns_none_without_querying(self):
        # "M 31" should be skipped (handled upstream), no VizieR query attempted.
        r = VizierResolver()
        with patch("astroquery.vizier.Vizier") as mock_v:
            assert r.resolve("M 31") is None
            mock_v.assert_not_called()

    def test_empty_returns_none(self):
        assert VizierResolver().resolve("") is None
