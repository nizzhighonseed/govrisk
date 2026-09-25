"""PARIKSHAN ML prediction service.

Clean abstraction around the trained PARIKSHAN .joblib artifacts:

    Sankalp Project  →  feature adapter  →  37-feature row  →  trained
    models  →  ML prediction result

Principles:
- Models are loaded ONCE at startup (see `MLModelRegistry.load`), never per
  request, never retrained.
- The ML result is an ADDITIONAL predictive signal. It never modifies the
  deterministic Sankalp risk fields (risk_score, risk_level, ...) computed by
  `services.risk_service`.
- Leakage is prevented: Sankalp future/outcome fields (predicted_completion,
  risk_score, delay_probability, ...) are forbidden as model inputs.
- French/the models were trained on SYNTHETIC PAIMANA-style data, so results
  are forecasts, not validated real-world accuracy.
- Only information available at prediction time may enter the feature row.
"""

from __future__ import annotations

import hashlib
import json
import math
import warnings
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------
# Config: feature contract (mirrors PARIKSHAN features/build.py)
# --------------------------------------------------------------------------
BASE_NUMERIC_FEATURES: tuple[str, ...] = (
    "elapsed_months",
    "elapsed_frac",
    "physical_progress_pct",
    "expenditure_to_date_cr",
    "financial_progress_pct",
    "progress_velocity_3q",
    "progress_gap_pp",
    "required_velocity",
    "velocity_ratio",
    "stalled_quarters",
    "n_reasons_active",
    "revisions_to_date",
    "months_since_last_revision",
    "original_cost_cr",
    "original_duration_months",
)

PARIKSHAN_DELAY_REASONS: tuple[str, ...] = (
    "land_acquisition",
    "forest_env_clearance",
    "funds_constraint",
    "contractor_issues",
    "tendering_delay",
    "litigation",
    "r_and_r",
    "law_and_order",
    "geological_surprise",
    "equipment_supply",
    "statutory_clearance",
    "force_majeure",
)

REASON_FEATURES: tuple[str, ...] = tuple(f"reason_{r}" for r in PARIKSHAN_DELAY_REASONS)

CATEGORICAL_FEATURES: tuple[str, ...] = (
    "sector",
    "state",
    "funding_mode",
    "implementing_agency_type",
    "cost_band",
)

BOOLEAN_FEATURES: tuple[str, ...] = ("is_multi_state",)

AGENCY_FEATURES: tuple[str, ...] = (
    "agency_prior_completed_count",
    "agency_prior_avg_cost_overrun_pct",
    "agency_prior_avg_time_overrun_months",
    "agency_prior_severe_rate",
)

ALL_FEATURES: tuple[str, ...] = (
    BASE_NUMERIC_FEATURES + REASON_FEATURES + CATEGORICAL_FEATURES + BOOLEAN_FEATURES + AGENCY_FEATURES
)

assert len(ALL_FEATURES) == 37, f"37-feature contract violated: {len(ALL_FEATURES)}"

# The serialized models' fixed categorical vocabularies (PARIKSHAN
# config.py / models/preprocessing.py). Anything outside these is an
# all-zero one-hot under OneHotEncoder(handle_unknown="ignore").
SECTORS: tuple[str, ...] = (
    "Railways", "Road Transport & Highways", "Petroleum", "Power", "Coal",
    "Atomic Energy", "Civil Aviation", "Telecommunications", "Steel", "Mines",
    "Shipping & Ports", "Water Resources", "Health & Family Welfare",
    "Urban Development", "Fertilizers", "Chemicals & Petrochemicals",
    "Heavy Industries", "Defence", "Higher Education",
    "Information & Broadcasting", "Textiles", "Food & Public Distribution",
)
STATES: tuple[str, ...] = (
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim",
    "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
    "West Bengal", "Andaman & Nicobar Islands", "Chandigarh",
    "Dadra & Nagar Haveli and Daman & Diu", "Delhi", "Jammu & Kashmir",
    "Ladakh", "Lakshadweep", "Puducherry",
)
FUNDING_MODES: tuple[str, ...] = ("Budgetary", "IEBR", "EAP", "PPP")
AGENCY_TYPES: tuple[str, ...] = ("CPSU", "Department", "JV", "SPV")
COST_BANDS: tuple[str, ...] = ("150-500", "500-1000", "1000-5000", ">5000")

