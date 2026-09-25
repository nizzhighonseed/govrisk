"""Ownership model for the `Project.risk_inputs` document.

`risk_inputs` is written by two different writers that must not fight:

- the ingestion pipeline, which can only ever supply what a machine-readable
  source actually publishes, and
- an analyst, who records qualitative judgements (a court stay, a land
  blockage, a contractor walkout) that no portal publishes.

Before this module existed the pipeline replaced the whole document with
`{}` on every sync, so a single re-sync silently erased every qualitative
judgement on the project. The rule now is explicit:

MANUAL-OWNED keys are written by a human and are never removed, blanked or
replaced by an ingestion run. SOURCE-OWNED keys are the ones a future
machine feed may legitimately fill in; an ingestion run may add or update
them. Any other key already present is left completely alone, so a manually
entered field this module has never heard of cannot be lost either.

The key names below are the exact branch names Layer 1 reads in
`services.risk_service._normalize_inputs`. They are duplicated here as
literals on purpose: importing the risk service would couple ingestion to
the engine, and the engine is the canonical authority that ingestion must
not reach into.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Optional, Set, Tuple

# Qualitative factors a human records and an external source cannot supply.
MANUAL_OWNED_RISK_INPUT_KEYS: frozenset = frozenset(
    {
        "clearance",
        "legalSocial",
        "contractor",
        "workforce",
        "engineering",
        "material",
        "supplyChain",
        "administrative",
    }
)

# Factors a future official machine feed could legitimately populate
# (weather, geology, hazard exposure). An ingestion run may add or update
# these; it still may not blank one that already holds a human's value.
SOURCE_OWNED_RISK_INPUT_KEYS: frozenset = frozenset(
    {
        "weather",
        "ground",
        "calamity",
    }
)


def load_risk_inputs(raw: Any) -> Dict[str, Any]:
    """Parse a `risk_inputs` column into a dict, tolerating junk.

    Unparseable or non-dict content is treated as an empty document rather
    than raising, because a single corrupt row must not abort a sync.
    """
    if not raw:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _has_evidence(value: Any) -> bool:
    """True when a branch carries a real value rather than an empty shell.

    Mirrors the evidence test Layer 1 uses in `_is_evidence`, so "empty" means
    the same thing to both writers.
    """
    if value is None or value is False or value == "" or value == 0:
        return False
    if isinstance(value, dict):
        return any(_has_evidence(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_evidence(v) for v in value)
    return True


def merge_risk_inputs(
    existing_raw: Any, incoming: Optional[Dict[str, Any]]
) -> Tuple[Dict[str, Any], Set[str]]:
    """Merge a source-supplied `risk_inputs` document into the stored one.

    Returns the merged document and the set of manual keys whose existing
    value was protected. Never mutates its arguments.
    """
    existing = load_risk_inputs(existing_raw)
    if not incoming:
        return existing, set()

    merged = dict(existing)
    preserved: Set[str] = set()

    for key, value in incoming.items():
        current = existing.get(key)
        incoming_has_value = _has_evidence(value)

        if key in MANUAL_OWNED_RISK_INPUT_KEYS:
            # A human owns this key. An ingestion run may only fill it in
            # when the human has not recorded anything yet. Whether the feed
            # sent nothing or sent something conflicting, the stored value
            # stands and the key is reported as protected.
            if _has_evidence(current):
                preserved.add(key)
                continue
            if incoming_has_value:
                merged[key] = value
            continue

        if key in SOURCE_OWNED_RISK_INPUT_KEYS:
            if not incoming_has_value and _has_evidence(current):
                # An empty branch from a feed must not erase a real value.
                preserved.add(key)
                continue
            merged[key] = value
            continue

        # Unknown key: a sync never touches what it does not own.
        if key not in merged and incoming_has_value:
            merged[key] = value

    return merged, preserved


def manual_keys() -> Iterable[str]:
    return sorted(MANUAL_OWNED_RISK_INPUT_KEYS)


__all__ = [
    "MANUAL_OWNED_RISK_INPUT_KEYS",
    "SOURCE_OWNED_RISK_INPUT_KEYS",
    "load_risk_inputs",
    "merge_risk_inputs",
    "manual_keys",
]
