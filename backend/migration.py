"""Idempotent schema migrations for the existing sankalp.db.

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
    # Ingestion provenance (backend/ingest). Existing rows default to ONGOING.
    "status": "TEXT NOT NULL DEFAULT 'ONGOING'",
    "scale": "TEXT",
    "funding_source": "TEXT",
    "external_ref": "TEXT",
    "source_name": "TEXT",
    "source_url": "TEXT",
    "retrieved_date": "TEXT",
    "data_confidence": "TEXT",
    "last_synced_at": "TEXT",
    # The source's own sector label, kept beside the canonical `sector`.
    "source_sector": "TEXT",
}

# Columns that were NOT NULL but must be able to hold "the source did not
# publish this". Relaxing NOT NULL cannot be done with ALTER TABLE in SQLite,
# so these require a table rebuild.
PROJECTS_RELAXABLE_COLUMNS = (
    "expenditure",
    "physical_progress",
    "planned_progress",
    "lat",
    "lng",
)


def _relax_projects_measurement_nullability(engine: Engine) -> None:
    """Allow NOT NULL -> NULL on the measurement and coordinate columns.

    SQLite cannot drop a NOT NULL constraint with ALTER TABLE, so the table is
    rebuilt from its own declared schema: column names, types, defaults and
    primary key are read back with PRAGMA, the NOT NULL flag is omitted for the
    target columns, every row is copied, and the row count is verified before
    the swap is committed.

    The rebuild is transactional. A row-count mismatch, or any failure at all,
    rolls the whole rebuild back and re-raises: a half-applied rebuild would
    leave the schema disagreeing with the model, which is far worse than a
    loud startup failure.

    No foreign key in this schema references `projects` (every reference is a
    bare project_id string), and no triggers or views exist, so dropping and
    recreating the table is safe. Explicit indexes are captured and recreated.
    """
    from sqlalchemy import text as _text

    try:
        with engine.connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    _text("SELECT name FROM sqlite_master WHERE type='table'")
                )
            }
            if "projects" not in tables:
                return

            columns = conn.execute(_text("PRAGMA table_info(projects)")).fetchall()
            # PRAGMA rows: (cid, name, type, notnull, default, pk)
            if not any(row[1] in PROJECTS_RELAXABLE_COLUMNS and row[3] for row in columns):
                return  # already nullable; nothing to do (idempotent)

            before = conn.execute(
                _text("SELECT COUNT(*) FROM projects")
            ).scalar() or 0

            index_sql = [
                row[0]
                for row in conn.execute(
                    _text(
                        "SELECT sql FROM sqlite_master WHERE type='index' "
                        "AND tbl_name='projects' AND sql IS NOT NULL"
                    )
                )
            ]

            definitions = []
            for _cid, name, col_type, not_null, default, is_pk in columns:
                # A PRIMARY KEY column must still be declared (SQLite rejects a
                # table-level constraint that references an undeclared name,
                # reading it as an expression), and it is always NOT NULL.
                part = f'"{name}" {col_type or "TEXT"}'
                relax = name in PROJECTS_RELAXABLE_COLUMNS
                if is_pk or (not_null and not relax):
                    part += " NOT NULL"
                if default is not None:
                    part += f" DEFAULT {default}"
                if is_pk:
                    part += " PRIMARY KEY"
                definitions.append(part)

            column_list = ", ".join(f'"{row[1]}"' for row in columns)
            conn.execute(_text("DROP TABLE IF EXISTS projects_relaxed"))
            conn.execute(
                _text("CREATE TABLE projects_relaxed (" + ", ".join(definitions) + ")")
            )
            conn.execute(
                _text(
                    f"INSERT INTO projects_relaxed ({column_list}) "
                    f"SELECT {column_list} FROM projects"
                )
            )
            after = conn.execute(
                _text("SELECT COUNT(*) FROM projects_relaxed")
            ).scalar() or 0
            if after != before:
                conn.rollback()
                raise RuntimeError(
                    "projects NOT NULL relaxation aborted: row count changed "
                    f"({before} -> {after}); no schema change was committed."
                )

            conn.execute(_text("DROP TABLE projects"))
            conn.execute(
                _text("ALTER TABLE projects_relaxed RENAME TO projects")
            )
            for sql in index_sql:
                conn.execute(_text(sql))
            conn.commit()
    except RuntimeError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        try:
            with engine.connect() as conn:
                conn.rollback()
        except Exception:
            pass
        raise RuntimeError(
            "projects NOT NULL relaxation failed; the projects table was left "
            f"unchanged. Original error: {type(exc).__name__}: {exc}"
        ) from exc


def _create_ai_tables(engine: Engine) -> None:
    """Idempotently create the AI tables + indexes on sankalp.db.

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
        # PARIKSHAN ML forecast columns (introduced with the ML integration).
        "ml_risk_score": "FLOAT",
        "ml_risk_band": "TEXT",
        "ml_cost_overrun_probability": "FLOAT",
        "ml_time_overrun_probability": "FLOAT",
        "ml_severe_overrun_probability": "FLOAT",
        "ml_expected_cost_overrun_pct": "FLOAT",
        "ml_expected_time_overrun_months": "FLOAT",
        "ml_cost_p10": "FLOAT",
        "ml_cost_p50": "FLOAT",
        "ml_cost_p90": "FLOAT",
        "ml_time_p10": "FLOAT",
        "ml_time_p50": "FLOAT",
        "ml_time_p90": "FLOAT",
        "ml_model_version": "TEXT",
        "ml_top_drivers": "TEXT",
        "ml_early_warnings": "TEXT",
        "ml_recommended_actions": "TEXT",
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


