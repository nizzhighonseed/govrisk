"""End-to-end API tests for the PARIKSHAN ML integration.

Uses an ISOLATED temp database + auth database (the dev db files are never
touched), loads the real trained artifacts, and verifies:
- /api/ai/ml-status and /api/ai/projects/{id}/ml-forecast
- the backward-compatible /prediction endpoint carries ml_forecast
- analyze persists ML rows (AIPrediction ml_* columns, MLSnapshot history)
- deterministic early-warning alerts are created and edge-triggered/deduped
- RBAC: ml-forecast restricted to admin/officer/analyst
- graceful 503 when the ML registry is unavailable
"""

import json
import os
import sys
import tempfile
import unittest
import uuid

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

try:
    from tests.test_risk_service import make_project
except ImportError:  # pragma: no cover - start dir variant (unittest discover)
    from test_risk_service import make_project

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _patch_temp_dbs() -> None:
    import database
    import auth.database
    import auth.models  # noqa: F401 - register tables on AuthBase.metadata
    import ai.ai_service

    tmpdir = tempfile.mkdtemp(prefix="sankalp-ml-test-")
    engine = create_engine(
        "sqlite:///" + os.path.join(tmpdir, "test.db"),
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


from models import Alert, MLSnapshot  # noqa: E402


class MlApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _patch_temp_dbs()
        from services import ml_prediction_service as mls
        mls.install_ml_service()
        from fastapi.testclient import TestClient
        from main import app
        cls.client = TestClient(app)

    def _auth_headers(self, role="officer"):
        suffix = uuid.uuid4().hex[:8]
        email = f"ml_test_{role}_{suffix}@sankalp.gov.in"
        r = self.client.post(
            "/api/auth/register",
            json={
                "fullName": "ML Test Officer",
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
            user.role = role
            user.is_approved = True
            db.commit()
        return {"Authorization": f"Bearer {r.json()['accessToken']}"}

    def _seed_project(self, pid="TP-ML-1", **overrides) -> str:
        defaults = dict(
            id=pid, name="ML Test Project", state="Karnataka",
            physical_progress=42, planned_progress=78,
            current_cost=1750, original_cost=1250,
            predicted_completion="2027-12-31",
            risk_score=52, risk_level="HIGH",
            cost_overrun_probability=50, delay_probability=70,
            implementation_risk=60,
            milestones_total=12, milestones_delayed=6,
            risk_inputs=json.dumps({
                "contractor": {"performance": "POOR", "delayedMilestoneCount": 6},
                "clearance": {"landAcquiredPct": 35},
            }),
        )
        defaults.update(overrides)
        p = make_project(**defaults)
        from database import SessionLocal
        with SessionLocal() as db:
            db.add(p)
            db.commit()
        return pid

    def test_ml_status_endpoint(self):
        headers = self._auth_headers()
        r = self.client.get("/api/ai/ml-status", headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["available"])
        self.assertTrue(str(body["model_version"]).startswith("parikshan-"))
        self.assertEqual(body["prediction_method"], "parikshan_ml")

    def test_ml_forecast_endpoint_returns_validated_forecast(self):
        headers = self._auth_headers()
        pid = self._seed_project("TP-ML-2")
        r = self.client.get(f"/api/ai/projects/{pid}/ml-forecast", headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        for key in ("cost_overrun_probability", "time_overrun_probability",
                    "severe_overrun_probability", "expected_cost_overrun_pct",
                    "expected_time_overrun_months"):
            self.assertIn(key, body)
        for prob in (body["cost_overrun_probability"],
                     body["time_overrun_probability"],
                     body["severe_overrun_probability"]):
            self.assertTrue(0.0 <= prob <= 1.0)
        self.assertTrue(body["cost_prediction_p10"] <= body["cost_prediction_p50"] <= body["cost_prediction_p90"])
        self.assertTrue(body["time_prediction_p10"] <= body["time_prediction_p50"] <= body["time_prediction_p90"])
        self.assertIn(body["risk_band"], ("Green", "Amber", "Red"))
        self.assertEqual(body["prediction_method"], "parikshan_ml")
        self.assertEqual(body["data_points_used"], 37)

    def test_ml_forecast_missing_project_404(self):
        headers = self._auth_headers()
        r = self.client.get("/api/ai/projects/NOPE-123/ml-forecast", headers=headers)
        self.assertEqual(r.status_code, 404)

    def test_ml_forecast_requires_roles(self):
        headers = self._auth_headers()
        pid = self._seed_project("TP-ML-3")
        viewer_headers = self._auth_headers(role="viewer")
        r = self.client.get(f"/api/ai/projects/{pid}/ml-forecast", headers=viewer_headers)
        self.assertEqual(r.status_code, 403)
        analyst_headers = self._auth_headers(role="analyst")
        r = self.client.get(f"/api/ai/projects/{pid}/ml-forecast", headers=analyst_headers)
        self.assertEqual(r.status_code, 200, r.text)

    def test_ml_forecast_is_optional_and_backward_compatible(self):
        headers = self._auth_headers()
        pid = self._seed_project("TP-ML-4")
        r = self.client.post(f"/api/ai/projects/{pid}/analyze", headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        prediction = body["prediction"]
        # pre-existing fields still present
        for key in ("schedule_delay_probability", "cost_overrun_probability",
                    "expected_delay_months", "future_score", "current_score",
                    "top_drivers"):
            self.assertIn(key, prediction)
        self.assertEqual(prediction["prediction_method"], "parikshan_ml")
        self.assertIsNotNone(prediction.get("ml_forecast"))
        mlf = prediction["ml_forecast"]
        self.assertTrue(0.0 <= mlf["risk_score"] <= 100.0)

        r2 = self.client.get(f"/api/ai/projects/{pid}/prediction", headers=headers)
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertIsNotNone(r2.json().get("ml_forecast"))

        r3 = self.client.get(f"/api/ai/projects/{pid}/insights", headers=headers)
        self.assertEqual(r3.status_code, 200, r3.text)
        self.assertIsNotNone(r3.json()["prediction"].get("ml_forecast"))

    def test_analyze_persists_ml_columns_and_snapshot(self):
        headers = self._auth_headers()
        pid = self._seed_project("TP-ML-5")
        self.client.post(f"/api/ai/projects/{pid}/analyze", headers=headers)
        from database import SessionLocal
        from models import AIPrediction
        with SessionLocal() as db:
            rec = (db.query(AIPrediction)
                   .filter(AIPrediction.project_id == pid)
                   .order_by(AIPrediction.created_at.desc()).first())
            self.assertIsNotNone(rec)
            self.assertIsNotNone(rec.ml_risk_score)
            self.assertIsNotNone(rec.ml_model_version)
            self.assertIsNotNone(rec.ml_cost_p10)
            self.assertIsNotNone(rec.ml_time_p90)
            snap = (db.query(MLSnapshot)
                    .filter(MLSnapshot.project_id == pid)
                    .order_by(MLSnapshot.created_at.desc()).first())
            self.assertIsNotNone(snap)
            self.assertEqual(snap.ml_risk_score, rec.ml_risk_score)

    def test_early_warning_alerts_created_and_edge_triggered(self):
        headers = self._auth_headers()
        pid = self._seed_project("TP-ML-6")
        self.client.post(f"/api/ai/projects/{pid}/analyze", headers=headers)
        from database import SessionLocal
        with SessionLocal() as db:
            count1 = db.query(Alert).filter(Alert.project_id == pid).count()
            types1 = {a.type for a in db.query(Alert).filter(Alert.project_id == pid).all()}
        self.assertGreaterEqual(count1, 1)
        self.assertTrue(
            any("AI Model" in t or "AI ML" in t for t in types1),
            f"No ML alerts created: {types1}",
        )
        # second analysis must not duplicate (edge-triggered + dedup window)
        self.client.post(f"/api/ai/projects/{pid}/analyze", headers=headers)
        with SessionLocal() as db:
            count2 = db.query(Alert).filter(Alert.project_id == pid).count()
        self.assertEqual(count2, count1)

    def test_deterministic_risk_fields_unchanged_by_ml(self):
        headers = self._auth_headers()
        pid = self._seed_project("TP-ML-7")
        r0 = self.client.get(f"/api/projects/{pid}", headers=headers)
        before = r0.json()["riskScore"]
        self.client.post(f"/api/ai/projects/{pid}/analyze", headers=headers)
        r1 = self.client.get(f"/api/projects/{pid}", headers=headers)
        after = r1.json()["riskScore"]
        self.assertEqual(before, after)


class MlUnavailableTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _patch_temp_dbs()
        from services import ml_prediction_service as mls
        mls.install_ml_service(enabled=False)
        from fastapi.testclient import TestClient
        from main import app
        cls.client = TestClient(app)

    def _officer_headers(self):
        suffix = uuid.uuid4().hex[:8]
        email = f"ml_unavail_{suffix}@sankalp.gov.in"
        r = self.client.post(
            "/api/auth/register",
            json={
                "fullName": "ML Unavailable Officer",
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
        pid = f"TP-ML-U-{uuid.uuid4().hex[:6]}"
        p = make_project(id=pid, state="Karnataka",
                         cost_overrun_probability=50, delay_probability=70,
                         implementation_risk=60, risk_score=52, risk_level="HIGH",
                         predicted_completion="2027-12-31",
                         milestones_total=10, milestones_delayed=0)
        from database import SessionLocal
        with SessionLocal() as db:
            db.add(p)
            db.commit()
        return pid

    def test_ml_status_reports_unavailable(self):
        headers = self._officer_headers()
        r = self.client.get("/api/ai/ml-status", headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["available"])

    def test_ml_forecast_503_when_unavailable(self):
        headers = self._officer_headers()
        pid = self._seed_project()
        r = self.client.get(f"/api/ai/projects/{pid}/ml-forecast", headers=headers)
        self.assertEqual(r.status_code, 503)

    def test_analyze_still_works_deterministically_when_ml_unavailable(self):
        headers = self._officer_headers()
        pid = self._seed_project()
        r = self.client.post(f"/api/ai/projects/{pid}/analyze", headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        prediction = r.json()["prediction"]
        self.assertIsNone(prediction.get("ml_forecast"))
        self.assertIn(prediction["prediction_method"], ("rule_statistical_fallback", "hybrid"))


if __name__ == "__main__":
    unittest.main()