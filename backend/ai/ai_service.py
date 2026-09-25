"""AI orchestration: runs the prediction/anomaly/emerging-risk pipeline,
persists results, caches them, and generates insights + alerts.

All heavy work happens inside short-lived sessions; functions never extend
a request-bound transaction longer than needed. Failures anywhere in the
AI layer are caught and degraded gracefully - the deterministic engine
keeps serving regardless.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from config import (
    AI_ALERT_DEDUP_HOURS,
    AI_ANALYSIS_TTL_HOURS,
    ai_logger,
)
from database import SessionLocal
from models import (
    AIPrediction,
    AIAnalysis,
    Anomaly,
    EmergingRisk,
    Project,
    ProjectUpdate,
    Alert,
)
from ai.schemas import (
    InsightsResponse,
    PredictionResult,
    ExplanationResponse,
    MLForecast,
    PREDICTION_METHOD_RULE,
    PREDICTION_METHOD_PARIKSHAN_ML,
)
from ai.predictor import predict
from ai.anomaly_detector import detect_anomalies, top_anomaly
from ai import emerging_risk
from ai import llm_service

# Anomaly closure provenance: an officer acknowledged the anomaly (USER), or
# the condition stopped being detected (AUTO).
RESOLUTION_USER = "USER"
RESOLUTION_AUTO = "AUTO"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fresh(created_at: str) -> bool:
    """True when an AI record is inside the configured freshness window."""
    if not created_at:
        return False
    try:
        ts = datetime.fromisoformat(created_at)
    except (TypeError, ValueError):
        return False
    return (datetime.now(timezone.utc) - ts) < timedelta(hours=AI_ANALYSIS_TTL_HOURS)


def _prepare_update_list(db: Session, project_id: str):
    return (
        db.query(ProjectUpdate)
        .filter(ProjectUpdate.project_id == project_id)
        .order_by(ProjectUpdate.created_at.asc())
        .all()
    )


def _prepare_alert_list(db: Session, project_id: str):
    return (
        db.query(Alert)
        .filter(Alert.project_id == project_id, Alert.status == "ACTIVE")
        .all()
    )


def _load_project(db: Session, project_id: str) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise ValueError("Project not found")
    return project


def latest_prediction(db: Session, project_id: str):
    return (
        db.query(AIPrediction)
        .filter(AIPrediction.project_id == project_id)
        .order_by(AIPrediction.created_at.desc())
        .first()
    )


def _prediction_to_dict(record) -> dict:
    return {
        "schedule_delay_probability": record.schedule_delay_probability,
        "cost_overrun_probability": record.cost_overrun_probability,
        "risk_escalation_probability": record.risk_escalation_probability,
        "clearance_delay_probability": record.clearance_delay_probability,
        "contractor_failure_probability": record.contractor_failure_probability,
        "expected_delay_months": {
            "min": record.expected_delay_min,
            "max": record.expected_delay_max,
        },
        "risk_horizon_days": record.horizon_days,
        "prediction_confidence": record.confidence,
        "future_score": record.future_score,
        "current_score": record.current_score,
        "prediction_method": record.prediction_method,
        "model_version": record.model_version,
        "top_drivers": _safe_json(record.drivers, []),
        "data_points_used": record.data_points_used,
        "generated_at": record.created_at,
        "ml_forecast": _ml_forecast_to_dict(record),
    }


def _ml_forecast_to_dict(record) -> Optional[dict]:
    """Serve the persisted PARIKSHAN ML forecast when the record carries it."""
    if getattr(record, "ml_risk_score", None) is None and getattr(
        record, "ml_model_version", None
    ) is None:
        return None
    if record.ml_model_version is None:
        return None
    return {
        "cost_overrun_probability": record.ml_cost_overrun_probability,
        "time_overrun_probability": record.ml_time_overrun_probability,
        "severe_overrun_probability": record.ml_severe_overrun_probability,
        "expected_cost_overrun_pct": record.ml_expected_cost_overrun_pct,
        "expected_time_overrun_months": record.ml_expected_time_overrun_months,
        "cost_prediction_p10": record.ml_cost_p10,
        "cost_prediction_p50": record.ml_cost_p50,
        "cost_prediction_p90": record.ml_cost_p90,
        "time_prediction_p10": record.ml_time_p10,
        "time_prediction_p50": record.ml_time_p50,
        "time_prediction_p90": record.ml_time_p90,
        "risk_score": record.ml_risk_score,
        "risk_band": record.ml_risk_band,
        "model_version": record.ml_model_version,
        "prediction_method": PREDICTION_METHOD_PARIKSHAN_ML,
        "data_points_used": 37,
        "top_drivers": _safe_json(record.ml_top_drivers, []),
        "early_warnings": _safe_json(record.ml_early_warnings, []),
        "recommended_actions": _safe_json(record.ml_recommended_actions, []),
    }


def _safe_json(raw, fallback):
    if not raw:
        return fallback
    try:
        value = json.loads(raw)
        return value if value is not None else fallback
    except (TypeError, ValueError):
        return fallback


def _anomaly_to_dict(record) -> dict:
    return {
        "id": record.id,
        "type": record.type,
        "severity": record.severity,
        "score": record.score,
        "title": record.title,
        "description": record.description,
        "evidence": _safe_json(record.evidence, []),
        "resolved": bool(record.resolved),
        "resolution_source": record.resolution_source,
        "batch_id": record.batch_id,
        "last_seen_at": record.last_seen_at or record.created_at,
        "resolved_at": record.resolved_at,
        "generated_at": record.created_at,
    }


def _risk_to_dict(record) -> dict:
    return {
        "id": record.id,
        "category": record.category,
        "title": record.title,
        "confidence": record.confidence,
        "severity": record.severity,
        "description": record.description,
        "evidence": _safe_json(record.evidence, []),
        "recommended_actions": _safe_json(record.recommendations, []),
        "source_update_ids": _safe_json(record.source_update_ids, []),
        "status": record.status,
        "resolved_at": getattr(record, "resolved_at", None),
        "generated_at": record.created_at,
    }


def _recent_anomalies(db: Session, project_id: str) -> list:
    """Anomalies of the newest analysis batch that are still open.

    The batch is identified by `batch_id` (one id per analysis run) rather
    than by `created_at` string equality, so a single analysis that detected
    several anomaly types returns all of them. Rows a user already resolved
    are excluded, and the result is ordered oldest-first for stable display.
    """
    newest = (
        db.query(Anomaly.batch_id, Anomaly.last_seen_at)
        .filter(
            Anomaly.project_id == project_id,
            Anomaly.resolved.is_(False),
            Anomaly.batch_id.isnot(None),
        )
        .order_by(Anomaly.last_seen_at.desc(), Anomaly.created_at.desc())
        .first()
    )
    if newest is None or not newest.batch_id:
        return []
    rows = (
        db.query(Anomaly)
        .filter(
            Anomaly.project_id == project_id,
            Anomaly.batch_id == newest.batch_id,
            Anomaly.resolved.is_(False),
        )
        .order_by(Anomaly.created_at.asc(), Anomaly.id.asc())
        .all()
    )
    return [_anomaly_to_dict(r) for r in rows]


def _active_emerging_risks(db: Session, project_id: str) -> list:
    rows = (
        db.query(EmergingRisk)
        .filter(EmergingRisk.project_id == project_id, EmergingRisk.status == "ACTIVE")
        .order_by(EmergingRisk.created_at.desc())
        .all()
    )
    return [_risk_to_dict(r) for r in rows]


def _clear_stale_predictions(db: Session, project_id: str) -> None:
    """Keep only the newest prediction per project (rolling history cap)."""
    rows = (
        db.query(AIPrediction)
        .filter(AIPrediction.project_id == project_id)
        .order_by(AIPrediction.created_at.desc())
        .all()
    )
    for stale in rows[3:]:
        db.delete(stale)


def _build_explanation(db: Session, project, prediction: PredictionResult) -> dict:
    """Deterministic explanation, optionally enriched by the LLM."""
    from services.risk_service import assess_project

    assessment = assess_project(project)
    drivers = prediction.top_drivers or ["No dominant risk driver identified"]

    deterministic = (
        f"Risk score {assessment['riskScore']}/100 ({assessment['riskLevel']}). "
        f"Top risks: {', '.join(assessment['topRisks'][:3])}. "
        f"Recommendations: {'; '.join(assessment['recommendations'][:3])}."
    )

    site = getattr(project, "state", "") or "the project"
    future = prediction.future_score if prediction.future_score is not None else assessment["riskScore"]
    summary = (
        f"{project.name} in {site} is assessed at {assessment['riskScore']}/100 "
        f"({assessment['riskLevel']}) today. Based on the latest trend signals it is "
        f"projected to reach ~{future}/100 within the next {prediction.risk_horizon_days} days. "
        f"{' '.join(drivers[:2])}."
    )
    if prediction.ml_forecast is not None:
        ml = prediction.ml_forecast
        summary += (
            f" PARIKSHAN ML forecast: ML risk score {ml.risk_score:.0f}/100 "
            f"({ml.risk_band}); estimated cost overrun {ml.expected_cost_overrun_pct:.0f}% "
            f"(probability {ml.cost_overrun_probability:.0%}); estimated delay "
            f"{ml.expected_time_overrun_months:.1f} months (probability {ml.time_overrun_probability:.0%})."
        )

    predicted_events = []
    if prediction.schedule_delay_probability >= 0.5:
        predicted_events.append("Further schedule slippage and delayed milestones")
    if prediction.cost_overrun_probability >= 0.5:
        predicted_events.append("Continued cost escalation beyond sanctioned estimate")
    if prediction.risk_escalation_probability >= 0.5:
        predicted_events.append("Upward repricing of the project risk level")
    if not predicted_events:
        predicted_events.append("Stable trend with no imminent major event")

    li = {}
    if llm_service.is_llm_available():
        updates = db.query(ProjectUpdate).filter(
            ProjectUpdate.project_id == project.id,
        ).order_by(ProjectUpdate.created_at.desc()).limit(5).all()
        history = "\n".join(
            f"- {u.created_at}: {u.content[:200]}" for u in updates
        ) or "No historical updates available."
        li = llm_service.explain_project(deterministic, history)
        summary = li.get("summary") or summary
        predicted_events = li.get("predicted_events") or predicted_events

    return ExplanationResponse(
        summary=summary,
        current_risk=int(assessment["riskScore"]),
        future_risk=future,
        main_drivers=drivers,
        predicted_events=predicted_events,
        recommended_interventions=assessment["recommendations"],
        ai_evidence=li.get("ai_evidence", []),
    ).model_dump()


def persist_prediction(db: Session, project_id: str, result: PredictionResult) -> AIPrediction:
    record = AIPrediction(
        id=str(uuid.uuid4()),
        project_id=project_id,
        created_at=_now_iso(),
        horizon_days=result.risk_horizon_days,
        schedule_delay_probability=result.schedule_delay_probability,
        cost_overrun_probability=result.cost_overrun_probability,
        risk_escalation_probability=result.risk_escalation_probability,
        clearance_delay_probability=result.clearance_delay_probability,
        contractor_failure_probability=result.contractor_failure_probability,
        expected_delay_min=result.expected_delay_months.get("min"),
        expected_delay_max=result.expected_delay_months.get("max"),
        future_score=result.future_score,
        confidence=result.prediction_confidence,
        prediction_method=result.prediction_method,
        model_version=result.model_version,
        drivers=json.dumps(result.top_drivers),
        data_points_used=result.data_points_used,
        current_score=result.current_score,
    )
    ml = result.ml_forecast
    if ml is not None:
        record.ml_risk_score = ml.risk_score
        record.ml_risk_band = ml.risk_band
        record.ml_cost_overrun_probability = ml.cost_overrun_probability
        record.ml_time_overrun_probability = ml.time_overrun_probability
        record.ml_severe_overrun_probability = ml.severe_overrun_probability
        record.ml_expected_cost_overrun_pct = ml.expected_cost_overrun_pct
        record.ml_expected_time_overrun_months = ml.expected_time_overrun_months
        record.ml_cost_p10 = ml.cost_prediction_p10
        record.ml_cost_p50 = ml.cost_prediction_p50
        record.ml_cost_p90 = ml.cost_prediction_p90
        record.ml_time_p10 = ml.time_prediction_p10
        record.ml_time_p50 = ml.time_prediction_p50
        record.ml_time_p90 = ml.time_prediction_p90
        record.ml_model_version = ml.model_version
        record.ml_top_drivers = json.dumps(ml.top_drivers)
        record.ml_early_warnings = json.dumps(ml.early_warnings)
        record.ml_recommended_actions = json.dumps(ml.recommended_actions)
    db.add(record)
    return record


def persist_anomalies(db: Session, project_id: str, anomalies: list, batch_id: str) -> None:
    """Apply one analysis batch to the anomaly lifecycle.

    Deterministic rules, one open row per (project, anomaly type):
    - a newly detected type creates one row tagged with this `batch_id`;
    - a type that is still detected refreshes its existing open row (score,
      severity, evidence, `batch_id`, `last_seen_at`) instead of inserting a
      duplicate;
    - any other open row is *resolved*, never deleted, so the detection
      history and its original `created_at` survive;
    - a type whose latest row was resolved BY A USER stays resolved and is only
      re-stamped with `last_seen_at`: acknowledging an anomaly must not be
      undone by a re-analysis that detects the same unchanged condition.
      A type closed automatically (the condition had gone away) does re-open
      as a new row when it genuinely re-appears.

    Pre-existing duplicate open rows (databases that accumulated one row per
    run) are collapsed: the earliest row per type stays open, the rest are
    resolved.
    """
    now = _now_iso()
    open_rows = (
        db.query(Anomaly)
        .filter(Anomaly.project_id == project_id, Anomaly.resolved.is_(False))
        .order_by(Anomaly.created_at.asc(), Anomaly.id.asc())
        .all()
    )
    by_type: dict[str, list] = {}
    for row in open_rows:
        by_type.setdefault(row.type, []).append(row)
    # Collapse legacy duplicates: keep the earliest, resolve the rest.
    for atype, rows in by_type.items():
        for extra in rows[1:]:
            extra.resolved = True
            extra.resolved_at = now
            extra.resolution_source = RESOLUTION_AUTO

    # Latest row per type, used to honour an outstanding user dismissal.
    latest_by_type: dict[str, Anomaly] = {}
    for row in open_rows:
        latest_by_type.setdefault(row.type, row)
    for atype in {a["type"] for a in anomalies}:
        if atype in latest_by_type:
            continue
        previous = (
            db.query(Anomaly)
            .filter(Anomaly.project_id == project_id, Anomaly.type == atype)
            .order_by(Anomaly.created_at.desc(), Anomaly.id.desc())
            .first()
        )
        if previous is not None:
            latest_by_type[atype] = previous

    seen: set[str] = set()
    for a in anomalies:
        atype = a["type"]
        seen.add(atype)
        existing = by_type.get(atype, [])
        row = existing[0] if existing else None
        if row is None:
            dismissed = latest_by_type.get(atype)
            if (
                dismissed is not None
                and dismissed.resolved
                and dismissed.resolution_source == RESOLUTION_USER
            ):
                # Still detected, but an officer already closed it: keep it
                # closed and only record that the condition persists.
                dismissed.last_seen_at = now
                continue
            db.add(
                Anomaly(
                    id=str(uuid.uuid4()),
                    project_id=project_id,
                    created_at=now,
                    type=atype,
                    severity=a["severity"],
                    score=a["score"],
                    title=a["title"],
                    description=a["description"],
                    evidence=json.dumps(a.get("evidence", [])),
                    resolved=False,
                    batch_id=batch_id,
                    last_seen_at=now,
                    resolved_at=None,
                    resolution_source=None,
                )
            )
            continue
        row.severity = a["severity"]
        row.score = a["score"]
        row.title = a["title"]
        row.description = a["description"]
        row.evidence = json.dumps(a.get("evidence", []))
        row.batch_id = batch_id
        row.last_seen_at = now
        row.resolved = False
        row.resolved_at = None
        row.resolution_source = None

    for atype, rows in by_type.items():
        if atype in seen:
            continue
        for row in rows:
            row.resolved = True
            row.resolved_at = now
            row.resolution_source = RESOLUTION_AUTO


def persist_emerging_risks(db: Session, project_id: str, risks: list) -> None:
    """Dedup by category for ACTIVE records; skip already-open categories."""
    existing = {
        r.category
        for r in db.query(EmergingRisk).filter(
            EmergingRisk.project_id == project_id,
            EmergingRisk.status == "ACTIVE",
        ).all()
    }
    for r in risks:
        if r.get("category") in existing:
            continue
        db.add(
            EmergingRisk(
                id=str(uuid.uuid4()),
                project_id=project_id,
                created_at=_now_iso(),
                category=r.get("category", "OTHER"),
                title=r.get("title", ""),
                confidence=r.get("confidence", 0.5),
                severity=r.get("severity", "MEDIUM"),
                description=r.get("description", ""),
                evidence=json.dumps(r.get("evidence", [])),
                recommendations=json.dumps(r.get("recommended_actions", [])),
                source_update_ids=json.dumps(r.get("source_update_ids", [])),
                status="ACTIVE",
            )
        )
        existing.add(r.get("category"))


def persist_insight_log(db: Session, project_id: str, insights: dict, summary: str) -> None:
    db.add(
        AIAnalysis(
            id=str(uuid.uuid4()),
            project_id=project_id,
            created_at=_now_iso(),
            analysis_type="insights",
            model=insights["prediction"].get("model_version", "") if insights.get("prediction") else "",
            prediction_method=insights["prediction"].get("prediction_method", "") if insights.get("prediction") else "",
            confidence=insights["prediction"].get("prediction_confidence") if insights.get("prediction") else None,
            summary=summary,
            raw_result=json.dumps(insights),
        )
    )


def build_insights(
    db: Session,
    project: Project,
    prediction_result: PredictionResult,
    anomaly_records: list,
    emerging_records: list,
    explanation: dict,
    analysis_kind: str,
) -> InsightsResponse:
    insights = InsightsResponse(
        project_id=project.id,
        prediction=prediction_result.model_dump(),
        anomalies=anomaly_records,
        emerging_risks=emerging_records,
        explanation=explanation,
        generated_at=_now_iso(),
        ai_available=llm_service.is_llm_available(),
        analysis_kind=analysis_kind,
    )
    persist_insight_log(db, project.id, insights.model_dump(), explanation.get("summary", ""))
    return insights


def project_for_analyze(db: Session, project_id: str):
    """Compute/refresh deterministic cached risk columns before AI use."""
    from services.risk_service import apply_assessment

    project = _load_project(db, project_id)
    apply_assessment(project)
    db.flush()
    return project


# --------------------------------------------------------------------------
# PARIKSHAN ML snapshot + early-warning alert persistence
# --------------------------------------------------------------------------
def _persist_ml_snapshot(db: Session, project_id: str, ml: dict) -> None:
    """Persist a single ML prediction snapshot (used for edge-triggered
    early-warning detection across successive analyses).

    The artifact fingerprint is stored alongside the numbers so a later run
    can only compare snapshots produced by the same model version.
    """
    from models import MLSnapshot

    db.add(
        MLSnapshot(
            id=str(uuid.uuid4()),
            project_id=project_id,
            created_at=_now_iso(),
            ml_risk_score=ml["risk_score"],
            ml_risk_band=ml["risk_band"],
            ml_severe_overrun_probability=ml["severe_overrun_probability"],
            ml_expected_cost_overrun_pct=ml["expected_cost_overrun_pct"],
            ml_expected_time_overrun_months=ml["expected_time_overrun_months"],
            feature_snapshot=json.dumps({k: ml[k] for k in (
                "cost_overrun_probability", "time_overrun_probability",
                "severe_overrun_probability", "expected_cost_overrun_pct",
                "expected_time_overrun_months",
            )}),
            model_version=ml.get("model_version"),
        )
    )


def _previous_ml_snapshot(db: Session, project_id: str, model_version: str | None = None):
    """Most recent snapshot of the *current* model version, or None.

    Snapshots written before provenance was recorded (and snapshots from a
    different artifact fingerprint) are intentionally ignored: a delta across
    model versions is not a real escalation, and a stale snapshot must never
    be presented as current ML output.
    """
    from models import MLSnapshot

    if not model_version:
        return None
    return (
        db.query(MLSnapshot)
        .filter(
            MLSnapshot.project_id == project_id,
            MLSnapshot.model_version == model_version,
        )
        .order_by(MLSnapshot.created_at.desc())
        .first()
    )


def _emit_ml_early_warning_alerts(
    db: Session,
    project_id: str,
    ml: dict,
    previous_snapshot,
) -> None:
    """Deterministically emit ML early-warning alerts using edge-triggering
    (only fire when the condition is newly true) and the standard dedup
    window. The LLM never participates in alert creation."""
    from models import Alert

    dedup_hours = AI_ALERT_DEDUP_HOURS
    now_utc = datetime.now(timezone.utc)

    def _already_active_by_type(alert_type: str) -> bool:
        recent_cutoff = (now_utc - timedelta(hours=dedup_hours)).isoformat()
        return db.query(Alert).filter(
            Alert.project_id == project_id,
            Alert.type == alert_type,
            Alert.status == "ACTIVE",
            Alert.detected_date >= recent_cutoff,
        ).first() is not None

    # Edge-triggered: risk-band transitions to Red from a non-Red previous band
    prev_band = previous_snapshot.ml_risk_band if previous_snapshot else "Green"
    if ml["risk_band"] == "Red" and prev_band != "Red":
        if not _already_active_by_type("AI Model Warning - Risk Score"):
            db.add(Alert(
                id=str(uuid.uuid4()),
                project_id=project_id,
                type="AI Model Warning - Risk Score",
                severity="High",
                description=(
                    f"ML risk band transitioned to Red (score {ml['risk_score']:.0f}/100, "
                    f"up from {prev_band}); prior band was {prev_band}."
                ),
                detected_date=_now_iso(),
                status="ACTIVE",
            ))

    # Edge-triggered: severe-overrun probability jumped by more than 0.2 since
    # the previous snapshot.
    prev_severe = (
        previous_snapshot.ml_severe_overrun_probability
        if previous_snapshot
        else 0.0
    )
    severe_jump = ml["severe_overrun_probability"] - prev_severe
    if severe_jump > 0.2 and ml["severe_overrun_probability"] > 0.4:
        if not _already_active_by_type("AI Model Warning - Severe Escalation"):
            db.add(Alert(
                id=str(uuid.uuid4()),
                project_id=project_id,
                type="AI Model Warning - Severe Escalation",
                severity="High",
                description=(
                    f"Severe-overrun probability rose by {severe_jump:.0%} to "
                    f"{ml['severe_overrun_probability']:.0%} since last analysis."
                ),
                detected_date=_now_iso(),
                status="ACTIVE",
            ))

    # Snapshot-level EW triggers (don't need history, but are deduplicated):
    for ew in ml.get("early_warnings", []):
        alert_type = f"AI ML Warning - {ew['rule_id']}"
        if not _already_active_by_type(alert_type):
            db.add(Alert(
                id=str(uuid.uuid4()),
                project_id=project_id,
                type=alert_type,
                severity=ew.get("severity", "Medium"),
                description=ew["description"],
                detected_date=_now_iso(),
                status="ACTIVE",
            ))


def analyze_project(db: Session, project_id: str) -> InsightsResponse:
    """Run the full AI pipeline and persist everything (fresh analysis)."""
    from ai.feature_engineering import build_features

    try:
        from services.ml_prediction_service import ml_prediction_for_project
    except ImportError as exc:
        ai_logger.warning("ai ml forecast skipped (deps missing) project=%s err=%s", project_id, exc)
        ml_prediction_for_project = None

    project = project_for_analyze(db, project_id)
    updates = _prepare_update_list(db, project_id)
    alerts = _prepare_alert_list(db, project_id)
    previous = latest_prediction(db, project_id)
    previous_score = previous.current_score if previous else None

    features = build_features(project, updates, alerts, previous_score)
    prediction = predict(project, updates, alerts, previous_score)
    # PARIKSHAN ML forecast — additive, never overwrites deterministic
    # schedule/cost/risk fields.
    try:
        ml_dict = (
            ml_prediction_for_project(project) if ml_prediction_for_project is not None else None
        )
    except Exception as exc:  # noqa: BLE001
        ai_logger.warning("ai ml forecast failed project=%s err=%s", project_id, exc)
        ml_dict = None
    if ml_dict is not None:
        prediction.ml_forecast = MLForecast(**ml_dict)
        prediction.prediction_method = PREDICTION_METHOD_PARIKSHAN_ML
        prediction.model_version = ml_dict["model_version"]
        prediction.top_drivers = ml_dict["top_drivers"]
        prediction.data_points_used = ml_dict["data_points_used"]
        previous_snapshot = _previous_ml_snapshot(db, project_id, ml_dict["model_version"])
        _persist_ml_snapshot(db, project_id, ml_dict)
        _emit_ml_early_warning_alerts(db, project_id, ml_dict, previous_snapshot)

    # One analysis = one anomaly batch. Every anomaly detected below shares
    # this id, and the previous canonical Layer 1 score is threaded into the
    # detector so RISK_JUMP can actually be evaluated.
    batch_id = str(uuid.uuid4())
    anomaly_records = detect_anomalies(project, updates, alerts, previous_score)
    persist_anomalies(db, project_id, anomaly_records, batch_id)
    persist_prediction(db, project_id, prediction)

    emerging_records = emerging_risk.extract_from_updates(updates)
    persist_emerging_risks(db, project_id, emerging_records)

    explanation = _build_explanation(db, project, prediction)
    # Flush first (the session disables autoflush) so the response carries the
    # same persisted anomaly shape - including `id`/`resolved` - as the cached
    # path served by GET /insights.
    db.flush()
    insights = build_insights(
        db, project,
        prediction_result=prediction,
        anomaly_records=_recent_anomalies(db, project_id),
        emerging_records=_active_emerging_risks(db, project_id),
        explanation=explanation,
        analysis_kind="fresh",
    )
    _clear_stale_predictions(db, project_id)
    db.commit()

    ai_logger.info(
        "ai analyze project=%s score=%s future=%s method=%s anomalies=%d emergent=%d ml=%s",
        project_id, features["current_risk_score"], prediction.future_score,
        prediction.prediction_method, len(anomaly_records), len(emerging_records),
        "yes" if ml_dict is not None else "no",
    )
    return insights


def get_cached_or_analyze(db: Session, project_id: str, force: bool = False) -> InsightsResponse:
    """Serve a cached analysis when fresh, else recompute."""
    latest = latest_prediction(db, project_id)
    if latest and not force and _fresh(latest.created_at):
        project = _load_project(db, project_id)
        prediction = _prediction_to_dict(latest)
        explanation = _build_explanation(db, project, PredictionResult(**prediction))
        insights = InsightsResponse(
            project_id=project_id,
            prediction=prediction,
            anomalies=_recent_anomalies(db, project_id),
            emerging_risks=_active_emerging_risks(db, project_id),
            explanation=explanation,
            generated_at=latest.created_at,
            ai_available=llm_service.is_llm_available(),
            analysis_kind="cached",
        )
        return insights
    return analyze_project(db, project_id)


def analyze_update_in_background(project_id: str, update_id: int) -> None:
    """Background task (fresh session): analyze one update for emerging
    risks + trigger a full project re-analysis. Never raises."""
    try:
        with SessionLocal() as db:
            update = (
                db.query(ProjectUpdate)
                .filter(
                    ProjectUpdate.id == update_id,
                    ProjectUpdate.project_id == project_id,
                )
                .first()
            )
            if not update:
                ai_logger.warning("ai background update not found %s/%s", project_id, update_id)
                return

            result = emerging_risk.analyze_update(
                update.id, update.update_type, update.created_at, update.content
            )
            if not result.get("risk_detected"):
                ai_logger.info("ai background update %s: no emerging risk", update_id)
            else:
                block = [
                    r for r in db.query(EmergingRisk).filter(
                        EmergingRisk.project_id == project_id,
                        EmergingRisk.status == "ACTIVE",
                        EmergingRisk.category == result["category"],
                    ).all()
                ]
                if block:
                    ai_logger.info(
                        "ai emerging risk %s already active for %s (dedup)",
                        result["category"], project_id,
                    )
                else:
                    db.add(
                        EmergingRisk(
                            id=str(uuid.uuid4()),
                            project_id=project_id,
                            created_at=_now_iso(),
                            category=result["category"],
                            title=result["title"],
                            confidence=result["confidence"],
                            severity=result["severity"],
                            description=result["description"],
                            evidence=json.dumps(result.get("evidence", [])),
                            recommendations=json.dumps(result.get("recommended_actions", [])),
                            source_update_ids=json.dumps(result.get("source_update_ids", [])),
                            status="ACTIVE",
                        )
                    )
                    if result["severity"] in ("HIGH", "CRITICAL"):
                        alert_exists = db.query(Alert).filter(
                            Alert.project_id == project_id,
                            Alert.type == "AI Emerging Risk",
                            Alert.description.like(f"%{result['title']}%"),
                        ).first()
                        if not alert_exists:
                            db.add(
                                Alert(
                                    id=str(uuid.uuid4()),
                                    project_id=project_id,
                                    type="AI Emerging Risk",
                                    severity=result["severity"],
                                    description=(
                                        f"AI detected emerging {result['category'].replace('_', ' ')} "
                                        f"risk: {result['title']}."
                                    ),
                                    detected_date=_now_iso(),
                                    status="ACTIVE",
                                )
                            )
                    db.commit()
                    ai_logger.info(
                        "ai emerging risk persisted %s severity=%s project=%s",
                        result["category"], result["severity"], project_id,
                    )

            try:
                analyze_project(db, project_id)
            except Exception as exc:  # noqa: BLE001
                ai_logger.warning("ai re-analysis failed project=%s err=%s", project_id, type(exc).__name__)
    except Exception as exc:  # noqa: BLE001 - background tasks must never crash the request
        ai_logger.error(
            "ai background analysis crashed project=%s err=%s",
            project_id, type(exc).__name__,
        )


def resolve_emerging_risk(db: Session, project_id: str, risk_id: str) -> bool:
    record = (
        db.query(EmergingRisk)
        .filter(
            EmergingRisk.id == risk_id,
            EmergingRisk.project_id == project_id,
            EmergingRisk.status == "ACTIVE",
        )
        .first()
    )
    if not record:
        return False
    record.status = "RESOLVED"
    record.resolved_at = _now_iso()
    db.commit()
    return True


def resolve_anomaly(db: Session, project_id: str, anomaly_id: str) -> bool:
    record = (
        db.query(Anomaly)
        .filter(
            Anomaly.id == anomaly_id,
            Anomaly.project_id == project_id,
            Anomaly.resolved.is_(False),
        )
        .first()
    )
    if not record:
        return False
    record.resolved = True
    record.resolved_at = _now_iso()
    record.resolution_source = RESOLUTION_USER
    db.commit()
    return True


def get_ml_status() -> dict:
    """Return the current ML service status (for the /ml-status endpoint)."""
    try:
        from services.ml_prediction_service import get_ml_service
    except ImportError as exc:
        return {"available": False, "model_version": None, "error": f"ML dependencies not installed: {exc}"}

    svc = get_ml_service()
    if svc is None:
        return {"available": False, "model_version": None, "error": "ML service not initialised"}
    return svc.status()


__all__ = [
    "analyze_project",
    "get_cached_or_analyze",
    "analyze_update_in_background",
    "resolve_emerging_risk",
    "resolve_anomaly",
    "latest_prediction",
    "project_for_analyze",
    "get_ml_status",
]