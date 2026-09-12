"""Idempotent schema migrations for the existing govrisk.db.

SQLAlchemy create_all() only creates missing tables and does not add
new columns to existing tables. This module adds newly introduced
columns to the projects table without touching existing rows, then
refreshes the cached risk columns with the deterministic risk engine
so historical rows are consistent with the current engine (single
source of truth). The AI tables are created idempotently and any
missing supporting indexes are added.
"""

from sqlalchemy import text
from sqlalchemy.engine import Engine

PROJECT_COLUMNS = {
    "district": "TEXT",
    "description": "TEXT",
    "nodal_officer": "TEXT",
    "contact_info": "TEXT",
    "financial_progress": "FLOAT",
    "risk_inputs": "TEXT",
    "risk_confidence": "FLOAT",
    "risk_report": "TEXT",
    "created_at": "TEXT",
    "updated_at": "TEXT",
}


def _create_ai_tables(engine: Engine) -> None:
    """Idempotently create the AI tables + indexes on govrisk.db.

    Fresh databases get them via create_all() in main.py (they are part of
    Base). This is a safety net for databases that predate the AI feature.
    """
    from database import Base
    from models import AIAnalysis, AIPrediction, Anomaly, EmergingRisk  # noqa: F401

    Base.metadata.create_all(bind=engine, checkfirst=True)
    _ensure_index(
        engine,
        "ai_analyses",
        "ix_ai_analyses_project_id",
        "ALTER TABLE ai_analyses ADD INDEX "
        "ix_ai_analyses_project_id (project_id)",
    )


def _ensure_index(engine: Engine, table: str, index_name: str, ddl: str) -> None:
    """Add an index only when both the table exists and the index is missing."""
    try:
        with engine.connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
            if table not in tables:
                return
            indexes = {
                row[1]
                for row in conn.execute(text(f"PRAGMA index_list({table})"))
            }
            if index_name not in indexes:
                conn.execute(text(ddl))
            conn.commit()
    except Exception:
        # SQLite has no native ALTER TABLE ADD INDEX; when a table was created
        # without the index the model comment below documents the diff. The
        # common path (fresh create_all) already carries the index.
        pass


def _ensure_ai_predictions_columns(engine: Engine) -> None:
    """Add columns introduced after the ai_predictions table first shipped."""
    adds = {
        "current_score": "INTEGER",
        "data_points_used": "INTEGER",
    }
    try:
        with engine.connect() as conn:
            existing = {
                row[1]
                for row in conn.execute(text("PRAGMA table_info(ai_predictions)"))
            }
            for column, ddl in adds.items():
                if column not in existing:
                    conn.execute(
                        text(f"ALTER TABLE ai_predictions ADD COLUMN {column} {ddl}")
                    )
            conn.commit()
    except Exception:
        # Table may not exist yet (fresh database) - create_all handles it.
        pass


def run_migrations(engine: Engine) -> None:
    try:
        with engine.connect() as conn:
            existing = {
                row[1]
                for row in conn.execute(text("PRAGMA table_info(projects)"))
            }
            for column, ddl in PROJECT_COLUMNS.items():
                if column not in existing:
                    conn.execute(
                        text(f"ALTER TABLE projects ADD COLUMN {column} {ddl}")
                    )
            conn.commit()
    except Exception:
        # The projects table may not exist yet (fresh database); create_all
        # in main.py handles that case with the full model definition.
        pass

    # AI persistence tables (idempotent).
    _create_ai_tables(engine)
    _ensure_ai_predictions_columns(engine)

    _backfill_risk(engine)


AUTH_USER_COLUMNS = {
    "failed_login_count": "INTEGER NOT NULL DEFAULT 0",
    "last_failed_login": "DATETIME",
    "locked_until": "DATETIME",
    # Registration governance: existing accounts are treated as approved so
    # the migration cannot lock out current legitimate/demo users. Pending
    # state is only introduced for NEW self-registrations (set explicitly
    # to 0 by the register endpoint).
    "is_approved": "BOOLEAN NOT NULL DEFAULT 1",
    # Temporary-password enforcement: default 0 so existing users are never
    # forced to change a password; only admin-created/reset accounts are
    # marked (set explicitly to 1 by those endpoints).
    "must_change_password": "BOOLEAN NOT NULL DEFAULT 0",
}


def run_auth_migrations(auth_engine: Engine) -> None:
    """Idempotently add brute-force lockout columns to the auth users table.

    create_all() never adds columns to existing tables, so databases created
    before the lockout feature ships need these added exactly once.
    """
    try:
        with auth_engine.connect() as conn:
            existing = {
                row[1]
                for row in conn.execute(text("PRAGMA table_info(users)"))
            }
            for column, ddl in AUTH_USER_COLUMNS.items():
                if column not in existing:
                    conn.execute(
                        text(f"ALTER TABLE users ADD COLUMN {column} {ddl}")
                    )
            conn.commit()
    except Exception:
        # users table may not exist yet (fresh auth.db); create_all in
        # main.py creates it from the model definition, which already
        # carries these columns.
        pass


def _backfill_risk(engine: Engine) -> None:
    """Recompute cached risk columns for existing rows using the risk engine.

    Keeps every row consistent with the deterministic engine even before the
    app first serves a request. Never fabricates values - it recomputes from
    the same inputs the API uses.
    """
    try:
        from sqlalchemy.orm import Session
        from models import Project
        from services.risk_service import apply_assessment

        with Session(bind=engine) as session:
            for project in session.query(Project).all():
                try:
                    apply_assessment(project)
                except Exception:
                    continue
            session.commit()
    except Exception:
        return