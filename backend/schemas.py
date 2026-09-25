from typing import Optional

from pydantic import BaseModel, Field, model_validator

VALID_SECTORS = [
    "Transport",
    "Energy",
    "Water",
    "Communication",
    "Social Infrastructure",
    "Mining",
]

VALID_UPDATE_TYPES = [
    "GENERAL",
    "PROGRESS",
    "RISK",
    "FINANCIAL",
    "MILESTONE",
    "FIELD_VISIT",
]


class ProjectResponse(BaseModel):
    id: str
    name: str
    ministry: str
    sector: str
    state: str
    agency: str
    district: Optional[str] = None
    description: Optional[str] = None
    nodalOfficer: Optional[str] = None
    contactInfo: Optional[str] = None
    originalCost: float
    currentCost: float
    # Optional because a source may simply not publish these. A NULL means
    # "not reported"; it is never substituted with 0, which would read as a
    # real measurement. Layer 1 treats a NULL as no evidence.
    expenditure: Optional[float] = None
    physicalProgress: Optional[float] = None
    financialProgress: Optional[float] = None
    plannedProgress: Optional[float] = None
    startDate: str
    expectedCompletion: str
    predictedCompletion: str
    costOverrunProbability: float
    delayProbability: float
    implementationRisk: float
    riskScore: float
    riskLevel: str
    milestonesTotal: int
    milestonesDelayed: int
    # Most government project portals publish no coordinates. NULL is the
    # honest value; 0,0 is a real point in the Gulf of Guinea and must not be
    # used as a stand-in.
    lat: Optional[float] = None
    lng: Optional[float] = None
    riskFactors: list[str]
    recommendations: list[str]
    riskConfidence: Optional[float] = None
    criticalBlocker: Optional[bool] = False
    riskInputs: Optional[dict] = None
    riskReport: Optional[dict] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    # Government-ingest provenance (empty for manually created records).
    status: Optional[str] = None
    scale: Optional[str] = None
    fundingSource: Optional[str] = None
    externalRef: Optional[str] = None
    dataSource: Optional[dict] = None
    lastSyncedAt: Optional[str] = None

    class Config:
        from_attributes = True


class RiskDataQualityResponse(BaseModel):
    totalFactors: int = 0
    availableFactors: int = 0
    missingFactors: int = 0
    completeness: int = 0
    weightedCompleteness: int = 0
    availableFactorKeys: list[str] = Field(default_factory=list)
    missingFactorKeys: list[str] = Field(default_factory=list)
    missingFactorNames: list[str] = Field(default_factory=list)


class RiskScoreBreakdownResponse(BaseModel):
    weightedBase: float = 0.0
    interactionPenalty: int = 0
    interactionPenaltyConfigured: int = 0
    interactionPenaltyCap: int = 0
    dominantFactorBoost: float = 0.0
    blockerFloor: int = 0
    rawScore: int = 0
    finalScore: int = 0


class RiskFactorResponse(BaseModel):
    key: str
    name: str
    score: int
    weight: int
    contribution: float
    probability: float
    impact: float
    severity: str
    reason: str
    dataAvailable: bool
    factor: Optional[str] = None
    explanation: Optional[str] = None
    triggeredConditions: list[str] = Field(default_factory=list)


class RiskInteractionResponse(BaseModel):
    key: str
    name: str
    penalty: int
    reason: str
    trigger: Optional[str] = None
    affectedFactors: list[str] = Field(default_factory=list)
    triggeredConditions: list[str] = Field(default_factory=list)
    explanation: Optional[str] = None


class RiskBlockerResponse(BaseModel):
    key: str
    level: str
    reason: str
    recommendation: str
    blocker: Optional[str] = None
    severity: Optional[str] = None
    minimumScore: int = 0
    explanation: Optional[str] = None


