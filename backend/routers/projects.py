import json
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from auth.database import get_auth_db
from models import Project, ProjectUpdate as ProjectUpdateRecord
from schemas import (
    AlertResponse,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate as ProjectUpdateSchema,
    ProjectUpdateCreate,
    ProjectUpdateResponse,
    RiskAssessmentResponse,
)
from auth.dependencies import get_current_user, require_roles
from auth.models import User
from auth.audit import log_audit, ACTIONS
from services.project_service import (
    next_project_id,
    planned_progress_from_dates,
    create_alert_for_new_project,
)
from services.risk_service import apply_assessment, assess_project
from ai.ai_service import analyze_update_in_background

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _project_to_response(p: Project) -> dict:
    assessment = assess_project(p)
    try:
        risk_inputs = json.loads(p.risk_inputs) if p.risk_inputs else {}
    except (TypeError, ValueError):
        risk_inputs = {}
    return {
        "id": p.id,
        "name": p.name,
        "ministry": p.ministry,
        "sector": p.sector,
        "state": p.state,
        "agency": p.agency,
        "district": p.district,
        "description": p.description,
        "nodalOfficer": p.nodal_officer,
        "contactInfo": p.contact_info,
        "originalCost": p.original_cost,
        "currentCost": p.current_cost,
        "expenditure": p.expenditure,
        "physicalProgress": p.physical_progress,
        "financialProgress": p.financial_progress,
        "plannedProgress": p.planned_progress,
        "startDate": p.start_date,
        "expectedCompletion": p.expected_completion,
        "predictedCompletion": p.predicted_completion,
        "costOverrunProbability": assessment["costOverrunProbability"],
        "delayProbability": assessment["delayProbability"],
        "implementationRisk": assessment["implementationRisk"],
        "riskScore": assessment["riskScore"],
        "riskLevel": assessment["riskLevel"],
        "milestonesTotal": p.milestones_total,
        "milestonesDelayed": p.milestones_delayed,
        "lat": p.lat,
        "lng": p.lng,
        "riskFactors": assessment["explanations"],
        "recommendations": assessment["recommendations"],
        "riskConfidence": assessment["confidence"],
        "criticalBlocker": assessment["criticalBlocker"],
        "riskInputs": risk_inputs,
        "riskReport": assessment,
        "createdAt": p.created_at,
        "updatedAt": p.updated_at,
        "status": p.status,
        "scale": p.scale,
        "fundingSource": p.funding_source,
        "externalRef": p.external_ref,
        "dataSource": (
            {
                "name": p.source_name,
                "url": p.source_url,
                "retrievedDate": p.retrieved_date,
                "confidence": p.data_confidence,
            }
            if p.source_name
            else None
        ),
        "lastSyncedAt": p.last_synced_at,
    }


def _valid_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _update_to_response(db_auth: Session, u: ProjectUpdateRecord) -> dict:
    author = db_auth.query(User).filter(User.user_id == u.user_id).first()
    return {
        "id": u.id,
        "projectId": u.project_id,
        "userId": u.user_id,
        "userName": author.full_name if author else "Unknown",
        "userRole": author.role if author else "Unknown",
        "updateType": u.update_type,
        "content": u.content,
        "createdAt": u.created_at,
        "updatedAt": u.updated_at,
    }


