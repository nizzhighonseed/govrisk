from sqlalchemy import Column, String, Float, Integer, Text, Boolean, Index
from database import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    ministry = Column(String, nullable=False)
    sector = Column(String, nullable=False)
    state = Column(String, nullable=False)
    agency = Column(String, nullable=False)
    district = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    nodal_officer = Column(String, nullable=True)
    contact_info = Column(String, nullable=True)
    original_cost = Column(Float, nullable=False)
    current_cost = Column(Float, nullable=False)
    # Nullable so a source that does not publish a figure records "unknown"
    # rather than a fabricated 0.0. Layer 1 reads these through `_num(v, 0)`
    # in `risk_service._derived`, so a NULL is handled, not crashed on.
    expenditure = Column(Float, nullable=True)
    physical_progress = Column(Float, nullable=True)
    financial_progress = Column(Float, nullable=True)
    planned_progress = Column(Float, nullable=True)
    start_date = Column(String, nullable=False)
    expected_completion = Column(String, nullable=False)
    predicted_completion = Column(String, nullable=False)
    cost_overrun_probability = Column(Float, nullable=False)
    delay_probability = Column(Float, nullable=False)
    implementation_risk = Column(Float, nullable=False)
    risk_score = Column(Float, nullable=False)
    risk_level = Column(String, nullable=False)
    milestones_total = Column(Integer, nullable=False)
    milestones_delayed = Column(Integer, nullable=False)
    # Nullable: most government project portals publish no coordinates, and a
    # NULL is the only honest value. 0,0 is a real point in the Gulf of Guinea
    # and must never be used as a placeholder - it puts the project on the map
    # as if its location were known.
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    risk_factors = Column(Text, nullable=False)
    recommendations = Column(Text, nullable=False)
    risk_inputs = Column(Text, nullable=True, default="{}")
    risk_confidence = Column(Float, nullable=True)
    risk_report = Column(Text, nullable=True)
    created_at = Column(String, nullable=True)
    updated_at = Column(String, nullable=True)

    # --- Government-ingest provenance -------------------------------------------------
    # Filled by the ingestion pipeline (backend/ingest). Manual records created
    # through the API leave these NULL / defaulted.
    status = Column(String, nullable=False, default="ONGOING")  # ONGOING|COMPLETED|DELAYED|STALLED|CANCELLED
    scale = Column(String, nullable=True)  # MEDIUM|LARGE (see ingest/normalize.py)
    funding_source = Column(String, nullable=True)
    external_ref = Column(String, nullable=True)  # source record id (dedup key)
    source_name = Column(String, nullable=True)
    source_url = Column(String, nullable=True)
    retrieved_date = Column(String, nullable=True)
    data_confidence = Column(String, nullable=True)  # OFFICIAL|VERIFIED_SECONDARY|UNVERIFIED
    last_synced_at = Column(String, nullable=True)
    # The sector label exactly as the source published it, kept alongside the
    # canonical `sector` so a corrected source-specific mapping can be applied
    # later without re-reading the source (see ingest/normalize.py).
    source_sector = Column(String, nullable=True)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False)
    type = Column(String, nullable=False)
    severity = Column(String, nullable=False)
    description = Column(String, nullable=False)
    detected_date = Column(String, nullable=False)
    status = Column(String, nullable=False, default="ACTIVE")


class ProjectUpdate(Base):
    __tablename__ = "project_updates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    update_type = Column(String, nullable=False, default="GENERAL")
    created_at = Column(String, nullable=True)
    updated_at = Column(String, nullable=True)


class AIAnalysis(Base):
    """Persisted AI run history for a project (cache + audit trail)."""

    __tablename__ = "ai_analyses"

    id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False, index=True)
    created_at = Column(String, nullable=False, index=True)
    analysis_type = Column(String, nullable=False)  # prediction|anomaly|emerging|explanation|insights
    model = Column(String, nullable=True)
    prediction_method = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    summary = Column(Text, nullable=True)
    raw_result = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_ai_analyses_project_created", "project_id", "created_at"),
    )


class AIPrediction(Base):
    """Latest numeric prediction snapshot per project."""

    __tablename__ = "ai_predictions"

    id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False, index=True)
    created_at = Column(String, nullable=False)
    horizon_days = Column(Integer, nullable=False, default=90)
    schedule_delay_probability = Column(Float, nullable=False)
    cost_overrun_probability = Column(Float, nullable=False)
    risk_escalation_probability = Column(Float, nullable=False)
    clearance_delay_probability = Column(Float, nullable=False)
    contractor_failure_probability = Column(Float, nullable=False)
    expected_delay_min = Column(Integer, nullable=True)
    expected_delay_max = Column(Integer, nullable=True)
    future_score = Column(Integer, nullable=True)
    current_score = Column(Integer, nullable=True)
    data_points_used = Column(Integer, nullable=True, default=0)
    confidence = Column(Float, nullable=False)
    prediction_method = Column(String, nullable=True)
    model_version = Column(String, nullable=True)
    drivers = Column(Text, nullable=True)  # JSON: list[str]

    # PARIKSHAN ML forecast (separate from the deterministic fields above).
    # Populated only when the trained models are available; deterministic
    # fields are never overwritten by ML output.
    ml_risk_score = Column(Float, nullable=True)
    ml_risk_band = Column(String, nullable=True)
    ml_cost_overrun_probability = Column(Float, nullable=True)
    ml_time_overrun_probability = Column(Float, nullable=True)
    ml_severe_overrun_probability = Column(Float, nullable=True)
    ml_expected_cost_overrun_pct = Column(Float, nullable=True)
    ml_expected_time_overrun_months = Column(Float, nullable=True)
    ml_cost_p10 = Column(Float, nullable=True)
    ml_cost_p50 = Column(Float, nullable=True)
    ml_cost_p90 = Column(Float, nullable=True)
    ml_time_p10 = Column(Float, nullable=True)
    ml_time_p50 = Column(Float, nullable=True)
    ml_time_p90 = Column(Float, nullable=True)
    ml_model_version = Column(String, nullable=True)
    ml_top_drivers = Column(Text, nullable=True)  # JSON: list[str]
    ml_early_warnings = Column(Text, nullable=True)  # JSON: list[dict]
    ml_recommended_actions = Column(Text, nullable=True)  # JSON: list[str]

    __table_args__ = (
        Index("ix_ai_predictions_project_created", "project_id", "created_at"),
    )