# Out-of-vocabulary sentinel used for categorical features Sankalp does not
# capture. OneHotEncoder(handle_unknown="ignore") yields an all-zero (neutral)
# one-hot for this value — it never creates a false category.
UNKNOWN_CATEGORY: str = "__UNKNOWN__"

# PARIKSHAN risk-score policy constants (risk/score.py + config.py).
RISK_WEIGHT_P_COST_OVERRUN: float = 0.35
RISK_WEIGHT_P_TIME_OVERRUN: float = 0.35
RISK_WEIGHT_MAGNITUDE: float = 0.15
RISK_WEIGHT_MOMENTUM: float = 0.15
RISK_MAGNITUDE_COST_CAP_PCT: float = 100.0
RISK_MAGNITUDE_TIME_CAP_MONTHS: float = 48.0
RISK_MOMENTUM_STALL_CAP_QUARTERS: float = 4.0
RISK_BAND_GREEN_MAX: int = 39
RISK_BAND_AMBER_MAX: int = 69

# Early-warning rule thresholds (PARIKSHAN risk/alerts.py + config.py).
EW_PROGRESS_GAP_THRESHOLD_PP: float = 20.0
EW_LATE_ELAPSED_FRAC_THRESHOLD: float = 0.8
EW_LATE_PHYSICAL_PROGRESS_THRESHOLD_PCT: float = 60.0
EW_MANY_REASONS_THRESHOLD: int = 3
EW_RISK_SCORE_RED_THRESHOLD: int = 70

# Sankalp deterministic fields that are FUTURE/OUTCOME information and must
# never feed the model (leakage guard). The live model may only receive
# information available at prediction time.
SANKALP_LEAKAGE_FIELDS: frozenset[str] = frozenset(
    {
        "predicted_completion",
        "cost_overrun_probability",
        "delay_probability",
        "implementation_risk",
        "risk_score",
        "risk_level",
        "risk_factors",
        "recommendations",
        "risk_report",
        "risk_confidence",
        "costOverrunProbability",
        "delayProbability",
        "implementationRisk",
        "riskScore",
        "riskLevel",
        "predictedCompletion",
        "future_score",
        "current_score",
    }
)

# Assumed Sankalp risk_inputs -> PARIKSHAN reason-feature mappings.
# Centralised so the assumptions are configurable in one place. Each value is
# a callable(row) -> bool. These are DERIVATIONS, flagged ASSUMED in docs.
def _as_number(value):
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _reason_land_acquisition(branch):
    pct = _as_number((branch.get("clearance") or {}).get("landAcquiredPct"))
    return pct is not None and pct < 100


def _reason_forest_env_clearance(branch):
    cl = branch.get("clearance") or {}
    env = str(cl.get("environmentalClearance") or "").upper()
    forest = str(cl.get("forestClearance") or "").upper()
    return env in ("PENDING", "REJECTED") or forest in ("PENDING", "REJECTED")


def _reason_funds_constraint(derived):
    fin = derived.get("fin")
    physical = derived.get("physical")
    return fin is not None and physical is not None and fin < physical - 10


def _reason_litigation(branch):
    ls = branch.get("legalSocial") or {}
    disputes = _as_number(ls.get("activeDisputeCount"))
    return ls.get("courtStay") is True or (disputes is not None and disputes > 0)


def _reason_r_and_r(branch):
    ls = branch.get("legalSocial") or {}
    comp = _as_number(ls.get("unresolvedCompensation"))
    return ls.get("rehabilitationOutstanding") is True or (comp is not None and comp > 0)


def _reason_law_and_order(branch):
    ls = branch.get("legalSocial") or {}
    protests = _as_number(ls.get("protestCount"))
    opp = str(ls.get("oppositionLevel") or "").upper()
    return (protests is not None and protests > 0) or opp in ("MODERATE", "HIGH")


def _reason_contractor_issues(branch):
    c = branch.get("contractor") or {}
    perf = str(c.get("performance") or "").upper()
    unresolved = _as_number(c.get("unresolvedIssueCount"))
    return perf in ("POOR", "CRITICAL") or (unresolved is not None and unresolved > 0)


def _reason_equipment_supply(branch):
    sc = branch.get("supplyChain") or {}
    eq = str(sc.get("equipmentAvailability") or "").upper()
    return eq in ("TIGHT", "SHORTAGE")


