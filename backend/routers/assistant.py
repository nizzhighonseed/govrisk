"""Hybrid assistant.

Base replies stay on the deterministic rule engine (so the assistant works
with zero LLM config), then an AI early-warning layer appends live
prediction/anomaly/emerging-risk context pulled from the persisted AI
snapshots.
"""

import re

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from schemas import AssistantRequest, AssistantResponse
from services.risk_service import generate_assistant_response
from ai.ai_service import latest_prediction, _active_emerging_risks, _recent_anomalies
from auth.dependencies import get_current_user
from auth.models import User
from config import ai_logger
from services.text_guard import strip_html_tags

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

_ID_PATTERN = re.compile(r"PRJ-\d{3}", re.IGNORECASE)


def _safe_text(value) -> str:
    """User/NLP-derived text embedded in replies, stripped of HTML tags.

    The frontend renders replies as text (primary trust boundary); stripping
    here is defense in depth so the backend never emits executable markup.
    """
    return strip_html_tags(value)


def _find_mentions(query: str) -> list:
    return [m.upper() for m in _ID_PATTERN.findall(query)]


def _early_warning_line(db: Session, project) -> str:
    pred = latest_prediction(db, project.id)
    anomalies = _recent_anomalies(db, project.id)
    risks = _active_emerging_risks(db, project.id)

    if not pred:
        return f"{_safe_text(project.name)} ({project.id}) has no AI snapshot yet - run an analysis first."

    line = (
        f"{_safe_text(project.name)} ({project.id}) is projected at ~{pred.future_score or pred.current_score or '?'}/100 "
        f"within {pred.horizon_days} days "
        f"(schedule-delay p: {pred.schedule_delay_probability * 100:.0f}%, "
        f"cost-overrun p: {pred.cost_overrun_probability * 100:.0f}%)."
    )
    if anomalies:
        top = max(anomalies, key=lambda a: a["score"])
        line += f" Top anomaly: {_safe_text(top['title'])} ({_safe_text(top['severity'])})."
    if risks:
        line += f" Emerging risk: {_safe_text(risks[0]['title'])} ({_safe_text(risks[0]['severity'])})."
    return line


def _ai_early_warning_note(db: Session, query: str) -> str:
    from models import Project

    pids = _find_mentions(query)
    lines = []
    if pids:
        mentioned = []
        for pid in pids:
            project = db.query(Project).filter(Project.id == pid).first()
            if project:
                mentioned.append(project)
        for project in mentioned:
            lines.append(_early_warning_line(db, project))
        if lines:
            return "\n\n[AI early-warning] " + " ".join(lines)
        return ""

    preds = []
    for project in db.query(Project).all():
        pred = latest_prediction(db, project.id)
        if pred:
            preds.append(pred)
        if len(preds) == 15:
            break
    if not preds:
        return ""
    at_risk = sum(
        1 for p in preds
        if (p.future_score or 0) >= 60 or p.schedule_delay_probability >= 0.6
    )
    note = f"\n\n[AI early-warning] live AI snapshots cover {len(preds)} project(s); "
    note += (
        f"{at_risk} currently project to HIGH/CRITICAL pressure within 90 days."
        if at_risk else
        "none currently project to HIGH/CRITICAL pressure within 90 days."
    )
    return note


@router.post("", response_model=AssistantResponse)
def query_assistant(
    request: AssistantRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    reply = generate_assistant_response(request.query, db)
    note = _ai_early_warning_note(db, request.query)
    if note:
        reply = reply + note
    else:
        ai_logger.debug("assistant: no AI note appended")
    return AssistantResponse(reply=reply)