class MLSnapshot(Base):
    """Per-project ML snapshot history enabling edge-triggered early
    warnings (EW-01/03/04/07 need two consecutive snapshots to be able to
    detect an abrupt change instead of a one-off boundary cross)."""

    __tablename__ = "ai_ml_snapshots"

    id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False, index=True)
    created_at = Column(String, nullable=False, index=True)
    ml_risk_score = Column(Float, nullable=False)
    ml_risk_band = Column(String, nullable=False)
    ml_severe_overrun_probability = Column(Float, nullable=False)
    ml_expected_cost_overrun_pct = Column(Float, nullable=False)
    ml_expected_time_overrun_months = Column(Float, nullable=False)
    # Snapshot of the raw feature row (JSON) used to trigger history-based
    # early-warning rules without recomputation or re-fitting.
    feature_snapshot = Column(Text, nullable=True)  # JSON: dict
    # Provenance: which PARIKSHAN artifact fingerprint produced this snapshot.
    # NULL for snapshots written before provenance was recorded (they are
    # retained for history but must never seed a cross-version edge trigger).
    model_version = Column(String, nullable=True, index=True)

    __table_args__ = (
        Index("ix_ai_ml_snapshots_project_created", "project_id", "created_at"),
    )


class Anomaly(Base):
    """Statistical anomaly detected on a project.

    Lifecycle (one row per project + anomaly type while it is active):
    - `batch_id` identifies the analysis run that most recently detected this
      anomaly. Every anomaly produced by a single analysis shares one
      `batch_id`, so the intelligence response can return the whole latest
      batch instead of a single row picked by timestamp equality.
    - `created_at` is the first detection and is never rewritten, so the
      detection history survives every re-analysis.
    - `last_seen_at` advances on every re-detection; `resolved_at` records
      when the anomaly stopped being detected or was resolved by a user.
    - `resolution_source` separates the two closures: `USER` (an officer
      acknowledged it, and a re-analysis must not silently resurrect it) from
      `AUTO` (the condition stopped being detected, so a later re-appearance is
      a genuinely new occurrence and opens a new row).
    """

    __tablename__ = "ai_anomalies"

    id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False, index=True)
    created_at = Column(String, nullable=False)
    type = Column(String, nullable=False)
    severity = Column(String, nullable=False)
    score = Column(Float, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    evidence = Column(Text, nullable=True)  # JSON: list[str]
    resolved = Column(Boolean, nullable=False, default=False)
    batch_id = Column(String, nullable=True, index=True)
    last_seen_at = Column(String, nullable=True)
    resolved_at = Column(String, nullable=True)
    resolution_source = Column(String, nullable=True)  # USER|AUTO

    __table_args__ = (
        Index("ix_ai_anomalies_project_created", "project_id", "created_at"),
        Index("ix_ai_anomalies_project_batch", "project_id", "batch_id"),
    )


class EmergingRisk(Base):
    """Emerging risk discovered from project updates (AI-extracted)."""

    __tablename__ = "ai_emerging_risks"

    id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False, index=True)
    created_at = Column(String, nullable=False)
    category = Column(String, nullable=False)
    title = Column(String, nullable=False)
    confidence = Column(Float, nullable=False)
    severity = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    evidence = Column(Text, nullable=True)  # JSON: list[str]
    recommendations = Column(Text, nullable=True)  # JSON: list[str]
    source_update_ids = Column(Text, nullable=True)  # JSON: list[int]
    status = Column(String, nullable=False, default="ACTIVE")  # ACTIVE|RESOLVED
    resolved_at = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_ai_emerging_risks_project_created", "project_id", "created_at"),
    )


class IngestAuditLog(Base):
    """Append-only provenance ledger for the ingestion pipeline.

    Every insert/update/skip/merge/reject writes a row here so every database
    state change is traceable to a source, a timestamp, and the changed
    record. No deletes: rows are soft-flagged via the audit record only.
    """

    __tablename__ = "ingest_audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String, nullable=False)
    project_id = Column(String, nullable=True, index=True)
    action = Column(String, nullable=False)  # INSERT|UPDATE|SKIP|MERGE|REJECT
    detail = Column(Text, nullable=True)
    created_at = Column(String, nullable=False)
