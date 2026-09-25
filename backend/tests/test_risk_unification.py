import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.ai_service import persist_prediction
from ai.schemas import MLForecast, PredictionResult
from models import Project
from routers.dashboard import get_dashboard
from routers.projects import (
    _project_to_response,
    create_project,
    get_project_risk,
    update_project,
)
from routers.risk_map import get_risk_map_data
from schemas import ProjectCreate, ProjectUpdate
from services import project_service
from services.risk_service import (
    assess_project,
    generate_assistant_response,
    get_project_analytics,
)


def _make_project(project_id="RISK-001", name="Canonical risk project"):
    return Project(
        id=project_id,
        name=name,
        ministry="Ministry of Roads",
        sector="Transport",
        state="Karnataka",
        agency="National Highways Authority",
        district="Bengaluru",
        description="A project used to verify live risk parity",
        original_cost=1000.0,
        current_cost=1000.0,
        expenditure=500.0,
        physical_progress=40.0,
        financial_progress=90.0,
        planned_progress=80.0,
        start_date="2024-01-01",
        expected_completion="2027-12-31",
        predicted_completion="",
        cost_overrun_probability=0.0,
        delay_probability=0.0,
        implementation_risk=0.0,
        risk_score=0.0,
        risk_level="LOW",
        milestones_total=10,
        milestones_delayed=5,
        lat=12.97,
        lng=77.59,
        risk_factors="[]",
        recommendations="[]",
        risk_inputs=json.dumps({
            "clearance": {
                "landAcquiredPct": 20,
                "environmentalClearance": "REJECTED",
            },
            "contractor": {
                "performance": "POOR",
                "delayedMilestoneCount": 5,
            },
            "administrative": {
                "turnaround": "SLOW",
                "pendingApprovalCount": 6,
            },
        }),
        risk_confidence=0.0,
        risk_report=json.dumps({"riskScore": 0}),
        status="ONGOING",
    )


def _session_with(projects=()):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    for project in projects:
        session.add(project)
    if projects:
        session.commit()
    return session, engine


def _close_session(session, engine):
    session.close()
    engine.dispose()


class _AuthCommitter:
    def commit(self):
        return None


