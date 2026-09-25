"""Statistical anomaly detection.

Answers "is something unusual happening in this project?" using
threshold-based deviation analysis over the engineered features.

Methods are statistical and transparent: score gaps, rolling sentiment
from the update log, slippage magnitudes, and update-gap outliers.
No black-box model is used.
"""

from datetime import datetime, timezone
from typing import List

from config import ai_logger
from ai.feature_engineering import build_features


def _sev(score: float) -> str:
    if score >= 0.8:
        return "HIGH"
    if score >= 0.5:
        return "MEDIUM"
    return "LOW"


def _smooth(score: float, lo: float, hi: float) -> float:
    """Map a deviation to a 0..1 score between lo and hi thresholds."""
    if score <= lo:
        return 0.0
    if score >= hi:
        return 1.0
    return round((score - lo) / (hi - lo), 3)


_CONTRIBUTORS = (
    ("contractor", ("performance", "dispute", "rework", "shortfall")),
    ("schedule", ("delay", "slippage", "behind")),
    ("cost", ("cost", "overrun", "price")),
    ("material", ("material", "supply", "procurement", "shortage")),
    ("clearance", ("land", "clearance", "approval", "permit")),
    ("workforce", ("labour", "workforce", "manpower")),
    ("stakeholder", ("objection", "protest", "resident", "stakeholder", "opposition")),
    ("financial", ("funding", "budget", "expenditure")),
)


