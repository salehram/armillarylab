"""Input normalization for the resolver chain.

Given a raw user-typed name (e.g. ``"c33"``, ``"ngc6992"``, ``"eastern veil"``,
``"Sh2-155"``), produce an **ordered** list of candidate query strings that
downstream resolvers should try, best first.

Design notes:
  * Pure functions, zero I/O, zero external dependencies. Easy to unit test.
  * The list is *deduplicated* while preserving order.
  * The original input (cleaned of leading/trailing whitespace) is always one
    of the candidates so legacy / unrecognized formats still get a chance.
  * Prefix detection is intentionally permissive (case-insensitive, optional
    whitespace and separators) but emits canonically-spaced forms.
"""
from __future__ import annotations

import re
import unicodedata

# Recognized catalog prefixes and their canonical short form.
# Order matters: more specific patterns first (e.g. SH2 before SH).
#
# Each entry: (regex, canonical_prefix, also_emit_long_form)
#   - regex matches the user-typed prefix + (optional separators) + number.
#   - canonical_prefix is the spaced short form (e.g. "NGC", "SH 2-").
#   - long_form (if not None) is an additional variant to emit (e.g. "Caldwell"
#     for "C N", "Messier" for "M N", "Sharpless" for "SH 2-N").
_PREFIX_RULES: list[tuple[re.Pattern[str], str, str | None]] = [
    # Messier
    (re.compile(r"^(?:M|Messier)\s*[-_]?\s*(\d{1,3})$", re.IGNORECASE),
     "M", "Messier"),
    # Caldwell — the bug we're fixing. Sesame rejects "C 33" but accepts "Caldwell 33".
    (re.compile(r"^(?:C|Cald|Caldwell)\s*[-_]?\s*(\d{1,3})$", re.IGNORECASE),
     "C", "Caldwell"),
    # NGC
    (re.compile(r"^N\s*G\s*C\s*[-_]?\s*(\d{1,5})$", re.IGNORECASE),
     "NGC", None),
    # IC
    (re.compile(r"^I\s*C\s*[-_]?\s*(\d{1,5})$", re.IGNORECASE),
     "IC", None),
    # Sharpless 2 catalog: "Sh2-155", "SH 2-155", "Sharpless 155"
    (re.compile(r"^(?:Sh\s*2|SH\s*2|Sharpless\s*2?|Sharpless)\s*[-_]?\s*(\d{1,4})$",
                re.IGNORECASE),
     "Sh2-", "Sharpless"),
    # Abell (galaxy clusters / planetary nebulae)
    (re.compile(r"^Abell\s*[-_]?\s*(\d{1,4})$", re.IGNORECASE),
     "Abell ", None),
    # van den Bergh reflection nebulae
    (re.compile(r"^vdB\s*[-_]?\s*(\d{1,4})$", re.IGNORECASE),
     "vdB ", None),
    # Lynds Bright Nebulae
    (re.compile(r"^LBN\s*[-_]?\s*(\d{1,4})$", re.IGNORECASE),
     "LBN ", None),
    # Lynds Dark Nebulae
    (re.compile(r"^LDN\s*[-_]?\s*(\d{1,4})$", re.IGNORECASE),
     "LDN ", None),
    # Arp peculiar galaxies
    (re.compile(r"^Arp\s*[-_]?\s*(\d{1,4})$", re.IGNORECASE),
     "Arp ", None),
    # Barnard dark nebulae — "B 33", "Barnard 33"
    (re.compile(r"^(?:B|Barnard)\s*[-_]?\s*(\d{1,4})$", re.IGNORECASE),
     "B ", "Barnard"),
    # Open cluster catalogs
    (re.compile(r"^Mel\s*[-_]?\s*(\d{1,4})$", re.IGNORECASE), "Mel ", "Melotte"),
    (re.compile(r"^Cr\s*[-_]?\s*(\d{1,4})$", re.IGNORECASE),  "Cr ",  "Collinder"),
    (re.compile(r"^Tr\s*[-_]?\s*(\d{1,4})$", re.IGNORECASE),  "Tr ",  "Trumpler"),
    (re.compile(r"^Stock\s*[-_]?\s*(\d{1,4})$", re.IGNORECASE), "Stock ", None),
    # Galaxy catalogs
    (re.compile(r"^PGC\s*[-_]?\s*(\d{1,7})$", re.IGNORECASE), "PGC ", None),
    (re.compile(r"^UGC\s*[-_]?\s*(\d{1,7})$", re.IGNORECASE), "UGC ", None),
]


def _strip_diacritics(s: str) -> str:
    """Remove combining accents so 'Cassiopée' matches 'Cassiopee'."""
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(ch)
    )


def _basic_clean(s: str) -> str:
    """Collapse internal whitespace, strip outer whitespace, strip diacritics."""
    s = _strip_diacritics(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _ordered_dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.casefold()
        if not item or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def normalize(raw: str) -> list[str]:
    """Return an ordered, deduplicated list of candidate query variants.

    The first element is the most likely-to-resolve canonical form; the
    original input is always preserved somewhere in the list.

    Examples:
        >>> normalize("c33")
        ['C 33', 'Caldwell 33', 'c33']
        >>> normalize("ngc6992")
        ['NGC 6992', 'ngc6992']
        >>> normalize("Sh2-155")
        ['Sh2-155', 'Sharpless 155']
        >>> normalize("  M 31 ")
        ['M 31', 'Messier 31']
        >>> normalize("Eastern Veil Nebula")
        ['Eastern Veil Nebula']
    """
    if not raw:
        return []

    cleaned = _basic_clean(raw)
    if not cleaned:
        return []

    variants: list[str] = [cleaned]

    # Try catalog-prefix rewriting. We test against a whitespace-collapsed
    # form so "N G C 6992" still matches the NGC pattern.
    compact = re.sub(r"\s+", " ", cleaned).strip()
    for pattern, short_prefix, long_prefix in _PREFIX_RULES:
        m = pattern.match(compact)
        if not m:
            continue
        number = m.group(1)
        # Emit canonical short form first.
        if short_prefix.endswith(" ") or short_prefix.endswith("-"):
            short = f"{short_prefix}{number}"
        else:
            short = f"{short_prefix} {number}"
        variants.insert(0, short)
        if long_prefix:
            variants.insert(1, f"{long_prefix} {number}")
        break  # Only one catalog rule should apply.

    # Always preserve the raw, cleaned input as a fallback variant.
    variants.append(cleaned)

    return _ordered_dedupe(variants)
