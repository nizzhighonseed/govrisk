"""Project creation helpers: ID generation, planned-progress calculation, and alert creation."""

from datetime import datetime

from sqlalchemy.orm import Session

from models import Project, Alert


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def next_project_id(db: Session) -> str:
    """Generate the next sequential PRJ-ID based on the max existing ID.

    Using max-ID (not count) keeps IDs unique even after deletions.
    """
    highest = 0
    for (pid,) in db.query(Project.id).all():
        if pid and pid.startswith("PRJ-"):
            try:
                n = int(pid.split("-")[1])
                if n > highest:
                    highest = n
            except (ValueError, IndexError):
                continue
    return f"PRJ-{highest + 1:03d}"


def next_alert_id(db: Session) -> str:
    highest = 0
    for (aid,) in db.query(Alert.id).all():
        if aid and aid.startswith("ALR-"):
            try:
                n = int(aid.split("-")[1])
                if n > highest:
                    highest = n
            except (ValueError, IndexError):
                continue
    return f"ALR-{highest + 1:03d}"


def _parse_date(value: str):
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d")
    except (ValueError, AttributeError):
        return None


def planned_progress_from_dates(start_date: str, completion_date: str):
    """Estimate a reference planned progress from elapsed/total duration."""
    start = _parse_date(start_date)
    completion = _parse_date(completion_date)
    if not start or not completion:
        return None
    total = (completion - start).days
    if total <= 0:
        return None
    elapsed = (datetime.now() - start).days
    pct = elapsed / total * 100
    return round(min(100.0, max(0.0, pct)), 1)


def create_alert_for_new_project(db: Session, project: Project):
    """Generate an alert for HIGH/CRITICAL newly created projects."""
    if project.risk_level not in ("HIGH", "CRITICAL"):
        return None
    alert = Alert(
        id=next_alert_id(db),
        project_id=project.id,
        type="New Project Risk Assessment",
        severity=project.risk_level,
        description=(
            f"New project {project.name} classified as {project.risk_level} risk "
            f"with a risk score of {project.risk_score:.0f}/100."
        ),
        detected_date=_fmt(datetime.now()),
        status="ACTIVE",
    )
    db.add(alert)
    db.flush()
    return alert