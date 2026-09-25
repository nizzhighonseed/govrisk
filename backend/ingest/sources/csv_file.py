"""Local CSV / JSON ingestor for data extracted from government reports.

Gov sources without a structured API (NHAI annual reports, CEA monthly
reports, MoSPI releases, state PWD portals) are routinely extracted to
CSV/JSON before ingestion. This adapter consumes any such file through one
documented column map, so the extraction step stays out of this repo.

Expected header names (case/order-insensitive) for the strings pipeline:

    project_name, sector, source_sector, status, agency, ministry, state_name,
    district_name, start_date, planned_end_date, cost_estimate_cr,
    original_cost_cr, expenditure_cr, physical_progress_pct, funding_source,
    latitude, longitude, description, external_ref, source_url, confidence

Cost columns carry distinct meanings and must not be collapsed:

- `original_cost_cr`   sanctioned/approved cost   -> Project.original_cost
- `revised_cost_cr`    current/latest estimate     -> Project.current_cost
                        (falls back to `cost_estimate_cr`)
- `expenditure_cr`     spent to date              -> Project.expenditure

`financial_progress` is derived by the pipeline, not read from the file.

Unknown columns are ignored. Missing optional columns stay None (never
invented). Set `--source csv_file --file path/to/file.csv`.
"""

from __future__ import annotations

import csv
import json
import os
import re
from typing import Any, Dict, List, Optional, Sequence

from ..base import BaseIngestor
from ..contract import DataConfidence, FundingSource, ProjectStatus, RawProject
from ..normalize import to_iso_date

COLUMN_MAP = {
    "name": ("project_name", "name", "project"),
    "sector": ("sector", "sector_name"),
    "sourceSector": ("source_sector", "sector_raw", "sector_original"),
    "status": ("status", "project_status"),
    "agency": ("implementing_agency", "agency", "agency_name"),
    "ministry": ("ministry", "ministry_name"),
    "state": ("state_name", "state", "state_ut"),
    "district": ("district_name", "district"),
    "startDate": ("start_date", "commencement_date"),
    "plannedEndDate": ("planned_end_date", "end_date", "expected_completion"),
    "actualEndDate": ("actual_end_date", "completion_date"),
    # Distinct cost fields - see the module docstring.
    "originalCostCr": (
        "original_cost_cr",
        "original_cost",
        "sanctioned_cost_cr",
        "approved_cost_cr",
    ),
    "costEstimateCr": (
        "revised_cost_cr",
        "current_cost_cr",
        "latest_cost_cr",
        "cost_estimate_cr",
        "cost",
    ),
    "costActualCr": (
        "expenditure_cr",
        "expenditure_to_date_cr",
        "spend_cr",
        "cost_actual_cr",
    ),
    "physicalProgressPct": (
        "physical_progress_pct",
        "physical_progress",
        "progress_pct",
    ),
    "fundingSource": ("funding_source", "funding"),
    "lat": ("latitude", "lat"),
    "lng": ("longitude", "lng"),
    "description": ("description", "remarks"),
    "externalRef": ("external_ref", "id", "source_id"),
    "sourceUrl": ("source_url",),
    "retrievedDate": ("retrieved_date",),
    "confidence": ("confidence",),
}

# Government exports carry units inline: "1,234.50", "Rs 450", "67.5%".
_NUM_NOISE = re.compile(r"[,\s]|rs\.?|inr|cr|crore|%|₹", re.IGNORECASE)


