"""data.gov.in (Open Government Data Platform India) adapter.

Source: https://data.gov.in  --  API: https://api.data.gov.in

Config (env):
  DATA_GOV_IN_API_KEY      required -- key issued for the domain you registered
  DATA_GOV_IN_RESOURCE_ID  required -- the `resource/{id}` dataset resource
  DATA_GOV_IN_BASE_URL     optional -- overrides the default endpoint host

The catalog changes schemas without notice, so the parser maps columns by
ALIASES (any of several common names) instead of hard-coding a snapshot. If a
resource uses different column names, add the alias here - the pipeline and
map need no changes.

Cost columns are kept distinct. `ORIGINAL`/`APPROVED`/`SANCTIONED` populate
`originalCostCr`, `REVISED`/`CURRENT`/`LATEST` populate `costEstimateCr`, and
neither is derived from the other. A resource that publishes only one figure
leaves the other field `None` so the pipeline reports the gap instead of
presenting a fabricated zero cost overrun.

NOTE: the raw `country` column is dropped; the parser targets Indian records
only (any extra rows fail state validation and are audited as rejects).
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlencode

from ..base import now_iso
from ..contract import (
    DataConfidence,
    FundingSource,
    ProjectStatus,
    RawProject,
)
from ..base import BaseIngestor
from ..normalize import to_iso_date

DEFAULT_BASE = "https://api.data.gov.in"
DEFAULT_LIMIT = 10000

_NUM_NOISE = re.compile(r"[,\s]|rs\.?|inr|cr|crore|%|₹", re.IGNORECASE)


def _pick(row: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = _NUM_NOISE.sub("", str(value)).strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return None


def _status(value: Optional[str]) -> ProjectStatus:
    raw = (value or "").strip().upper()
    for candidate in ProjectStatus:
        if candidate.name in raw or raw in candidate.value:
            return candidate
    return ProjectStatus.ONGOING


def _funding(value: Optional[str]) -> Optional[FundingSource]:
    raw = (value or "").strip().upper()
    for candidate in FundingSource:
        if candidate.name in raw or raw in candidate.value.upper():
            return candidate
    return None


def _parse_funding(row: Dict[str, Any]) -> Optional[FundingSource]:
    return _funding(_pick(row, "funding_source", "funding_source_type", "mode_of_financing"))


def _parse_status(row: Dict[str, Any]) -> ProjectStatus:
    return _status(_pick(row, "project_status", "status", "stage"))


def _parse_dates(row: Dict[str, Any]) -> dict:
    start = to_iso_date(_pick(row, "start_date", "commencement_date", "date_of_commencement"))
    planned = to_iso_date(_pick(row, "end_date", "expected_completion", "scheduled_completion_date"))
    actual = to_iso_date(_pick(row, "actual_end_date", "completion_date"))
    return {"startDate": start, "plannedEndDate": planned, "actualEndDate": actual}


class DataGovInIngestor(BaseIngestor):
    """data.gov.in resource -> RawProject adapter."""

    source_name = "data.gov.in"
    source_url = "https://data.gov.in"
    confidence = DataConfidence.OFFICIAL

    # Column names commonly seen across infrastructure datasets on the portal.
    # Original and revised cost are deliberately separate groups.
    ALIASES = {
        "name": ("project_name", "name_of_project", "project", "title", "scheme_name"),
        "sector": ("sector", "sector_name", "objective", "programme"),
        "source_sector": ("source_sector", "sector_raw", "sector_original"),
        "agency": ("implementing_agency", "implementation_agency", "agency", "department", "ministry"),
        "ministry": ("ministry", "ministry_name"),
        "state": ("state_name", "state", "state_ut_name"),
        "district": ("district_name", "district", "district_ut_name"),
        "original_cost": (
            "original_project_cost",
            "original_cost",
            "approved_project_cost",
            "sanctioned_cost",
            "original_estimated_cost",
        ),
        "revised_cost": (
            "revised_project_cost",
            "revised_cost",
            "current_cost",
            "latest_estimated_cost",
            "cost_estimate",
        ),
        "cost": ("project_cost", "estimated_cost", "total_cost", "cost"),
        "expenditure": (
            "expenditure",
            "expenditure_to_date",
            "expenditure_cr",
            "spend",
        ),
        "physical_progress": (
            "physical_progress",
            "physical_progress_pct",
            "progress_pct",
        ),
        "lat": ("latitude", "lat"),
        "lng": ("longitude", "lng", "lon"),
    }

    def __init__(
        self,
        resource_id: Optional[str] = None,
        api_key: Optional[str] = None,
        dry_run: bool = False,
    ) -> None:
        # `dry_run` is honoured here, not just for local files: a first call
        # against a live API key must never write, whatever the CLI does.
        super().__init__(dry_run=dry_run)
        self.resource_id = resource_id or os.environ.get("DATA_GOV_IN_RESOURCE_ID")
        self.api_key = api_key or os.environ.get("DATA_GOV_IN_API_KEY")
        self.base = os.environ.get("DATA_GOV_IN_BASE_URL", DEFAULT_BASE)

    def fetch(self) -> List[dict]:
        if not self.resource_id:
            raise RuntimeError(
                "DATA_GOV_IN_RESOURCE_ID is required. Open the dataset page on "
                "data.gov.in and copy the resource id from /resource/{id}."
            )
        if not self.api_key:
            raise RuntimeError(
                "DATA_GOV_IN_API_KEY is required. Get a key at "
                "https://data.gov.in/backend/mini-app-api and set it in the "
                "environment (never commit it)."
            )
        query = urlencode({"api-key": self.api_key, "format": "json", "limit": DEFAULT_LIMIT})
        url = f"{self.base}/resource/{self.resource_id}?{query}"
        import urllib.request

        with urllib.request.urlopen(url, timeout=30) as response:  # nosec: user-controlled env URL
            payload = response.read()
        import json

        data = json.loads(payload)
        records = data.get("records", [])
        if not records:
            raise RuntimeError(
                "data.gov.in returned no records. Check RESUMER_ID / API key / quota."
            )
        if len(records) >= DEFAULT_LIMIT:
            # Silent truncation would look like a complete import.
            raise RuntimeError(
                f"data.gov.in returned {len(records)} rows, the requested page limit. "
                "Paginate before ingesting, or raise DATA_GOV_IN_LIMIT deliberately - "
                "a truncated import must not be mistaken for a complete one."
            )
        return records

    def parse(
        self, rows: Sequence[dict], retrieved_date: Optional[str] = None
    ) -> List[RawProject]:
        out: List[RawProject] = []
        for row in rows:
            name = _pick(row, *self.ALIASES["name"])
            if not name:
                raise ValueError("Missing project name in source row")
            state = _pick(row, *self.ALIASES["state"])
            dates = _parse_dates(row)
            sector = str(_pick(row, *self.ALIASES["sector"]) or "Other").strip()
            # A resource that gives only a single generic cost column is used
            # for the current estimate; `originalCostCr` stays None so the
            # pipeline records that no sanctioned figure was published rather
            # than duplicating one figure into both columns.
            revised = _to_float(_pick(row, *self.ALIASES["revised_cost"]))
            if revised is None:
                revised = _to_float(_pick(row, *self.ALIASES["cost"]))
            out.append(
                RawProject(
                    name=str(name).strip(),
                    sector=sector,
                    sourceSector=str(
                        _pick(row, *self.ALIASES["source_sector"]) or sector
                    ).strip(),
                    status=_parse_status(row),
                    implementingAgency=str(_pick(row, *self.ALIASES["agency"]) or "").strip(),
                    ministry=str(_pick(row, *self.ALIASES["ministry"]) or "").strip(),
                    stateName=str(state).strip(),
                    districtName=str(_pick(row, *self.ALIASES["district"]) or "").strip() or None,
                    fundingSource=_parse_funding(row),
                    startDate=dates["startDate"],
                    plannedEndDate=dates["plannedEndDate"],
                    actualEndDate=dates["actualEndDate"],
                    originalCostCr=_to_float(_pick(row, *self.ALIASES["original_cost"])),
                    costEstimateCr=revised,
                    costActualCr=_to_float(_pick(row, *self.ALIASES["expenditure"])),
                    physicalProgressPct=_to_float(
                        _pick(row, *self.ALIASES["physical_progress"])
                    ),
                    lat=_to_float(_pick(row, *self.ALIASES["lat"])),
                    lng=_to_float(_pick(row, *self.ALIASES["lng"])),
                    description=str(_pick(row, "description", "project_details") or "").strip() or None,
                    externalRef=str(row.get("_id", "")).strip() or None,
                    sourceUrl=self.base,
                    # The retrieval time of THIS run, never a literal baked
                    # into the adapter.
                    retrievedDate=retrieved_date or now_iso(),
                    confidence=self.confidence,
                )
            )
        return out


# TODO: connect real data source here - set DATA_GOV_IN_RESOURCE_ID (+ key) to
# the specific infrastructure dataset, then run the pipeline (see ingest/run.py).
__all__ = ["DataGovInIngestor"]
