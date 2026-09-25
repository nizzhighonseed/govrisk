export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
export type RiskAssessmentStatus = 'COMPLETE' | 'INSUFFICIENT_DATA' | 'UNKNOWN';

export type Sector =
  'Transport' | 'Energy' | 'Water' | 'Communication' | 'Mining' | 'Social Infrastructure';

export type AlertSeverity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'RESOLVED';

export interface RiskInputs {
  weather?: Record<string, any>;
  ground?: Record<string, any>;
  calamity?: Record<string, any>;
  material?: Record<string, any>;
  workforce?: Record<string, any>;
  contractor?: Record<string, any>;
  engineering?: Record<string, any>;
  clearance?: Record<string, any>;
  administrative?: Record<string, any>;
  supplyChain?: Record<string, any>;
  legalSocial?: Record<string, any>;
}

export interface RiskFactor {
  key: string;
  factor: string;
  name: string;
  score: number;
  weight: number;
  contribution: number;
  probability: number;
  impact: number;
  severity: string;
  reason: string;
  explanation: string;
  triggeredConditions: string[];
  dataAvailable: boolean;
}

export interface RiskInteraction {
  key: string;
  trigger: string;
  name: string;
  affectedFactors: string[];
  triggeredConditions: string[];
  penalty: number;
  reason: string;
  explanation: string;
}

export interface RiskBlocker {
  key: string;
  blocker: string;
  level: string;
  severity: string;
  minimumScore: number;
  reason: string;
  explanation: string;
  recommendation: string;
}

export interface RiskDataQuality {
  totalFactors: number;
  availableFactors: number;
  missingFactors: number;
  completeness: number;
  weightedCompleteness: number;
  availableFactorKeys: string[];
  missingFactorKeys: string[];
  missingFactorNames: string[];
}

export interface RiskScoreBreakdown {
  weightedBase: number;
  interactionPenalty: number;
  interactionPenaltyConfigured: number;
  interactionPenaltyCap: number;
  dominantFactorBoost: number;
  blockerFloor: number;
  rawScore: number;
  finalScore: number;
}

export interface RiskAssessment {
  projectId: string;
  riskScore: number;
  riskLevel: RiskLevel;
  confidence: number;
  dataCompleteness: number;
  criticalBlocker: boolean;
  criticalBlockerReasons: string[];
  factors: RiskFactor[];
  interactions: RiskInteraction[];
  blockers: RiskBlocker[];
  topRisks: string[];
  topRiskFactors: RiskFactor[];
  recommendations: string[];
  explanations: string[];
  missingData: string[];
  dataQuality: RiskDataQuality;
  assessmentStatus: RiskAssessmentStatus;
  riskLevelProvisional: boolean;
  interactionPenalty: number;
  blockerFloor: number;
  scoreBreakdown?: RiskScoreBreakdown;
  engineVersion?: string;
  contractVersion?: string;
  assessedAt?: string;
  riskTrend?: { available: boolean; note?: string };
  costOverrunProbability: number;
  delayProbability: number;
  implementationRisk: number;
  calculatedAt?: string;
}

export interface Project {
  id: string;
  name: string;
  ministry: string;
  sector: Sector;
  state: string;
  agency: string;
  district?: string;
  description?: string;
  nodalOfficer?: string;
  contactInfo?: string;
  originalCost: number;
  currentCost: number;
  /**
   * `null` means the source never reported the value. It is deliberately not
   * coerced to 0, because 0 is a real measurement (no spend, no progress) and
   * substituting it would silently fabricate evidence. Layer 1 scores a `null`
   * as "no evidence" rather than "zero".
   */
  expenditure: number | null;
  physicalProgress: number | null;
  financialProgress?: number | null;
  plannedProgress: number | null;
  startDate: string;
  expectedCompletion: string;
  predictedCompletion: string;
  costOverrunProbability: number;
  delayProbability: number;
  implementationRisk: number;
  riskScore: number;
  riskLevel: RiskLevel;
  milestonesTotal: number;
  milestonesDelayed: number;
  /**
   * Null when the portal publishes no coordinates. (0, 0) is a real point in
   * the Gulf of Guinea, so it must never be used as a stand-in for "unknown".
   */
  lat: number | null;
  lng: number | null;
  riskFactors: string[];
  recommendations: string[];
  riskConfidence?: number;
  criticalBlocker?: boolean;
  riskInputs?: RiskInputs;
  riskReport?: RiskAssessment;
  createdAt?: string;
  updatedAt?: string;
}

export interface DashboardResponse {
  totalProjects: number;
  highRiskProjects: number;
  scheduleRiskCount: number;
  costRiskCount: number;
  portfolioValue: number;
  revisedValue: number;
  riskDistribution: Record<string, number>;
  highRiskTable: Project[];
}

export interface Alert {
  id: string;
  projectId: string;
  projectName: string;
  type: string;
  severity: AlertSeverity;
  detectedDate: string;
  description: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
}

export interface SectorAnalytics {
  sector: string;
  avgRisk: number;
  projectCount: number;
  avgCostOverrun: number;
  avgDelay: number;
}

export interface MinistryRanking {
  rank: number;
  ministry: string;
  projectCount: number;
  avgRisk: number;
  highRiskCount: number;
}

export interface ScatterPoint {
  name: string;
  physicalProgress: number;
  costOverrun: number;
  sector: string;
}

export interface RiskTrend {
  month: string;
  low: number;
  medium: number;
  high: number;
  critical: number;
  overall: number;
}

export type ProjectUpdateType =
  'GENERAL' | 'PROGRESS' | 'RISK' | 'FINANCIAL' | 'MILESTONE' | 'FIELD_VISIT';

export interface ProjectUpdate {
  id: number;
  projectId: string;
  userId: string;
  userName: string;
  userRole: string;
  updateType: ProjectUpdateType;
  content: string;
  createdAt: string;
  updatedAt: string;
}
