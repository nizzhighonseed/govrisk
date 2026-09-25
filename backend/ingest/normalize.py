"""Normalization helpers shared by every ingestion adapter.

These functions map provider-specific vocabulary onto the platform's single
canonical vocabulary (sectors, scale thresholds, state names) so database rows
and map joins are consistent regardless of which source produced them.
"""

from __future__ import annotations

from typing import Dict, Optional

from .contract import ProjectScale

# --- Sectors ------------------------------------------------------------------
# Canonical sectors mirror the platform schema (see backend/schemas.py
# VALID_SECTORS) plus "Other" as the safety net for unmapped values.

CANONICAL_SECTORS = {
    "Roads": "Transport",
    "Transport": "Transport",
    "Highways": "Transport",
    "Road": "Transport",
    "Road Transport": "Transport",
    "Railways": "Transport",
    "Railways & Metro": "Transport",
    "Rail": "Transport",
    "Metro": "Transport",
    "Urban Transit": "Transport",
    "Transit": "Transport",
    "Airports": "Transport",
    "Airport": "Transport",
    "Ports": "Transport",
    "Port": "Transport",
    "Shipping": "Transport",
    "Power": "Energy",
    "Energy": "Energy",
    "Electricity": "Energy",
    "Transmission": "Energy",
    "Distribution": "Energy",
    "Renewable Energy": "Energy",
    "Solar": "Energy",
    "Wind": "Energy",
    "Hydro": "Energy",
    "Thermal": "Energy",
    "Nuclear": "Energy",
    "Oil & Gas": "Energy",
    "Petroleum": "Energy",
    "Water": "Water",
    "Irrigation": "Water",
    "Water Supply": "Water",
    "Drinking Water": "Water",
    "Flood Control": "Water",
    "Drainage": "Water",
    "Communication": "Communication",
    "Telecom": "Communication",
    "Telecommunications": "Communication",
    "Digital": "Communication",
    "IT": "Communication",
    "Social Infrastructure": "Social Infrastructure",
    "Housing": "Social Infrastructure",
    "Urban Housing": "Social Infrastructure",
    "Health": "Social Infrastructure",
    "Hospitals": "Social Infrastructure",
    "Education": "Social Infrastructure",
    "Schools": "Social Infrastructure",
    "Colleges": "Social Infrastructure",
    "Mining": "Mining",
    "Minerals": "Mining",
    "Coal": "Mining",
}

# Source-specific sector vocabularies, consulted BEFORE the generic table.
#
# A government source publishes its own sector taxonomy, and the generic
# substring table above is the wrong tool for it: PAIMANA alone reports 22
# distinct sectors, most of which ("Atomic Energy", "Civil Aviation",
# "Fertilizers") have no substring in common with GovRisk's six canonical
# sectors and would silently collapse to "Other", destroying sector analysis.
#
# Each source gets its own explicit map here, added when that source's
# adapter is written. Deliberately empty for now: the real PAIMANA 22 -> 6
# mapping is a Phase-2 deliverable that must be derived from the actual
# published labels, not guessed ahead of time. The registry exists so that
# mapping is added in one reviewable place instead of inside a parser.
SOURCE_SECTOR_MAPS: Dict[str, Dict[str, str]] = {
    "paimana": {},
}


def _lookup_sector(mapping: Dict[str, str], key: str) -> Optional[str]:
    """Case-insensitive exact-then-substring lookup within one mapping."""
    if not mapping:
        return None
    direct = mapping.get(key.title()) or mapping.get(key)
    if direct:
        return direct
    lowered = key.lower()
    for label, target in mapping.items():
        if label.lower() == lowered:
            return target
    for label, target in mapping.items():
        if label.lower() in lowered:
            return target
    return None


def canonical_sector(raw: Optional[str], source: Optional[str] = None) -> str:
    """Map a source sector label onto the canonical set.

    Resolution order, most specific first:
      1. the source's own explicit vocabulary (`SOURCE_SECTOR_MAPS[source]`)
      2. the generic `CANONICAL_SECTORS` table
      3. "Other"

    `source` selects which source-specific table applies. The raw label is
    never modified here - it is preserved separately on the record as
    `sourceSector` so a corrected mapping can be applied later without
    re-reading the source.
    """
    if not raw:
        return "Other"
    key = " ".join(str(raw).strip().split())
    if source:
        specific = _lookup_sector(SOURCE_SECTOR_MAPS.get(source, {}), key)
        if specific:
            return specific
    direct = CANONICAL_SECTORS.get(key.title()) or CANONICAL_SECTORS.get(key)
    if direct:
        return direct
    lowered = key.lower()
    for label, target in CANONICAL_SECTORS.items():
        if label.lower() in lowered:
            return target
    return "Other"