@router.get("", response_model=list[ProjectResponse])
def list_projects(
    sector: str | None = None,
    status: str | None = None,
    state: str | None = None,
    min_cost: float | None = None,
    max_cost: float | None = None,
    funding_source: str | None = None,
    source: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """List projects with optional government-reporting filters."""
    query = db.query(Project)
    if sector:
        query = query.filter(func.lower(Project.sector) == sector.strip().lower())
    if status:
        query = query.filter(func.lower(Project.status) == status.strip().lower())
    if state:
        query = query.filter(func.lower(Project.state) == state.strip().lower())
    if min_cost is not None:
        query = query.filter(Project.original_cost >= min_cost)
    if max_cost is not None:
        query = query.filter(Project.original_cost <= max_cost)
    if funding_source:
        query = query.filter(Project.funding_source == funding_source.strip().upper())
    if source:
        query = query.filter(func.lower(Project.source_name).contains(source.strip().lower()))
    if q:
        query = query.filter(
            Project.name.ilike(f"%{q.strip()}%")
            | Project.agency.ilike(f"%{q.strip()}%")
            | Project.sector.ilike(f"%{q.strip()}%")
        )
    projects = query.order_by(Project.state.asc(), Project.original_cost.desc()).all()
    return [_project_to_response(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return _project_to_response(project)


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    data: ProjectCreate,
    actor: User = Depends(require_roles("admin", "officer")),
    db: Session = Depends(get_db),
    db_auth: Session = Depends(get_auth_db),
):
    for field in (data.startDate, data.completionDate):
        if not _valid_date(field):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Dates must use the YYYY-MM-DD format",
            )
    if data.predictedCompletionDate and not _valid_date(data.predictedCompletionDate):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Expected completion date must use the YYYY-MM-DD format",
        )

    duplicate = (
        db.query(Project)
        .filter(
            func.lower(Project.name) == data.name.strip().lower(),
            func.lower(Project.agency) == data.agency.strip().lower(),
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A project with this name already exists for this agency",
        )

    name = data.name.strip()
    agency = data.agency.strip()
    original_cost = data.originalCost
    current_cost = data.revisedCost if data.revisedCost is not None else original_cost
    expenditure = data.expenditure or 0.0
    physical_progress = data.physicalProgress
    planned = planned_progress_from_dates(data.startDate, data.completionDate)
    planned_progress = planned if planned is not None else physical_progress

    project_id = next_project_id(db)
    projected_id_exists = db.query(Project).filter(Project.id == project_id).first()
    if projected_id_exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unable to allocate a unique project ID, please retry",
        )

    project = Project(
        id=project_id,
        name=name,
        ministry=data.ministry.strip(),
        sector=data.sector.strip(),
        state=data.state.strip(),
        agency=agency,
        district=data.district,
        description=data.description,
        nodal_officer=data.nodalOfficer,
        contact_info=data.contactInfo,
        original_cost=original_cost,
        current_cost=current_cost,
        expenditure=expenditure,
        physical_progress=physical_progress,
        financial_progress=data.financialProgress,
        planned_progress=planned_progress,
        start_date=data.startDate.strip(),
        expected_completion=data.completionDate.strip(),
        predicted_completion=data.predictedCompletionDate or "",
        cost_overrun_probability=0,
        delay_probability=0,
        implementation_risk=0,
        risk_score=0,
        risk_level="LOW",
        milestones_total=0,
        milestones_delayed=0,
        # No coordinate fallback: 0,0 is a real location in the Gulf of
        # Guinea, so defaulting to it would place a project on the map as if
        # its site were known. The column is nullable and stays NULL.
        lat=data.lat,
        lng=data.lng,
        risk_factors=json.dumps([]),
        recommendations=json.dumps([]),
        risk_inputs=json.dumps(data.riskInputs or {}),
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    assessment = apply_assessment(project, predicted=data.predictedCompletionDate)
    project.risk_score = float(assessment["riskScore"])
    project.risk_level = assessment["riskLevel"]
    db.add(project)
    db.flush()

    log_audit(
        db_auth,
        actor,
        ACTIONS["PROJECT_CREATED"],
        target_user_id=project.id,
        details=f'Created project "{project.name}"',
    )
    db_auth.commit()

    create_alert_for_new_project(db, project)
    db.commit()
    db.refresh(project)
    return _project_to_response(project)


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: str,
    data: ProjectUpdateSchema,
    editor: User = Depends(require_roles("admin", "officer")),
    db: Session = Depends(get_db),
    db_auth: Session = Depends(get_auth_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if data.name is not None:
        name = data.name.strip()
        duplicate = (
            db.query(Project)
            .filter(
                func.lower(Project.name) == name.lower(),
                func.lower(Project.agency)
                == (data.agency or project.agency).strip().lower(),
                Project.id != project.id,
            )
            .first()
        )
        if duplicate:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A project with this name already exists for this agency",
            )
        project.name = name

    if data.ministry is not None:
        project.ministry = data.ministry.strip()
    if data.sector is not None:
        project.sector = data.sector.strip()
    if data.state is not None:
        project.state = data.state.strip()
    if data.agency is not None:
        project.agency = data.agency.strip()
    if data.district is not None:
        project.district = data.district
    if data.description is not None:
        project.description = data.description
    if data.nodalOfficer is not None:
        project.nodal_officer = data.nodalOfficer
    if data.contactInfo is not None:
        project.contact_info = data.contactInfo

    if data.originalCost is not None:
        project.original_cost = data.originalCost
    if data.revisedCost is not None:
        project.current_cost = data.revisedCost
    if data.expenditure is not None:
        project.expenditure = data.expenditure

    if data.physicalProgress is not None:
        project.physical_progress = data.physicalProgress
    if data.financialProgress is not None:
        project.financial_progress = data.financialProgress

    if data.startDate is not None:
        if not _valid_date(data.startDate):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Start date must use the YYYY-MM-DD format",
            )
        project.start_date = data.startDate.strip()
    if data.completionDate is not None:
        if not _valid_date(data.completionDate):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Completion date must use the YYYY-MM-DD format",
            )
        project.expected_completion = data.completionDate.strip()
    if project.expected_completion < project.start_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Completion date cannot be before start date",
        )

    if data.lat is not None:
        project.lat = data.lat
    if data.lng is not None:
        project.lng = data.lng

    if data.name is not None or data.originalCost is not None or data.revisedCost is not None \
            or data.expenditure is not None or data.physicalProgress is not None \
            or data.financialProgress is not None or data.startDate is not None \
            or data.completionDate is not None \
            or data.predictedCompletionDate is not None or data.riskInputs is not None:
        planned = planned_progress_from_dates(project.start_date, project.expected_completion)
        if planned is not None:
            project.planned_progress = planned
        if data.riskInputs is not None:
            project.risk_inputs = json.dumps(data.riskInputs)
        predicted = data.predictedCompletionDate or project.predicted_completion or None
        apply_assessment(
            project,
            predicted=predicted if _valid_date(predicted) else None,
        )

    if data.predictedCompletionDate is not None:
        if not _valid_date(data.predictedCompletionDate):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Expected completion date must use the YYYY-MM-DD format",
            )
        project.predicted_completion = data.predictedCompletionDate.strip()

    project.updated_at = _now_iso()
    db.flush()
    log_audit(
        db_auth,
        editor,
        ACTIONS["PROJECT_UPDATED"],
        target_user_id=project.id,
        details=f'Updated project "{project.name}"',
    )
    db_auth.commit()
    db.commit()
    db.refresh(project)
    return _project_to_response(project)


