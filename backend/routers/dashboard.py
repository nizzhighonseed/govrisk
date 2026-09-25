from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import Project
from routers.projects import _project_to_response
from services.risk_service import assess_project
from auth.dependencies import get_current_user
from auth.models import User

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def get_dashboard(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    projects = db.query(Project).all()
    assessments = {p.id: assess_project(p) for p in projects}

    total = len(projects)
    high_risk = [
        p
        for p in projects
        if assessments[p.id]["riskLevel"] in ("HIGH", "CRITICAL")
    ]
    schedule_risk = [
        p for p in projects if assessments[p.id]["delayProbability"] >= 60
    ]
    cost_risk = [
        p for p in projects if assessments[p.id]["costOverrunProbability"] >= 50
    ]

    total_original = sum(p.original_cost for p in projects)
    total_current = sum(p.current_cost for p in projects)

    risk_dist = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    for p in projects:
        level = assessments[p.id]["riskLevel"]
        risk_dist[level] = risk_dist.get(level, 0) + 1

    high_risk_table = sorted(
        [p for p in projects if assessments[p.id]["riskLevel"] in ("HIGH", "CRITICAL")],
        key=lambda p: assessments[p.id]["riskScore"],
        reverse=True,
    )[:8]

    return {
        "totalProjects": total,
        "highRiskProjects": len(high_risk),
        "scheduleRiskCount": len(schedule_risk),
        "costRiskCount": len(cost_risk),
        "portfolioValue": total_original,
        "revisedValue": total_current,
        "riskDistribution": {
            "low": risk_dist.get("LOW", 0),
            "medium": risk_dist.get("MEDIUM", 0),
            "high": risk_dist.get("HIGH", 0),
            "critical": risk_dist.get("CRITICAL", 0),
        },
        "highRiskTable": [_project_to_response(p) for p in high_risk_table],
    }
