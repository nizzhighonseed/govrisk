import json
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Project
from routers.projects import _project_to_response, get_project_risk
from schemas import ProjectResponse, RiskAssessmentResponse
from services import risk_config as CFG
from services.risk_service import assess_project


def make_project(**overrides):
    defaults = {
        "id": "EX-001",
        "name": "Explainability project",
        "ministry": "MoRD",
        "sector": "Transport",
        "state": "Karnataka",
        "agency": "Test Agency",
        "original_cost": 1000,
        "current_cost": 1000,
        "expenditure": 0,
        "physical_progress": 95,
        "planned_progress": 96,
        "financial_progress": 96,
        "start_date": "2024-01-01",
        "expected_completion": "2026-12-31",
        "predicted_completion": "",
        "milestones_total": 10,
        "milestones_delayed": 0,
        "lat": 0,
        "lng": 0,
        "risk_factors": "[]",
        "recommendations": "[]",
        "risk_inputs": json.dumps({}),
        "cost_overrun_probability": 0.0,
        "delay_probability": 0.0,
        "implementation_risk": 0.0,
        "risk_score": 0.0,
        "risk_level": "LOW",
        "risk_confidence": 0.0,
        "risk_report": json.dumps({"riskScore": 0}),
        "status": "ONGOING",
    }
    defaults.update(overrides)
    project = Project()
    for key, value in defaults.items():
        setattr(project, key, value)
    return project


def data_rich_project(**overrides):
    values = {
        "original_cost": 1000,
        "current_cost": 1400,
        "expenditure": 1300,
        "physical_progress": 20,
        "planned_progress": 90,
        "financial_progress": 95,
        "predicted_completion": "2028-06-30",
        "milestones_total": 10,
        "milestones_delayed": 6,
        "risk_inputs": json.dumps({
            "weather": {
                "condition": "SEVERE",
                "disruption": "CRITICAL",
                "workingDaysLost": 20,
            },
            "ground": {
                "condition": "DIFFICULT",
                "rockExcavation": "EXTENSIVE",
                "groundwater": "HIGH",
                "landslidePotential": "HIGH",
            },
            "calamity": {
                "floodExposure": "HIGH",
                "earthquakeExposure": "HIGH",
            },
            "material": {
                "availability": "SHORTAGE",
                "priceIncreasePct": 10,
                "qualityIssues": 2,
                "criticalMaterial": True,
            },
            "workforce": {
                "availability": "SEVERE_SHORTAGE",
                "skilledAvailability": "SHORTAGE",
                "productivity": "VERY_LOW",
                "absenteeism": "HIGH",
                "turnoverPct": 10,
                "safetyIncidentCount": 2,
            },
            "contractor": {
                "performance": "CRITICAL",
                "delayedMilestoneCount": 6,
                "qualityIssueCount": 2,
                "complianceIssueCount": 1,
                "financialStress": "HIGH",
                "unresolvedIssueCount": 3,
            },
            "engineering": {
                "reworkLevel": "HIGH",
                "designChangeCount": 4,
                "designErrorCount": 3,
                "technicalComplexity": "HIGH",
                "approvalPending": True,
            },
            "clearance": {
                "landAcquiredPct": 20,
                "environmentalClearance": "PENDING",
                "forestClearance": "PENDING",
                "rehabilitationPending": True,
            },
            "administrative": {
                "turnaround": "BLOCKED",
                "pendingApprovalCount": 3,
                "interDepartmentDependency": "HIGH",
                "procurementDelay": True,
            },
            "supplyChain": {
                "accessibility": "POOR",
                "supplierDependency": "HIGH",
                "equipmentAvailability": "SHORTAGE",
                "importDependency": True,
                "deliveryDelayCount": 3,
            },
            "legalSocial": {
                "oppositionLevel": "HIGH",
                "activeDisputeCount": 4,
                "protestCount": 2,
                "unresolvedCompensation": 100,
                "courtStay": True,
                "rehabilitationOutstanding": True,
            },
        }),
    }
    values.update(overrides)
    return make_project(**values)


