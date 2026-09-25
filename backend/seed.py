"""
Sankalp Demo Seed Script
========================
Creates the SQLite database and populates it with demonstration data.

This is DEMONSTRATION DATA for Smart India Hackathon 2026.
It is NOT official government data.

Usage:
    python seed.py
"""

import json
import os
import sys

from database import engine, SessionLocal, Base
from models import Project, Alert, ProjectUpdate
from seed_data import SEED_PROJECTS, SEED_ALERTS, SEED_PROJECT_UPDATES
from services.risk_service import apply_assessment


def seed():
    print("Sankalp Seed Script")
    print("=" * 40)

    # Remove existing database
    db_path = os.path.join(os.path.dirname(__file__), "sankalp.db")
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"Removed existing database: {db_path}")

    # Create tables
    Base.metadata.create_all(bind=engine)
    print("Created database tables")

    db = SessionLocal()
    try:
        # Seed projects
        for project_data in SEED_PROJECTS:
            project = Project(
                id=project_data["id"],
                name=project_data["name"],
                ministry=project_data["ministry"],
                sector=project_data["sector"],
                state=project_data["state"],
                agency=project_data["agency"],
                original_cost=project_data["original_cost"],
                current_cost=project_data["current_cost"],
                expenditure=project_data["expenditure"],
                physical_progress=project_data["physical_progress"],
                planned_progress=project_data["planned_progress"],
                start_date=project_data["start_date"],
                expected_completion=project_data["expected_completion"],
                predicted_completion=project_data["predicted_completion"],
                cost_overrun_probability=project_data["cost_overrun_probability"],
                delay_probability=project_data["delay_probability"],
                implementation_risk=project_data["implementation_risk"],
                risk_score=project_data["risk_score"],
                risk_level=project_data["risk_level"],
                milestones_total=project_data["milestones_total"],
                milestones_delayed=project_data["milestones_delayed"],
                lat=project_data["lat"],
                lng=project_data["lng"],
                risk_factors=json.dumps(project_data["risk_factors"]),
                recommendations=json.dumps(project_data["recommendations"]),
                risk_inputs=json.dumps(project_data.get("risk_inputs") or {}),
            )
            apply_assessment(
                project,
                predicted=project_data.get("predicted_completion") or None,
            )
            db.add(project)
        print(f"Inserted {len(SEED_PROJECTS)} projects")

        # Seed alerts
        for alert_data in SEED_ALERTS:
            alert = Alert(
                id=alert_data["id"],
                project_id=alert_data["project_id"],
                type=alert_data["type"],
                severity=alert_data["severity"],
                description=alert_data["description"],
                detected_date=alert_data["detected_date"],
                status=alert_data["status"],
            )
            db.add(alert)
        print(f"Inserted {len(SEED_ALERTS)} alerts")

        # Seed project updates (AI early-warning signal history)
        for update_data in SEED_PROJECT_UPDATES:
            update = ProjectUpdate(
                project_id=update_data["project_id"],
                user_id=update_data["user_id"],
                content=update_data["content"],
                update_type=update_data.get("type", "GENERAL"),
                created_at=update_data["created_at"],
                updated_at=update_data["created_at"],
            )
            db.add(update)
        print(f"Inserted {len(SEED_PROJECT_UPDATES)} project updates")

        db.commit()

        # Generate the initial AI analysis snapshots (prediction, anomalies,
        # emerging risks) so the demo surfaces early warnings immediately.
        analyzed = 0
        for project_data in SEED_PROJECTS:
            try:
                from ai.ai_service import analyze_project

                analyze_project(db, project_data["id"])
                analyzed += 1
            except Exception as exc:
                print(f"  [warn] AI analysis skipped for {project_data['id']}: {exc}")
        print(f"Rendered AI analysis snapshots for {analyzed} projects")

        print("=" * 40)
        print("Seed complete!")
        print(f"  Projects: {len(SEED_PROJECTS)}")
        print(f"  Alerts:   {len(SEED_ALERTS)}")
        print(f"  Database: {db_path}")

    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    seed()