class RiskAssessmentResponse(BaseModel):
    projectId: str
    riskScore: int
    riskLevel: str
    confidence: int
    dataCompleteness: int
    criticalBlocker: bool
    criticalBlockerReasons: list[str]
    factors: list[RiskFactorResponse]
    interactions: list[RiskInteractionResponse]
    blockers: list[RiskBlockerResponse] = Field(default_factory=list)
    topRisks: list[str]
    topRiskFactors: list[RiskFactorResponse] = Field(default_factory=list)
    recommendations: list[str]
    explanations: list[str]
    missingData: list[str]
    dataQuality: RiskDataQualityResponse = Field(default_factory=RiskDataQualityResponse)
    assessmentStatus: str = "UNKNOWN"
    riskLevelProvisional: bool = False
    interactionPenalty: int = 0
    blockerFloor: int = 0
    scoreBreakdown: Optional[RiskScoreBreakdownResponse] = None
    engineVersion: Optional[str] = None
    contractVersion: Optional[str] = None
    assessedAt: Optional[str] = None
    riskTrend: Optional[dict] = None
    costOverrunProbability: int
    delayProbability: int
    implementationRisk: int
    calculatedAt: Optional[str] = None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    ministry: str = Field(min_length=1, max_length=200)
    agency: str = Field(min_length=1, max_length=200)
    sector: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=1, max_length=100)
    district: Optional[str] = Field(default=None, max_length=100)

    originalCost: float = Field(gt=0)
    revisedCost: Optional[float] = Field(default=None, ge=0)
    expenditure: Optional[float] = Field(default=0, ge=0)

    physicalProgress: float = Field(ge=0, le=100)
    financialProgress: Optional[float] = Field(default=None, ge=0, le=100)

    startDate: str = Field(min_length=1)
    completionDate: str = Field(min_length=1)
    predictedCompletionDate: Optional[str] = None

    description: Optional[str] = None
    nodalOfficer: Optional[str] = Field(default=None, max_length=200)
    contactInfo: Optional[str] = Field(default=None, max_length=200)

    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    riskInputs: Optional[dict] = None

    @model_validator(mode="after")
    def check_dates(self):
        if self.completionDate < self.startDate:
            raise ValueError("Completion date cannot be before start date")
        if (
            self.predictedCompletionDate
            and self.predictedCompletionDate < self.startDate
        ):
            raise ValueError(
                "Expected completion date cannot be before start date"
            )
        return self


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=300)
    ministry: Optional[str] = Field(default=None, min_length=1, max_length=200)
    agency: Optional[str] = Field(default=None, min_length=1, max_length=200)
    sector: Optional[str] = Field(default=None, min_length=1, max_length=100)
    state: Optional[str] = Field(default=None, min_length=1, max_length=100)
    district: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = None
    nodalOfficer: Optional[str] = Field(default=None, max_length=200)
    contactInfo: Optional[str] = Field(default=None, max_length=200)

    originalCost: Optional[float] = Field(default=None, gt=0)
    revisedCost: Optional[float] = Field(default=None, ge=0)
    expenditure: Optional[float] = Field(default=None, ge=0)

    physicalProgress: Optional[float] = Field(default=None, ge=0, le=100)
    financialProgress: Optional[float] = Field(default=None, ge=0, le=100)

    startDate: Optional[str] = None
    completionDate: Optional[str] = None
    predictedCompletionDate: Optional[str] = None

    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    riskInputs: Optional[dict] = None


class ProjectUpdateCreate(BaseModel):
    updateType: str = Field(default="GENERAL")
    content: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def check_type_and_content(self):
        if self.updateType not in VALID_UPDATE_TYPES:
            raise ValueError(
                f"updateType must be one of: {', '.join(VALID_UPDATE_TYPES)}"
            )
        if not self.content.strip():
            raise ValueError("content cannot be empty")
        return self


class ProjectUpdateResponse(BaseModel):
    id: int
    projectId: str
    userId: str
    userName: str
    userRole: str
    updateType: str
    content: str
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None


class AlertResponse(BaseModel):
    id: str
    projectId: str
    projectName: str
    type: str
    severity: str
    detectedDate: str
    description: str

    class Config:
        from_attributes = True


class DashboardResponse(BaseModel):
    totalProjects: int
    highRiskProjects: int
    scheduleRiskCount: int
    costRiskCount: int
    portfolioValue: float
    revisedValue: float
    riskDistribution: dict
    highRiskTable: list[ProjectResponse]


class AssistantRequest(BaseModel):
    query: str


class AssistantResponse(BaseModel):
    reply: str