# --- Financial progress --------------------------------------------------------
def derive_financial_progress(
    expenditure_cr: Optional[float], current_cost_cr: Optional[float]
) -> Optional[float]:
    """Financial progress as a percentage of the current cost.

    `financial_progress = expenditure / current_cost * 100`, rounded to two
    decimals. Returns `None` - never a number - whenever the ratio cannot be
    computed honestly:

    - either input missing
    - current cost zero or negative (a zero denominator is a data error, and
      returning 0.0 for it would read as "nothing spent", which is the
      opposite of what an unknown value means)

    A result above 100 is legitimate and is returned unclamped: spending more
    than the current estimate is a real and important signal, and clamping it
    would hide exactly the overspend this ratio exists to surface.
    """
    if expenditure_cr is None or current_cost_cr is None:
        return None
    if current_cost_cr <= 0:
        return None
    return round(expenditure_cr / current_cost_cr * 100, 2)


# --- Scale thresholds ----------------------------------------------------------
MEDIUM_MIN_CR = 100.0
LARGE_MIN_CR = 1000.0


def derive_scale(cost_estimate_cr: Optional[float]) -> Optional[ProjectScale]:
    """MEDIUM = 100-1000 Cr, LARGE > 1000 Cr. None when cost unknown."""
    if cost_estimate_cr is None:
        return None
    if cost_estimate_cr > LARGE_MIN_CR:
        return ProjectScale.LARGE
    if cost_estimate_cr >= MEDIUM_MIN_CR:
        return ProjectScale.MEDIUM
    return None


# --- State name aliases --------------------------------------------------------
# GADM / data.gov.in name variants normalised to the canonical name used by the
# map boundary join (mirrors frontend `utils/geo.ts` resolveStateKey).

STATE_ALIASES = {
    "Orissa": "Odisha",
    "Odisha": "Odisha",
    "Uttaranchal": "Uttarakhand",
    "Uttarakhand": "Uttarakhand",
    "Andaman & Nicobar Islands": "Andaman and Nicobar Islands",
    "Andaman and Nicobar Islands": "Andaman and Nicobar Islands",
    "Dadra & Nagar Haveli": "Dadra and Nagar Haveli and Daman and Diu",
    "Daman & Diu": "Dadra and Nagar Haveli and Daman and Diu",
    "Dadra and Nagar Haveli and Daman and Diu": "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi": "Delhi",
    "National Capital Territory of Delhi": "Delhi",
    "NCT Of Delhi": "Delhi",
    "Puducherry": "Puducherry",
    "Pondicherry": "Puducherry",
    "Chhattisgarh": "Chhattisgarh",
    "Jammu and Kashmir": "Jammu and Kashmir",
    "Jammu & Kashmir": "Jammu and Kashmir",
    "Ladakh": "Ladakh",
    "Telangana": "Telangana",
    "Andhra Pradesh": "Andhra Pradesh",
    "Arunachal Pradesh": "Arunachal Pradesh",
    "Assam": "Assam",
    "Bihar": "Bihar",
    "Goa": "Goa",
    "Gujarat": "Gujarat",
    "Haryana": "Haryana",
    "Himachal Pradesh": "Himachal Pradesh",
    "Jharkhand": "Jharkhand",
    "Karnataka": "Karnataka",
    "Kerala": "Kerala",
    "Madhya Pradesh": "Madhya Pradesh",
    "Maharashtra": "Maharashtra",
    "Manipur": "Manipur",
    "Meghalaya": "Meghalaya",
    "Mizoram": "Mizoram",
    "Nagaland": "Nagaland",
    "Punjab": "Punjab",
    "Rajasthan": "Rajasthan",
    "Sikkim": "Sikkim",
    "Tamil Nadu": "Tamil Nadu",
    "Tripura": "Tripura",
    "Uttar Pradesh": "Uttar Pradesh",
    "West Bengal": "West Bengal",
}


def canonical_state(raw: Optional[str]) -> str:
    """Canonical state name for consistent DB rows and map geometry joins."""
    if not raw:
        return "Unknown"
    key = " ".join(str(raw).strip().split())
    return STATE_ALIASES.get(key, key)


def to_iso_date(value: Optional[str]) -> Optional[str]:
    """Coerce common date spellings to YYYY-MM-DD (or None when unparsable)."""
    if not value:
        return None
    from datetime import datetime

    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


__all__ = [
    "canonical_sector",
    "canonical_state",
    "derive_financial_progress",
    "derive_scale",
    "to_iso_date",
    "MEDIUM_MIN_CR",
    "LARGE_MIN_CR",
    "CANONICAL_SECTORS",
    "SOURCE_SECTOR_MAPS",
    "STATE_ALIASES",
]