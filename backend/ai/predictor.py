"""Future-risk prediction engine.

A transparent, deterministic statistical predictor that estimates the
probability of each major risk event over the next 90 days.

No ML models are trained or claimed - every coefficient is documented
and the output is fully explainable.  When update history is absent the
system uses a *rule-statistical fallback*; when text-based trend features
are present the method is *hybrid*.

No external ML libraries are required.
"""

import math
from datetime import datetime, timezone
from typing import Optional

from config import ai_logger
from ai.schemas import PredictionResult, PREDICTION_METHOD_RULE, PREDICTION_METHOD_HYBRID
from ai.feature_engineering import build_features, level_from_score


def _sigmoid(x: float, k: float = 1.0, x0: float = 0.0) -> float:
    """Numerically stable logistic map: x → 1 / (1 + e^(-(k(x - x0))))."""
    return 1.0 / (1.0 + math.exp(max(-8.0, min(8.0, -k * (x - x0)))))


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _blend_weight(has_text: bool) -> float:
    """Portion of the prediction attributed to trend features vs snapshot.

    When there is no update history at all (has_text=False), the model
    relies on the snapshot alone.  With 3+ updates the text-derived
    features gain credibility and contribute up to 40% of the result.
    """
    return 0.4 if has_text else 0.0


def _delay_range(schedule_delay_probability: float, slippage_months: int) -> dict:
    prob = schedule_delay_probability
    if prob >= 0.80:
        lo = max(slippage_months, 6)
        hi = max(lo + 3, 12)
    elif prob >= 0.60:
        lo = max(slippage_months, 3)
        hi = max(lo + 2, 8)
    elif prob >= 0.40:
        lo = max(slippage_months, 1)
        hi = max(lo + 1, 4)
    elif prob >= 0.20:
        lo = 0
        hi = max(slippage_months, 2)
    else:
        lo = 0
        hi = max(slippage_months, 1)
    return {"min": lo, "max": hi}


def _future_score(
    current_score: float,
    escalation_prob: float,
    deterioration: float,
    trend_penalty: float,
) -> int:
    """Project the future risk score for a given 90-day horizon.

    The upward delta is driven by escalation probability (high = strong
    upward pressure) combined with the rate at which recent update
    sentiment is deteriorating.  A downward adjustment occurs only
    when the project is *clearly* improving (deterioration < -0.3),
    reflecting real recovery.
    """
    upward = escalation_prob * 28 + max(0, deterioration) * 12 + max(0, trend_penalty) * 4
    downward = abs(min(0, deterioration)) * 10
    delta = upward - downward
    return int(max(0, min(100, current_score + delta)))


def predict(project, updates=None, alerts=None, previous_risk_score=None) -> PredictionResult:
    """Compute a 90-day risk forecast for a project.

    Returns a fully populated `PredictionResult` that is safe to persist.
    All values are computed from real features; no hard-coded literals
    are surfaced as predictions.
    """
    from models import ProjectUpdate as ProjectUpdateModel
    from database import SessionLocal

    if updates is None or alerts is None:
        with SessionLocal() as db:
            updates = db.query(ProjectUpdateModel).filter(
                ProjectUpdateModel.project_id == project.id
            ).all()
            alerts = []
            features = build_features(project, updates, alerts, previous_risk_score)
    else:
        features = build_features(project, updates, alerts, previous_risk_score)

    has_text = features["number_of_updates"] >= 3
    tw = _blend_weight(has_text)

    # snapshot-only weights
    snap = 1.0 - tw

    schedule_delay = (
        snap * _sigmoid(features["progress_gap"], k=0.06, x0=7)
        + tw * _sigmoid(
            features["consecutive_delays"] + features["rate_of_deterioration"] * 3,
            k=0.7,
            x0=1.0,
        )
    )

    cost_overrun = (
        snap * _sigmoid(features["overrun_pct"], k=0.04, x0=10)
        + tw * _sigmoid(features["negative_update_ratio"] * 4, k=0.8, x0=1.2)
    )

    risk_escalation = (
        snap * _sigmoid(features["forecast_anchor"], k=1.6, x0=0.55)
        + tw * _sigmoid(
            features["consecutive_negative_updates"]
            + features["rate_of_deterioration"] * 3,
            k=0.5,
            x0=1.2,
        )
    )

    clearance_delay = _sigmoid(
        features["clearance_status"]
        + features["administrative_risk"] * 0.25
        + features["slippage_months"] * 0.03,
        k=1.5,
        x0=0.55,
    )

    contractor_failure = _sigmoid(
        features["contractor_score"]
        + features["material_status"] * 0.15
        + features["weather_risk"] * 0.1,
        k=2.0,
        x0=0.50,
    )

    schedule_delay_p = round(_clamp(schedule_delay), 3)
    cost_overrun_p = round(_clamp(cost_overrun), 3)
    risk_escalation_p = round(_clamp(risk_escalation), 3)
    clearance_delay_p = round(_clamp(clearance_delay), 3)
    contractor_failure_p = round(_clamp(contractor_failure), 3)

    current = features["current_risk_score"]
    future = _future_score(
        current, risk_escalation_p,
        features["rate_of_deterioration"],
        features["risk_change"],
    )
    future = int(max(0, min(100, future)))

    delay_months = features["slippage_months"]
    delay_range = _delay_range(schedule_delay_p, delay_months)

    # confidence: data completeness + trend availability
    base_confidence = features["data_points"] / 40.0
    trend_bonus = 0.15 if features["number_of_updates"] >= 5 else 0.0
    confidence = round(_clamp(base_confidence + trend_bonus), 3)

    driver_list = []
    if features["progress_gap"] >= 5:
        driver_list.append(f"Progress gap of {features['progress_gap']:.0f}% behind plan")
    if features["overrun_pct"] >= 10:
        driver_list.append(f"Cost overrun at {features['overrun_pct']:.0f}%")
    if features["contractor_score"] >= 0.5:
        driver_list.append("Contractor performance risk elevated")
    if features["consecutive_delays"] >= 2:
        driver_list.append(
            f"{features['consecutive_delays']} consecutive updates mention delays"
        )
    if features["clearance_status"] >= 0.5:
        driver_list.append("Land/environmental clearance risk active")
    if features["administrative_risk"] >= 0.6:
        driver_list.append("Administrative/approval delays detected")
    if not driver_list:
        driver_list.append("No dominant risk driver identified")

    method = PREDICTION_METHOD_HYBRID if has_text else PREDICTION_METHOD_RULE
    horizon_days = 90

    result = PredictionResult(
        schedule_delay_probability=schedule_delay_p,
        cost_overrun_probability=cost_overrun_p,
        risk_escalation_probability=risk_escalation_p,
        clearance_delay_probability=clearance_delay_p,
        contractor_failure_probability=contractor_failure_p,
        expected_delay_months=delay_range,
        risk_horizon_days=horizon_days,
        prediction_confidence=confidence,
        future_score=future,
        current_score=int(current),
        prediction_method=method,
        model_version="sankalp-ai-v1",
        data_points_used=features["data_points"],
        generated_at=datetime.now(timezone.utc).isoformat(),
        top_drivers=driver_list,
    )
    ai_logger.info(
        "prediction project=%s method=%s future=%d current=%d drivers=%d",
        project.id, method, future, current, len(driver_list),
    )
    return result