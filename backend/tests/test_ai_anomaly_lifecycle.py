"""P0 regression tests for the anomaly/ML layer.

Covers:
- migration path from the real legacy schema (columns + non-destructive
  backfill + index), not just create_all()
- one batch id per analysis, and _recent_anomalies returning every anomaly of
  the newest batch
- deduplication: one open row per (project, type) across repeated analyses
- auto-resolution when a condition disappears, history preserved
- explicit user resolution persists and is excluded from the active list
- RISK_JUMP actually fires when a previous canonical score is supplied
- ML snapshot provenance: cross-version snapshots never seed edge triggers
- Layer 1 fields are never overwritten by the AI layer
"""

import json
import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

try:
    from tests.test_risk_service import make_project
except ImportError:  # pragma: no cover - start dir variant (unittest discover)
    from test_risk_service import make_project
from models import Anomaly


def _iso(offset_seconds: int = 0) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    ).isoformat()


def _anomaly_rec(atype: str, score: float = 50.0, severity: str = "HIGH") -> dict:
    return {
        "type": atype,
        "severity": severity,
        "score": score,
        "title": f"{atype} detected",
        "description": "synthetic anomaly for the lifecycle test",
        "evidence": ["synthetic"],
    }


_VOLATILE_KEYS = (
    "id",
    "time",
    "date",
    "generated",
    "assessedat",
    "calculatedat",
    "timestamp",
    "createdat",
    "updatedat",
)


