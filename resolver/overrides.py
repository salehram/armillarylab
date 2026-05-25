"""ObjectMapping integration — user-defined target_type overrides.

The ``ObjectMapping`` DB table lets users pin a specific target_type to
a name (e.g. user marks "NGC 7000" as ``emission`` even though SIMBAD
returns ``Cl+N``). This module applies those overrides as a post-
resolution enricher rather than as a chain source: we still want the
coordinates / common_names / magnitude from upstream catalogs, but we
honor the user's classification.

Lookup is case-insensitive and tries every alias of the resolved object
(canonical_name + common_names + the original input).
"""
from __future__ import annotations

import logging
from typing import Iterable

from resolver.types import ResolvedObject

logger = logging.getLogger(__name__)


def _candidate_keys(obj: ResolvedObject) -> list[str]:
    """All names we should consult ObjectMapping under, casefolded."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in [obj.canonical_name, obj.input_name, *obj.common_names]:
        if not raw:
            continue
        key = " ".join(str(raw).split()).casefold()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def apply_override(obj: ResolvedObject) -> ResolvedObject:
    """If the user has a matching ObjectMapping row, override target_type
    in place and return the same instance. No-op on DB / context errors.
    """
    if obj is None:
        return obj

    try:
        from flask import has_app_context
        if not has_app_context():
            return obj
        from app import ObjectMapping, TargetType
    except Exception as exc:  # pragma: no cover
        logger.debug("ObjectMapping: skipped (%s)", exc)
        return obj

    keys = _candidate_keys(obj)
    if not keys:
        return obj

    try:
        # Pull all relevant mappings in one query.
        mappings = (
            ObjectMapping.query
            .join(TargetType)
            .all()
        )
    except Exception as exc:
        logger.debug("ObjectMapping: query failed: %s", exc)
        return obj

    if not mappings:
        return obj

    # Build a casefolded lookup once.
    by_name: dict[str, str] = {}
    for m in mappings:
        try:
            if m.object_name and m.target_type and m.target_type.name:
                by_name[m.object_name.strip().casefold()] = m.target_type.name
        except Exception:
            continue

    for key in keys:
        ttype = by_name.get(key)
        if ttype:
            if ttype != obj.target_type:
                logger.info(
                    "ObjectMapping override: %r %s → %s",
                    obj.canonical_name, obj.target_type, ttype,
                )
            obj.target_type = ttype
            obj.source = f"{obj.source}+override" if "override" not in obj.source else obj.source
            break

    return obj