def _ensure_ai_ml_snapshots(engine: Engine) -> None:
    """Create the ML snapshot-history table on databases that predate it."""
    try:
        from database import Base
        from models import MLSnapshot  # noqa: F401

        Base.metadata.create_all(bind=engine, checkfirst=True)
    except Exception:
        pass
    _ensure_ml_snapshot_model_version(engine)


def _create_index_if_missing(conn, table: str, index_name: str, *columns: str) -> None:
    """Create a plain SQLite index when it is absent.

    `create_all()` cannot add indexes to a pre-existing table, and
    `ALTER TABLE ... ADD INDEX` is not portable, so `CREATE INDEX IF NOT
    EXISTS` is used on the open connection.
    """
    indexes = {row[1] for row in conn.execute(text(f"PRAGMA index_list({table})"))}
    if index_name in indexes:
        return
    cols = ", ".join(columns)
    conn.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({cols})"))


def _ensure_ml_snapshot_model_version(engine: Engine) -> None:
    """Add snapshot provenance so stale snapshots cannot seed edge triggers.

    Reversible: the column is nullable and only ever written for new
    snapshots. Rows written before provenance existed keep NULL and are
    therefore excluded from cross-version comparisons (see
    `ai.ai_service._previous_ml_snapshot`).
    """
    try:
        with engine.connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
            if "ai_ml_snapshots" not in tables:
                return
            existing = {
                row[1] for row in conn.execute(text("PRAGMA table_info(ai_ml_snapshots)"))
            }
            if "model_version" not in existing:
                conn.execute(
                    text("ALTER TABLE ai_ml_snapshots ADD COLUMN model_version TEXT")
                )
            _create_index_if_missing(
                conn, "ai_ml_snapshots", "ix_ai_ml_snapshots_model_version", "model_version"
            )
            _create_index_if_missing(
                conn, "ai_ml_snapshots", "ix_ai_ml_snapshots_project_id", "project_id"
            )
            conn.commit()
    except Exception:
        pass


def _ensure_anomaly_lifecycle_columns(engine: Engine) -> None:
    """Add the anomaly lifecycle columns and backfill them in place.

    Non-destructive and idempotent:
    - `batch_id` / `last_seen_at` are backfilled from the existing
      `created_at`, so every pre-existing anomaly becomes the single member of
      its own batch. No row is deleted or rewritten beyond those two columns.
    - `resolved_at` stays NULL for open rows and is backfilled only for rows
      already flagged resolved.
    """
    try:
        with engine.connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
            if "ai_anomalies" not in tables:
                return
            existing = {
                row[1] for row in conn.execute(text("PRAGMA table_info(ai_anomalies)"))
            }
            for column, ddl in (
                ("batch_id", "TEXT"),
                ("last_seen_at", "TEXT"),
                ("resolved_at", "TEXT"),
                ("resolution_source", "TEXT"),
            ):
                if column not in existing:
                    conn.execute(text(f"ALTER TABLE ai_anomalies ADD COLUMN {column} {ddl}"))
            # Backfill legacy rows: one batch per persisted timestamp.
            conn.execute(
                text(
                    "UPDATE ai_anomalies SET batch_id = created_at "
                    "WHERE batch_id IS NULL OR batch_id = ''"
                )
            )
            conn.execute(
                text(
                    "UPDATE ai_anomalies SET last_seen_at = created_at "
                    "WHERE last_seen_at IS NULL OR last_seen_at = ''"
                )
            )
            conn.execute(
                text(
                    "UPDATE ai_anomalies SET resolved_at = created_at "
                    "WHERE resolved = 1 AND (resolved_at IS NULL OR resolved_at = '')"
                )
            )
            # Rows that were already closed could only have been closed by a
            # user (auto-closure is new), so treat them as dismissals.
            conn.execute(
                text(
                    "UPDATE ai_anomalies SET resolution_source = 'USER' "
                    "WHERE resolved = 1 AND (resolution_source IS NULL "
                    "OR resolution_source = '')"
                )
            )
            _create_index_if_missing(
                conn, "ai_anomalies", "ix_ai_anomalies_project_batch", "project_id", "batch_id"
            )
            _create_index_if_missing(
                conn, "ai_anomalies", "ix_ai_anomalies_batch_id", "batch_id"
            )
            conn.commit()
    except Exception:
        pass

    _ensure_emerging_risk_resolved_at(engine)
    _fix_legacy_resolution_provenance(engine)