def detect_anomalies(
    project,
    updates=None,
    alerts=None,
    previous_risk_score: float | None = None,
) -> List[dict]:
    """Detect anomalies and return a detail list of anomaly records.

    Each record matches the AnomalyResult-friendly shape (plus a
    `type` identier) so the orchestrator can persist them.

    `previous_risk_score` is the canonical Layer 1 risk score recorded by the
    previous analysis. It is required for the RISK_JUMP rule: without it
    `build_features` falls back to the current score and `risk_change` is
    always 0, so the rule can never fire. No second risk score is computed
    here - the caller passes the already-persisted previous value.
    """
    features = build_features(project, updates, alerts, previous_risk_score)
    anomalies = []
    now = datetime.now(timezone.utc).isoformat()

    # 1. Progress variance
    gap = features["progress_gap"]
    if gap >= 10:
        score = _smooth(gap, 10, 25)
        anomalies.append(
            {
                "type": "PROGRESS_VARIANCE",
                "severity": _sev(score),
                "score": score,
                "title": "Physical progress behind plan",
                "description": (
                    f"Physical progress ({features['actual_progress']:.0f}%) is "
                    f"{gap:.0f} percentage points behind the planned level "
                    f"({features['planned_progress']:.0f}%)."
                ),
                "evidence": [
                    f"Physical progress: {features['actual_progress']:.0f}%",
                    f"Planned progress: {features['planned_progress']:.0f}%",
                    "Gap exceeds the 10% monitoring threshold",
                ],
            }
        )

    # 2. Cost escalation
    overrun = features["overrun_pct"]
    if overrun >= 10:
        score = _smooth(overrun, 10, 25)
        anomalies.append(
            {
                "type": "COST_ESCALATION",
                "severity": _sev(score),
                "score": score,
                "title": "Cost escalation beyond estimate",
                "description": (
                    f"Current cost is {overrun:.1f}% above the original estimate, "
                    "indicating an active escalation trend."
                ),
                "evidence": [
                    f"Cost variance: +{overrun:.1f}%",
                    f"Reported expenditure utilisation: {features['burn_pct']:.0f}%",
                ],
            }
        )

    # 3. Progress/cost mismatch
    fin_gap = features["fin_gap"]
    if fin_gap is not None and fin_gap >= 10:
        score = _smooth(fin_gap, 10, 30)
        anomalies.append(
            {
                "type": "PROGRESS_COST_MISMATCH",
                "severity": _sev(score),
                "score": score,
                "title": "Progress and expenditure mismatch",
                "description": (
                    f"Financial utilisation is {features['financial_progress']:.0f}% "
                    f"versus {features['actual_progress']:.0f}% physical progress - "
                    "spending and physical delivery are out of step."
                ),
                "evidence": [
                    f"Financial progress: {features['financial_progress']:.0f}%",
                    f"Physical progress: {features['actual_progress']:.0f}%",
                    "Mismatch exceeds the 10-point threshold",
                ],
            }
        )

    # 4. Update gap outlier
    days_since = features["days_since_last_update"]
    if days_since is not None and days_since >= 30 and features["number_of_updates"] >= 1:
        score = _smooth(days_since, 30, 90)
        anomalies.append(
            {
                "type": "UPDATE_GAP",
                "severity": _sev(score),
                "score": score,
                "title": "Unusually long gap in updates",
                "description": (
                    f"No project update in {days_since} days. For an early-warning "
                    "system this quiet period is itself a signal."
                ),
                "evidence": [
                    f"Days since last update: {days_since}",
                    f"Total updates logged: {features['number_of_updates']}",
                ],
            }
        )

    # 5. Schedule slippage
    slippage = features["slippage_months"]
    if slippage >= 6:
        score = _smooth(slippage, 6, 18)
        anomalies.append(
            {
                "type": "SCHEDULE_SLIPPAGE",
                "severity": _sev(score),
                "score": score,
                "title": "Schedule slippage beyond plan",
                "description": (
                    f"Predicted completion is {slippage} months beyond the original "
                    "completion date."
                ),
                "evidence": [
                    f"Estimated slippage: {slippage} months",
                    f"Consecutive delayed updates: {features['consecutive_delays']}",
                ],
            }
        )

    # 6. Risk jump
    if features["risk_change"] >= 15:
        score = _smooth(features["risk_change"], 15, 35)
        anomalies.append(
            {
                "type": "RISK_JUMP",
                "severity": _sev(score),
                "score": score,
                "title": "Rapid risk-score increase",
                "description": (
                    f"Risk score rose {features['risk_change']:.0f} points since the "
                    "last AI analysis."
                ),
                "evidence": [
                    f"Previous score: {features['previous_risk_score']:.0f}",
                    f"Current score: {features['current_risk_score']:.0f}",
                ],
            }
        )

    # 7. Repeated negative updates (repeated contractor/delay mentions)
    if features["consecutive_negative_updates"] >= 3:
        score = _smooth(features["consecutive_negative_updates"], 3, 6)
        anomalies.append(
            {
                "type": "REPEATED_NEGATIVE_TREND",
                "severity": _sev(score),
                "score": score,
                "title": "Repeated negative updates",
                "description": (
                    f"The last {features['consecutive_negative_updates']} updates "
                    "continue to report adverse conditions (delays, disputes, "
                    "shortages, or cost pressures)."
                ),
                "evidence": [
                    f"Consecutive negative updates: {features['consecutive_negative_updates']}",
                    f"Negative update ratio: {features['negative_update_ratio'] * 100:.0f}%",
                ],
            }
        )

    # 8. Alert surge
    if features["number_of_active_alerts"] >= 5:
        score = _smooth(features["number_of_active_alerts"], 5, 10)
        anomalies.append(
            {
                "type": "ALERT_SURGE",
                "severity": _sev(score),
                "score": score,
                "title": "Surge in active alerts",
                "description": (
                    f"{features['number_of_active_alerts']} active alerts are "
                    "currently open for this project."
                ),
                "evidence": [
                    f"Active alerts: {features['number_of_active_alerts']}",
                ],
            }
        )

    for a in anomalies:
        a["generated_at"] = now

    ai_logger.info(
        "anomaly project=%s detected=%d",
        getattr(project, "id", "?"), len(anomalies),
    )
    return anomalies


def top_anomaly(anomalies: List[dict]) -> dict:
    """Highest-severity anomaly in a list, or an empty 'none' record."""
    if not anomalies:
        return {
            "anomaly_detected": False,
            "severity": "LOW",
            "score": 0.0,
            "type": "NONE",
            "title": "",
            "description": "",
            "evidence": [],
        }
    best = max(anomalies, key=lambda a: (a["score"], a["severity"]))
    return {
        "anomaly_detected": True,
        "severity": best["severity"],
        "score": best["score"],
        "type": best["type"],
        "title": best["title"],
        "description": best["description"],
        "evidence": best["evidence"],
    }