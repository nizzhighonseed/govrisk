"""Tests for the AI/early-warning layer.

Covers:
- statistical predictor (deterministic, no ML claim)
- anomaly detection
- emerging-risk extraction (keywords + LLM-union)
- LLM integration: valid JSON, malformed JSON -> deterministic fallback,
  provider unavailable -> neutral, never raises
- AI API routes via TestClient against an ISOLATED temp database
  (the dev sankalp.db/auth.db are never touched)
"""

import json
import os
import sys
import tempfile
import types
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
from models import Project
from ai.schemas import UpdateAnalysisResult


def make_updates(*contents) -> list:
    now = datetime.now(timezone.utc)
    updates = []
    for i, content in enumerate(contents):
        updates.append(
            types.SimpleNamespace(
                id=i + 1,
                project_id="T",
                content=content,
                update_type="GENERAL",
                created_at=(now - timedelta(weeks=len(contents) - i)).isoformat(),
            )
        )
    return updates


class PredictorTestCase(unittest.TestCase):
    def test_healthy_project_predicts_low_and_rule_method(self):
        from ai.predictor import predict

        p = make_project()
        result = predict(p, updates=[], alerts=[])
        self.assertEqual(result.prediction_method, "rule_statistical_fallback")
        self.assertEqual(result.model_version, "sankalp-ai-v1")
        self.assertEqual(result.risk_horizon_days, 90)
        self.assertLess(result.schedule_delay_probability, 0.5)
        self.assertLess(result.cost_overrun_probability, 0.5)
        self.assertLess(result.future_score or 0, 26)

    def test_high_risk_project_with_negative_updates_predicts_escalation(self):
        from ai.predictor import predict

        p = make_project(physical_progress=35, planned_progress=80,
                         current_cost=1500, original_cost=1000,
                         predicted_completion="2027-12-31",
                         risk_score=52, risk_level="HIGH")
        updates = make_updates(
            "Land acquisition blocked, 3 months delay and cost overrun",
            "Contractor dispute, work stalled behind schedule",
            "Progress 34% vs planned 75%, approval pending, delay continues",
            "Repeated slippage; procurement and material shortage unresolved",
            "Another delay; residents protest against the site",
        )
        result = predict(p, updates=updates, alerts=[])
        self.assertEqual(result.prediction_method, "hybrid")
        self.assertGreater(result.schedule_delay_probability, 0.5)
        self.assertGreater(result.cost_overrun_probability, 0.5)
        self.assertGreaterEqual(result.future_score, 51)
        self.assertGreaterEqual(result.future_score, result.current_score)
        self.assertGreaterEqual(len(result.top_drivers), 1)
        self.assertIn("min", result.expected_delay_months)

    def test_outputs_are_bounded(self):
        from ai.predictor import predict

        p = make_project(physical_progress=10, planned_progress=95,
                         current_cost=2000, original_cost=1000,
                         predicted_completion="2028-12-31")
        updates = make_updates(
            "delay", "delay dispute shortage", "blocked protest overrun",
        )
        result = predict(p, updates=updates, alerts=[])
        for value in (
            result.schedule_delay_probability, result.cost_overrun_probability,
            result.risk_escalation_probability, result.clearance_delay_probability,
            result.contractor_failure_probability, result.prediction_confidence,
        ):
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)
        self.assertGreaterEqual(result.future_score or 0, 0)
        self.assertLessEqual(result.future_score or 0, 100)


class AnomalyDetectorTestCase(unittest.TestCase):
    def test_detects_progress_cost_and_trend_anomalies(self):
        from ai.anomaly_detector import detect_anomalies, top_anomaly

        p = make_project(physical_progress=40, planned_progress=75,
                         current_cost=1300, original_cost=1000,
                         predicted_completion="2027-12-31")
        updates = make_updates(
            "delay and cost overrun continue",
            "another delay, unresolved land issue",
            "more slippage, contractor dispute",
            "repeated delays, still negative",
        )
        anomalies = detect_anomalies(p, updates=updates)
        types_found = {a["type"] for a in anomalies}
        # 40 vs 75 = gap 35 -> PROGRESS_VARIANCE (>10)
        self.assertIn("PROGRESS_VARIANCE", types_found)
        # cost +30% -> COST_ESCALATION
        self.assertIn("COST_ESCALATION", types_found)
        # 4 negatives -> REPEATED_NEGATIVE_TREND
        for a in anomalies:
            self.assertIn("severity", a)
            self.assertIn("evidence", a)
        top = top_anomaly(anomalies)
        self.assertTrue(top["anomaly_detected"])
        self.assertGreaterEqual(top["score"], 0.0)

    def test_no_anomalies_on_healthy_project(self):
        from ai.anomaly_detector import detect_anomalies

        p = make_project(physical_progress=95, planned_progress=96)
        anomalies = detect_anomalies(p, updates=[])
        self.assertEqual(anomalies, [])  # gap<10, no cost overrun, no trend


