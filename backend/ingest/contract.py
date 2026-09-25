"""Normalized contract for infrastructure project ingestion.

Every raw source (data.gov.in resource, government report extract, CSV dump)
is adapted into this shape *before* anything touches the database. Adapters
own their source-specific mapping; the ingestion pipeline below only ever sees
RawProject. Swapping a data source never requires changing the pipeline or the
map rendering.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ProjectStatus(str, Enum):
    ONGOING = "ONGOING"
    COMPLETED = "COMPLETED"
    DELAYED = "DELAYED"
    STALLED = "STALLED"
    CANCELLED = "CANCELLED"


class FundingSource(str, Enum):
    CENTRAL_GOVT = "CENTRAL_GOVT"
    STATE_GOVT = "STATE_GOVT"
    PPP = "PPP"
    PRIVATE = "PRIVATE"
    MULTILATERAL = "MULTILATERAL"
    MIXED = "MIXED"


class DataConfidence(str, Enum):
    """Provenance confidence for a record.

    OFFICIAL            - straight from a primary government source
    VERIFIED_SECONDARY  - reputable secondary publication, cross-checked
    UNVERIFIED          - scraped/crowdsourced, not yet validated
    """

    OFFICIAL = "OFFICIAL"
    VERIFIED_SECONDARY = "VERIFIED_SECONDARY"
    UNVERIFIED = "UNVERIFIED"


class ProjectScale(str, Enum):
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class RawProject(BaseModel):
    """A single, source-normalized project record (pre-database).

    All date strings are ISO `YYYY-MM-DD`. Money is in INR crores. Fields that
    a source cannot provide stay `None` - never improvised or interpolated.

    Cost fields carry distinct meanings and must not be collapsed:

    - `originalCostCr`  the sanctioned/approved cost
    - `costEstimateCr`  the CURRENT (revised/latest) estimate
    - `costActualCr`    cumulative expenditure to date

    Mapping `originalCostCr` and `costEstimateCr` to the same source field
    makes cost overrun identically zero, which is a false all-clear rather
    than a missing value. When a source publishes only one cost figure, set
    that one field and leave the other `None`; the pipeline records the gap
    instead of inventing the missing side.
    """

    name: str = Field(min_length=2, max_length=300)
    status: ProjectStatus = ProjectStatus.ONGOING
    sector: str = Field(min_length=1, max_length=100)
    implementingAgency: Optional[str] = Field(default=None, max_length=200)
    ministry: Optional[str] = Field(default=None, max_length=200)
    stateName: str = Field(min_length=2, max_length=100)
    districtName: Optional[str] = Field(default=None, max_length=100)
    startDate: Optional[str] = None
    plannedEndDate: Optional[str] = None
    actualEndDate: Optional[str] = None
    originalCostCr: Optional[float] = Field(default=None, ge=0)
    costEstimateCr: Optional[float] = Field(default=None, ge=0)
    costActualCr: Optional[float] = Field(default=None, ge=0)
    physicalProgressPct: Optional[float] = Field(default=None, ge=0, le=100)
    fundingSource: Optional[FundingSource] = None
    description: Optional[str] = None
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    externalRef: Optional[str] = None
    sourceUrl: Optional[str] = None
    retrievedDate: str = Field(min_length=10)
    confidence: DataConfidence = DataConfidence.UNVERIFIED
    # The sector label exactly as the source published it. Kept so a
    # source-specific mapping can be corrected later without going back to
    # the source; the canonical `sector` above is only the GovRisk label.
    sourceSector: Optional[str] = Field(default=None, max_length=200)
    # Qualitative risk branches a source can legitimately supply. Merged into
    # `Project.risk_inputs` under the ownership rules in `ingest.ownership`,
    # never written over a human's value.
    riskInputs: Optional[Dict[str, Any]] = None

    def effective_cost_cr(self) -> Optional[float]:
        """The cost that best represents the project today.

        Prefers the current estimate, falls back to the original. `None`
        when the source published neither.
        """
        if self.costEstimateCr is not None:
            return self.costEstimateCr
        return self.originalCostCr

    def has_cost_revision(self) -> bool:
        """True when the source published a cost that differs from the original."""
        if self.originalCostCr is None or self.costEstimateCr is None:
            return False
        return self.originalCostCr != self.costEstimateCr

    def has_coordinates(self) -> bool:
        """True only when BOTH coordinates are present and usable.

        A half-specified coordinate is not a location; treating it as one
        places the project in the wrong hemisphere.
        """
        return self.lat is not None and self.lng is not None

    def scale(self) -> Optional[ProjectScale]:  # noqa: N802 (pydantic method name)
        """Derive MEDIUM/LARGE from the project's effective cost.

        Thresholds (documented with the platform):
        MEDIUM = INR 100-1000 Cr, LARGE > INR 1000 Cr.
        Projects below 100 Cr are out of scope for this module and excluded
        upstream (they are not reported on the risk map).
        """
        from .normalize import derive_scale

        return derive_scale(self.effective_cost_cr())


# Convenience re-exports used by the pipeline and call sites.
__all__ = [
    "ProjectStatus",
    "FundingSource",
    "DataConfidence",
    "ProjectScale",
    "RawProject",
]