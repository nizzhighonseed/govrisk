from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import Project
from services.risk_service import assess_project
from auth.dependencies import get_current_user
from auth.models import User

router = APIRouter(prefix="/api/risk-map", tags=["risk-map"])


@router.get("")
def get_risk_map_data(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    projects = db.query(Project).all()
    assessments = {p.id: assess_project(p) for p in projects}
    return [
        {
            "id": p.id,
            "name": p.name,
            "state": p.state,
            "riskScore": assessments[p.id]["riskScore"],
            "riskLevel": assessments[p.id]["riskLevel"],
            "costOverrunProbability": assessments[p.id]["costOverrunProbability"],
            "delayProbability": assessments[p.id]["delayProbability"],
            "lat": p.lat,
            "lng": p.lng,
            # Project-layer fields (government-ingest provenance).
            "status": p.status or "ONGOING",
            "sector": p.sector,
            "agency": p.agency,
            "scale": p.scale,
            "costEstimateCr": p.original_cost,
            "fundingSource": p.funding_source,
            "confidence": p.data_confidence,
        }
        for p in projects
        if p.lat is not None and p.lng is not None and not (p.lat == 0 and p.lng == 0)
    ]