@router.get(
    "/{project_id}/risk",
    response_model=RiskAssessmentResponse,
)
def get_project_risk(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return assess_project(project)


@router.get(
    "/{project_id}/updates",
    response_model=list[ProjectUpdateResponse],
)
def list_project_updates(
    project_id: str,
    db: Session = Depends(get_db),
    db_auth: Session = Depends(get_auth_db),
    _user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    updates = (
        db.query(ProjectUpdateRecord)
        .filter(ProjectUpdateRecord.project_id == project_id)
        .order_by(ProjectUpdateRecord.created_at.asc())
        .all()
    )
    return [_update_to_response(db_auth, u) for u in updates]


@router.post(
    "/{project_id}/updates",
    response_model=ProjectUpdateResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_project_update(
    project_id: str,
    data: ProjectUpdateCreate,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    db_auth: Session = Depends(get_auth_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    update = ProjectUpdateRecord(
        project_id=project.id,
        user_id=user.user_id,
        content=data.content.strip(),
        update_type=data.updateType,
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    db.add(update)
    db.flush()
    log_audit(
        db_auth,
        user,
        ACTIONS["PROJECT_UPDATE_ADDED"],
        target_user_id=project.id,
        details=f'Added update to "{project.name}"',
    )
    db_auth.commit()
    db.commit()
    db.refresh(update)
    background.add_task(analyze_update_in_background, update.project_id, update.id)
    return _update_to_response(db_auth, update)


@router.put(
    "/{project_id}/updates/{update_id}",
    response_model=ProjectUpdateResponse,
)
def edit_project_update(
    project_id: str,
    update_id: int,
    data: ProjectUpdateCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    db_auth: Session = Depends(get_auth_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    update = (
        db.query(ProjectUpdateRecord)
        .filter(
            ProjectUpdateRecord.id == update_id,
            ProjectUpdateRecord.project_id == project_id,
        )
        .first()
    )
    if not update:
        raise HTTPException(status_code=404, detail="Update not found")
    if user.user_id != update.user_id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the author or an admin can edit this update",
        )

    update.content = data.content.strip()
    update.update_type = data.updateType
    update.updated_at = _now_iso()
    db.commit()
    db.refresh(update)
    return _update_to_response(db_auth, update)


@router.delete(
    "/{project_id}/updates/{update_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_project_update(
    project_id: str,
    update_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    db_auth: Session = Depends(get_auth_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    update = (
        db.query(ProjectUpdateRecord)
        .filter(
            ProjectUpdateRecord.id == update_id,
            ProjectUpdateRecord.project_id == project_id,
        )
        .first()
    )
    if not update:
        raise HTTPException(status_code=404, detail="Update not found")
    if user.user_id != update.user_id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the author or an admin can delete this update",
        )

    db.delete(update)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)