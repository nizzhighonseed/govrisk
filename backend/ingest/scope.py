"""Per-source ingestion scope.

The cost floor below which a record is out of scope is a property of the
SOURCE, not of the platform. Two different government sources disagree about
where the floor sits, and silently applying the wrong one either drops
legitimate projects or lets in projects the source itself never reports.

The generic portal default is unchanged (INR 100 Cr). MoSPI PAIMANA only
tracks central-sector projects above INR 150 Cr, so it gets its own entry.
Registering a source here is what makes its floor explicit and auditable
rather than an implicit constant buried in the pipeline.

Adding a source to this registry is the ONLY supported way to change a cost
floor; `BaseIngestor` never hardcodes one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

# Generic floor used by sources that publish no scope statement of their own.
# Historical behaviour: unchanged.
DEFAULT_MIN_COST_CR: float = 100.0

# MoSPI PAIMANA's own reporting threshold for central-sector infrastructure
# projects. A project below this is not tracked by the source at all, so
# ingesting one would contradict the source.
PAIMANA_MIN_COST_CR: float = 150.0


@dataclass(frozen=True)
class SourceScope:
    """The scope rules that apply to every record from one source."""

    min_cost_cr: float
    label: str
    reference: Optional[str] = None

    def out_of_scope_reason(self, cost_cr: Optional[float]) -> Optional[str]:
        """Why a record is out of scope, or None when it is in scope.

        A record with no cost cannot be judged against the floor, so it is
        reported separately from a genuine below-floor rejection: scoring it
        would require inventing a cost, and a 0.0 cost reads as "free
        project", which is a false signal, not a missing one.
        """
        if cost_cr is None:
            return (
                "No cost data from source - scope and budget factor cannot be "
                "determined without inventing a value"
            )
        if cost_cr < self.min_cost_cr:
            return (
                f"Below {self.label} floor (< INR {self.min_cost_cr:g} Cr) - out of scope"
            )
        return None


DEFAULT_SCOPE = SourceScope(DEFAULT_MIN_COST_CR, "Default source")

SOURCE_SCOPES: Dict[str, SourceScope] = {
    "data.gov.in": SourceScope(
        DEFAULT_MIN_COST_CR, "Generic data.gov.in resource"
    ),
    "file-import": SourceScope(DEFAULT_MIN_COST_CR, "Local file import"),
    # Registered ahead of the adapter so the floor is explicit and testable
    # before any PAIMANA code exists.
    "paimana": SourceScope(
        PAIMANA_MIN_COST_CR,
        "MoSPI PAIMANA",
        "PAIMANA covers central-sector projects above INR 150 crore",
    ),
}


def scope_for(source_name: Optional[str]) -> SourceScope:
    """Scope rules for a source name, falling back to the generic default."""
    if not source_name:
        return DEFAULT_SCOPE
    return SOURCE_SCOPES.get(source_name, DEFAULT_SCOPE)


__all__ = [
    "SourceScope",
    "SOURCE_SCOPES",
    "DEFAULT_SCOPE",
    "DEFAULT_MIN_COST_CR",
    "PAIMANA_MIN_COST_CR",
    "scope_for",
]