def _strip_volatile(payload):
    """Drop id/timestamp keys so two reports can be compared structurally."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            return payload
    if isinstance(payload, dict):
        return {
            k: _strip_volatile(v)
            for k, v in payload.items()
            if not any(tok in k.lower() for tok in _VOLATILE_KEYS)
        }
    if isinstance(payload, list):
        return [_strip_volatile(v) for v in payload]
    return payload


class _EngineTestCase(unittest.TestCase):
    """Gives each test class its own throwaway SQLite file."""

    def setUp(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        import database
        import models  # noqa: F401  (register ORM metadata)

        tmpdir = tempfile.mkdtemp(prefix="p0-ai-")
        self.engine = create_engine(
            "sqlite:///" + os.path.join(tmpdir, "p0.db"),
            connect_args={"check_same_thread": False},
        )
        database.Base.metadata.create_all(bind=self.engine)
        self._previous_session_local = database.SessionLocal
        make = sessionmaker(autocommit=False, autoflush=False)
        make.configure(bind=self.engine)
        database.SessionLocal = make
        self.Session = make

    def tearDown(self):
        import database

        database.SessionLocal = self._previous_session_local
        self.engine.dispose()


class MigrationPathTestCase(unittest.TestCase):
    """The migration must work on the schema that actually exists in the wild."""

    LEGACY_SCHEMA = [
        """CREATE TABLE ai_anomalies (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            type TEXT NOT NULL,
            severity TEXT,
            score FLOAT,
            title TEXT,
            description TEXT,
            evidence TEXT,
            resolved BOOLEAN DEFAULT 0
        )""",
        """CREATE TABLE ai_emerging_risks (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            category TEXT,
            title TEXT,
            confidence FLOAT,
            severity TEXT,
            description TEXT,
            evidence TEXT,
            recommendations TEXT,
            source_update_ids TEXT,
            status TEXT DEFAULT 'ACTIVE'
        )""",
        """CREATE TABLE ai_ml_snapshots (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            ml_risk_score FLOAT,
            ml_risk_band TEXT,
            ml_severe_overrun_probability FLOAT,
            ml_expected_cost_overrun_pct FLOAT,
            ml_expected_time_overrun_months FLOAT,
            feature_snapshot TEXT
        )""",
    ]

    def setUp(self):
        from sqlalchemy import create_engine, text

        tmpdir = tempfile.mkdtemp(prefix="p0-legacy-")
        self.engine = create_engine("sqlite:///" + os.path.join(tmpdir, "legacy.db"))
        with self.engine.connect() as conn:
            for ddl in self.LEGACY_SCHEMA:
                conn.execute(text(ddl))
            # Three legacy open duplicates of the same type, as measured in the
            # audit (146 rows, 0 resolved), plus one already-resolved row.
            for i in range(3):
                conn.execute(
                    text(
                        "INSERT INTO ai_anomalies (id, project_id, created_at, type, "
                        "severity, score, title, description, evidence, resolved) "
                        "VALUES (:id, 'LEGACY', :ts, 'PROGRESS_VARIANCE', 'HIGH', 50, "
                        "'t', 'd', '[]', 0)"
                    ),
                    {"id": f"a{i}", "ts": _iso(-3600 + i)},
                )
            conn.execute(
                text(
                    "INSERT INTO ai_anomalies (id, project_id, created_at, type, "
                    "severity, score, title, description, evidence, resolved) "
                    "VALUES ('a3', 'LEGACY', :ts, 'COST_ESCALATION', 'MEDIUM', 30, "
                    "'t', 'd', '[]', 1)"
                ),
                {"ts": _iso(-7200)},
            )
            conn.execute(
                text(
                    "INSERT INTO ai_emerging_risks (id, project_id, created_at, category, "
                    "title, confidence, severity, description, evidence, recommendations, "
                    "source_update_ids, status) VALUES ('e1', 'LEGACY', :ts, 'delay', "
                    "'t', 0.6, 'HIGH', 'd', '[]', '[]', '[]', 'RESOLVED')"
                ),
                {"ts": _iso(-7200)},
            )
            conn.execute(
                text(
                    "INSERT INTO ai_ml_snapshots (id, project_id, created_at, ml_risk_score, "
                    "ml_risk_band, ml_severe_overrun_probability, "
                    "ml_expected_cost_overrun_pct, ml_expected_time_overrun_months, "
                    "feature_snapshot) VALUES ('m1', 'LEGACY', :ts, 61.0, 'HIGH', 0.4, "
                    "12.0, 3.0, '{}')"
                ),
                {"ts": _iso(-7200)},
            )
            conn.commit()

    def tearDown(self):
        self.engine.dispose()

    def _columns(self, table: str) -> set:
        from sqlalchemy import text

        with self.engine.connect() as conn:
            return {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}

    def _indexes(self, table: str) -> set:
        from sqlalchemy import text

        with self.engine.connect() as conn:
            return {r[1] for r in conn.execute(text(f"PRAGMA index_list({table})"))}

    def test_migration_upgrades_legacy_schema_in_place(self):
        from migration import run_migrations

        run_migrations(self.engine)

        self.assertTrue(
            {"batch_id", "last_seen_at", "resolved_at"}
            <= self._columns("ai_anomalies")
        )
        self.assertIn("model_version", self._columns("ai_ml_snapshots"))
        self.assertIn("resolved_at", self._columns("ai_emerging_risks"))
        self.assertIn("ix_ai_anomalies_project_batch", self._indexes("ai_anomalies"))
        self.assertIn(
            "ix_ai_ml_snapshots_model_version", self._indexes("ai_ml_snapshots")
        )

    def test_migration_preserves_every_row_and_backfills(self):
        from migration import run_migrations
        from sqlalchemy import text

        run_migrations(self.engine)

        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, created_at, batch_id, last_seen_at, resolved, "
                    "resolved_at FROM ai_anomalies ORDER BY created_at"
                )
            ).all()
            # Nothing is deleted.
            self.assertEqual(len(rows), 4)
            for row in rows:
                # Every legacy row becomes the single member of its own batch.
                self.assertEqual(row[2], row[1])
                self.assertEqual(row[3], row[1])
            # Resolved rows (the pre-existing one plus the collapsed duplicates)
            # all carry a resolution timestamp; open ones do not.
            for row in rows:
                if row[4]:
                    self.assertIsNotNone(row[5], f"row {row[0]} missing resolved_at")
                else:
                    self.assertIsNone(row[5])
            # The pre-existing resolved row keeps its original resolution time.
            already = [r for r in rows if r[0] == "a3"][0]
            self.assertEqual(already[5], already[1])
            # Stale snapshot stays, but with unknown provenance (NULL).
            snaps = conn.execute(
                text("SELECT model_version FROM ai_ml_snapshots")
            ).all()
            self.assertEqual([s[0] for s in snaps], [None])

    def test_migration_collapses_legacy_duplicates_without_deleting(self):
        from migration import run_migrations
        from sqlalchemy import text

        run_migrations(self.engine)

        with self.engine.connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM ai_anomalies")).scalar()
            open_rows = conn.execute(
                text(
                    "SELECT COUNT(*) FROM ai_anomalies WHERE resolved = 0"
                )
            ).scalar()
        self.assertEqual(total, 4)
        # One open row per (project, type): 3 duplicates -> 1 open.
        self.assertEqual(open_rows, 1)

    def test_migration_is_idempotent(self):
        from migration import run_migrations
        from sqlalchemy import text

        run_migrations(self.engine)
        run_migrations(self.engine)
        with self.engine.connect() as conn:
            self.assertEqual(
                conn.execute(text("SELECT COUNT(*) FROM ai_anomalies")).scalar(), 4
            )

    def test_migration_labels_auto_closures_not_user_dismissals(self):
        """Legacy duplicates closed by the migration must be AUTO.

        If they were recorded as USER, a condition that later re-appeared would
        be silently swallowed instead of re-opening.
        """
        from migration import run_migrations
        from sqlalchemy import text

        run_migrations(self.engine)
        with self.engine.connect() as conn:
            collapsed = conn.execute(
                text(
                    "SELECT resolution_source FROM ai_anomalies "
                    "WHERE resolved = 1 AND type = 'PROGRESS_VARIANCE'"
                )
            ).all()
            self.assertEqual({r[0] for r in collapsed}, {"AUTO"})
            # A legacy row with no open sibling keeps the user interpretation.
            single = conn.execute(
                text(
                    "SELECT resolution_source FROM ai_anomalies "
                    "WHERE id = 'a3'"
                )
            ).scalar()
            self.assertEqual(single, "USER")

    def test_user_dismissal_is_not_relabelled_by_a_later_migration(self):
        from ai.ai_service import persist_anomalies, resolve_anomaly
        from migration import run_migrations
        from sqlalchemy import text
        from sqlalchemy.orm import sessionmaker

        make = sessionmaker(autocommit=False, autoflush=False)
        make.configure(bind=self.engine)
        run_migrations(self.engine)
        with make() as db:
            db.execute(
                text(
                    "INSERT INTO ai_anomalies (id, project_id, created_at, type, "
                    "severity, score, title, description, evidence, resolved) "
                    "VALUES ('u1', 'DISMISS', '2026-01-01T00:00:00+00:00', "
                    "'COST_ESCALATION', 'HIGH', 40, 't', 'd', '[]', 0)"
                )
            )
            db.commit()
            persist_anomalies(
                db, "DISMISS", [_anomaly_rec("COST_ESCALATION")], "batch-x"
            )
            db.commit()
            self.assertTrue(resolve_anomaly(db, "DISMISS", "u1"))
            db.commit()

        # A later migration run must not reinterpret that real dismissal.
        run_migrations(self.engine)
        with self.engine.connect() as conn:
            self.assertEqual(
                conn.execute(
                    text(
                        "SELECT resolution_source FROM ai_anomalies WHERE id='u1'"
                    )
                ).scalar(),
                "USER",
            )


class AnomalyBatchTestCase(_EngineTestCase):
    def test_one_batch_id_shared_by_every_detected_anomaly(self):
        from ai.ai_service import persist_anomalies, _recent_anomalies

        with self.Session() as db:
            batch = str(uuid.uuid4())
            persist_anomalies(
                db,
                "B1",
                [_anomaly_rec("PROGRESS_VARIANCE"), _anomaly_rec("COST_ESCALATION")],
                batch,
            )
            db.commit()
            rows = db.query(Anomaly).filter(Anomaly.project_id == "B1").all()
            self.assertEqual(len(rows), 2)
            self.assertEqual({r.batch_id for r in rows}, {batch})
            # Both anomalies of the batch are returned, not just one.
            listed = _recent_anomalies(db, "B1")
            self.assertEqual(len(listed), 2)
            self.assertEqual(
                {a["type"] for a in listed},
                {"PROGRESS_VARIANCE", "COST_ESCALATION"},
            )
            for item in listed:
                self.assertIn("id", item)
                self.assertFalse(item["resolved"])

    def test_repeated_analysis_does_not_duplicate_open_rows(self):
        from ai.ai_service import persist_anomalies

        with self.Session() as db:
            for _ in range(3):
                persist_anomalies(
                    db,
                    "B2",
                    [_anomaly_rec("PROGRESS_VARIANCE", 55.0)],
                    str(uuid.uuid4()),
                )
                db.commit()
            rows = (
                db.query(Anomaly)
                .filter(Anomaly.project_id == "B2", Anomaly.resolved.is_(False))
                .all()
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].score, 55.0)
            # The first detection timestamp survives re-detection.
            first_created = rows[0].created_at
            persist_anomalies(
                db, "B2", [_anomaly_rec("PROGRESS_VARIANCE", 60.0)], str(uuid.uuid4())
            )
            db.commit()
            self.assertEqual(
                db.query(Anomaly).filter(Anomaly.project_id == "B2").count(), 1
            )
            self.assertEqual(rows[0].created_at, first_created)

    def test_disappearing_condition_is_auto_resolved_and_history_kept(self):
        from ai.ai_service import persist_anomalies, _recent_anomalies

        with self.Session() as db:
            persist_anomalies(
                db,
                "B3",
                [_anomaly_rec("PROGRESS_VARIANCE"), _anomaly_rec("COST_ESCALATION")],
                str(uuid.uuid4()),
            )
            db.commit()
            # Second run only detects one of the two conditions.
            persist_anomalies(
                db, "B3", [_anomaly_rec("PROGRESS_VARIANCE")], str(uuid.uuid4())
            )
            db.commit()

            open_rows = (
                db.query(Anomaly)
                .filter(Anomaly.project_id == "B3", Anomaly.resolved.is_(False))
                .all()
            )
            self.assertEqual([r.type for r in open_rows], ["PROGRESS_VARIANCE"])

            stale = (
                db.query(Anomaly)
                .filter(Anomaly.project_id == "B3", Anomaly.type == "COST_ESCALATION")
                .one()
            )
            self.assertTrue(stale.resolved)
            self.assertIsNotNone(stale.resolved_at)
            # Historical row is retained with its original detection time.
            self.assertIsNotNone(stale.created_at)
            self.assertEqual(
                db.query(Anomaly).filter(Anomaly.project_id == "B3").count(), 2
            )
            self.assertEqual(
                [a["type"] for a in _recent_anomalies(db, "B3")], ["PROGRESS_VARIANCE"]
            )

    def test_reappearing_condition_opens_a_new_row(self):
        from ai.ai_service import persist_anomalies

        with self.Session() as db:
            persist_anomalies(
                db, "B4", [_anomaly_rec("COST_ESCALATION")], str(uuid.uuid4())
            )
            db.commit()
            # The condition disappears -> closed automatically.
            persist_anomalies(db, "B4", [], str(uuid.uuid4()))
            db.commit()
            closed = (
                db.query(Anomaly)
                .filter(Anomaly.project_id == "B4", Anomaly.type == "COST_ESCALATION")
                .one()
            )
            self.assertTrue(closed.resolved)
            self.assertEqual(closed.resolution_source, "AUTO")
            # It comes back -> a genuinely new occurrence opens a new row.
            persist_anomalies(
                db, "B4", [_anomaly_rec("COST_ESCALATION")], str(uuid.uuid4())
            )
            db.commit()
            rows = db.query(Anomaly).filter(Anomaly.project_id == "B4").all()
            self.assertEqual(len(rows), 2)
            self.assertEqual(
                len([r for r in rows if not r.resolved]),
                1,
                "the re-detected condition must be open again",
            )

    def test_user_dismissal_survives_reanalysis_of_the_same_condition(self):
        from ai.ai_service import persist_anomalies, resolve_anomaly

        with self.Session() as db:
            persist_anomalies(
                db, "B6", [_anomaly_rec("PROGRESS_VARIANCE")], str(uuid.uuid4())
            )
            db.commit()
            target = (
                db.query(Anomaly)
                .filter(Anomaly.project_id == "B6")
                .one()
            )
            self.assertTrue(resolve_anomaly(db, "B6", target.id))
            db.commit()
            dismissed_at = target.resolved_at

            # Same condition detected again on a later analysis run.
            persist_anomalies(
                db, "B6", [_anomaly_rec("PROGRESS_VARIANCE", 80.0)], str(uuid.uuid4())
            )
            db.commit()

            rows = db.query(Anomaly).filter(Anomaly.project_id == "B6").all()
            self.assertEqual(len(rows), 1, "no duplicate may be created")
            row = rows[0]
            self.assertTrue(row.resolved, "a user dismissal must not be undone")
            self.assertEqual(row.resolution_source, "USER")
            self.assertEqual(row.resolved_at, dismissed_at)
            # It is still being observed, so the record stays fresh.
            self.assertIsNotNone(row.last_seen_at)
            self.assertGreaterEqual(row.last_seen_at, dismissed_at)

    def test_resolved_rows_are_excluded_from_recent_view(self):
        from ai.ai_service import persist_anomalies, resolve_anomaly, _recent_anomalies

        with self.Session() as db:
            persist_anomalies(
                db,
                "B5",
                [_anomaly_rec("PROGRESS_VARIANCE"), _anomaly_rec("COST_ESCALATION")],
                str(uuid.uuid4()),
            )
            db.commit()
            target = (
                db.query(Anomaly)
                .filter(Anomaly.project_id == "B5", Anomaly.type == "COST_ESCALATION")
                .one()
            )
            self.assertTrue(resolve_anomaly(db, "B5", target.id))
            db.refresh(target)
            self.assertTrue(target.resolved)
            self.assertIsNotNone(target.resolved_at)
            remaining = _recent_anomalies(db, "B5")
            self.assertEqual([a["type"] for a in remaining], ["PROGRESS_VARIANCE"])

    def test_resolving_an_unknown_id_reports_failure(self):
        from ai.ai_service import resolve_anomaly

        with self.Session() as db:
            self.assertFalse(resolve_anomaly(db, "B5", "does-not-exist"))


class RiskJumpTestCase(_EngineTestCase):
    def test_jump_of_15_points_or_more_is_detected(self):
        from ai.anomaly_detector import detect_anomalies

        p = make_project(risk_score=75, risk_level="HIGH")
        found = detect_anomalies(p, updates=[], alerts=[], previous_risk_score=50)
        types = {a["type"] for a in found}
        self.assertIn("RISK_JUMP", types)
        jump = next(a for a in found if a["type"] == "RISK_JUMP")
        self.assertIn("50", " ".join(jump["evidence"]))
        self.assertIn("75", " ".join(jump["evidence"]))

    def test_small_move_does_not_trigger_jump(self):
        from ai.anomaly_detector import detect_anomalies

        p = make_project(risk_score=60, risk_level="HIGH")
        found = detect_anomalies(p, updates=[], alerts=[], previous_risk_score=50)
        self.assertNotIn("RISK_JUMP", {a["type"] for a in found})

    def test_no_previous_score_means_no_jump(self):
        from ai.anomaly_detector import detect_anomalies

        p = make_project(risk_score=75, risk_level="HIGH")
        found = detect_anomalies(p, updates=[], alerts=[])
        self.assertNotIn("RISK_JUMP", {a["type"] for a in found})

    def test_jump_uses_the_canonical_previous_score_from_history(self):
        """The orchestrator must thread the persisted previous score through."""
        from ai.ai_service import latest_prediction
        from models import AIPrediction

        with self.Session() as db:
            db.add(
                AIPrediction(
                    id=str(uuid.uuid4()),
                    project_id="P1",
                    created_at=_iso(-86400),
                    horizon_days=90,
                    schedule_delay_probability=0.3,
                    cost_overrun_probability=0.3,
                    risk_escalation_probability=0.2,
                    clearance_delay_probability=0.1,
                    contractor_failure_probability=0.1,
                    expected_delay_min=0,
                    expected_delay_max=1,
                    future_score=70,
                    current_score=48,
                    confidence=0.5,
                    prediction_method="rule_statistical_fallback",
                    model_version="sankalp-ai-v1",
                    drivers="[]",
                )
            )
            db.commit()
            previous = latest_prediction(db, "P1")
            self.assertEqual(previous.current_score, 48)
            p = make_project(risk_score=75, risk_level="HIGH")
            from ai.anomaly_detector import detect_anomalies

            found = detect_anomalies(
                p, updates=[], alerts=[], previous_risk_score=previous.current_score
            )
            self.assertIn("RISK_JUMP", {a["type"] for a in found})


class MlProvenanceTestCase(_EngineTestCase):
    def _ml_dict(self, risk_score: float, version: str) -> dict:
        return {
            "risk_score": risk_score,
            "risk_band": "HIGH",
            "cost_overrun_probability": 0.6,
            "time_overrun_probability": 0.5,
            "severe_overrun_probability": 0.4,
            "expected_cost_overrun_pct": 12.0,
            "expected_time_overrun_months": 3.0,
            "model_version": version,
            "top_drivers": ["cost"],
            "data_points_used": 10,
        }

    def test_snapshot_records_the_model_version(self):
        from ai.ai_service import _persist_ml_snapshot, _previous_ml_snapshot
        from models import MLSnapshot

        with self.Session() as db:
            _persist_ml_snapshot(db, "M1", self._ml_dict(60.0, "ml-fp-abc123"))
            db.commit()
            stored = db.query(MLSnapshot).filter(MLSnapshot.project_id == "M1").one()
            self.assertEqual(stored.model_version, "ml-fp-abc123")
            same = _previous_ml_snapshot(db, "M1", "ml-fp-abc123")
            self.assertIsNotNone(same)
            self.assertEqual(same.id, stored.id)

    def test_snapshot_from_another_model_version_is_not_a_baseline(self):
        from ai.ai_service import _persist_ml_snapshot, _previous_ml_snapshot

        with self.Session() as db:
            _persist_ml_snapshot(db, "M2", self._ml_dict(90.0, "ml-fp-OLD"))
            db.commit()
            self.assertIsNone(_previous_ml_snapshot(db, "M2", "ml-fp-NEW"))
            self.assertIsNone(_previous_ml_snapshot(db, "M2", None))

    def test_provenance_free_snapshot_never_seeds_edge_triggers(self):
        from ai.ai_service import _previous_ml_snapshot
        from models import MLSnapshot

        with self.Session() as db:
            db.add(
                MLSnapshot(
                    id=str(uuid.uuid4()),
                    project_id="M3",
                    created_at=_iso(-3600),
                    ml_risk_score=95.0,
                    ml_risk_band="CRITICAL",
                    ml_severe_overrun_probability=0.9,
                    ml_expected_cost_overrun_pct=40.0,
                    ml_expected_time_overrun_months=9.0,
                    feature_snapshot="{}",
                    model_version=None,
                )
            )
            db.commit()
            self.assertIsNone(_previous_ml_snapshot(db, "M3", "ml-fp-abc123"))


class LayerOneImmutabilityTestCase(_EngineTestCase):
    def test_layer_one_fields_match_the_layer_one_engine_after_analysis(self):
        """The AI layer may not invent risk values.

        `analyze_project` refreshes the cached Layer 1 columns through the
        deterministic engine (`project_for_analyze` -> `apply_assessment`), so
        the invariant is not "the numbers never change" but "whatever is
        stored is exactly what Layer 1 computed" - the AI layer has no vote.
        """
        from ai.ai_service import analyze_project
        from services.risk_service import apply_assessment

        with self.Session() as db:
            p = make_project(
                id="TP-P0-L1",
                name="P0 Layer One",
                physical_progress=38,
                planned_progress=80,
                current_cost=1600,
                original_cost=1200,
                predicted_completion="2027-12-31",
                # Placeholders only: analyze_project refreshes these through the
                # Layer 1 engine, and the assertions compare against the
                # engine's output rather than these values.
                risk_score=1,
                risk_level="LOW",
                risk_inputs=json.dumps(
                    {
                        "contractor": {
                            "performance": "POOR",
                            "delayedMilestoneCount": 6,
                        },
                        "administrative": {
                            "turnaround": "SLOW",
                            "pendingApprovalCount": 7,
                        },
                    }
                ),
                cost_overrun_probability=50,
                delay_probability=70,
                implementation_risk=60,
            )
            db.add(p)
            db.commit()

            # Expected Layer 1 state, computed by the engine on an identical row.
            expected = make_project(
                id="TP-P0-L1-EXPECTED",
                name="P0 Layer One",
                physical_progress=38,
                planned_progress=80,
                current_cost=1600,
                original_cost=1200,
                predicted_completion="2027-12-31",
                risk_score=1,
                risk_level="LOW",
                risk_inputs=json.dumps(
                    {
                        "contractor": {
                            "performance": "POOR",
                            "delayedMilestoneCount": 6,
                        },
                        "administrative": {
                            "turnaround": "SLOW",
                            "pendingApprovalCount": 7,
                        },
                    }
                ),
                cost_overrun_probability=50,
                delay_probability=70,
                implementation_risk=60,
            )
            apply_assessment(expected)

            analyze_project(db, "TP-P0-L1")
            db.expire_all()
            after = db.get(type(p), "TP-P0-L1")
            self.assertEqual(after.risk_score, expected.risk_score)
            self.assertEqual(after.risk_level, expected.risk_level)
            self.assertEqual(after.risk_factors, expected.risk_factors)
            self.assertEqual(after.risk_confidence, expected.risk_confidence)
            # risk_report embeds the project id and a wall-clock timestamp, so
            # compare the structural content with volatile keys removed.
            self.assertEqual(
                _strip_volatile(after.risk_report),
                _strip_volatile(expected.risk_report),
            )

            # Layer 2 output lands in its own columns, never on the project row.
            from models import AIPrediction

            pred = (
                db.query(AIPrediction)
                .filter(AIPrediction.project_id == "TP-P0-L1")
                .first()
            )
            self.assertIsNotNone(pred)
            self.assertIsNotNone(pred.future_score)
            for ai_only in ("future_score", "ml_risk_score"):
                self.assertTrue(
                    hasattr(after, ai_only) is False,
                    f"project row must not carry {ai_only}",
                )

    def test_analysis_response_exposes_resolvable_identifiers(self):
        from ai.ai_service import analyze_project

        with self.Session() as db:
            p = make_project(
                id="TP-P0-ID",
                name="P0 Identifiers",
                physical_progress=30,
                planned_progress=85,
                current_cost=1900,
                original_cost=1200,
                predicted_completion="2027-12-31",
                risk_score=61,
                risk_level="HIGH",
                cost_overrun_probability=50,
                delay_probability=70,
                implementation_risk=60,
            )
            db.add(p)
            db.commit()
            insights = analyze_project(db, "TP-P0-ID")
            self.assertTrue(insights.anomalies, "expected at least one anomaly")
            for item in insights.anomalies:
                self.assertTrue(item["id"])
                self.assertIn("resolved", item)
                self.assertFalse(item["resolved"])
            # Same shape as the cached path so the UI can always resolve.
            from ai.ai_service import _recent_anomalies

            cached_shape = _recent_anomalies(db, "TP-P0-ID")
            self.assertEqual(
                sorted(a["id"] for a in cached_shape),
                sorted(a["id"] for a in insights.anomalies),
            )


class ResolvedFilterTestCase(_EngineTestCase):
    def _seed(self, db):
        from ai.ai_service import persist_anomalies

        persist_anomalies(
            db,
            "TP-P0-F",
            [_anomaly_rec("PROGRESS_VARIANCE"), _anomaly_rec("COST_ESCALATION")],
            str(uuid.uuid4()),
        )
        db.commit()
        rows = db.query(Anomaly).filter(Anomaly.project_id == "TP-P0-F").all()
        db.query(Anomaly).filter(Anomaly.id == rows[0].id).one().resolved = True
        db.commit()
        return rows

    def test_listing_defaults_to_active_and_can_include_resolved(self):
        """Mirrors the router's filter without needing an HTTP client."""
        from ai.ai_service import _anomaly_to_dict

        with self.Session() as db:
            self._seed(db)
            active = (
                db.query(Anomaly)
                .filter(Anomaly.project_id == "TP-P0-F", Anomaly.resolved.is_(False))
                .all()
            )
            every = db.query(Anomaly).filter(Anomaly.project_id == "TP-P0-F").all()
            self.assertEqual(len(active), 1)
            self.assertEqual(len(every), 2)
            self.assertTrue(all("id" in _anomaly_to_dict(r) for r in every))


