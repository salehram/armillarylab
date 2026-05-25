"""Offline catalog resolver — instant, zero-network.

Loads the JSON files produced by ``scripts/build_resolver_catalogs.py``
(see ``resolver/data/README.md``) into an in-memory dict indexed by every
known alias (catalog ID, aliases, common names) under a casefolded key.

This resolver should always run first in the chain: it eliminates the
``C 33`` class of bugs, handles the most common Messier / Caldwell / NGC
lookups without any network round-trip, and yields rich metadata
(target_type, common_names, magnitude) that downstream consumers want.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

from resolver.base import Resolver
from resolver.types import ResolvedObject

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Catalogs are loaded in priority order; earlier entries win when an alias
# collides (e.g. "M 31" -> messier.json wins over a hypothetical NGC alias).
_CATALOG_FILES = (
    "messier.json",
    "caldwell.json",
    "ngc_ic.json",
)


class LocalCatalogResolver(Resolver):
    """Instant lookup against bundled NGC/IC/Messier/Caldwell data."""

    name = "local_catalog"
    requires_network = False
    default_confidence = 1.0

    # Module-level singletons (lazy-loaded, shared across instances).
    _index: dict[str, dict] | None = None
    _nicknames: dict[str, str] | None = None
    _load_lock = threading.Lock()
    _load_failed = False

    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir or _DATA_DIR

    # ------------------------------------------------------------------
    # Lazy loading
    # ------------------------------------------------------------------

    @classmethod
    def _ensure_loaded(cls, data_dir: Path) -> None:
        """Load bundled JSON files once into class-level dicts.

        Two-phase indexing so that each entry's own ``catalog_id`` is the
        authoritative key for lookups by that exact ID:

            Phase A: register every entry's primary catalog_id (and its
                     no-space compact form). Primary IDs always win.
            Phase B: register aliases + common_names with ``setdefault``,
                     so they only fill gaps and never overwrite primaries.

        Without this, "NGC 6992" typed by the user would resolve to the
        Caldwell wrapper entry because Caldwell 33's aliases list contains
        "NGC 6992".
        """
        if cls._index is not None or cls._load_failed:
            return
        with cls._load_lock:
            if cls._index is not None or cls._load_failed:
                return
            try:
                all_entries: list[dict] = []
                for fname in _CATALOG_FILES:
                    path = data_dir / fname
                    if not path.exists():
                        logger.warning("Resolver catalog file missing: %s", path)
                        continue
                    entries = json.loads(path.read_text(encoding="utf-8"))
                    all_entries.extend(entries)
                    logger.info("Loaded %d entries from %s", len(entries), fname)

                index: dict[str, dict] = {}

                # Phase A — primary IDs win unconditionally.
                for entry in all_entries:
                    cid = entry.get("catalog_id", "")
                    if not cid:
                        continue
                    for k in (cid, cid.replace(" ", "")):
                        ck = k.casefold().strip()
                        if ck:
                            index[ck] = entry  # overwrite OK in this phase

                # Phase B — aliases + common names fill remaining gaps only.
                for entry in all_entries:
                    keys: list[str] = []
                    for alias in entry.get("aliases", []) or []:
                        keys.append(alias)
                        keys.append(alias.replace(" ", ""))
                    for cn in entry.get("common_names", []) or []:
                        keys.append(cn)
                    for k in keys:
                        ck = k.casefold().strip()
                        if ck:
                            index.setdefault(ck, entry)

                nicknames_path = data_dir / "nicknames.json"
                if nicknames_path.exists():
                    nicknames_raw = json.loads(nicknames_path.read_text(encoding="utf-8"))
                    # Keys are already casefolded by the build script.
                    cls._nicknames = {k: v for k, v in nicknames_raw.items()}
                    logger.info("Loaded %d nicknames", len(cls._nicknames))
                else:
                    cls._nicknames = {}

                cls._index = index
            except Exception as exc:
                cls._load_failed = True
                logger.exception("Failed to load resolver catalogs: %s", exc)

    # ------------------------------------------------------------------
    # Resolver protocol
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        self._ensure_loaded(self._data_dir)
        return self._index is not None and bool(self._index)

    def resolve(self, query: str) -> Optional[ResolvedObject]:
        if not query:
            return None
        self._ensure_loaded(self._data_dir)
        if not self._index:
            return None

        key = query.casefold().strip()
        entry = self._index.get(key)

        # Fallback: nickname index (also casefolded)
        if entry is None and self._nicknames:
            cid = self._nicknames.get(key)
            if cid:
                entry = self._index.get(cid.casefold())

        # Compact form fallback ("ngc6992" already handled by catalog_id no-space
        # key, but cover the case for user input without going through normalizer)
        if entry is None:
            compact = key.replace(" ", "")
            entry = self._index.get(compact)

        if entry is None:
            return None

        return ResolvedObject(
            canonical_name=entry["catalog_id"],
            ra_hours=float(entry["ra_hours"]),
            dec_deg=float(entry["dec_deg"]),
            object_type=entry.get("object_type", "") or "",
            target_type=entry.get("target_type", "other") or "other",
            common_names=list(entry.get("common_names", []) or []),
            catalog_aliases=[
                a for a in (entry.get("aliases", []) or [])
                # Drop the compact "C33" / "M31" duplicates and the
                # entry's own catalog_id — keep only spaced cross-catalog IDs.
                if a and " " in a and a != entry.get("catalog_id")
            ],
            magnitude=entry.get("magnitude"),
            source=self.name,
            confidence=self.default_confidence,
            matched_variant=query,
        )
