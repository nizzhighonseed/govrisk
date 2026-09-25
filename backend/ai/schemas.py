"""Structured contracts for the AI layer.

These Pydantic models are the single source of truth for AI JSON shapes.
The LLM is never relied on for free-form text - everything it produces is
validated against these schemas before it is persisted or exposed.
"""

from typing import Optional
from pydantic import BaseModel, Field

PREDICTION_METHOD_ML = "ml"
PREDICTION_METHOD_PARIKSHAN_ML = "parikshan_ml"
PREDICTION_METHOD_HYBRID = "hybrid"
PREDICTION_METHOD_RULE = "rule_statistical_fallback"

MODEL_VERSION = "sankalp-ai-v1"


class MLForecast(BaseModel):
    """Structured output of the trained PARIKSHAN models (non-deterministic,
    additive ML signal — never replaces the deterministic risk fields)."""

    cost_overrun_probability: float = Field(ge=0, le=1)
    time_overrun_probability: float = Field(ge=0, le=1)
    severe_overrun_probability: float = Field(ge=0, le=1)
    expected_cost_overrun_pct: float
    expected_time_overrun_months: float
    cost_prediction_p10: float
    cost_prediction_p50: float
    cost_prediction_p90: float
    time_prediction_p10: float
    time_prediction_p50: float
    time_prediction_p90: float
    risk_score: float = Field(ge=0, le=100)
    risk_band: str
    model_version: str
    prediction_method: str = PREDICTION_METHOD_PARIKSHAN_ML
    data_points_used: int = 37
    top_drivers: list = Field(default_factory=list)
    early_warnings: list = Field(default_factory=list)
    recommended_actions: list = Field(default_factory=list)


class PredictionResult(BaseModel):
    schedule_delay_probability: float = Field(ge=0, le=1)
    cost_overrun_probability: float = Field(ge=0, le=1)
    risk_escalation_probability: float = Field(ge=0, le=1)
    clearance_delay_probability: float = Field(ge=0, le=1)
    contractor_failure_probability: float = Field(ge=0, le=1)
    expected_delay_months: dict = Field(
        default_factory=lambda: {"min": 0, "max": 0}
    )
    risk_horizon_days: int = 90
    prediction_confidence: float = Field(ge=0, le=1)
    future_score: Optional[int] = Field(default=None, ge=0, le=100)
    current_score: Optional[int] = Field(default=None, ge=0, le=100)
    prediction_method: str = PREDICTION_METHOD_RULE
    model_version: str = MODEL_VERSION
    data_points_used: int = 0
    generated_at: Optional[str] = None
    top_drivers: list = Field(default_factory=list)
    ml_forecast: Optional[MLForecast] = None


class AnomalyResult(BaseModel):
    anomaly_detected: bool = False
    severity: str = "LOW"
    score: float = Field(default=0, ge=0, le=1)
    type: str = "NONE"
    title: str = ""
    description: str = ""
    evidence: list = Field(default_factory=list)
    generated_at: Optional[str] = None


class EmergingRiskResult(BaseModel):
    risk_detected: bool
    category: str = "OTHER"
    title: str = ""
    confidence: float = Field(ge=0, le=1)
    severity: str = "MEDIUM"
    potential_impact: list = Field(default_factory=list)
    description: str = ""
    evidence: list = Field(default_factory=list)
    recommended_actions: list = Field(default_factory=list)
    time_horizon_days: Optional[int] = None
    source_update_ids: list = Field(default_factory=list)


class UpdateAnalysisResult(BaseModel):
    """Structured output required from the LLM for project-update analysis.

    Parsing failures on any required field trigger a retry, then an
    automatic fallback to deterministic keyword analysis.
    """

    risk_detected: bool
    risk_category: str = "OTHER"
    risk_title: str = ""
    confidence: float = Field(ge=0, le=1, default=0.5)
    severity: str = "MEDIUM"
    potential_impact: str = "MEDIUM"
    time_horizon_days: Optional[int] = Field(default=None, ge=0, le=3650)
    evidence: list = Field(default_factory=list)
    recommended_actions: list = Field(default_factory=list)


class ExplanationResponse(BaseModel):
    summary: str
    current_risk: int
    future_risk: int
    main_drivers: list = Field(default_factory=list)
    predicted_events: list = Field(default_factory=list)
    recommended_interventions: list = Field(default_factory=list)
    ai_evidence: list = Field(default_factory=list)


class InsightsResponse(BaseModel):
    project_id: str
    prediction: Optional[dict] = None
    anomalies: list = Field(default_factory=list)
    emerging_risks: list = Field(default_factory=list)
    explanation: Optional[dict] = None
    generated_at: Optional[str] = None
    ai_available: bool = True
    analysis_kind: str = "cached"


class AIHealthResponse(BaseModel):
    available: bool
    provider: str = ""
    model: str = ""
    fallback_enabled: bool = True