"""Ingestion pipeline shared by every data source.

Flow: fetch() -> parse() -> validate -> normalize -> deduplicate -> upsert ->
Layer 1 assessment -> audit. Adapters implement `fetch` and `parse`;
everything downstream is data-source-agnostic, so adding a portal is one new
adapter file, not a change to the pipeline or the map.

Two invariants this module is responsible for, both of which were violated
before it was hardened for real government data:

1. A missing source value stays missing. It is never replaced by a zero, a
   default, or a placeholder, because a fabricated zero is a false signal
   rather than an absent one - "no coordinates" must not become a pin in the
   ocean, and "expenditure unknown" must not become "nothing spent".
2. Ingestion supplies facts and Layer 1 decides risk. The deterministic
   engine in `services.risk_service` remains the only risk algorithm; this
   module never computes a score of its own and never writes one by hand.
   A failed assessment is reported and the record is rejected, never replaced
   with a fabricated LOW/0 result.
"""

from __future__ import annotations

import inspect
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from .contract import DataConfidence, RawProject
from .normalize import (
    canonical_sector,
    canonical_state,
    derive_financial_progress,
    derive_scale,
    to_iso_date,
)
from .ownership import load_risk_inputs, merge_risk_inputs
from .scope import scope_for

logger = logging.getLogger("govrisk.ingest")

ACTION_INSERT = "INSERT"
ACTION_UPDATE = "UPDATE"
ACTION_SKIP = "SKIP"
ACTION_REJECT = "REJECT"

# Describes when a row was first created. A re-sync must never rewrite it.
_IMMUTABLE_ON_UPDATE: frozenset = frozenset({"created_at"})

# Columns where a NULL arriving from the source means "this source run did not
# publish it", not "the value is now unknown". Writing NULL over a real stored
# value would destroy good data with absent data - the mirror image of the
# fabricated-zero bug. These are fields an analyst or an earlier verified run
# can legitimately hold, and a source that omits them must leave them alone.
#
# Deliberately excluded: the DERIVED columns (financial_progress,
# planned_progress). Those are recomputed every run, so a stale value must be
# replaced rather than protected.
_PROTECT_EXISTING_ON_NULL: frozenset = frozenset(
    {
        "lat",
        "lng",
        "physical_progress",
        "expenditure",
        "district",
        "description",
        "funding_source",
        "source_url",
    }
)

_MAX_WARNINGS = 200


def now_iso() -> str:
    """One UTC timestamp, reused for every record written by a single run."""
    return datetime.now(timezone.utc).isoformat()


class IngestSummary:
    def __init__(self, source: str) -> None:
        self.source = source
        self.total = 0
        self.inserted = 0
        self.updated = 0
        self.skipped = 0
        self.rejected = 0
        # Records that parsed and validated but could not be persisted
        # because Layer 1 refused to assess them. Counted separately from
        # `rejected` so an assessment failure is never mistaken for bad input.
        self.failed = 0
        self.warnings: List[str] = []

    def warn(self, message: str) -> None:
        if len(self.warnings) < _MAX_WARNINGS:
            self.warnings.append(message)
        logger.warning("%s", message)

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "total": self.total,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
            "rejected": self.rejected,
            "failed": self.failed,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# value resolution helpers - each returns a value plus a note when it had to
# make a judgement call, so the judgement is auditable rather than silent.
# ---------------------------------------------------------------------------
def _resolve_costs(p: RawProject) -> Tuple[float, float, Optional[str]]:
    """Resolve (original_cost, current_cost) without collapsing a revision.

    When the source publishes both figures they are kept apart, so cost
    overrun stays a real measurement. When it publishes only one, the other
    side is filled from it - the columns are NOT NULL and there is no honest
    alternative - but the gap is reported rather than presented as a
    measured zero overrun.
    """
    original = p.originalCostCr
    current = p.costEstimateCr

    if original is None and current is None:
        return 0.0, 0.0, "source published no cost; cost columns defaulted to 0.0"

    if original is None:
        return current, current, (
            "source published no original cost; current cost used for both so the "
            "budget factor sees no overrun rather than a fabricated one"
        )

    if current is None:
        return original, original, (
            "source published no revised cost; original cost used for both"
        )

    return original, current, None


