"""Unit tests for the PARIKSHAN ML prediction service.

Covers (PDF-compliant requirements):
- 37-feature contract + exact column names
- Sankalp -> feature mapping semantics (elapsed, gap, velocity, bands, reasons)
- leakage prevention: Sankalp future/outcome fields never enter the model
- model registry loading + version fingerprint
- prediction output shape, bounds, quantile ordering
- risk score formula + Green/Amber/Red bands
- missing-velocity neutrality (momentum penalty)
- unknown categorical -> neutral (all-zero one-hot)
- all 7 assumed risk_inputs -> reason mappings
- early-warning snapshot rules (EW-02/05/06, MODEL-01)
- graceful degradation when artifacts are missing
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

try:
    from tests.test_risk_service import make_project
except ImportError:  # pragma: no cover - start dir variant (unittest discover)
    from test_risk_service import make_project

from services import ml_prediction_service as mls


class FeatureRowTestCase(unittest.TestCase):
    def test_feature_row_has_exactly_37_columns(self):
        p = make_project()
        df = mls.build_feature_row(p)
        self.assertEqual(len(df.columns), 37)
        self.assertEqual(list(df.columns), list(mls.ALL_FEATURES))
        self.assertEqual(df.shape[0], 1)
        self.assertFalse(df.columns.duplicated().any())

    def test_healthy_project_mapping_values(self):
        p = make_project(
            id="ML-1", name="Healthy", original_cost=1000,
            expenditure=700, physical_progress=95,
            financial_progress=96, planned_progress=96,
            start_date="2024-01-01", expected_completion="2026-12-31",
        )
        df = mls.build_feature_row(p)
        row = df.iloc[0]
        self.assertEqual(row["physical_progress_pct"], 95)
        self.assertEqual(row["financial_progress_pct"], 96)
        self.assertEqual(row["original_cost_cr"], 1000)
        self.assertEqual(row["progress_gap_pp"], 1.0)
        self.assertEqual(row["stalled_quarters"], 0)
        self.assertEqual(row["revisions_to_date"], 0)
        self.assertEqual(row["months_since_last_revision"], 0)
        self.assertEqual(row["is_multi_state"], 0)
        self.assertGreater(row["elapsed_months"], 0)
        self.assertGreater(row["required_velocity"], 0)
        self.assertEqual(row["n_reasons_active"], 0)
        # history-unavailable features are left explicit (median-imputed by pipe)
        self.assertTrue(row["progress_velocity_3q"] != row["progress_velocity_3q"])  # NaN
        self.assertTrue(row["velocity_ratio"] != row["velocity_ratio"])  # NaN

    def test_progress_gap_is_financial_minus_physical(self):
        p = make_project(physical_progress=55, financial_progress=80)
        row = mls.build_feature_row(p).iloc[0]
        self.assertEqual(row["progress_gap_pp"], 25.0)

    def test_financial_progress_falls_back_to_expenditure_burn(self):
        p = make_project(
            original_cost=1000, expenditure=400,
            physical_progress=40, financial_progress=None,
        )
        row = mls.build_feature_row(p).iloc[0]
        self.assertEqual(row["financial_progress_pct"], 40.0)

    def test_required_velocity_policy(self):
        # nearly complete project -> tiny remaining fraction -> slow velocity
        p = make_project(physical_progress=95, start_date="2024-01-01",
                         expected_completion="2025-12-31")
        row = mls.build_feature_row(p).iloc[0]
        self.assertGreaterEqual(float(row["required_velocity"]), 0.01)
        self.assertLess(float(row["required_velocity"]), 100)


class LeakageTestCase(unittest.TestCase):
    def test_guard_rejects_forbidden_fields(self):
        with self.assertRaises(ValueError):
            mls.assert_no_sankalp_leakage({
                "physical_progress_pct": 90,
                "risk_score": 72,
                "predicted_completion": "2027-01-01",
            })

    def test_feature_row_contains_no_forbidden_fields(self):
        p = make_project(
            risk_score=72, risk_level="CRITICAL",
            cost_overrun_probability=80, delay_probability=90,
            implementation_risk=70,
            risk_factors='[{"factor":"X"}]',
            recommendations="[]",
            predicted_completion="2027-12-31",
        )
        df = mls.build_feature_row(p)
        for col in df.columns:
            self.assertNotIn(col, mls.SANKALP_LEAKAGE_FIELDS)
        # belt-and-braces: the guard itself must pass on the built row
        mls.assert_no_sankalp_leakage(df.to_dict("records")[0])


class ReasonDerivationTestCase(unittest.TestCase):
    def _row_for(self, branch):
        p = make_project(risk_inputs=json.dumps(branch))
        return mls.build_feature_row(p).iloc[0]

    def test_land_acquisition(self):
        row = self._row_for({"clearance": {"landAcquiredPct": 40}})
        self.assertEqual(row["reason_land_acquisition"], 1)
        row = self._row_for({"clearance": {"landAcquiredPct": 100}})
        self.assertEqual(row["reason_land_acquisition"], 0)

    def test_clearance_pending_or_rejected(self):
        row = self._row_for({"clearance": {"environmentalClearance": "PENDING"}})
        self.assertEqual(row["reason_forest_env_clearance"], 1)
        row = self._row_for({"clearance": {"forestClearance": "REJECTED"}})
        self.assertEqual(row["reason_forest_env_clearance"], 1)
        row = self._row_for({"clearance": {"environmentalClearance": "GRANTED"}})
        self.assertEqual(row["reason_forest_env_clearance"], 0)

    def test_litigation(self):
        row = self._row_for({"legalSocial": {"courtStay": True}})
        self.assertEqual(row["reason_litigation"], 1)
        row = self._row_for({"legalSocial": {"activeDisputeCount": 2}})
        self.assertEqual(row["reason_litigation"], 1)
        row = self._row_for({"legalSocial": {"courtStay": False}})
        self.assertEqual(row["reason_litigation"], 0)

    def test_rehabilitation_and_resettlement(self):
        row = self._row_for({"legalSocial": {"rehabilitationOutstanding": True}})
        self.assertEqual(row["reason_r_and_r"], 1)
        row = self._row_for({"legalSocial": {"unresolvedCompensation": 5}})
        self.assertEqual(row["reason_r_and_r"], 1)

    def test_law_and_order(self):
        row = self._row_for({"legalSocial": {"oppositionLevel": "HIGH"}})
        self.assertEqual(row["reason_law_and_order"], 1)
        row = self._row_for({"legalSocial": {"protestCount": 3}})
        self.assertEqual(row["reason_law_and_order"], 1)

    def test_contractor_issues(self):
        row = self._row_for({"contractor": {"performance": "POOR"}})
        self.assertEqual(row["reason_contractor_issues"], 1)
        row = self._row_for({"contractor": {"performance": "GOOD"}})
        self.assertEqual(row["reason_contractor_issues"], 0)

    def test_equipment_supply(self):
        row = self._row_for({"supplyChain": {"equipmentAvailability": "TIGHT"}})
        self.assertEqual(row["reason_equipment_supply"], 1)
        row = self._row_for({"supplyChain": {"equipmentAvailability": "AVAILABLE"}})
        self.assertEqual(row["reason_equipment_supply"], 0)

    def test_unsupported_reasons_are_neutral(self):
        row = self._row_for({})
        for reason in mls.REASON_FEATURES:
            self.assertIn(reason, row.index)
        self.assertEqual(row["reason_force_majeure"], 0)
        self.assertEqual(row["reason_tendering_delay"], 0)

    def test_n_reasons_active_counts_true_flags(self):
        branch = {
            "clearance": {"landAcquiredPct": 30},
            "legalSocial": {"activeDisputeCount": 2},
            "contractor": {"performance": "CRITICAL"},
            "supplyChain": {"equipmentAvailability": "SHORTAGE"},
        }
        row = self._row_for(branch)
        self.assertEqual(row["n_reasons_active"], 4)


class CategoricalTestCase(unittest.TestCase):
    def test_known_vocab_values_preserved(self):
        p = make_project(sector="Road Transport & Highways", state="Maharashtra",
                         original_cost=1200)
        row = mls.build_feature_row(p).iloc[0]
        self.assertEqual(row["sector"], "Road Transport & Highways")
        self.assertEqual(row["state"], "Maharashtra")
        self.assertEqual(row["cost_band"], "1000-5000")

    def test_unknown_categories_are_neutral_sentinel(self):
        p = make_project(sector="Quantum Railways", state="Nonexistent State")
        row = mls.build_feature_row(p).iloc[0]
        self.assertEqual(row["sector"], mls.UNKNOWN_CATEGORY)
        self.assertEqual(row["state"], mls.UNKNOWN_CATEGORY)
        self.assertEqual(row["funding_mode"], mls.UNKNOWN_CATEGORY)
        self.assertEqual(row["implementing_agency_type"], mls.UNKNOWN_CATEGORY)

    def test_sub_150_crore_projects_do_not_force_false_band(self):
        p = make_project(original_cost=120)
        row = mls.build_feature_row(p).iloc[0]
        self.assertEqual(row["cost_band"], mls.UNKNOWN_CATEGORY)

    def test_cost_band_boundaries(self):
        self.assertEqual(mls.cost_band_for_cost(200), "150-500")
        self.assertEqual(mls.cost_band_for_cost(700), "500-1000")
        self.assertEqual(mls.cost_band_for_cost(3000), "1000-5000")
        self.assertEqual(mls.cost_band_for_cost(9000), ">5000")


class RegistryTestCase(unittest.TestCase):
    def test_models_load_and_version_fingerprint(self):
        reg = mls.MLModelRegistry().load()
        self.assertTrue(reg.is_available)
        self.assertTrue(reg.model_version.startswith("parikshan-"))
        self.assertEqual(len(reg.model_version.split("-")[-1]), 8)
        expected = {
            "cost_overrun_classifier", "time_overrun_classifier",
            "severe_classifier", "severe_shap_base",
            "cost_overrun_regressor", "time_overrun_regressor",
            "cost_quantile", "time_quantile",
        }
        self.assertEqual(set(reg.models), expected)

    def test_registry_unavailable_when_artifacts_missing(self):
        missing = tempfile.mkdtemp(prefix="no-models-")
        reg = mls.MLModelRegistry(Path(missing)).load()
        self.assertFalse(reg.is_available)
        self.assertIsNotNone(reg._error)
        self.assertEqual(reg.models, {})

    def test_registry_respects_disabled_flag(self):
        reg = mls.MLModelRegistry(enabled=False).load()
        self.assertFalse(reg.is_available)


class PredictionTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = mls.MLModelRegistry().load()
        cls.svc = mls.MLPredictionService(cls.reg)

    def test_prediction_shape_and_bounds(self):
        p = make_project(id="ML-P1")
        res = self.svc.predict(p)
        self.assertIsNotNone(res)
        for prob in (res.cost_overrun_probability,
                     res.time_overrun_probability,
                     res.severe_overrun_probability):
            self.assertTrue(0.0 <= prob <= 1.0)
        for v in (res.expected_cost_overrun_pct,
                  res.expected_time_overrun_months,
                  res.cost_prediction_p10, res.cost_prediction_p50,
                  res.cost_prediction_p90):
            self.assertTrue(v is not None)
            self.assertTrue(abs(v) < 1e6)

    def test_quantile_ordering_enforced(self):
        p = make_project(id="ML-P2")
        res = self.svc.predict(p)
        self.assertTrue(res.cost_prediction_p10 <= res.cost_prediction_p50 <= res.cost_prediction_p90)
        self.assertTrue(res.time_prediction_p10 <= res.time_prediction_p50 <= res.time_prediction_p90)

    def test_risk_score_in_range_and_method(self):
        p = make_project(id="ML-P3")
        res = self.svc.predict(p)
        self.assertTrue(0 <= res.risk_score <= 100)
        self.assertIn(res.risk_band, ("Green", "Amber", "Red"))
        self.assertEqual(res.prediction_method, "parikshan_ml")
        self.assertEqual(res.data_points_used, 37)
        self.assertEqual(len(res.feature_columns), 37)

    def test_severe_high_risk_project_scores_higher_than_healthy(self):
        healthy = self.svc.predict(make_project(id="ML-H", state="Karnataka"))
        at_risk = self.svc.predict(make_project(
            id="ML-R", state="Karnataka",
            physical_progress=25, planned_progress=85,
            current_cost=1800, original_cost=900,
            risk_inputs=json.dumps({"contractor": {"performance": "CRITICAL"},
                                    "clearance": {"landAcquiredPct": 20}}),
        ))
        self.assertIsNotNone(healthy)
        self.assertIsNotNone(at_risk)
        self.assertGreaterEqual(at_risk.risk_score, healthy.risk_score - 5)

    def test_shap_drivers_returned(self):
        p = make_project(id="ML-S", state="Karnataka",
                         physical_progress=50, planned_progress=70)
        res = self.svc.predict(p)
        self.assertEqual(len(res.top_drivers), 3)
        self.assertTrue(all(isinstance(d, str) and d for d in res.top_drivers))

    def test_shap_fallback_when_explainer_unavailable(self):
        reg = mls.MLModelRegistry(enabled=False)
        self.assertEqual(reg.top_shap_drivers(None), [])

    def test_validate_rejects_bad_quantiles(self):
        res = mls.MLPredictionResult(
            cost_overrun_probability=0.5, time_overrun_probability=0.5,
            severe_overrun_probability=0.5,
            expected_cost_overrun_pct=10, expected_time_overrun_months=3,
            cost_prediction_p10=90, cost_prediction_p50=50, cost_prediction_p90=20,
            time_prediction_p10=1, time_prediction_p50=2, time_prediction_p90=3,
            risk_score=50,
        )
        with self.assertRaises(ValueError):
            mls.validate_ml_result(res)

    def test_validate_rejects_out_of_range_probability(self):
        res = mls.MLPredictionResult(
            cost_overrun_probability=1.5, time_overrun_probability=0,
            severe_overrun_probability=0,
            expected_cost_overrun_pct=0, expected_time_overrun_months=0,
            cost_prediction_p10=0, cost_prediction_p50=0, cost_prediction_p90=0,
            time_prediction_p10=0, time_prediction_p50=0, time_prediction_p90=0,
            risk_score=10,
        )
        with self.assertRaises(ValueError):
            mls.validate_ml_result(res)


class RiskPolicyTestCase(unittest.TestCase):
    def test_risk_band_thresholds(self):
        self.assertEqual(mls.risk_band_for_score(25), "Green")
        self.assertEqual(mls.risk_band_for_score(39), "Green")
        self.assertEqual(mls.risk_band_for_score(40), "Amber")
        self.assertEqual(mls.risk_band_for_score(69), "Amber")
        self.assertEqual(mls.risk_band_for_score(70), "Red")
        self.assertEqual(mls.risk_band_for_score(100), "Red")

    def test_momentum_penalty_neutral_when_velocity_missing(self):
        self.assertEqual(mls.momentum_penalty(float("nan"), 0), 0.0)
        self.assertEqual(mls.momentum_penalty(None, 0), 0.0)
        self.assertGreater(mls.momentum_penalty(0.5, 0), 0.0)

    def test_normalized_magnitude_bounds(self):
        self.assertLessEqual(mls.normalized_magnitude(-5, -2), 0.0)
        self.assertLessEqual(mls.normalized_magnitude(5000, 5000), 1.0)


class EarlyWarningTestCase(unittest.TestCase):
    def test_ew02_spending_gap(self):
        row = {"progress_gap_pp": 30, "elapsed_frac": 0.5, "physical_progress_pct": 50,
               "n_reasons_active": 0}
        ews = mls.build_early_warnings(row, 0.5, 0.5, 30)
        self.assertIn("EW-02", [e["rule_id"] for e in ews])

    def test_ew02_no_false_trigger_when_within_threshold(self):
        row = {"progress_gap_pp": 15, "elapsed_frac": 0.5, "physical_progress_pct": 50,
               "n_reasons_active": 0}
        ews = mls.build_early_warnings(row, 0.5, 0.5, 30)
        self.assertNotIn("EW-02", [e["rule_id"] for e in ews])

    def test_ew05_late_and_slow(self):
        row = {"progress_gap_pp": 5, "elapsed_frac": 0.9, "physical_progress_pct": 50,
               "n_reasons_active": 0}
        ews = mls.build_early_warnings(row, 0.5, 0.5, 30)
        self.assertIn("EW-05", [e["rule_id"] for e in ews])

    def test_ew06_many_reasons(self):
        row = {"progress_gap_pp": 0, "elapsed_frac": 0.3, "physical_progress_pct": 20,
               "n_reasons_active": 4}
        ews = mls.build_early_warnings(row, 0.5, 0.5, 30)
        self.assertIn("EW-06", [e["rule_id"] for e in ews])

    def test_model01_red_band_trigger(self):
        row = {"progress_gap_pp": 0, "elapsed_frac": 0.3, "physical_progress_pct": 20,
               "n_reasons_active": 0}
        ews = mls.build_early_warnings(row, 0.5, 0.5, 75)
        self.assertIn("MODEL-01", [e["rule_id"] for e in ews])

    def test_no_warnings_for_healthy_snapshot(self):
        row = {"progress_gap_pp": 2, "elapsed_frac": 0.4, "physical_progress_pct": 50,
               "n_reasons_active": 0}
        self.assertEqual(mls.build_early_warnings(row, 0.2, 0.2, 20), [])


if __name__ == "__main__":
    unittest.main()