class RiskExplainabilityTestCase(unittest.TestCase):
    def test_all_15_factors_expose_standard_contract(self):
        assessment = assess_project(data_rich_project())
        self.assertEqual(len(assessment["factors"]), 15)
        self.assertEqual(
            {factor["key"] for factor in assessment["factors"]},
            set(CFG.FACTOR_WEIGHTS),
        )
        for factor in assessment["factors"]:
            self.assertEqual(factor["factor"], factor["key"])
            self.assertIsInstance(factor["score"], int)
            self.assertIsInstance(factor["probability"], float)
            self.assertIsInstance(factor["impact"], float)
            self.assertTrue(factor["dataAvailable"])
            self.assertEqual(factor["explanation"], factor["reason"])
            self.assertTrue(factor["explanation"])
            self.assertIsInstance(factor["triggeredConditions"], list)
            self.assertTrue(factor["triggeredConditions"])
            self.assertEqual(
                factor["score"],
                round(factor["probability"] * factor["impact"] * 100),
            )

    def test_missing_data_is_explicit_and_does_not_claim_complete_evidence(self):
        assessment = assess_project(make_project())
        quality = assessment["dataQuality"]
        self.assertEqual(assessment["assessmentStatus"], "INSUFFICIENT_DATA")
        self.assertTrue(assessment["riskLevelProvisional"])
        self.assertEqual(quality["totalFactors"], 15)
        self.assertEqual(
            quality["completeness"],
            round(quality["availableFactors"] / quality["totalFactors"] * 100),
        )
        self.assertEqual(quality["weightedCompleteness"], assessment["confidence"])
        self.assertEqual(quality["missingFactors"], len(quality["missingFactorKeys"]))
        self.assertEqual(quality["missingFactorNames"], assessment["missingData"])
        self.assertIn("dataAvailable", assessment["factors"][0])
        self.assertTrue(
            any(
                "insufficient data" in factor["explanation"].lower()
                for factor in assessment["factors"]
                if not factor["dataAvailable"]
            )
        )

    def test_top_risk_factors_are_engine_ranked_and_not_client_ranked(self):
        assessment = assess_project(
            data_rich_project(
                physical_progress=30,
                planned_progress=90,
                risk_inputs=json.dumps({
                    "contractor": {"performance": "POOR", "delayedMilestoneCount": 6},
                }),
            )
        )
        top = assessment["topRiskFactors"]
        self.assertEqual(len(top), 3)
        contributions = [factor["contribution"] for factor in top]
        self.assertEqual(contributions, sorted(contributions, reverse=True))
        for factor in top:
            self.assertIn(factor["key"], {item["key"] for item in assessment["factors"]})
            self.assertEqual(factor["score"], next(
                item["score"] for item in assessment["factors"]
                if item["key"] == factor["key"]
            ))

    def test_interactions_expose_configured_conditions_and_applied_penalty(self):
        assessment = assess_project(data_rich_project())
        interaction = next(
            item for item in assessment["interactions"]
            if item["key"] == "schedule_contractor_completion"
        )
        self.assertEqual(interaction["trigger"], interaction["key"])
        self.assertIn("schedule", interaction["affectedFactors"])
        self.assertIn("schedule >= 60", interaction["triggeredConditions"])
        self.assertEqual(interaction["penalty"], 10)
        self.assertEqual(interaction["explanation"], interaction["reason"])
        self.assertLessEqual(assessment["interactionPenalty"], CFG.MAX_INTERACTION_PENALTY)
        self.assertEqual(
            assessment["interactionPenalty"],
            min(
                sum(item["penalty"] for item in assessment["interactions"]),
                CFG.MAX_INTERACTION_PENALTY,
            ),
        )

    def test_blockers_expose_configured_level_and_minimum_score(self):
        assessment = assess_project(data_rich_project())
        blocker = next(item for item in assessment["blockers"] if item["key"] == "court_stay")
        self.assertEqual(blocker["blocker"], "court_stay")
        self.assertEqual(blocker["severity"], "CRITICAL")
        self.assertEqual(blocker["minimumScore"], CFG.BLOCKER_CRITICAL_FLOOR)
        self.assertEqual(blocker["explanation"], blocker["reason"])
        self.assertGreaterEqual(assessment["riskScore"], CFG.BLOCKER_CRITICAL_FLOOR)
        self.assertEqual(assessment["blockerFloor"], CFG.BLOCKER_CRITICAL_FLOOR)

    def test_score_breakdown_matches_the_existing_score(self):
        assessment = assess_project(data_rich_project())
        breakdown = assessment["scoreBreakdown"]
        self.assertEqual(breakdown["finalScore"], assessment["riskScore"])
        self.assertEqual(
            breakdown["weightedBase"],
            round(
                sum(
                    factor["score"] * factor["weight"]
                    for factor in assessment["factors"]
                ) / 100.0,
                4,
            ),
        )
        self.assertEqual(breakdown["interactionPenalty"], assessment["interactionPenalty"])
        self.assertEqual(breakdown["blockerFloor"], assessment["blockerFloor"])
        self.assertGreaterEqual(assessment["riskScore"], breakdown["rawScore"])

    def test_response_model_preserves_explanation_fields(self):
        assessment = assess_project(data_rich_project())
        response = RiskAssessmentResponse.model_validate(assessment)
        self.assertEqual(response.assessmentStatus, assessment["assessmentStatus"])
        self.assertEqual(response.dataQuality.completeness, assessment["dataQuality"]["completeness"])
        self.assertEqual(len(response.topRiskFactors), 3)
        self.assertTrue(response.factors[0].explanation)
        self.assertTrue(response.interactions)
        self.assertTrue(response.blockers)
        self.assertEqual(response.engineVersion, CFG.ENGINE_VERSION)
        self.assertEqual(response.contractVersion, CFG.RISK_CONTRACT_VERSION)

    def test_explanation_fields_are_deterministic(self):
        now = datetime(2025, 1, 1)
        first = assess_project(data_rich_project(), now=now)
        second = assess_project(data_rich_project(), now=now)
        self.assertEqual(first, second)

    def test_risk_endpoint_response_model_keeps_every_explanation_field(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from database import Base

        engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        session = sessionmaker(bind=engine)()
        try:
            session.add(data_rich_project())
            session.commit()

            payload = get_project_risk("EX-001", session, None)
            response = RiskAssessmentResponse.model_validate_json(
                RiskAssessmentResponse.model_validate(payload).model_dump_json()
            )
            self.assertEqual(response.assessmentStatus, "COMPLETE")
            self.assertFalse(response.riskLevelProvisional)
            self.assertEqual(response.engineVersion, CFG.ENGINE_VERSION)
            self.assertEqual(response.contractVersion, CFG.RISK_CONTRACT_VERSION)
            self.assertTrue(response.assessedAt)
            self.assertEqual(response.dataQuality.totalFactors, 15)
            self.assertEqual(response.dataQuality.missingFactors, 0)
            self.assertEqual(response.scoreBreakdown.finalScore, response.riskScore)
            self.assertEqual(
                [item.key for item in response.topRiskFactors],
                [item["key"] for item in payload["topRiskFactors"]],
            )
            self.assertTrue(all(item.triggeredConditions for item in response.factors))
            self.assertTrue(all(item.explanation for item in response.factors))
            self.assertTrue(all(item.triggeredConditions for item in response.interactions))
            self.assertTrue(all(item.minimumScore for item in response.blockers))

            project_response = ProjectResponse.model_validate(_project_to_response(
                session.query(Project).filter(Project.id == "EX-001").one()
            ))
            report = RiskAssessmentResponse.model_validate(project_response.riskReport)
            self.assertEqual(report.assessmentStatus, "COMPLETE")
            self.assertEqual(report.scoreBreakdown.finalScore, project_response.riskScore)
            self.assertEqual(report.topRiskFactors[0].name, response.topRiskFactors[0].name)
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
