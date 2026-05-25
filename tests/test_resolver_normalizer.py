"""Unit tests for resolver.normalizer.

Pure-function tests; no Flask app, no DB, no network. Safe to run anywhere.
"""
from __future__ import annotations

import pytest

from resolver.normalizer import normalize


class TestEmpty:
    def test_empty_string_returns_empty_list(self):
        assert normalize("") == []

    def test_whitespace_only_returns_empty_list(self):
        assert normalize("   \t\n  ") == []


class TestCaldwell:
    """The specific bug we're fixing: 'C 33' must produce 'Caldwell 33'."""

    @pytest.mark.parametrize("raw", ["C 33", "C33", "c 33", "c33", "Cald 33", "Caldwell 33"])
    def test_caldwell_variants_emit_long_form(self, raw):
        variants = normalize(raw)
        assert "Caldwell 33" in variants, f"missing 'Caldwell 33' for input {raw!r}: {variants}"

    def test_caldwell_short_form_emitted_first(self):
        variants = normalize("c33")
        assert variants[0] == "C 33"

    def test_caldwell_109_max(self):
        variants = normalize("C109")
        assert "Caldwell 109" in variants


class TestMessier:
    @pytest.mark.parametrize("raw", ["M31", "M 31", "m31", "Messier 31", "messier31"])
    def test_messier_variants(self, raw):
        variants = normalize(raw)
        assert "M 31" in variants
        assert "Messier 31" in variants


class TestNGC:
    @pytest.mark.parametrize("raw", ["NGC6992", "ngc 6992", "ngc6992", "N G C 6992", "NGC-6992"])
    def test_ngc_variants_canonicalize(self, raw):
        variants = normalize(raw)
        assert "NGC 6992" in variants


class TestIC:
    @pytest.mark.parametrize("raw", ["IC1805", "ic 1805", "I C 1805"])
    def test_ic_variants_canonicalize(self, raw):
        variants = normalize(raw)
        assert "IC 1805" in variants


class TestSharpless:
    @pytest.mark.parametrize("raw", ["Sh2-155", "sh2 155", "SH 2-155", "Sharpless 155", "Sharpless2-155"])
    def test_sharpless_variants(self, raw):
        variants = normalize(raw)
        assert "Sharpless 155" in variants
        assert "Sh2-155" in variants


class TestSpecialtyCatalogs:
    def test_abell(self):
        assert "Abell 426" in normalize("Abell426")

    def test_vdb(self):
        assert "vdB 142" in normalize("vdb142")

    def test_lbn(self):
        assert "LBN 529" in normalize("lbn529")

    def test_arp(self):
        assert "Arp 273" in normalize("arp273")

    def test_barnard_short_form(self):
        variants = normalize("B33")
        assert "B 33" in variants
        assert "Barnard 33" in variants

    def test_barnard_long_form_input(self):
        variants = normalize("Barnard 33")
        assert "Barnard 33" in variants


class TestNicknames:
    """Free-text nicknames must pass through unchanged so SIMBAD can try them."""

    @pytest.mark.parametrize("raw", [
        "Eastern Veil Nebula",
        "Andromeda Galaxy",
        "Orion Nebula",
        "Pinwheel Galaxy",
    ])
    def test_nickname_preserved(self, raw):
        variants = normalize(raw)
        assert raw in variants
        # Nicknames shouldn't be matched by any prefix rule.
        assert len(variants) == 1


class TestDedupe:
    def test_no_duplicate_variants(self):
        variants = normalize("M 31")
        assert len(variants) == len(set(v.casefold() for v in variants))

    def test_order_preserved(self):
        # Canonical short form must come before long form.
        variants = normalize("M31")
        assert variants.index("M 31") < variants.index("Messier 31")


class TestEdgeCases:
    def test_diacritics_stripped(self):
        # 'Andrómeda' should normalize to plain ASCII
        variants = normalize("Andrómeda")
        assert any("Andromeda" in v for v in variants)

    def test_leading_trailing_whitespace_trimmed(self):
        variants = normalize("   NGC 6992   ")
        assert "NGC 6992" in variants

    def test_internal_whitespace_collapsed(self):
        variants = normalize("NGC    6992")
        assert "NGC 6992" in variants

    def test_unknown_prefix_falls_through(self):
        # No rule matches "XYZ 999" — original is preserved.
        variants = normalize("XYZ 999")
        assert "XYZ 999" in variants