def _resolve_planned_progress(
    p: RawProject, physical: Optional[float]
) -> Tuple[Optional[float], Optional[str]]:
    """Derive the reference planned-progress curve, or report why it cannot be.

    Mirrors the manual create endpoint
    (`routers.projects.planned_progress_from_dates` -> fall back to physical
    progress) so an ingested project and an analyst-entered project are
    scored on the same basis.
    """
    from services.project_service import planned_progress_from_dates

    planned = planned_progress_from_dates(p.startDate or "", p.plannedEndDate or "")
    if planned is not None:
        return planned, None
    if physical is not None:
        return physical, (
            "planned progress not derivable from dates; physical progress used as "
            "the reference curve"
        )
    return None, "planned progress not derivable from dates or physical progress"


def _resolve_coordinates(p: RawProject) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """Coordinates, or (None, None). Never a placeholder.

    A source that has no coordinates for a project is the normal case for
    government project portals, so this is a routine path, not an error.
    """
    lat, lng = p.lat, p.lng
    if lat is None and lng is None:
        return None, None, None
    if (lat is None) != (lng is None):
        return None, None, (
            "source supplied only one coordinate; both discarded rather than "
            "plotting a half-known location"
        )
    if lat == 0.0 and lng == 0.0:
        return None, None, (
            "source supplied 0,0 (open ocean, not a project site); discarded"
        )
    return lat, lng, None


