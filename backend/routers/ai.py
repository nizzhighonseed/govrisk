"""AI/early-warning endpoints.

All routes are authenticated. Numeric results come from the deterministic
statistical predictor; the LLM (when configured) only enriches explanations
and update classification. An AI failure never surfaces as an application
crash - it degrades to deterministic fallback or a friendly 503.
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from database import get_db
from auth.dependencies import get_current_user, require_roles
from auth.models import User
from ai import llm_service
from ai.ai_service import (
    analyze_project,
    analyze_update_in_background,
    get_cached_or_analyze,
    resolve_anomaly,
    resolve_emerging_risk,
    get_ml_status,
)
from ai.schemas import InsightsResponse, AIHealthResponse

router = APIRouter(prefix="/api/ai", tags=["ai"])


def _project_or_404(db: Session, project_id: str):
    from models import Project

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _degrade(exc) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="AI analysis is temporarily unavailable.",
    )


@router.get("/health", response_model=AIHealthResponse)
def ai_health(_user: User = Depends(get_current_user)):
    return AIHealthResponse(**llm_service.health())


@router.get("/ml-status")
def ml_status(_user: User = Depends(get_current_user)):
    """Diagnostic endpoint: reveal whether the trained PARIKSHAN models
    loaded and which version is live. Failures never crash the app."""
    return get_ml_status()


@router.get("/projects/{project_id}/ml-forecast")
def project_ml_forecast(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles("admin", "officer", "analyst")),
):
    """Direct access to the PARIKSHAN ML forecast for a project (live model
    run). Numeric output only - never influenced by the LLM."""
    try:
        from services.ml_prediction_service import ml_prediction_for_project
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="PARIKSHAN ML unavailable. ML dependencies are not installed in this "
            "runtime (run the backend from the ML virtual environment). "
            "Deterministic risk analysis remains available.",
        ) from exc

    project = _project_or_404(db, project_id)
    try:
        forecast = ml_prediction_for_project(project)
    except Exception as exc:  # noqa: BLE001
        raise _degrade(exc) from exc
    if forecast is None:
        raise HTTPException(
            status_code=503,
            detail="PARIKSHAN ML forecast unavailable. Model artifacts may not be loaded "
            "or prediction failed. Deterministic risk analysis remains available.",
        )
    return forecast


@router.get("/projects/{project_id}/prediction")
def project_prediction(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    from ai.ai_service import latest_prediction
    from ai.ai_service import _prediction_to_dict

    _project_or_404(db, project_id)
    latest = latest_prediction(db, project_id)
    if not latest:
        raise HTTPException(status_code=404, detail="No AI prediction available yet")
    return _prediction_to_dict(latest)


@router.get("/projects/{project_id}/anomalies")
def project_anomalies(
    project_id: str,
    include_resolved: bool = False,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Open anomalies of the latest analysis batch by default.

    `include_resolved=true` additionally returns the historical, already
    resolved records. Each item carries its `id` so the client can address
    the resolve endpoint.
    """
    from models import Anomaly

    _project_or_404(db, project_id)
    query = db.query(Anomaly).filter(Anomaly.project_id == project_id)
    if not include_resolved:
        query = query.filter(Anomaly.resolved.is_(False))
    rows = query.order_by(Anomaly.created_at.desc()).limit(50).all()
    from ai.ai_service import _anomaly_to_dict

    return [_anomaly_to_dict(r) for r in rows]


@router.get("/projects/{project_id}/emerging-risks")
def project_emerging_risks(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    from ai.ai_service import _active_emerging_risks

    _project_or_404(db, project_id)
    return _active_emerging_risks(db, project_id)


@router.get("/projects/{project_id}/explanation")
def project_explanation(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    from ai.ai_service import latest_prediction, _build_explanation, _safe_json
    from ai.schemas import PredictionResult

    project = _project_or_404(db, project_id)
    latest = latest_prediction(db, project_id)
    if not latest:
        raise HTTPException(status_code=404, detail="No AI prediction available yet")
    prediction = PredictionResult(
        schedule_delay_probability=latest.schedule_delay_probability,
        cost_overrun_probability=latest.cost_overrun_probability,
        risk_escalation_probability=latest.risk_escalation_probability,
        clearance_delay_probability=latest.clearance_delay_probability,
        contractor_failure_probability=latest.contractor_failure_probability,
        expected_delay_months={"min": latest.expected_delay_min, "max": latest.expected_delay_max},
        risk_horizon_days=latest.horizon_days,
        prediction_confidence=latest.confidence,
        future_score=latest.future_score,
        current_score=latest.current_score,
        data_points_used=latest.data_points_used or 0,
        top_drivers=_safe_json(latest.drivers, []),
    )
    return _build_explanation(db, project, prediction)


@router.get("/projects/{project_id}/insights", response_model=InsightsResponse)
def project_insights(
    project_id: str,
    refresh: bool = False,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    _project_or_404(db, project_id)
    try:
        return get_cached_or_analyze(db, project_id, force=refresh)
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as exc:  # noqa: BLE001
        raise _degrade(exc) from exc


@router.post("/projects/{project_id}/analyze")
def force_analyze(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles("admin", "officer")),
):
    _project_or_404(db, project_id)
    try:
        return analyze_project(db, project_id)
    except Exception as exc:  # noqa: BLE001
        raise _degrade(exc) from exc


@router.post(
    "/projects/{project_id}/updates/{update_id}/analyze",
    status_code=202,
)
def analyze_update(
    project_id: str,
    update_id: int,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles("admin", "officer")),
):
    from models import ProjectUpdate

    project = _project_or_404(db, project_id)
    update = (
        db.query(ProjectUpdate)
        .filter(
            ProjectUpdate.id == update_id,
            ProjectUpdate.project_id == project_id,
        )
        .first()
    )
    if not update:
        raise HTTPException(status_code=404, detail="Update not found")
    background.add_task(analyze_update_in_background, project_id, update_id)
    return {"status": "queued", "projectId": project.id, "updateId": update.id}


@router.post("/projects/{project_id}/emerging-risks/{risk_id}/resolve")
def resolve_risk(
    project_id: str,
    risk_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles("admin", "officer")),
):
    _project_or_404(db, project_id)
    if not resolve_emerging_risk(db, project_id, risk_id):
        raise HTTPException(status_code=404, detail="Active emerging risk not found")
    return {"status": "resolved"}


@router.post("/projects/{project_id}/anomalies/{anomaly_id}/resolve")
def resolve_anomaly_endpoint(
    project_id: str,
    anomaly_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles("admin", "officer")),
):
    _project_or_404(db, project_id)
    if not resolve_anomaly(db, project_id, anomaly_id):
        raise HTTPException(status_code=404, detail="Open anomaly not found")
    return {"status": "resolved"}