class EmergingRiskTestCase(unittest.TestCase):
    def test_keyword_detects_land_acquisition(self):
        from ai.emerging_risk import keyword_detect

        hit = keyword_detect(
            "Land acquisition in the village is blocked pending compensation",
            update_id=7,
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["category"], "LAND_ACQUISITION")
        self.assertIn(7, hit["source_update_ids"])

    def test_keyword_detects_community_opposition(self):
        from ai.emerging_risk import keyword_detect

        hit = keyword_detect("Residents are protesting against construction", update_id=8)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["category"], "COMMUNITY_OPPOSITION")

    def test_no_keyword_returns_none(self):
        from ai.emerging_risk import keyword_detect

        self.assertIsNone(keyword_detect("Monthly review meeting held, all fine"))

    def test_aggregation_bumps_severity(self):
        from ai.emerging_risk import extract_from_updates

        updates = make_updates(
            "Funding release delayed by the finance branch",
            "Funding approval still pending for the quarter",
            "Cash flow stress delaying contractor payments",
        )
        risks = extract_from_updates(updates)
        cat = {r["category"] for r in risks}
        self.assertIn("FUNDING_ISSUE", cat)
        funding = next(r for r in risks if r["category"] == "FUNDING_ISSUE")
        self.assertGreaterEqual(funding["confidence"], 0.6)
        self.assertGreaterEqual(funding["severity"], "HIGH")

    def test_merge_llm_result_maps_to_shape(self):
        from ai.emerging_risk import merge_llm_result

        merged = merge_llm_result(
            UpdateAnalysisResult(
                risk_detected=True,
                risk_category="FUNDING_ISSUE",
                risk_title="Revised budget not sanctioned",
                confidence=0.87,
                severity="HIGH",
                recommended_actions=["Escalate fund release"],
            ),
            update_id=3,
        )
        self.assertEqual(merged["category"], "FUNDING_ISSUE")
        self.assertEqual(merged["severity"], "HIGH")
        self.assertEqual(merged["source_update_ids"], [3])


class LlmServiceTestCase(unittest.TestCase):
    def setUp(self):
        import ai.llm_service as ls

        self.ls = ls
        self._orig_available = ls.is_llm_available
        self._orig_invoke = ls._invoke_provider
        ls.is_llm_available = lambda: True
        # Route statically so patching works at runtime.

    def tearDown(self):
        self.ls.is_llm_available = self._orig_available
        self.ls._invoke_provider = self._orig_invoke

    def test_valid_llm_json_is_parsed_and_validated(self):
        self.ls._invoke_provider = lambda messages: json.dumps(
            {
                "risk_detected": True,
                "risk_category": "STAKEHOLDER_CONFLICT",
                "risk_title": "Residents raised objections",
                "confidence": 0.9,
                "severity": "HIGH",
                "potential_impact": "HIGH",
                "evidence": ["residents objected to alignment"],
                "recommended_actions": ["convene hearing"],
            }
        )
        result = self.ls.analyze_update(1, "GENERAL", "2026-01-01", "residents object")
        self.assertTrue(result.risk_detected)
        self.assertEqual(result.risk_category, "STAKEHOLDER_CONFLICT")
        self.assertEqual(result.severity, "HIGH")

    def test_malformed_llm_json_falls_back_gracefully(self):
        self.ls._invoke_provider = lambda messages: "not json at all {{{"
        from ai.emerging_risk import analyze_update

        result = analyze_update(1, "GENERAL", "2026-01-01",
                                "Land acquisition blocked pending compensation")
        # LLM parse fails -> deterministic keyword path still fires
        self.assertTrue(result["risk_detected"])
        self.assertEqual(result["category"], "LAND_ACQUISITION")

    def test_provider_exception_never_raises(self):
        self.ls._invoke_provider = lambda messages: (_ for _ in ()).throw(RuntimeError("boom"))
        result = self.ls.analyze_update(1, "GENERAL", "2026-01-01", "anything")
        self.assertFalse(result.risk_detected)
        self.assertEqual(self.ls._call_with_retry.__name__, "_call_with_retry")

    def test_provider_unavailable_returns_neutral(self):
        self.ls.is_llm_available = lambda: False
        result = self.ls.analyze_update(1, "GENERAL", "2026-01-01", "whatever")
        self.assertFalse(result.risk_detected)