# reason -> (branch_key_needed, resolver). Resolvers returning None are
# unsupported/missing and map to False (neutral).
_REASON_RESOLVERS: dict[str, object] = {
    "reason_land_acquisition": _reason_land_acquisition,
    "reason_forest_env_clearance": _reason_forest_env_clearance,
    "reason_funds_constraint": "derived",
    "reason_contractor_issues": _reason_contractor_issues,
    "reason_tendering_delay": None,          # unsupported — no Sankalp source
    "reason_litigation": _reason_litigation,
    "reason_r_and_r": _reason_r_and_r,
    "reason_law_and_order": _reason_law_and_order,
    "reason_geological_surprise": None,      # unsupported
    "reason_equipment_supply": _reason_equipment_supply,
    "reason_statutory_clearance": None,      # unsupported
    "reason_force_majeure": None,            # unsupported
}


# --------------------------------------------------------------------------
# Model artifact config
# --------------------------------------------------------------------------
DEFAULT_ARTIFACTS_DIR: Path = (
    Path(__file__).resolve().parents[2] / "PARIKSHAN-ship" / "artifacts" / "models"
)

MODEL_FILES: tuple[str, ...] = (
    "y_cost_overrun_classifier_calibrated.joblib",
    "y_time_overrun_classifier_calibrated.joblib",
    "y_severe_classifier_calibrated.joblib",
    "y_severe_shap_base_model.joblib",
    "cost_overrun_pct_regressor.joblib",
    "time_overrun_months_regressor.joblib",
    "cost_overrun_pct_quantile.joblib",
    "time_overrun_months_quantile.joblib",
)


def _artifacts_fingerprint(artifacts_dir: Path) -> str:
    """Short stable fingerprint (first 8 hex of SHA-1 over artifact bytes)."""
    h = hashlib.sha1()
    for fname in MODEL_FILES:
        path = artifacts_dir / fname
        if not path.exists():
            continue
        with path.open("rb") as fh:
            h.update(fh.read())
    return h.hexdigest()[:8]


# --------------------------------------------------------------------------
# Leakage guard
# --------------------------------------------------------------------------
def assert_no_sankalp_leakage(feature_row: dict) -> None:
    """Raise if any forbidden Sankalp future/outcome field entered the row."""
    leaked = [k for k in feature_row if k in SANKALP_LEAKAGE_FIELDS]
    if leaked:
        raise ValueError(
            "Leakage detected: Sankalp future/outcome fields must never feed "
            f"the PARIKSHAN model: {sorted(leaked)}"
        )


# --------------------------------------------------------------------------
# Structured result
# --------------------------------------------------------------------------
class MLPredictionResult:
    """Validated structured output from the PARIKSHAN models."""

    __slots__ = (
        "cost_overrun_probability",
        "time_overrun_probability",
        "severe_overrun_probability",
        "expected_cost_overrun_pct",
        "expected_time_overrun_months",
        "cost_prediction_p10",
        "cost_prediction_p50",
        "cost_prediction_p90",
        "time_prediction_p10",
        "time_prediction_p50",
        "time_prediction_p90",
        "risk_score",
        "risk_band",
        "model_version",
        "prediction_method",
        "data_points_used",
        "top_drivers",
        "early_warnings",
        "recommended_actions",
        "feature_columns",
        "model_available",
    )

    def __init__(self, **kwargs):
        for k in self.__slots__:
            setattr(self, k, kwargs.get(k))


def risk_band_for_score(risk_score: float) -> str:
    """Green/Amber/Red band for an ML risk score (PARIKSHAN policy)."""
    if risk_score <= RISK_BAND_GREEN_MAX:
        return "Green"
    if risk_score <= RISK_BAND_AMBER_MAX:
        return "Amber"
    return "Red"


def normalized_magnitude(pred_cost_pct: float, pred_time_months: float) -> float:
    cost_component = max(0.0, min(1.0, max(0.0, pred_cost_pct) / RISK_MAGNITUDE_COST_CAP_PCT))
    time_component = max(0.0, min(1.0, max(0.0, pred_time_months) / RISK_MAGNITUDE_TIME_CAP_MONTHS))
    return (cost_component + time_component) / 2.0