def _fix_legacy_resolution_provenance(engine: Engine) -> None:
    """Label closures that predate provenance correctly.

    The backfill above assumes a pre-existing resolved row was closed by a
    user, because the resolve endpoint used to be a no-op and auto-closure
    only arrived with the lifecycle work. A row whose `resolved_at` equals its
    `created_at` was stamped by that backfill rather than by a real user
    action, so when an open sibling of the same (project, type) exists it was
    collapsed by `_collapse_duplicate_active_anomalies` and is labelled AUTO.

    A genuine dismissal always records a resolution time later than the
    detection, so it is left untouched. Idempotent: it only rewrites the
    backfill signature.
    """
    try:
        with engine.connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
            if "ai_anomalies" not in tables:
                return
            existing = {
                row[1] for row in conn.execute(text("PRAGMA table_info(ai_anomalies)"))
            }
            if "resolution_source" not in existing:
                return
            conn.execute(
                text(
                    "UPDATE ai_anomalies SET resolution_source = 'AUTO' "
                    "WHERE resolution_source = 'USER' "
                    "AND resolved_at IS NOT NULL AND resolved_at = created_at "
                    "AND EXISTS ("
                    "  SELECT 1 FROM ai_anomalies o "
                    "  WHERE o.project_id = ai_anomalies.project_id "
                    "    AND o.type = ai_anomalies.type "
                    "    AND o.resolved = 0)"
                )
            )
            conn.commit()
    except Exception:
        pass


def _ensure_emerging_risk_resolved_at(engine: Engine) -> None:
    """Add a persisted resolution timestamp to emerging risks.

    Reversible: nullable, backfilled from `created_at` only for rows already
    in the RESOLVED state.
    """
    try:
        with engine.connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
            if "ai_emerging_risks" not in tables:
                return
            existing = {
                row[1] for row in conn.execute(text("PRAGMA table_info(ai_emerging_risks)"))
            }
            if "resolved_at" not in existing:
                conn.execute(
                    text("ALTER TABLE ai_emerging_risks ADD COLUMN resolved_at TEXT")
                )
            conn.execute(
                text(
                    "UPDATE ai_emerging_risks SET resolved_at = created_at "
                    "WHERE status = 'RESOLVED' AND (resolved_at IS NULL OR resolved_at = '')"
                )
            )
            conn.commit()
    except Exception:
        pass


def _collapse_duplicate_active_anomalies(engine: Engine) -> None:
    """Keep one active anomaly per (project_id, type) and close the rest.

    Older databases accumulated one row per detection run (the audit measured
    146 rows / 0 resolved). The duplicates are *resolved*, never deleted, so
    the full history stays queryable.
    """
    try:
        from sqlalchemy.orm import Session
        from models import Anomaly

        with Session(bind=engine) as session:
            rows = (
                session.query(Anomaly)
                .filter(Anomaly.resolved.is_(False))
                .order_by(Anomaly.project_id, Anomaly.type, Anomaly.created_at)
                .all()
            )
            seen = set()
            changed = False
            for row in rows:
                key = (row.project_id, row.type)
                if key in seen:
                    row.resolved = True
                    row.resolved_at = row.created_at
                    row.resolution_source = "AUTO"
                    changed = True
                else:
                    seen.add(key)
            if changed:
                session.commit()
    except Exception:
        return


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

    # Relax NOT NULL on the columns that must be able to hold "not published".
    # Runs after the additive migration above so a legacy table gains
    # `source_sector` before the rebuild copies its columns across.
    _relax_projects_measurement_nullability(engine)

    # AI persistence tables (idempotent).
    _create_ai_tables(engine)
    _ensure_ai_predictions_columns(engine)
    _ensure_ai_ml_snapshots(engine)
    _ensure_anomaly_lifecycle_columns(engine)
    _collapse_duplicate_active_anomalies(engine)

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