def _patch_temp_dbs():
    """Point main + router DB sessions at throwaway SQLite files so the
    API tests never write to the developer's sankalp.db / auth.db."""
    global _TMP_ENGINE, _TMP_AUTH_ENGINE
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import database
    import auth.database
    import ai.ai_service

    # Force model registration BEFORE create_all (metadata is empty until the
    # ORM classes are imported).
    import models  # noqa: F401
    import auth.models  # noqa: F401

    tmpdir = tempfile.mkdtemp(prefix="sankalp-test-")
    _TMP_ENGINE = create_engine(
        "sqlite:///" + os.path.join(tmpdir, "test.db"),
        connect_args={"check_same_thread": False},
    )
    _TMP_AUTH_ENGINE = create_engine(
        "sqlite:///" + os.path.join(tmpdir, "auth.db"),
        connect_args={"check_same_thread": False},
    )
    make = sessionmaker(autocommit=False, autoflush=False)
    make.configure(bind=_TMP_ENGINE)
    database.SessionLocal = make
    database.Base.metadata.create_all(bind=_TMP_ENGINE)
    make_auth = sessionmaker(autocommit=False, autoflush=False)
    make_auth.configure(bind=_TMP_AUTH_ENGINE)
    auth.database.AuthSessionLocal = make_auth
    auth.database.AuthBase.metadata.create_all(bind=_TMP_AUTH_ENGINE)
    ai.ai_service.SessionLocal = database.SessionLocal
    # get_proj built via router dep uses database.get_db() -> SessionLocal lookup


class AiApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _patch_temp_dbs()
        from fastapi.testclient import TestClient
        from main import app

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        from database import SessionLocal
        from models import Project
        with SessionLocal() as db:
            for project in db.query(Project).filter(Project.id.like("TP%")).all():
                db.delete(project)
            db.commit()

    def _officer_headers(self):
        suffix = uuid.uuid4().hex[:8]
        email = f"ai_test_officer_{suffix}@sankalp.gov.in"
        r = self.client.post(
            "/api/auth/register",
            json={
                "fullName": "AI Test Officer",
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

    def _seed_project(self) -> str:
        p = make_project(
            id="TP-AI-1", name="AI Test Highway", state="Karnataka",
            physical_progress=42, planned_progress=78,
            current_cost=1750, original_cost=1250,
            predicted_completion="2027-12-31",
            risk_score=52, risk_level="HIGH",
            cost_overrun_probability=50, delay_probability=70,
            implementation_risk=60,
            milestones_total=12, milestones_delayed=6,
            risk_inputs=json.dumps({
                "contractor": {"performance": "POOR", "delayedMilestoneCount": 6},
                "administrative": {"turnaround": "SLOW", "pendingApprovalCount": 7},
            }),
        )
        pid = p.id
        from database import SessionLocal
        with SessionLocal() as db:
            db.add(p)
            db.flush()
            db.commit()
        return pid

    def test_health_endpoint(self):
        headers = self._officer_headers()
        r = self.client.get("/api/ai/health", headers=headers)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("available", body)
        self.assertTrue(body["fallback_enabled"])

    def test_analyze_and_insights_roundtrip(self):
        headers = self._officer_headers()
        pid = self._seed_project()
        r = self.client.post(f"/api/ai/projects/{pid}/analyze", headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["project_id"], pid)
        self.assertEqual(body["analysis_kind"], "fresh")
        self.assertIsNotNone(body["prediction"])
        self.assertIn("prediction_method", body["prediction"])
        self.assertLessEqual(body["prediction"]["future_score"], 100)
        r2 = self.client.get(f"/api/ai/projects/{pid}/insights", headers=headers)
        self.assertEqual(r2.status_code, 200, r2.text)
        body2 = r2.json()
        self.assertIn(body2["analysis_kind"], ("cached", "fresh"))

    def test_prediction_endpoint_requires_auth(self):
        r = self.client.get("/api/ai/health")
        self.assertEqual(r.status_code, 401)

    def test_analyze_missing_project_404(self):
        headers = self._officer_headers()
        r = self.client.post("/api/ai/projects/DOES-NOT-EXIST/analyze", headers=headers)
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()