def momentum_penalty(velocity_ratio, stalled_quarters: int) -> float:
    """PARIKSHAN momentum term; missing velocity is neutral (no penalty)."""
    stall_component = min(1.0, max(0.0, stalled_quarters / RISK_MOMENTUM_STALL_CAP_QUARTERS))
    vr = velocity_ratio
    if vr is None or not math.isfinite(vr):
        vr = 1.0
    velocity_component = min(1.0, max(0.0, 1.0 - vr))
    return (stall_component + velocity_component) / 2.0


def _clamp_prob(v: float) -> float:
    return float(min(1.0, max(0.0, v)))


# --------------------------------------------------------------------------
# Feature adapter (Sankalp Project -> 37-feature row)
# --------------------------------------------------------------------------
def _parse_date(value):
    if isinstance(value, (datetime, date)):
        return value
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _months_between(a: datetime, b: datetime) -> float:
    return max(0.0, (b.year - a.year) * 12 + (b.month - a.month) + (b.day - a.day) / 30.44)


def cost_band_for_cost(original_cost: float) -> str:
    """PAIMANA cost-band (₹ crore). Sub-150 crore projects feed the
    out-of-vocab sentinel, producing a neutral (all-zero) one-hot instead of
    forcing a false category."""
    if original_cost is None or math.isnan(original_cost):
        return UNKNOWN_CATEGORY
    if original_cost < 150:
        return UNKNOWN_CATEGORY
    if original_cost <= 500:
        return "150-500"
    if original_cost <= 1000:
        return "500-1000"
    if original_cost <= 5000:
        return "1000-5000"
    return ">5000"


def _safe_vocab(value, vocab: tuple[str, ...]) -> str:
    """Return the value if in the closed vocab, else the out-of-vocab sentinel
    (which OneHotEncoder(handle_unknown='ignore') maps to all-zero one-hot)."""
    if value is None:
        return UNKNOWN_CATEGORY
    text = str(value).strip()
    return text if text in vocab else UNKNOWN_CATEGORY