def _patch_temp_dbs():
    """Point main + router DB sessions at throwaway SQLite files."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import database
    import auth.database
    import ai.ai_service
    import models  # noqa: F401
    import auth.models  # noqa: F401

    tmpdir = tempfile.mkdtemp(prefix="p0-api-")
    engine = create_engine(
        "sqlite:///" + os.path.join(tmpdir, "api.db"),
        connect_args={"check_same_thread": False},
    )
    auth_engine = create_engine(
        "sqlite:///" + os.path.join(tmpdir, "auth.db"),
        connect_args={"check_same_thread": False},
    )
    make = sessionmaker(autocommit=False, autoflush=False)
    make.configure(bind=engine)
    database.SessionLocal = make
    database.Base.metadata.create_all(bind=engine)
    make_auth = sessionmaker(autocommit=False, autoflush=False)
    make_auth.configure(bind=auth_engine)
    auth.database.AuthSessionLocal = make_auth
    auth.database.AuthBase.metadata.create_all(bind=auth_engine)
    ai.ai_service.SessionLocal = database.SessionLocal


class AnomalyResolveApiTestCase(unittest.TestCase):
    """The UI flow: analyze -> list -> resolve -> refresh."""

    @classmethod
    def setUpClass(cls):
        _patch_temp_dbs()
        from fastapi.testclient import TestClient
        from main import app

        cls.client = TestClient(app)

    def _headers(self):
        email = f"p0_officer_{uuid.uuid4().hex[:8]}@sankalp.gov.in"
        r = self.client.post(
            "/api/auth/register",
            json={
                "fullName": "P0 Officer",
                "email": email,
                "password": "testpass123",
                "department": "IT",
                "designation": "Testing",
            },
        )
        self.assertEqual(r.status_code, 201, r.text)
        from auth.database import AuthSessionLocal
        from auth.models import User

        with AuthSessionLocal() as db:
            user = db.query(User).filter(User.email == email).first()
            user.role = "officer"
            user.is_approved = True
            db.commit()
        return {"Authorization": f"Bearer {r.json()['accessToken']}"}

    def _seed_project(self, pid: str) -> None:
        from database import SessionLocal

        p = make_project(
            id=pid,
            name="P0 Resolve Project",
            state="Karnataka",
            physical_progress=32,
            planned_progress=82,
            current_cost=1820,
            original_cost=1200,
            predicted_completion="2027-12-31",
            risk_score=1,
            risk_level="LOW",
            cost_overrun_probability=55,
            delay_probability=75,
            implementation_risk=60,
        )
        with SessionLocal() as db:
            db.add(p)
            db.commit()

    def test_resolve_anomaly_roundtrip(self):
        headers = self._headers()
        pid = "TP-P0-RESOLVE"
        self._seed_project(pid)

        r = self.client.post(f"/api/ai/projects/{pid}/analyze", headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["anomalies"], "expected detected anomalies")

        listed = self.client.get(f"/api/ai/projects/{pid}/anomalies", headers=headers)
        self.assertEqual(listed.status_code, 200, listed.text)
        active = listed.json()
        self.assertTrue(active)
        for item in active:
            self.assertTrue(item["id"], "list must expose an id the client can resolve")
            self.assertFalse(item["resolved"])

        target = active[0]
        resolved = self.client.post(
            f"/api/ai/projects/{pid}/anomalies/{target['id']}/resolve", headers=headers
        )
        self.assertEqual(resolved.status_code, 200, resolved.text)

        after = self.client.get(f"/api/ai/projects/{pid}/anomalies", headers=headers)
        self.assertNotIn(
            target["id"], [a["id"] for a in after.json()],
            "resolved anomaly must leave the default active list",
        )

        with_resolved = self.client.get(
            f"/api/ai/projects/{pid}/anomalies?include_resolved=true", headers=headers
        )
        history = {a["id"]: a for a in with_resolved.json()}
        self.assertIn(target["id"], history, "history must be retained")
        self.assertTrue(history[target["id"]]["resolved"])
        self.assertIsNotNone(history[target["id"]]["resolved_at"])

        # Re-analysis must not resurrect the user's resolution by duplicating.
        self.client.post(f"/api/ai/projects/{pid}/analyze", headers=headers)
        with_resolved2 = self.client.get(
            f"/api/ai/projects/{pid}/anomalies?include_resolved=true", headers=headers
        )
        history2 = {a["id"]: a for a in with_resolved2.json()}
        self.assertTrue(history2[target["id"]]["resolved"])
        self.assertEqual(len([a for a in history2.values() if not a["resolved"]]),
                         len([a for a in after.json() if not a["resolved"]]))

    def test_resolve_unknown_anomaly_is_404(self):
        headers = self._headers()
        pid = "TP-P0-RESOLVE-404"
        self._seed_project(pid)
        r = self.client.post(
            f"/api/ai/projects/{pid}/anomalies/not-a-real-id/resolve", headers=headers
        )
        self.assertEqual(r.status_code, 404)

    def test_ml_status_reports_unavailable_honestly(self):
        headers = self._headers()
        r = self.client.get("/api/ai/ml-status", headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("available", body)
        if not body["available"]:
            # No artifacts are shipped, so the API must not claim a forecast.
            self.assertTrue(
                body.get("error") or body.get("model_version") is None,
                "an unavailable ML status must explain itself",
            )


if __name__ == "__main__":
    unittest.main()