class RiskAuthorityTestCase(unittest.TestCase):
    def test_legacy_project_risk_authority_is_removed(self):
        self.assertFalse(hasattr(project_service, "compute_project_risk"))
        self.assertFalse(hasattr(project_service, "_shift_date"))

    def test_project_create_update_and_read_responses_use_canonical_assessment(self):
        session, engine = _session_with()
        try:
            data = ProjectCreate(
                name="Created project",
                ministry="Ministry of Roads",
                agency="Agency A",
                sector="Transport",
                state="Karnataka",
                originalCost=1000,
                revisedCost=1000,
                expenditure=500,
                physicalProgress=40,
                financialProgress=90,
                startDate="2024-01-01",
                completionDate="2027-12-31",
                riskInputs={
                    "contractor": {"performance": "POOR"},
                    "clearance": {"environmentalClearance": "REJECTED"},
                },
            )
            with patch("routers.projects.log_audit"):
                created = create_project(
                    data,
                    SimpleNamespace(user_id="test-user"),
                    session,
                    _AuthCommitter(),
                )

            project = session.query(Project).one()
            created_assessment = assess_project(project)
            self.assertEqual(created["riskScore"], created_assessment["riskScore"])
            self.assertEqual(created["riskLevel"], created_assessment["riskLevel"])
            self.assertEqual(created["riskFactors"], created_assessment["explanations"])
            self.assertEqual(
                created["recommendations"], created_assessment["recommendations"]
            )
            self.assertEqual(created["riskConfidence"], created_assessment["confidence"])

            update_data = ProjectUpdate(
                revisedCost=1100,
                physicalProgress=70,
                financialProgress=75,
                riskInputs={"contractor": {"performance": "GOOD"}},
            )
            with patch("routers.projects.log_audit"):
                updated = update_project(
                    project.id,
                    update_data,
                    SimpleNamespace(user_id="test-user"),
                    session,
                    _AuthCommitter(),
                )

            session.refresh(project)
            updated_assessment = assess_project(project)
            self.assertEqual(updated["riskScore"], updated_assessment["riskScore"])
            self.assertEqual(updated["riskLevel"], updated_assessment["riskLevel"])
            self.assertEqual(project.risk_score, updated_assessment["riskScore"])
            self.assertEqual(project.risk_level, updated_assessment["riskLevel"])

            project.risk_score = 0.0
            project.risk_level = "LOW"
            project.delay_probability = 0.0
            project.cost_overrun_probability = 0.0
            session.commit()

            response = _project_to_response(project)
            risk_response = get_project_risk(project.id, session, None)
            self.assertEqual(response["riskScore"], updated_assessment["riskScore"])
            self.assertEqual(response["riskLevel"], updated_assessment["riskLevel"])
            self.assertEqual(risk_response["riskScore"], updated_assessment["riskScore"])
            self.assertEqual(risk_response["riskLevel"], updated_assessment["riskLevel"])
            self.assertEqual(project.risk_score, 0.0)
            self.assertEqual(project.risk_level, "LOW")
        finally:
            _close_session(session, engine)

    def test_dashboard_map_analytics_and_assistant_use_live_assessment(self):
        project = _make_project()
        session, engine = _session_with([project])
        try:
            session.refresh(project)
            assessment = assess_project(project)
            self.assertIn(assessment["riskLevel"], ("HIGH", "CRITICAL"))

            dashboard = get_dashboard(session, None)
            distribution = dashboard["riskDistribution"]
            self.assertEqual(
                distribution[assessment["riskLevel"].lower()],
                1,
            )
            self.assertEqual(
                dashboard["highRiskProjects"],
                1,
            )
            self.assertEqual(
                dashboard["scheduleRiskCount"],
                int(assessment["delayProbability"] >= 60),
            )
            self.assertEqual(
                dashboard["costRiskCount"],
                int(assessment["costOverrunProbability"] >= 50),
            )
            self.assertEqual(
                dashboard["highRiskTable"][0]["riskScore"],
                assessment["riskScore"],
            )

            map_data = get_risk_map_data(session, None)
            self.assertEqual(len(map_data), 1)
            self.assertEqual(map_data[0]["riskScore"], assessment["riskScore"])
            self.assertEqual(map_data[0]["riskLevel"], assessment["riskLevel"])
            self.assertEqual(
                map_data[0]["costOverrunProbability"],
                assessment["costOverrunProbability"],
            )
            self.assertEqual(map_data[0]["delayProbability"], assessment["delayProbability"])

            analytics = get_project_analytics(session)
            self.assertEqual(
                analytics["sectorAnalytics"][0]["avgRisk"],
                assessment["riskScore"],
            )
            self.assertEqual(
                analytics["ministryRankings"][0]["highRiskCount"],
                1,
            )
            self.assertEqual(analytics["riskByState"][0]["high"], 0)
            self.assertEqual(analytics["riskByState"][0]["critical"], 1)
            self.assertEqual(
                analytics["riskTrends"][0][assessment["riskLevel"].lower()],
                1,
            )

            reply = generate_assistant_response("highest risk", session)
            self.assertIn(
                f"Risk Score: {assessment['riskScore']}/100",
                reply,
            )
            self.assertIn(
                f"Delay Probability: {assessment['delayProbability']}%",
                reply,
            )
            self.assertIn(f"Status: {assessment['riskLevel']}", reply)
            self.assertNotIn("Risk Score: 0/100", reply)

            overview = generate_assistant_response("portfolio overview", session)
            self.assertIn(
                f"Average Risk Score:** {assessment['riskScore']}",
                overview,
            )
        finally:
            _close_session(session, engine)

    def test_ml_prediction_persists_only_separate_ml_fields(self):
        project = _make_project(project_id="ML-001", name="ML boundary project")
        session, engine = _session_with()
        try:
            session.add(project)
            session.commit()
            session.refresh(project)
            before = (
                project.risk_score,
                project.risk_level,
                project.delay_probability,
                project.cost_overrun_probability,
                project.implementation_risk,
            )
            forecast = MLForecast(
                cost_overrun_probability=0.8,
                time_overrun_probability=0.75,
                severe_overrun_probability=0.6,
                expected_cost_overrun_pct=24.0,
                expected_time_overrun_months=8.0,
                cost_prediction_p10=1100.0,
                cost_prediction_p50=1250.0,
                cost_prediction_p90=1400.0,
                time_prediction_p10=2.0,
                time_prediction_p50=6.0,
                time_prediction_p90=11.0,
                risk_score=88.0,
                risk_band="RED",
                model_version="test-ml",
                prediction_method="parikshan_ml",
            )
            prediction = PredictionResult(
                schedule_delay_probability=0.8,
                cost_overrun_probability=0.7,
                risk_escalation_probability=0.6,
                clearance_delay_probability=0.5,
                contractor_failure_probability=0.4,
                expected_delay_months={"min": 1, "max": 8},
                prediction_confidence=0.8,
                current_score=before[0],
                future_score=95,
                prediction_method="parikshan_ml",
                model_version="test-ml",
                ml_forecast=forecast,
            )
            record = persist_prediction(session, project.id, prediction)
            session.commit()
            session.refresh(project)
            self.assertEqual(
                (
                    project.risk_score,
                    project.risk_level,
                    project.delay_probability,
                    project.cost_overrun_probability,
                    project.implementation_risk,
                ),
                before,
            )
            self.assertEqual(record.ml_risk_score, 88.0)
            self.assertEqual(record.ml_risk_band, "RED")
        finally:
            _close_session(session, engine)


if __name__ == "__main__":
    unittest.main()