def build_feature_row(project) -> pd.DataFrame:
    """Build the exact 1-row x 37-column feature DataFrame for a Sankalp
    Project ORM object. Only as-of-now information is used; Sankalp
    deterministic/future output columns are excluded by construction."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    original_cost = float(getattr(project, "original_cost", 0) or 0)
    expenditure = float(getattr(project, "expenditure", 0) or 0)
    physical = float(getattr(project, "physical_progress", 0) or 0)

    financial_raw = getattr(project, "financial_progress", None)
    if financial_raw is not None and str(financial_raw) != "":
        try:
            financial = float(financial_raw)
        except (TypeError, ValueError):
            financial = None
    else:
        financial = None
    burn = (expenditure / original_cost * 100.0) if original_cost > 0 else None
    fin = financial if financial is not None else burn

    start = _parse_date(getattr(project, "start_date", None))
    expected = _parse_date(getattr(project, "expected_completion", None))
    total_duration = _months_between(start, expected) if start and expected and expected > start else 0.0
    elapsed_months = _months_between(start, now) if start else 0.0
    elapsed_frac = (elapsed_months / total_duration) if total_duration > 0 else 0.0

    planned = float(getattr(project, "planned_progress", 0) or 0)
    planned = planned if planned > 0 else max(0.0, min(100.0, elapsed_frac * 100.0))

    # PARIKSHAN's progress_gap_pp = financial - physical (spending-vs-progress
    # early-warning signal), NOT planned-vs-physical.
    gap_pp = (fin - physical) if fin is not None else 0.0

    # Velocity features. Without quarterly history Sankalp cannot reproduce
    # a trailing 3-quarter velocity; required_velocity is derived from the
    # remaining plan and velocity_ratio is left missing (the serialized
    # pipeline median-imputes it, exactly as in training).
    remaining_frac = max(100.0 - physical, 0.0)
    remaining_quarters = max((total_duration - elapsed_months) / 3.0, 1.0)
    required_velocity = remaining_frac / remaining_quarters if remaining_frac > 0 else 0.01
    velocity_ratio = float("nan")  # history unavailable -> median imputed

    # risk_inputs structured JSON (Sankalp's only qualitative evidence).
    raw_inputs = getattr(project, "risk_inputs", None)
    try:
        branch = json.loads(raw_inputs) if raw_inputs else {}
    except (TypeError, ValueError):
        branch = {}
    if not isinstance(branch, dict):
        branch = {}

    derived = {"fin": fin, "physical": physical}

    row: dict = {}
    row.update({c: 0.0 for c in BASE_NUMERIC_FEATURES})
    row.update({c: 0 for c in REASON_FEATURES} | {c: 0 for c in BOOLEAN_FEATURES})
    row.update({c: float("nan") for c in AGENCY_FEATURES})

    row["elapsed_months"] = round(elapsed_months, 3)
    row["elapsed_frac"] = round(elapsed_frac, 4)
    row["physical_progress_pct"] = round(physical, 2)
    row["expenditure_to_date_cr"] = round(expenditure, 2)
    row["financial_progress_pct"] = round(fin, 2) if fin is not None else float("nan")
    row["progress_velocity_3q"] = float("nan")         # no quarterly history
    row["progress_gap_pp"] = round(gap_pp, 2)
    row["required_velocity"] = round(required_velocity, 3)
    row["velocity_ratio"] = velocity_ratio
    row["stalled_quarters"] = 0
    row["revisions_to_date"] = 0
    row["months_since_last_revision"] = 0
    row["original_cost_cr"] = round(original_cost, 2)
    row["original_duration_months"] = round(total_duration, 2)

    for reason in REASON_FEATURES:
        resolver = _REASON_RESOLVERS.get(reason)
        if resolver is None:
            row[reason] = 0
        elif resolver == "derived":
            row[reason] = 1 if _reason_funds_constraint(derived) else 0
        else:
            row[reason] = 1 if bool(resolver(branch)) else 0

    row["n_reasons_active"] = int(sum(1 for r in REASON_FEATURES if row[r]))

    row["sector"] = _safe_vocab(getattr(project, "sector", None), SECTORS)
    row["state"] = _safe_vocab(getattr(project, "state", None), STATES)
    row["funding_mode"] = UNKNOWN_CATEGORY          # not captured by Sankalp
    row["implementing_agency_type"] = UNKNOWN_CATEGORY
    row["cost_band"] = cost_band_for_cost(original_cost)
    row["is_multi_state"] = 0

    row["agency_prior_completed_count"] = 0
    row["agency_prior_avg_cost_overrun_pct"] = float("nan")
    row["agency_prior_avg_time_overrun_months"] = float("nan")
    row["agency_prior_severe_rate"] = float("nan")

    assert_no_sankalp_leakage(row)

    df = pd.DataFrame([row])
    missing = [c for c in ALL_FEATURES if c not in df.columns]
    if missing:
        raise ValueError(f"Feature row missing columns: {missing}")
    return df[list(ALL_FEATURES)]


# --------------------------------------------------------------------------
# Model registry
# --------------------------------------------------------------------------
class MLModelRegistry:
    """Loads every PARIKSHAN artifact once and exposes them read-only.

    The registry never trains or re-fits anything. `load()` is called once at
    app startup (lifespan). If any artifact cannot load, `is_available` is
    False and callers must fall back to the deterministic pipeline — the app
    never crashes because the ML layer is missing.
    """

    def __init__(self, artifacts_dir: Path = DEFAULT_ARTIFACTS_DIR, enabled: bool = True):
        self.artifacts_dir = Path(artifacts_dir)
        self.enabled = enabled
        self.is_available = False
        self.models: dict[str, object] = {}
        self._shap_state: Optional[tuple] = None
        self._error: Optional[str] = None
        self.model_version: str = ""
        self.prediction_method = "parikshan_ml"

    # -- loading ----------------------------------------------------------
    def load(self) -> "MLModelRegistry":
        if not self.enabled:
            self._error = "ML disabled via configuration"
            return self
        if not self.artifacts_dir.exists():
            self._error = f"Artifacts dir not found: {self.artifacts_dir}"
            return self
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                import joblib  # noqa: PLC0415
                for fname in MODEL_FILES:
                    path = self.artifacts_dir / fname
                    if not path.exists():
                        raise FileNotFoundError(f"Missing artifact: {path}")
                self.models = {
                    "cost_overrun_classifier": joblib.load(self.artifacts_dir / "y_cost_overrun_classifier_calibrated.joblib"),
                    "time_overrun_classifier": joblib.load(self.artifacts_dir / "y_time_overrun_classifier_calibrated.joblib"),
                    "severe_classifier": joblib.load(self.artifacts_dir / "y_severe_classifier_calibrated.joblib"),
                    "severe_shap_base": joblib.load(self.artifacts_dir / "y_severe_shap_base_model.joblib"),
                    "cost_overrun_regressor": joblib.load(self.artifacts_dir / "cost_overrun_pct_regressor.joblib"),
                    "time_overrun_regressor": joblib.load(self.artifacts_dir / "time_overrun_months_regressor.joblib"),
                    "cost_quantile": joblib.load(self.artifacts_dir / "cost_overrun_pct_quantile.joblib"),
                    "time_quantile": joblib.load(self.artifacts_dir / "time_overrun_months_quantile.joblib"),
                }
            self.model_version = f"parikshan-{_artifacts_fingerprint(self.artifacts_dir)}"
            self.is_available = True
            self._error = None
            return self
        except Exception as exc:  # noqa: BLE001
            self.models = {}
            self.is_available = False
            self.model_version = "unavailable"
            self._error = f"{type(exc).__name__}: {exc}"
            return self

    # -- SHAP -------------------------------------------------------------
    def _ensure_shap(self):
        """Lazily build the TreeExplainer over the base (uncalibrated) severe
        model — computed once per registry lifetime, never per request."""
        if self._shap_state is None:
            try:
                import shap  # noqa: PLC0415
            except Exception as exc:  # noqa: BLE001
                self._shap_state = ("unavailable", exc)
                return self._shap_state
            pipeline = self.models.get("severe_shap_base")
            if pipeline is None:
                self._shap_state = ("unavailable", ValueError("shap base model missing"))
                return self._shap_state
            try:
                preprocess = pipeline.named_steps["preprocess"]
                tree_model = pipeline.named_steps["model"]
                explainer = shap.TreeExplainer(tree_model)
                self._shap_state = (preprocess, tree_model, explainer)
            except Exception as exc:  # noqa: BLE001
                self._shap_state = ("unavailable", exc)
        return self._shap_state

    def top_shap_drivers(self, feature_row: pd.DataFrame, k: int = 3) -> list[str]:
        """Top-k absolute-SHAP drivers for the row, on the severe model.
        Returns human-readable driver names; falls back to [] silently when
        SHAP is unavailable (the app must never depend on it)."""
        state = self._ensure_shap()
        if not self.is_available or not state or state[0] == "unavailable":
            return []
        try:
            preprocess, tree_model, explainer = state
            feature_names = list(preprocess.get_feature_names_out())
            Xt = preprocess.transform(feature_row)
            values = explainer.shap_values(Xt)
            if isinstance(values, list):
                values = values[1]
            elif getattr(values, "ndim", 1) == 3:
                values = values[:, :, 1]
            arr = np.asarray(values).ravel()
            idx = np.argsort(-np.abs(arr))[:k]
            return [feature_names[i].split("__", 1)[-1].rstrip("_0123456789") for i in idx]
        except Exception:  # noqa: BLE001 - SHAP must never break prediction
            return []


# --------------------------------------------------------------------------
# Prediction service
# --------------------------------------------------------------------------
class MLPredictionService:
    """High-level facade: feature row -> all model calls -> validated result."""

    def __init__(self, registry: MLModelRegistry):
        self.registry = registry
        self.model_available = registry.is_available

    def predict(self, project) -> MLPredictionResult | None:
        if not self.registry.is_available:
            return None
        X = build_feature_row(project)

        models = self.registry.models
        try:
            p_cost = float(models["cost_overrun_classifier"].predict_proba(X)[:, 1][0])
            p_time = float(models["time_overrun_classifier"].predict_proba(X)[:, 1][0])
            p_severe = float(models["severe_classifier"].predict_proba(X)[:, 1][0])

            pred_cost_pct = float(models["cost_overrun_regressor"].predict(X)[0])
            pred_time_months = float(models["time_overrun_regressor"].predict(X)[0])

            cost_q = np.asarray(models["cost_quantile"].predict(X)[0])
            time_q = np.asarray(models["time_quantile"].predict(X)[0])

            X_row = X.iloc[0]
            stalled = int(X_row.get("stalled_quarters", 0) or 0)
            vr = X_row.get("velocity_ratio", float("nan"))
            try:
                vr = float(vr)
            except (TypeError, ValueError):
                vr = float("nan")

            magnitude = normalized_magnitude(pred_cost_pct, pred_time_months)
            momentum = momentum_penalty(vr, stalled)
            risk_score = 100.0 * (
                RISK_WEIGHT_P_COST_OVERRUN * p_cost
                + RISK_WEIGHT_P_TIME_OVERRUN * p_time
                + RISK_WEIGHT_MAGNITUDE * magnitude
                + RISK_WEIGHT_MOMENTUM * momentum
            )
            risk_score = float(min(100.0, max(0.0, risk_score)))
            risk_band = risk_band_for_score(risk_score)

            # Early-warning triggers computed from this snapshot (edge-triggered
            # rules that need history (EW-01/03/04/07) are disabled without a
            # project-quarter history).
            warnings_list = build_early_warnings(X_row, p_cost, p_time, risk_score)
            recommendations = recommend_actions(int(X_row.get("n_reasons_active", 0) or 0), risk_band)

            result = MLPredictionResult(
                cost_overrun_probability=_clamp_prob(p_cost),
                time_overrun_probability=_clamp_prob(p_time),
                severe_overrun_probability=_clamp_prob(p_severe),
                expected_cost_overrun_pct=float(pred_cost_pct),
                expected_time_overrun_months=float(pred_time_months),
                cost_prediction_p10=float(cost_q[0]),
                cost_prediction_p50=float(cost_q[1]),
                cost_prediction_p90=float(cost_q[2]),
                time_prediction_p10=float(time_q[0]),
                time_prediction_p50=float(time_q[1]),
                time_prediction_p90=float(time_q[2]),
                risk_score=risk_score,
                risk_band=risk_band,
                model_version=self.registry.model_version,
                prediction_method=self.registry.prediction_method,
                data_points_used=37,
                top_drivers=self.registry.top_shap_drivers(X),
                early_warnings=warnings_list,
                recommended_actions=recommendations,
                feature_columns=list(ALL_FEATURES),
                model_available=True,
            )
            validate_ml_result(result)
            return result
        except Exception as exc:  # noqa: BLE001
            self.registry._error = f"{type(exc).__name__}: {exc}"
            return None

    def status(self) -> dict:
        return {
            "available": self.registry.is_available,
            "model_version": self.registry.model_version,
            "prediction_method": self.registry.prediction_method if self.registry.is_available else None,
            "error": self.registry._error,
            "enabled": self.registry.enabled,
        }


def validate_ml_result(result: MLPredictionResult) -> None:
    """Validate outputs: bounds, ordering, finiteness."""
    probs = [
        result.cost_overrun_probability,
        result.time_overrun_probability,
        result.severe_overrun_probability,
    ]
    if any(not math.isfinite(p) or not 0.0 <= p <= 1.0 for p in probs):
        raise ValueError(f"ML probabilities out of range: {probs}")
    magnitudes = [
        result.expected_cost_overrun_pct,
        result.expected_time_overrun_months,
        result.cost_prediction_p10,
        result.cost_prediction_p50,
        result.cost_prediction_p90,
        result.time_prediction_p10,
        result.time_prediction_p50,
        result.time_prediction_p90,
    ]
    if any(v is None or not math.isfinite(v) for v in magnitudes):
        raise ValueError("ML magnitudes must be finite")
    if not (result.cost_prediction_p10 <= result.cost_prediction_p50 <= result.cost_prediction_p90):
        raise ValueError("Cost quantile ordering violated (p10<=p50<=p90)")
    if not (result.time_prediction_p10 <= result.time_prediction_p50 <= result.time_prediction_p90):
        raise ValueError("Time quantile ordering violated (p10<=p50<=p90)")
    if not (0.0 <= result.risk_score <= 100.0):
        raise ValueError(f"Risk score out of range: {result.risk_score}")


# --------------------------------------------------------------------------
# Early-warning + recommended actions (adapted from PARIKSHAN risk/alerts.py)
# --------------------------------------------------------------------------
def build_early_warnings(row, p_cost: float, p_time: float, risk_score: float) -> list[dict]:
    """Snapshot-level EW rules that can fire WITHOUT quarterly history
    (EW-02, EW-05, EW-06, MODEL-01). My/edge-triggered rules needing history
    (EW-01, EW-03, EW-04, EW-07) are omitted here — see snapshot history."""
    gap = float(row.get("progress_gap_pp", 0) or 0)
    elapsed_frac = float(row.get("elapsed_frac", 0) or 0)
    physical = float(row.get("physical_progress_pct", 0) or 0)
    n_reasons = int(row.get("n_reasons_active", 0) or 0)
    triggers: list[dict] = []

    if gap > EW_PROGRESS_GAP_THRESHOLD_PP:
        triggers.append({
            "rule_id": "EW-02",
            "severity": "High",
            "description": f"Spending is {gap:.0f}pp ahead of physical progress",
        })
    if elapsed_frac > EW_LATE_ELAPSED_FRAC_THRESHOLD and physical < EW_LATE_PHYSICAL_PROGRESS_THRESHOLD_PCT:
        triggers.append({
            "rule_id": "EW-05",
            "severity": "High",
            "description": (
                f"Past {elapsed_frac:.0%} of planned duration with "
                f"{physical:.0f}% physical progress"
            ),
        })
    if n_reasons >= EW_MANY_REASONS_THRESHOLD:
        triggers.append({
            "rule_id": "EW-06",
            "severity": "Medium",
            "description": f"{n_reasons} delay reasons active simultaneously",
        })
    if risk_score >= EW_RISK_SCORE_RED_THRESHOLD:
        triggers.append({
            "rule_id": "MODEL-01",
            "severity": "High",
            "description": f"Model-predicted risk score is {risk_score:.0f} (Red band)",
        })
    return triggers


def recommend_actions(n_reasons_active: int, risk_band: str) -> list[str]:
    actions: list[str] = []
    if n_reasons_active >= 3:
        actions.append(
            "Multiple concurrent issues - prioritise a joint resolution meeting across stakeholders"
        )
    if risk_band == "Red":
        actions.append("Flag for portfolio-level review; convene a monitoring committee within 14 days")
    elif risk_band == "Amber":
        actions.append("Increase monitoring frequency; verify reported physical progress on site")
    if n_reasons_active >= 1:
        actions.append("Reconcile disbursed funds against verified physical progress before the next release")
    if not actions:
        actions.append("Monitor - no dominant risk driver identified; review at the next scheduled check")
    return actions[:4]


# Convenience singleton installed by the app lifespan (main.py)
_registry: MLModelRegistry | None = None
_service: MLPredictionService | None = None


def get_ml_registry() -> MLModelRegistry | None:
    return _registry


def get_ml_service() -> MLPredictionService | None:
    return _service


def install_ml_service(artifacts_dir: Path = DEFAULT_ARTIFACTS_DIR, enabled: bool = True) -> MLPredictionService:
    """Create+load the registry and install service singletons (app startup)."""
    global _registry, _service
    _registry = MLModelRegistry(artifacts_dir=Path(artifacts_dir), enabled=enabled).load()
    _service = MLPredictionService(_registry)
    return _service


def ml_prediction_for_project(project) -> Optional[dict]:
    """Convenience for the API layer: run prediction and return a plain dict
    (or None when ML unavailable/fails)."""
    service = get_ml_service()
    if service is None or not service.model_available:
        return None
    result = service.predict(project)
    if result is None:
        return None
    return {
        "cost_overrun_probability": result.cost_overrun_probability,
        "time_overrun_probability": result.time_overrun_probability,
        "severe_overrun_probability": result.severe_overrun_probability,
        "expected_cost_overrun_pct": result.expected_cost_overrun_pct,
        "expected_time_overrun_months": result.expected_time_overrun_months,
        "cost_prediction_p10": result.cost_prediction_p10,
        "cost_prediction_p50": result.cost_prediction_p50,
        "cost_prediction_p90": result.cost_prediction_p90,
        "time_prediction_p10": result.time_prediction_p10,
        "time_prediction_p50": result.time_prediction_p50,
        "time_prediction_p90": result.time_prediction_p90,
        "risk_score": result.risk_score,
        "risk_band": result.risk_band,
        "model_version": result.model_version,
        "prediction_method": result.prediction_method,
        "data_points_used": result.data_points_used,
        "top_drivers": result.top_drivers,
        "early_warnings": result.early_warnings,
        "recommended_actions": result.recommended_actions,
    }


__all__ = [
    "ALL_FEATURES",
    "build_feature_row",
    "assert_no_sankalp_leakage",
    "MLModelRegistry",
    "MLPredictionService",
    "MLPredictionResult",
    "install_ml_service",
    "get_ml_registry",
    "get_ml_service",
    "ml_prediction_for_project",
    "risk_band_for_score",
    "cost_band_for_cost",
]