class BaseIngestor:
    """Adapter base class. Subclasses implement `fetch` and `parse` only."""

    source_name = "base"
    source_url: Optional[str] = None
    confidence = DataConfidence.UNVERIFIED

    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run

    @property
    def scope(self):
        """Cost floor and scope rules for THIS source.

        Resolved from the source name so no adapter can silently inherit
        another source's threshold. See `ingest/scope.py`.
        """
        return scope_for(self.source_name)

    # -- Adapter surface -----------------------------------------------------
    def fetch(self) -> List[dict]:
        raise NotImplementedError

    def parse(
        self, rows: Sequence[dict], retrieved_date: Optional[str] = None
    ) -> List[RawProject]:
        """Map raw source rows to `RawProject`s.

        `retrieved_date` is the single timestamp for the whole run. Adapters
        must stamp it on every record so provenance reflects when the data was
        actually fetched, not when the adapter file was written.
        """
        raise NotImplementedError

    def _parse_accepts_retrieved_date(self) -> bool:
        try:
            return "retrieved_date" in inspect.signature(self.parse).parameters
        except (TypeError, ValueError):  # pragma: no cover - exotic callables
            return False

    # -- Model mapping (deterministic, source-agnostic) ----------------------
    def _build_record(
        self, p: RawProject, run_ts: str
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Build the DB column dict (no `id`) for a validated RawProject.

        Returns the record and a list of human-readable notes describing any
        judgement call or data gap, which the caller surfaces in the run
        summary and the audit ledger.
        """
        notes: List[str] = []
        scale = derive_scale(p.effective_cost_cr())
        original_cost, current_cost, note = _resolve_costs(p)
        if note:
            notes.append(note)

        expenditure = p.costActualCr
        physical = p.physicalProgressPct
        financial = derive_financial_progress(expenditure, current_cost)
        if financial is None and (expenditure is not None or current_cost):
            notes.append(
                "financial progress not derivable (expenditure or current cost "
                "missing/non-positive); left NULL for Layer 1 to handle"
            )

        planned, note = _resolve_planned_progress(p, physical)
        if note:
            notes.append(note)

        lat, lng, note = _resolve_coordinates(p)
        if note:
            notes.append(note)

        expected = p.plannedEndDate or ""
        retrieved = to_iso_date(p.retrievedDate) or p.retrievedDate

        record: Dict[str, Any] = {
            "name": p.name.strip(),
            "ministry": (p.ministry or p.implementingAgency or "Unknown").strip(),
            "sector": canonical_sector(p.sector, source=self.source_name),
            "state": canonical_state(p.stateName),
            "agency": (p.implementingAgency or p.ministry or "Unknown").strip(),
            "district": p.districtName,
            "description": p.description,
            "original_cost": original_cost,
            "current_cost": current_cost,
            "expenditure": expenditure,
            "physical_progress": physical,
            "financial_progress": financial,
            "planned_progress": planned,
            "start_date": p.startDate or "",
            "expected_completion": expected,
            "predicted_completion": expected,
            "cost_overrun_probability": 0.0,
            "delay_probability": 0.0,
            "implementation_risk": 0.0,
            "risk_score": 0.0,
            "risk_level": "LOW",
            "milestones_total": 0,
            "milestones_delayed": 0,
            "lat": lat,
            "lng": lng,
            "risk_factors": json.dumps([]),
            "recommendations": json.dumps([]),
            "risk_inputs": json.dumps(p.riskInputs or {}),
            "risk_confidence": None,
            "risk_report": None,
            "created_at": run_ts,
            "updated_at": run_ts,
            "status": p.status.value,
            "scale": scale.value if scale else None,
            "funding_source": p.fundingSource.value if p.fundingSource else None,
            "external_ref": p.externalRef,
            "source_name": self.source_name,
            "source_url": p.sourceUrl or self.source_url,
            # The source's own sector label, kept verbatim so a corrected
            # mapping can be applied later without re-reading the source.
            "source_sector": (p.sourceSector or p.sector or "").strip() or None,
            "retrieved_date": retrieved,
            "data_confidence": p.confidence.value,
            "last_synced_at": run_ts,
        }
        return record, notes

    # -- Layer 1 -------------------------------------------------------------
    @staticmethod
    def _populate_risk(project) -> Optional[str]:
        """Recompute cached risk columns with the deterministic risk engine.

        Returns None on success, or a diagnostic string on failure. The
        caller decides what to do with a failure; this method never swallows
        one and never writes a substitute score, because a fabricated LOW/0
        row is indistinguishable from a genuinely healthy project once it is
        in the database.
        """
        try:
            from services.risk_service import apply_assessment

            apply_assessment(project)
            return None
        except Exception as exc:  # noqa: BLE001 - diagnostic must be returned
            return f"{type(exc).__name__}: {exc}"

    # -- Scope ---------------------------------------------------------------
    def _out_of_scope(self, p: RawProject) -> Optional[str]:
        """Reason when a record falls outside this source's scope."""
        return self.scope.out_of_scope_reason(p.effective_cost_cr())

    # -- Dedup ---------------------------------------------------------------
    def _find_existing(self, db: Session, p: RawProject):
        """Locate the row this record refers to.

        `external_ref` is the primary identity whenever the source provides
        one: a government project code is stable and unique, whereas the
        name+state fallback collides on long near-duplicate project names.
        """
        from models import Project

        if p.externalRef:
            found = (
                db.query(Project)
                .filter(Project.external_ref == p.externalRef)
                .first()
            )
            if found is not None:
                return found
        return (
            db.query(Project)
            .filter(
                func.lower(Project.name) == p.name.strip().lower(),
                func.lower(Project.state) == canonical_state(p.stateName).lower(),
            )
            .first()
        )

    # -- Audit ---------------------------------------------------------------
    def _audit(
        self, db: Session, action: str, project_id: Optional[str], detail: str
    ) -> None:
        if self.dry_run:
            return
        from models import IngestAuditLog

        db.add(
            IngestAuditLog(
                source=self.source_name,
                project_id=project_id,
                action=action,
                detail=detail[:2000],
                created_at=now_iso(),
            )
        )

    # -- Run -----------------------------------------------------------------
    def run(self, db: Session) -> IngestSummary:
        """Validate -> dedupe -> upsert -> assess every fetched record.

        In `dry_run` mode this performs the full read/parse/validate/normalize
        path and computes the record each row would produce, but performs no
        INSERT, UPDATE, DELETE, assessment write or audit write.
        """
        from models import Project
        from services.project_service import next_project_id

        run_ts = now_iso()
        summary = IngestSummary(self.source_name)
        rows = self.fetch() or []
        summary.total = len(rows)
        accepts_retrieved = self._parse_accepts_retrieved_date()

        parsed: List[RawProject] = []
        for row in rows:
            try:
                if accepts_retrieved:
                    parsed.extend(self.parse([row], retrieved_date=run_ts))
                else:
                    parsed.extend(self.parse([row]))
            except Exception as exc:  # a bad row must not kill the run
                summary.rejected += 1
                summary.warn(f"Rejected raw row (parse): {type(exc).__name__}: {exc}")
                self._audit(db, ACTION_REJECT, None, f"Parse error: {exc}")

        for p in parsed:
            label = f"{p.name.strip()} [{p.externalRef or 'no-ref'}]"
            reason = self._out_of_scope(p)
            if reason:
                summary.skipped += 1
                summary.warn(f"Skipped {label}: {reason}")
                self._audit(db, ACTION_SKIP, None, f"{label}: {reason}")
                continue

            existing = self._find_existing(db, p)
            if existing is not None:
                changed, error, preserved = self._apply(db, existing, p, run_ts)
                if error:
                    summary.failed += 1
                    summary.warn(f"Failed {label}: assessment error: {error}")
                    self._audit(
                        db,
                        ACTION_REJECT,
                        existing.id,
                        f"{label}: Layer 1 assessment failed, row left unchanged: {error}",
                    )
                    continue
                action = ACTION_UPDATE if changed else ACTION_SKIP
                detail = (
                    f"{label}: updated {len(changed)} fields"
                    if changed
                    else f"{label}: up-to-date"
                )
                if preserved:
                    detail += f"; preserved manual risk_inputs: {sorted(preserved)}"
                summary.updated += 1 if changed else 0
                self._audit(db, action, existing.id, detail)
                continue

            if self.dry_run:
                record, notes = self._build_record(p, run_ts)
                probe = _transient_project(record)
                error = self._populate_risk(probe)
                if error:
                    summary.failed += 1
                    summary.warn(
                        f"Failed {label}: assessment error (dry-run): {error}"
                    )
                    continue
                summary.inserted += 1
                for note in notes:
                    summary.warn(f"{label}: {note}")
                continue

            record, notes = self._build_record(p, run_ts)
            project = Project(id=next_project_id(db), **record)
            error = self._populate_risk(project)
            if error:
                # Reject the record rather than persist an unassessed row
                # whose cached columns would read as a healthy project.
                summary.failed += 1
                summary.warn(f"Failed {label}: assessment error: {error}")
                self._audit(
                    db,
                    ACTION_REJECT,
                    None,
                    f"{label}: Layer 1 assessment failed, project not created: {error}",
                )
                continue

            db.add(project)
            db.flush()
            summary.inserted += 1
            for note in notes:
                summary.warn(f"{label}: {note}")
            self._audit(
                db,
                ACTION_INSERT,
                project.id,
                f"{label}: inserted ({'; '.join(notes)})" if notes else f"{label}: inserted",
            )

        if not self.dry_run:
            db.commit()
        return summary

    def _apply(
        self, db: Session, project, p: RawProject, run_ts: str
    ) -> Tuple[List[str], Optional[str], Set[str]]:
        """Refresh source-owned columns on an existing row.

        Returns (changed field names, assessment error, preserved manual
        `risk_inputs` keys). On an assessment failure every field this method
        touched is rolled back, so a failed re-sync cannot leave a row with
        new costs and a stale risk score.
        """
        record, notes = self._build_record(p, run_ts)

        existing_inputs = load_risk_inputs(project.risk_inputs)
        merged_inputs, preserved = merge_risk_inputs(project.risk_inputs, p.riskInputs)
        # Always write the MERGED document, never the raw incoming one. A
        # source that carries no qualitative branches at all still produces
        # `{}` here, and writing that unconditionally is what used to erase
        # an analyst's judgements on every re-sync.
        record["risk_inputs"] = json.dumps(merged_inputs)
        if preserved:
            logger.info(
                "%s: manual risk_inputs preserved against source values for: %s",
                p.name.strip(),
                sorted(preserved),
            )

        updatable = {k: v for k, v in record.items() if k not in _IMMUTABLE_ON_UPDATE}
        originals = {k: getattr(project, k, None) for k in updatable}

        changed: List[str] = []
        for key, value in updatable.items():
            if (
                value is None
                and key in _PROTECT_EXISTING_ON_NULL
                and originals[key] is not None
            ):
                # The source is silent on a field that already holds a real
                # value. Keep it, and say so.
                logger.info(
                    "%s: source published no %s; keeping stored value %r",
                    p.name.strip(),
                    key,
                    originals[key],
                )
                continue
            if originals[key] != value:
                if not self.dry_run:
                    setattr(project, key, value)
                changed.append(key)

        if not changed or self.dry_run:
            return changed, None, preserved

        error = self._populate_risk(project)
        if error:
            for key, value in originals.items():
                setattr(project, key, value)
            return changed, error, preserved
        return changed, None, preserved


def _transient_project(record: Dict[str, Any]):
    """An unattached Project used to exercise Layer 1 without touching the DB."""
    from models import Project

    return Project(id="DRY-RUN", **record)


__all__ = [
    "BaseIngestor",
    "IngestSummary",
    "ACTION_INSERT",
    "ACTION_UPDATE",
    "ACTION_SKIP",
    "ACTION_REJECT",
    "now_iso",
]
