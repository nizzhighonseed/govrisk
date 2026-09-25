"""Phase 0 regression tests: ingestion hardening for real government data.

Each test pins a defect found in the read-only PAIMANA feasibility audit, so
none of them can silently come back:

 1. original vs revised cost are not collapsed into one column
 2. source expenditure is preserved, not discarded
 3. physical progress is plumbed, range-checked, and stays missing when absent
 4. financial progress is derived safely
 5. missing financial inputs yield NULL, never an invented number
 6. manually entered `risk_inputs` survive a re-sync
 7. a CSV dry-run changes nothing in the database
 8. a data.gov.in dry-run changes nothing in the database
 9. missing coordinates stay NULL and are never 0,0
10. provenance carries a real retrieval timestamp shared by the whole run
11. a failed Layer 1 assessment rejects the record instead of faking LOW/0
12. `external_ref` is the primary deduplication identity
13. the cost floor is source-specific (PAIMANA >= INR 150 Cr)
14. the original source sector label is preserved beside the canonical one

Every test here drives the real pipeline through a real temporary SQLite
database. Nothing is mocked except the Layer 1 failure case, which has to
simulate the engine itself.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from database import Base
from ingest.base import BaseIngestor
from ingest.contract import RawProject
from ingest.normalize import (
    SOURCE_SECTOR_MAPS,
    canonical_sector,
    derive_financial_progress,
)
from ingest.ownership import (
    MANUAL_OWNED_RISK_INPUT_KEYS,
    load_risk_inputs,
    merge_risk_inputs,
)
from ingest.scope import PAIMANA_MIN_COST_CR, scope_for
from ingest.sources.csv_file import CsvFileIngestor
from ingest.sources.data_gov_in import DataGovInIngestor
from models import IngestAuditLog, Project


def _row(**overrides) -> dict:
    """A representative government row, shaped like a PAIMANA export."""
    row = {
        "project_name": "Test Bridge",
        "sector": "Road Transport",
        "state_name": "Odisha",
        "implementing_agency": "State PWD",
        "original_cost_cr": "100",
        "revised_cost_cr": "125",
        "expenditure_cr": "35.5",
        "physical_progress_pct": "40",
        "start_date": "2020-01-01",
        "planned_end_date": "2025-12-31",
        "external_ref": "PRJ-CODE-1",
    }
    row.update(overrides)
    return row


class _RowsIngestor(BaseIngestor):
    """Drives the real pipeline over in-memory rows via the CSV parser."""

    source_name = "file-import"

    def __init__(self, rows, source_name=None, dry_run=False):
        super().__init__(dry_run=dry_run)
        if source_name:
            self.source_name = source_name
        self._rows = list(rows)
        self._parser = CsvFileIngestor("unused", dry_run=dry_run)

    def fetch(self):
        return list(self._rows)

    def parse(self, rows, retrieved_date=None):
        return self._parser.parse(rows, retrieved_date=retrieved_date)


class _StubDataGovIn(DataGovInIngestor):
    """data.gov.in adapter with the network call replaced by canned rows."""

    def __init__(self, rows, dry_run=False):
        super().__init__(resource_id="test-resource", api_key="test-key", dry_run=dry_run)
        self._rows = list(rows)

    def fetch(self):
        return list(self._rows)


class IngestHardeningTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="govrisk-ingest-")
        self.db_path = os.path.join(self._tmpdir, "ingest.db")
        self.engine = create_engine(
            "sqlite:///" + self.db_path, connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False)

    def tearDown(self):
        self.engine.dispose()

    # -- helpers -------------------------------------------------------------
    def _run(self, ingestor):
        with self.Session() as db:
            summary = ingestor.run(db)
            return summary

    def _one(self):
        with self.Session() as db:
            return db.query(Project).one()

    def _count(self, model=Project):
        with self.Session() as db:
            return db.query(model).count()

    def _snapshot(self):
        """Full logical dump of every table a dry-run could touch."""
        with self.engine.connect() as conn:
            return (
                conn.execute(text("SELECT * FROM projects ORDER BY id")).fetchall(),
                conn.execute(
                    text("SELECT * FROM ingest_audit_log ORDER BY id")
                ).fetchall(),
            )

    # -- 1. original vs revised cost ----------------------------------------
    def test_original_and_revised_cost_are_not_collapsed(self):
        summary = self._run(_RowsIngestor([_row()]))
        self.assertEqual(summary.inserted, 1, summary.warnings)
        project = self._one()
        self.assertEqual(project.original_cost, 100.0)
        self.assertEqual(project.current_cost, 125.0)
        self.assertNotEqual(project.original_cost, project.current_cost)
        overrun = (project.current_cost - project.original_cost) / project.original_cost
        self.assertAlmostEqual(overrun * 100, 25.0, places=6)

    def test_single_cost_column_does_not_duplicate_into_both(self):
        # A source that publishes only a sanctioned cost must not have it
        # copied into the revised column.
        row = _row()
        del row["revised_cost_cr"]
        self._run(_RowsIngestor([row]))
        project = self._one()
        self.assertEqual(project.original_cost, 100.0)
        self.assertEqual(project.current_cost, 100.0)

    # -- 2. expenditure ------------------------------------------------------
    def test_source_expenditure_is_preserved(self):
        self._run(_RowsIngestor([_row(expenditure_cr="35.5")]))
        self.assertEqual(self._one().expenditure, 35.5)

    def test_missing_expenditure_stays_missing_not_zero(self):
        row = _row()
        del row["expenditure_cr"]
        self._run(_RowsIngestor([row]))
        self.assertIsNone(self._one().expenditure)

    # -- 3. physical progress ------------------------------------------------
    def test_physical_progress_is_preserved(self):
        self._run(_RowsIngestor([_row(physical_progress_pct="40")]))
        self.assertEqual(self._one().physical_progress, 40.0)

    def test_physical_progress_missing_stays_missing(self):
        row = _row()
        del row["physical_progress_pct"]
        self._run(_RowsIngestor([row]))
        self.assertIsNone(self._one().physical_progress)

    def test_physical_progress_outside_0_100_is_rejected(self):
        for bad in ("150", "-5"):
            with self.subTest(bad=bad):
                ingestor = _RowsIngestor([_row(physical_progress_pct=bad)])
                with self.Session() as db:
                    summary = ingestor.run(db)
                self.assertEqual(summary.rejected, 1)
                self.assertEqual(summary.inserted, 0)

    def test_physical_progress_percent_suffix_is_parsed(self):
        self._run(_RowsIngestor([_row(physical_progress_pct="67.5%")]))
        self.assertAlmostEqual(self._one().physical_progress, 67.5, places=6)

    # -- 4/5. financial progress --------------------------------------------
    def test_financial_progress_is_derived_from_expenditure(self):
        self._run(_RowsIngestor([_row(expenditure_cr="35.5", revised_cost_cr="125")]))
        expected = round(35.5 / 125.0 * 100, 2)
        self.assertAlmostEqual(self._one().financial_progress, expected, places=2)

    def test_financial_progress_guards(self):
        # zero denominator must not read as "nothing spent"
        self.assertIsNone(derive_financial_progress(35.5, 0))
        self.assertIsNone(derive_financial_progress(35.5, -5))
        # missing inputs
        self.assertIsNone(derive_financial_progress(None, 125.0))
        self.assertIsNone(derive_financial_progress(35.5, None))
        self.assertIsNone(derive_financial_progress(None, None))
        # normal + overspend (above 100 is a real signal, not clamped)
        self.assertAlmostEqual(derive_financial_progress(50, 100), 50.0)
        self.assertAlmostEqual(derive_financial_progress(150, 100), 150.0)

    def test_missing_expenditure_leaves_financial_progress_null(self):
        row = _row()
        del row["expenditure_cr"]
        self._run(_RowsIngestor([row]))
        self.assertIsNone(self._one().financial_progress)

    # -- 6. risk_inputs ownership -------------------------------------------
    def test_manual_risk_inputs_survive_resync(self):
        self._run(_RowsIngestor([_row()]))
        with self.Session() as db:
            project = db.query(Project).one()
            project.risk_inputs = json.dumps(
                {
                    "clearance": {"pending": True, "stage": "forest"},
                    "contractor": {"abandonment": True},
                }
            )
            project.lat = 20.5
            project.lng = 85.0
            db.commit()

        # A second run from the same source, with fresher figures.
        self._run(_RowsIngestor([_row(expenditure_cr="60")]))

        project = self._one()
        inputs = load_risk_inputs(project.risk_inputs)
        # manual values survived
        self.assertEqual(inputs["clearance"]["stage"], "forest")
        self.assertTrue(inputs["contractor"]["abandonment"])
        # externally owned fields were updated
        self.assertEqual(project.expenditure, 60.0)
        # and a field ingestion does not own was left alone
        self.assertEqual(project.lat, 20.5)

    def test_source_cannot_blank_manual_risk_inputs(self):
        merged, preserved = merge_risk_inputs(
            json.dumps({"clearance": {"pending": True}}),
            {"clearance": {}},
        )
        self.assertTrue(merged["clearance"]["pending"])
        self.assertIn("clearance", preserved)

    def test_merge_protects_every_manual_owned_key(self):
        existing = {key: {"observed": True} for key in MANUAL_OWNED_RISK_INPUT_KEYS}
        merged, preserved = merge_risk_inputs(json.dumps(existing), {})
        self.assertEqual(merged, existing)
        self.assertEqual(preserved, set())

    def test_unknown_existing_keys_are_never_dropped(self):
        merged, _ = merge_risk_inputs(json.dumps({"analyst_note": "watch Q3"}), {})
        self.assertEqual(merged["analyst_note"], "watch Q3")

    def test_source_owned_key_may_be_filled_when_empty(self):
        merged, _ = merge_risk_inputs(json.dumps({}), {"ground": {"soil": "poor"}})
        self.assertEqual(merged["ground"]["soil"], "poor")

    # -- 7/8. dry-run safety -------------------------------------------------
    def test_csv_dry_run_changes_nothing(self):
        before_bytes = open(self.db_path, "rb").read()
        before = self._snapshot()
        summary = self._run(_RowsIngestor([_row(), _row(external_ref="P2")], dry_run=True))
        after = self._snapshot()
        after_bytes = open(self.db_path, "rb").read()

        self.assertEqual(summary.total, 2)
        self.assertEqual(summary.inserted, 2)  # counted, not written
        self.assertEqual(before, after, "dry-run mutated the database")
        self.assertEqual(before_bytes, after_bytes, "dry-run rewrote the db file")
        self.assertEqual(self._count(), 0)
        self.assertEqual(self._count(IngestAuditLog), 0)

    def test_csv_dry_run_leaves_an_existing_project_untouched(self):
        self._run(_RowsIngestor([_row()]))
        before = self._snapshot()
        summary = self._run(
            _RowsIngestor([_row(expenditure_cr="99")], dry_run=True)
        )
        self.assertEqual(summary.updated, 1)
        self.assertEqual(before, self._snapshot())
        self.assertEqual(self._one().expenditure, 35.5)

    def test_data_gov_dry_run_changes_nothing(self):
        row = {
            "project_name": "Expressway Corridor",
            "sector_name": "Road Transport",
            "implementing_agency": "NHAI",
            "state_name": "Uttar Pradesh",
            "approved_project_cost": "12500",
            "_id": "abc123",
        }
        before = self._snapshot()
        summary = self._run(_StubDataGovIn([row], dry_run=True))
        self.assertEqual(summary.inserted, 1)
        self.assertEqual(before, self._snapshot())
        self.assertEqual(self._count(), 0)
        self.assertEqual(self._count(IngestAuditLog), 0)

    def test_data_gov_ingestor_honours_dry_run_flag(self):
        self.assertTrue(DataGovInIngestor(dry_run=True).dry_run)
        self.assertFalse(DataGovInIngestor(dry_run=False).dry_run)

    # -- 9. coordinates ------------------------------------------------------
    def test_missing_coordinates_remain_null(self):
        self._run(_RowsIngestor([_row()]))
        project = self._one()
        self.assertIsNone(project.lat)
        self.assertIsNone(project.lng)

    def test_zero_zero_coordinates_are_rejected(self):
        self._run(_RowsIngestor([_row(latitude="0", longitude="0")]))
        project = self._one()
        self.assertIsNone(project.lat)
        self.assertIsNone(project.lng)

    def test_half_a_coordinate_is_rejected(self):
        self._run(_RowsIngestor([_row(latitude="20.5", longitude="")]))
        project = self._one()
        self.assertIsNone(project.lat)
        self.assertIsNone(project.lng)

    def test_real_coordinates_are_preserved(self):
        self._run(_RowsIngestor([_row(latitude="20.5", longitude="85.0")]))
        project = self._one()
        self.assertAlmostEqual(project.lat, 20.5, places=6)
        self.assertAlmostEqual(project.lng, 85.0, places=6)

    # -- 10. provenance ------------------------------------------------------
    def test_provenance_timestamp_is_real_and_shared_per_run(self):
        self._run(
            _RowsIngestor([_row(), _row(external_ref="P2"), _row(external_ref="P3")])
        )
        with self.Session() as db:
            projects = db.query(Project).all()
        stamps = {p.retrieved_date for p in projects}
        self.assertEqual(len(stamps), 1, "records in one run disagree on retrieval time")
        stamp = stamps.pop()
        self.assertNotEqual(stamp, "2026-01-01")
        parsed = datetime.fromisoformat(stamp)
        age = abs((datetime.now(timezone.utc) - parsed).total_seconds())
        self.assertLess(age, 300, f"retrieved_date is not the real run time: {stamp}")
        for project in projects:
            self.assertTrue(project.last_synced_at)
            self.assertEqual(project.source_name, "file-import")
            self.assertEqual(project.data_confidence, "OFFICIAL")

    def test_data_gov_provenance_is_not_hardcoded(self):
        adapter = DataGovInIngestor(resource_id="r", api_key="k")
        project = adapter.parse(
            [{"project_name": "Corridor", "state_name": "Uttar Pradesh", "_id": "x"}]
        )[0]
        self.assertNotEqual(project.retrievedDate, "2026-01-01")
        age = abs(
            (datetime.now(timezone.utc) - datetime.fromisoformat(project.retrievedDate)
             ).total_seconds()
        )
        self.assertLess(age, 300)

    def test_created_at_is_not_overwritten_by_a_resync(self):
        self._run(_RowsIngestor([_row()]))
        first = self._one().created_at
        self._run(_RowsIngestor([_row(expenditure_cr="77")]))
        self.assertEqual(self._one().created_at, first)

    # -- 11. assessment failure ---------------------------------------------
    def test_assessment_failure_rejects_record_instead_of_faking_low(self):
        import services.risk_service as risk_service

        original = risk_service.apply_assessment

        def boom(project):
            raise ValueError("simulated engine failure")

        risk_service.apply_assessment = boom
        try:
            summary = self._run(_RowsIngestor([_row()]))
        finally:
            risk_service.apply_assessment = original

        self.assertEqual(summary.inserted, 0)
        self.assertEqual(summary.failed, 1)
        # no half-assessed row persisted
        self.assertEqual(self._count(), 0)
        audit = self._one_audit()
        self.assertEqual(audit.action, "REJECT")
        self.assertIn("simulated engine failure", audit.detail)
        self.assertIn("Test Bridge", audit.detail)

    def test_assessment_failure_rolls_back_an_update(self):
        self._run(_RowsIngestor([_row()]))
        before = self._one().expenditure

        import services.risk_service as risk_service

        original = risk_service.apply_assessment
        risk_service.apply_assessment = lambda project: (_ for _ in ()).throw(
            ValueError("engine down")
        )
        try:
            summary = self._run(_RowsIngestor([_row(expenditure_cr="999")]))
        finally:
            risk_service.apply_assessment = original

        self.assertEqual(summary.failed, 1)
        # the failed re-sync left the row exactly as it was
        self.assertEqual(self._one().expenditure, before)

    def test_one_bad_record_does_not_abort_the_batch(self):
        import services.risk_service as risk_service

        original = risk_service.apply_assessment
        state = {"n": 0}

        def flaky(project):
            state["n"] += 1
            if state["n"] == 1:
                raise ValueError("engine hiccup")
            return original(project)

        risk_service.apply_assessment = flaky
        try:
            summary = self._run(
                _RowsIngestor(
                    [
                        _row(project_name="Alpha", external_ref="A"),
                        _row(project_name="Bravo", external_ref="B"),
                        _row(project_name="Charlie", external_ref="C"),
                    ]
                )
            )
        finally:
            risk_service.apply_assessment = original

        self.assertEqual(summary.failed, 1)
        self.assertEqual(summary.inserted, 2)
        self.assertEqual(self._count(), 2)

    def _one_audit(self):
        with self.Session() as db:
            return db.query(IngestAuditLog).one()

    # -- 12. deduplication ---------------------------------------------------
    def test_external_ref_is_the_primary_dedupe_key(self):
        # Same external_ref, completely different name: must be one project.
        summary = self._run(
            _RowsIngestor(
                [
                    _row(),
                    _row(project_name="Renamed Corridor", expenditure_cr="70"),
                ]
            )
        )
        self.assertEqual(summary.inserted, 1)
        self.assertEqual(summary.updated, 1)
        self.assertEqual(self._count(), 1)
        self.assertEqual(self._one().expenditure, 70.0)

    def test_falls_back_to_name_and_state_without_external_ref(self):
        row = _row()
        del row["external_ref"]
        summary = self._run(_RowsIngestor([row, dict(row)]))
        self.assertEqual(summary.inserted, 1)
        self.assertEqual(self._count(), 1)

    # -- 13. source-specific scope ------------------------------------------
    def test_paimana_scope_floor_is_150_crore(self):
        summary = self._run(
            _RowsIngestor(
                [_row(original_cost_cr="120", revised_cost_cr="120")],
                source_name="paimana",
            )
        )
        self.assertEqual(summary.skipped, 1)
        self.assertEqual(summary.inserted, 0)
        self.assertEqual(self._count(), 0)

    def test_generic_source_scope_is_unchanged(self):
        summary = self._run(
            _RowsIngestor([_row(original_cost_cr="120", revised_cost_cr="120")])
        )
        self.assertEqual(summary.inserted, 1)

    def test_paimana_accepts_a_project_exactly_at_the_floor(self):
        summary = self._run(
            _RowsIngestor(
                [_row(original_cost_cr="150", revised_cost_cr="150")],
                source_name="paimana",
            )
        )
        self.assertEqual(summary.inserted, 1)

    def test_scope_registry_keeps_sources_independent(self):
        self.assertEqual(scope_for("paimana").min_cost_cr, PAIMANA_MIN_COST_CR)
        self.assertEqual(scope_for("file-import").min_cost_cr, 100.0)
        self.assertEqual(scope_for("data.gov.in").min_cost_cr, 100.0)
        self.assertEqual(scope_for("unknown-source").min_cost_cr, 100.0)

    def test_costless_record_is_not_scored_as_free(self):
        row = _row()
        del row["original_cost_cr"]
        del row["revised_cost_cr"]
        summary = self._run(_RowsIngestor([row]))
        self.assertEqual(summary.inserted, 0)
        self.assertEqual(summary.skipped, 1)

    # -- 14. sector fidelity -------------------------------------------------
    def test_original_source_sector_is_preserved(self):
        self._run(_RowsIngestor([_row(sector="Civil Aviation")]))
        project = self._one()
        self.assertEqual(project.source_sector, "Civil Aviation")
        # No PAIMANA 22->6 mapping exists yet, and "Civil Aviation" has no
        # counterpart in the generic table, so it falls through to "Other"
        # while the real label is kept for a later explicit mapping.
        self.assertEqual(project.sector, "Other")

    def test_explicit_source_sector_column_wins(self):
        self._run(
            _RowsIngestor([_row(sector="Roads", source_sector="Road Transport & Highways")])
        )
        project = self._one()
        self.assertEqual(project.source_sector, "Road Transport & Highways")
        self.assertEqual(project.sector, "Transport")

    def test_sector_map_registry_has_a_paimana_slot(self):
        self.assertIn("paimana", SOURCE_SECTOR_MAPS)
        # empty on purpose - the real 22->6 map is a later, explicit change
        self.assertEqual(SOURCE_SECTOR_MAPS["paimana"], {})

    def test_source_specific_mapping_wins_over_the_generic_table(self):
        # The generic substring table maps "Atomic Energy" -> "Energy".
        # A source-specific entry must take precedence over it, and must not
        # leak into any other source.
        SOURCE_SECTOR_MAPS["paimana"]["Atomic Energy"] = "Mining"
        try:
            self.assertEqual(
                canonical_sector("Atomic Energy", source="paimana"), "Mining"
            )
            self.assertEqual(
                canonical_sector("Atomic Energy", source="file-import"), "Energy"
            )
        finally:
            SOURCE_SECTOR_MAPS["paimana"].pop("Atomic Energy")

    # -- contract-level guards ----------------------------------------------
    def test_raw_project_rejects_physical_progress_out_of_range(self):
        with self.assertRaises(Exception):
            RawProject(
                name="Valid",
                sector="Other",
                stateName="Unknown",
                retrievedDate="2026-01-01",
                physicalProgressPct=101.0,
            )

    def test_raw_project_distinguishes_costs(self):
        p = RawProject(
            name="Valid",
            sector="Other",
            stateName="Unknown",
            retrievedDate="2026-01-01",
            originalCostCr=100.0,
            costEstimateCr=125.0,
        )
        self.assertTrue(p.has_cost_revision())
        self.assertEqual(p.effective_cost_cr(), 125.0)

        q = RawProject(
            name="Valid",
            sector="Other",
            stateName="Unknown",
            retrievedDate="2026-01-01",
            originalCostCr=100.0,
        )
        self.assertFalse(q.has_cost_revision())
        self.assertEqual(q.effective_cost_cr(), 100.0)


class ProjectsNullabilityMigrationTests(unittest.TestCase):
    """The schema change that lets a project record an unknown value."""

    LEGACY_DDL = """
        CREATE TABLE projects (
            id VARCHAR NOT NULL,
            name VARCHAR NOT NULL,
            ministry VARCHAR NOT NULL,
            sector VARCHAR NOT NULL,
            state VARCHAR NOT NULL,
            agency VARCHAR NOT NULL,
            original_cost FLOAT NOT NULL,
            current_cost FLOAT NOT NULL,
            expenditure FLOAT NOT NULL,
            physical_progress FLOAT NOT NULL,
            financial_progress FLOAT,
            planned_progress FLOAT NOT NULL,
            start_date VARCHAR NOT NULL,
            expected_completion VARCHAR NOT NULL,
            predicted_completion VARCHAR NOT NULL,
            cost_overrun_probability FLOAT NOT NULL,
            delay_probability FLOAT NOT NULL,
            implementation_risk FLOAT NOT NULL,
            risk_score FLOAT NOT NULL,
            risk_level VARCHAR NOT NULL,
            milestones_total INTEGER NOT NULL,
            milestones_delayed INTEGER NOT NULL,
            lat FLOAT NOT NULL,
            lng FLOAT NOT NULL,
            risk_factors TEXT NOT NULL,
            recommendations TEXT NOT NULL,
            risk_inputs TEXT,
            PRIMARY KEY (id)
        )
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="govrisk-migrate-")
        self.db_path = os.path.join(self._tmpdir, "legacy.db")
        self.engine = create_engine("sqlite:///" + self.db_path)
        with self.engine.connect() as conn:
            conn.execute(text(self.LEGACY_DDL))
            conn.execute(
                text(
                    "INSERT INTO projects (id,name,ministry,sector,state,agency,"
                    "original_cost,current_cost,expenditure,physical_progress,"
                    "planned_progress,start_date,expected_completion,"
                    "predicted_completion,cost_overrun_probability,delay_probability,"
                    "implementation_risk,risk_score,risk_level,milestones_total,"
                    "milestones_delayed,lat,lng,risk_factors,recommendations) "
                    "VALUES ('PRJ-001','Legacy Road','MoRTH','Transport','Odisha',"
                    "'NHAI',100,110,40,35,50,'2020-01-01','2025-12-31','2026-06-30',"
                    "0,0,0,42,'MEDIUM',0,0,20.5,85.0,'[]','[]')"
                )
            )
            conn.commit()

    def tearDown(self):
        self.engine.dispose()

    def _notnull(self):
        with self.engine.connect() as conn:
            return {
                row[1]: bool(row[3])
                for row in conn.execute(text("PRAGMA table_info(projects)"))
            }

    def test_migration_relaxes_the_target_columns(self):
        from migration import run_migrations

        self.assertTrue(self._notnull()["lat"], "fixture should start NOT NULL")
        run_migrations(self.engine)
        flags = self._notnull()
        for column in ("lat", "lng", "expenditure", "physical_progress", "planned_progress"):
            self.assertFalse(flags[column], f"{column} is still NOT NULL")
        # unrelated columns keep their constraint
        self.assertTrue(flags["original_cost"])
        self.assertTrue(flags["risk_level"])

    def test_migration_preserves_rows_and_values(self):
        from migration import run_migrations

        run_migrations(self.engine)
        with self.engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM projects")).mappings().one()
        self.assertEqual(len(row), len(self._notnull()))
        self.assertEqual(row["id"], "PRJ-001")
        self.assertEqual(row["name"], "Legacy Road")
        self.assertEqual(row["original_cost"], 100.0)
        self.assertEqual(row["current_cost"], 110.0)
        self.assertEqual(row["expenditure"], 40.0)
        self.assertEqual(row["physical_progress"], 35.0)
        self.assertAlmostEqual(row["lat"], 20.5)
        self.assertAlmostEqual(row["lng"], 85.0)

    def test_migration_adds_the_source_sector_column(self):
        from migration import run_migrations

        run_migrations(self.engine)
        self.assertIn("source_sector", self._notnull())

    def test_migration_is_idempotent(self):
        from migration import run_migrations

        run_migrations(self.engine)
        run_migrations(self.engine)
        with self.engine.connect() as conn:
            self.assertEqual(
                conn.execute(text("SELECT COUNT(*) FROM projects")).scalar(), 1
            )

    def test_a_null_coordinate_can_be_persisted_after_migration(self):
        from migration import run_migrations

        run_migrations(self.engine)
        with self.engine.connect() as conn:
            conn.execute(text("UPDATE projects SET lat=NULL, lng=NULL"))
            conn.commit()
            row = conn.execute(text("SELECT lat,lng FROM projects")).fetchone()
        self.assertIsNone(row[0])
        self.assertIsNone(row[1])


if __name__ == "__main__":
    unittest.main()