def _pick(row: Dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _to_float(value: Any) -> Optional[float]:
    """Parse a number out of a government export cell.

    Returns None when the cell holds no number, which the pipeline records as
    a genuine data gap rather than a zero.
    """
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


class CsvFileIngestor(BaseIngestor):
    """One CSV/JSON file -> RawProject adapter. Uses COLUMN_MAP above."""

    source_name = "file-import"
    source_url = None

    def __init__(self, path: str, dry_run: bool = False) -> None:
        super().__init__(dry_run=dry_run)
        self.path = path

    def fetch(self) -> List[dict]:
        if not os.path.exists(self.path):
            raise FileNotFoundError(f"Ingest file not found: {self.path}")
        with open(self.path, encoding="utf-8-sig", newline="") as fh:
            if self.path.lower().endswith(".json"):
                data = json.load(fh)
                if isinstance(data, dict):
                    data = data.get("records", data.get("projects", []))
                return list(data)
            return list(csv.DictReader(fh))

    def parse(
        self, rows: Sequence[dict], retrieved_date: Optional[str] = None
    ) -> List[RawProject]:
        out: List[RawProject] = []
        for row in rows:
            name = _pick(row, COLUMN_MAP["name"])
            if not name:
                raise ValueError("Missing project_name column / value in row")
            row_retrieved = to_iso_date(_pick(row, COLUMN_MAP["retrievedDate"]))
            sector = str(_pick(row, COLUMN_MAP["sector"]) or "Other").strip()
            out.append(
                RawProject(
                    name=str(name).strip(),
                    sector=sector,
                    sourceSector=str(
                        _pick(row, COLUMN_MAP["sourceSector"]) or sector
                    ).strip(),
                    status=self._status(_pick(row, COLUMN_MAP["status"])),
                    implementingAgency=str(_pick(row, COLUMN_MAP["agency"]) or "").strip(),
                    ministry=str(_pick(row, COLUMN_MAP["ministry"]) or "").strip(),
                    stateName=str(_pick(row, COLUMN_MAP["state"]) or "Unknown").strip(),
                    districtName=str(_pick(row, COLUMN_MAP["district"]) or "").strip() or None,
                    startDate=to_iso_date(_pick(row, COLUMN_MAP["startDate"])),
                    plannedEndDate=to_iso_date(_pick(row, COLUMN_MAP["plannedEndDate"])),
                    actualEndDate=to_iso_date(_pick(row, COLUMN_MAP["actualEndDate"])),
                    originalCostCr=_to_float(_pick(row, COLUMN_MAP["originalCostCr"])),
                    costEstimateCr=_to_float(_pick(row, COLUMN_MAP["costEstimateCr"])),
                    costActualCr=_to_float(_pick(row, COLUMN_MAP["costActualCr"])),
                    physicalProgressPct=_to_float(
                        _pick(row, COLUMN_MAP["physicalProgressPct"])
                    ),
                    fundingSource=self._funding(_pick(row, COLUMN_MAP["fundingSource"])),
                    lat=_to_float(_pick(row, COLUMN_MAP["lat"])),
                    lng=_to_float(_pick(row, COLUMN_MAP["lng"])),
                    description=str(_pick(row, COLUMN_MAP["description"]) or "").strip() or None,
                    externalRef=str(_pick(row, COLUMN_MAP["externalRef"]) or "").strip() or None,
                    sourceUrl=str(_pick(row, COLUMN_MAP["sourceUrl"]) or "").strip() or None,
                    # The run timestamp wins so every record in a run shares
                    # one honest retrieval time; a per-row value is only a
                    # fallback for standalone `parse()` calls.
                    retrievedDate=(
                        retrieved_date or row_retrieved or _fallback_retrieved()
                    ),
                    confidence=self._confidence(_pick(row, COLUMN_MAP["confidence"])),
                )
            )
        return out

    @staticmethod
    def _status(value: Any) -> ProjectStatus:
        raw = str(value or "").strip().upper()
        for candidate in ProjectStatus:
            if candidate.name in raw or raw in candidate.value:
                return candidate
        return ProjectStatus.ONGOING

    @staticmethod
    def _funding(value: Any) -> Optional[FundingSource]:
        raw = str(value or "").strip().upper()
        for candidate in FundingSource:
            if candidate.name in raw or raw in candidate.value.upper():
                return candidate
        return None

    @staticmethod
    def _confidence(value: Any) -> DataConfidence:
        raw = str(value or "").strip().upper()
        for candidate in DataConfidence:
            if candidate.name in raw or raw in candidate.value:
                return candidate
        return DataConfidence.UNVERIFIED


def _fallback_retrieved() -> str:
    from ..base import now_iso

    return now_iso()


# TODO: connect real data source here - point this adapter at extracted
# government report CSVs (e.g. backend/data/extracts/nhai_projects.csv).
__all__ = ["CsvFileIngestor", "COLUMN_MAP"]
