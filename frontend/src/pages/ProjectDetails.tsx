import { useState, useEffect, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  AlertTriangle,
  DollarSign,
  ArrowLeft,
  Building,
  MapPin,
  Calendar,
  Target,
  TrendingDown,
  FileText,
  ShieldAlert,
  MessageSquare,
  Plus,
  PenSquare,
  Trash2,
  Brain,
  AlertCircle,
  AlertOctagon,
  CheckCircle2,
  RefreshCw,
} from 'lucide-react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';
import {
  getProject,
  getProjectUpdates,
  deleteProjectUpdate,
  getAiInsights,
  getAiMlStatus,
  resolveAiAnomaly,
  resolveEmergingRisk,
} from '../services/api';
import type { AiInsights, AiMlForecast } from '../services/api';
import type { Project, RiskAssessment } from '../types';
import { useAuth } from '../context/AuthContext';
import { RiskBadge } from '../components/ui/RiskBadge';
import { RiskScore } from '../components/ui/RiskScore';
import { ProgressBar } from '../components/ui/ProgressBar';
import { LoadingState } from '../components/ui/LoadingState';
import { RiskFactorChart } from '../components/charts/RiskFactorChart';
import { ProjectTimeline } from '../components/project/ProjectTimeline';
import AddUpdateModal from '../components/project/AddUpdateModal';
import AddProjectModal from '../components/admin/AddProjectModal';
import {
  formatCurrency,
  formatCurrencyNullable,
  formatDate,
  getRiskColor,
} from '../utils/helpers';

const UPDATE_TYPE_LABELS: Record<string, string> = {
  GENERAL: 'General',
  PROGRESS: 'Progress',
  RISK: 'Risk',
  FINANCIAL: 'Financial',
  MILESTONE: 'Milestone',
  FIELD_VISIT: 'Field Visit',
};

const UPDATE_TYPE_COLORS: Record<string, string> = {
  GENERAL: 'bg-gray-100 text-gray-600 ring-gray-200',
  PROGRESS: 'bg-blue-50 text-blue-700 ring-blue-200',
  RISK: 'bg-red-50 text-red-700 ring-red-200',
  FINANCIAL: 'bg-green-50 text-green-700 ring-green-200',
  MILESTONE: 'bg-amber-50 text-amber-700 ring-amber-200',
  FIELD_VISIT: 'bg-purple-50 text-purple-700 ring-purple-200',
};

function roleLabel(role: string) {
  switch (role) {
    case 'admin':
      return 'Admin';
    case 'officer':
      return 'Officer';
    case 'analyst':
      return 'Analyst';
    case 'viewer':
      return 'Viewer';
    default:
      return role;
  }
}

function formatUpdateTime(iso?: string) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function getBarColor(name: string) {
  switch (name) {
    case 'Original Cost':
      return '#3b82f6';
    case 'Current Cost':
      return '#f97316';
    case 'Predicted Final Cost':
      return '#ef4444';
    default:
      return '#3b82f6';
  }
}

function getMonthDifference(date1: string, date2: string) {
  const d1 = new Date(date1);
  const d2 = new Date(date2);
  const months = (d2.getFullYear() - d1.getFullYear()) * 12 + (d2.getMonth() - d1.getMonth());
  return Math.max(months, 0);
}

function getProgressColor(percentage: number): 'green' | 'yellow' | 'red' {
  if (percentage <= 50) return 'green';
  if (percentage <= 75) return 'yellow';
  return 'red';
}

function buildStatus(project: { riskLevel: string }) {
  if (!project) return '';
  return project.riskLevel;
}

export default function ProjectDetails() {
  const { id } = useParams<{ id: string }>();
  const { user: currentUser } = useAuth();
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const [updates, setUpdates] = useState<any[]>([]);
  const [updatesLoading, setUpdatesLoading] = useState(true);
  const [noteModal, setNoteModal] = useState<{ open: boolean; edit: any | null }>({
    open: false,
    edit: null,
  });
  const [noteToast, setNoteToast] = useState('');
  const [editProjectOpen, setEditProjectOpen] = useState(false);

  const [aiInsights, setAiInsights] = useState<AiInsights | null>(null);
  const [aiLoading, setAiLoading] = useState(true);
  const [aiError, setAiError] = useState(false);
  const [mlStatus, setMlStatus] = useState<Awaited<ReturnType<typeof getAiMlStatus>> | null>(null);
  const [resolvingId, setResolvingId] = useState<string | null>(null);

  const canEditProject = currentUser?.role === 'admin' || currentUser?.role === 'officer';

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError(false);
    getProject(id)
      .then((data) => {
        setProject(data);
      })
      .catch(() => {
        setError(true);
      })
      .finally(() => {
        setLoading(false);
      });
  }, [id]);

  const fetchUpdates = useCallback(async () => {
    if (!id) return;
    try {
      const data = await getProjectUpdates(id);
      setUpdates(data);
    } catch {
      setUpdates([]);
    } finally {
      setUpdatesLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchUpdates();
  }, [fetchUpdates]);

  useEffect(() => {
    if (!id) return;
    setAiLoading(true);
    setAiError(false);
    getAiInsights(id)
      .then(setAiInsights)
      .catch(() => setAiError(true))
      .finally(() => setAiLoading(false));
  }, [id]);

  useEffect(() => {
    if (!id) return;
    getAiMlStatus()
      .then(setMlStatus)
      .catch(() => setMlStatus(null));
  }, [id]);

  const refreshAiInsights = useCallback(() => {
    if (!id) return;
    getAiInsights(id)
      .then(setAiInsights)
      .catch(() => setAiError(true));
  }, [id]);

  async function handleResolveAnomaly(anomalyId: string) {
    if (!id) return;
    setResolvingId(anomalyId);
    try {
      await resolveAiAnomaly(id, anomalyId);
      refreshAiInsights();
    } catch (e: any) {
      alert(e.message || 'Failed to resolve anomaly');
    } finally {
      setResolvingId(null);
    }
  }

  async function handleResolveEmergingRisk(riskId: string) {
    if (!id) return;
    setResolvingId(riskId);
    try {
      await resolveEmergingRisk(id, riskId);
      refreshAiInsights();
    } catch (e: any) {
      alert(e.message || 'Failed to resolve emerging risk');
    } finally {
      setResolvingId(null);
    }
  }

  useEffect(() => {
    if (!noteToast) return;
    const t = setTimeout(() => setNoteToast(''), 4000);
    return () => clearTimeout(t);
  }, [noteToast]);

  function canModifyUpdate(u: any) {
    return currentUser?.role === 'admin' || u.userId === currentUser?.userId;
  }

  async function handleDeleteUpdate(u: any) {
    if (!id) return;
    const confirmed = window.confirm('Delete this update? This action cannot be undone.');
    if (!confirmed) return;
    try {
      await deleteProjectUpdate(id, u.id);
      fetchUpdates();
    } catch (e: any) {
      alert(e.message || 'Failed to delete update');
    }
  }

  if (loading) {
    return (
      <div className="mx-auto min-w-0 max-w-[1600px]">
        <LoadingState />
      </div>
    );
  }

  if (!project || error) {
    return (
      <div className="mx-auto min-w-0 max-w-[1600px]">
        <div className="flex flex-col items-center justify-center py-20">
          <AlertTriangle className="mb-4 h-12 w-12 text-red-500" />
          <h1 className="mb-2 text-2xl font-bold text-navy-900">Project not found</h1>
          <p className="mb-6 text-gray-500">The project you are looking for does not exist.</p>
          <Link
            to="/projects"
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
          >
            <ArrowLeft size={16} />
            Back to Projects
          </Link>
        </div>
      </div>
    );
  }

  const predictedCost = Math.round(project.currentCost * 1.087);
  const costOverrunPercent = Math.round(
    ((predictedCost - project.originalCost) / project.originalCost) * 100,
  );
  const delayMonths = getMonthDifference(project.expectedCompletion, project.predictedCompletion);

  const projectCostData = [
    { name: 'Original Cost', value: project.originalCost },
    { name: 'Current Cost', value: project.currentCost },
    { name: 'Predicted Final Cost', value: predictedCost },
  ];

  const report: RiskAssessment | undefined = project.riskReport;
  const riskFactorChartData = (report?.topRiskFactors || []).map((factor) => ({
    key: factor.key,
    name: factor.name,
    score: factor.score,
    severity: factor.severity,
    dataAvailable: factor.dataAvailable,
  }));

  const sectionLabel = 'text-xs font-semibold uppercase tracking-widest text-blue-600';

  return (
    <div className="mx-auto min-w-0 max-w-[1600px]">
      <Link
        to="/projects"
        className="mb-5 inline-flex items-center gap-1.5 text-sm font-medium text-gray-500 transition-colors hover:text-navy-900"
      >
        <ArrowLeft size={16} />
        Back to Projects
      </Link>

      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold tracking-tight text-navy-900 lg:text-3xl">
            {project.name}
          </h1>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm text-gray-500">
            <span className="inline-flex items-center gap-1.5">
              <Building size={14} className="text-gray-400" />
              {project.ministry}
            </span>
            <span className="text-gray-300">•</span>
            <span className="inline-flex items-center gap-1.5">
              <FileText size={14} className="text-gray-400" />
              {project.sector}
            </span>
            <span className="text-gray-300">•</span>
            <span className="inline-flex items-center gap-1.5">
              <MapPin size={14} className="text-gray-400" />
              {project.state}
            </span>
            <span className="text-gray-300">•</span>
            <span className="inline-flex items-center gap-1.5">{project.agency}</span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <RiskBadge level={project.riskLevel} />
          {canEditProject && (
            <button
              onClick={() => setEditProjectOpen(true)}
              className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3.5 py-2 text-sm font-semibold text-navy-900 transition-colors hover:bg-gray-50"
            >
              <PenSquare className="h-4 w-4" />
              Edit Project
            </button>
          )}
        </div>
      </div>

      <div className="mb-8">
        <p className={`${sectionLabel} mb-3`}>Project Overview</p>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="mb-2 flex items-center gap-2">
              <DollarSign size={16} className="text-blue-500" />
              <span className="text-xs font-medium text-gray-500">Original Cost</span>
            </div>
            <p className="text-base font-bold text-navy-900 lg:text-lg">
              {formatCurrency(project.originalCost)}
            </p>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="mb-2 flex items-center gap-2">
              <DollarSign size={16} className="text-orange-500" />
              <span className="text-xs font-medium text-gray-500">Current Cost</span>
            </div>
            <p className="text-base font-bold text-navy-900 lg:text-lg">
              {formatCurrency(project.currentCost)}
            </p>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="mb-2 flex items-center gap-2">
              <TrendingDown size={16} className="text-gray-500" />
              <span className="text-xs font-medium text-gray-500">Expenditure</span>
            </div>
            <p className="text-base font-bold text-navy-900 lg:text-lg">
              {formatCurrencyNullable(project.expenditure)}
            </p>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="mb-2 flex items-center gap-2">
              <Target size={16} className="text-green-500" />
              <span className="text-xs font-medium text-gray-500">Physical Progress</span>
            </div>
            <p className="mb-1.5 text-base font-bold text-navy-900 lg:text-lg">
              {project.physicalProgress}%
            </p>
            <ProgressBar value={project.physicalProgress} color="green" />
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="mb-2 flex items-center gap-2">
              <Target size={16} className="text-gray-500" />
              <span className="text-xs font-medium text-gray-500">Planned Progress</span>
            </div>
            <p className="mb-1.5 text-base font-bold text-navy-900 lg:text-lg">
              {project.plannedProgress}%
            </p>
            <ProgressBar value={project.plannedProgress} color="gray" />
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="mb-2 flex items-center gap-2">
              <Calendar size={16} className="text-navy-500" />
              <span className="text-xs font-medium text-gray-500">Expected Completion</span>
            </div>
            <p className="text-sm font-bold text-navy-900">
              {formatDate(project.expectedCompletion)}
            </p>
          </div>
        </div>
      </div>

      <div className="mb-8">
        <p className={`${sectionLabel} mb-3`}>Risk Assessment</p>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="rounded-xl border border-gray-200 bg-white p-6">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-gray-700">Overall Risk</h3>
              <ShieldAlert size={18} className="text-navy-300" />
            </div>
            <div className="my-5 flex justify-center">
              <RiskScore score={project.riskScore} size="lg" />
            </div>
            <p className="text-center text-sm text-gray-400">
              Score <span className="text-xl font-bold text-navy-900">{project.riskScore}</span> /
              100
            </p>
            <p
              className={`mb-3 mt-1 text-center text-xl font-bold tracking-wide ${getRiskColor(project.riskLevel)}`}
            >
              {project.riskLevel} RISK
            </p>
            <p className="mb-2 text-center text-xs text-gray-400">
              {report?.dataQuality
                ? `Evidence: ${report.dataQuality.availableFactors}/${report.dataQuality.totalFactors} factors · ${report.dataQuality.completeness}% complete`
                : project.riskConfidence !== undefined && project.riskConfidence !== null
                  ? `Model confidence: ${project.riskConfidence}% data completeness`
                  : 'Data-driven, rule-based assessment'}
            </p>
            {report?.riskLevelProvisional && (
              <p className="mb-5 text-center text-xs font-medium text-amber-600">
                Insufficient data: this risk level is provisional
              </p>
            )}

            {project.criticalBlocker && (
              <div className="mb-5 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3">
                <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-red-600" />
                <div>
                  <p className="text-xs font-semibold text-red-700">Critical blocker detected</p>
                  <ul className="mt-1 space-y-0.5 text-xs text-red-600">
                    {(
                      report?.criticalBlockerReasons || ['Unresolved critical issue']
                    ).map((r: string, i: number) => (
                      <li key={i}>• {r}</li>
                    ))}
                  </ul>
                </div>
              </div>
            )}

            <div className="space-y-4 border-t border-gray-100 pt-4">
              <div>
                <div className="mb-1.5 flex items-center justify-between">
                  <span className="text-sm text-gray-600">Cost Overrun Probability</span>
                  <span className="text-sm font-semibold text-gray-800">
                    {project.costOverrunProbability}%
                  </span>
                </div>
                <ProgressBar
                  value={project.costOverrunProbability}
                  color={getProgressColor(project.costOverrunProbability)}
                  size="sm"
                />
              </div>
              <div>
                <div className="mb-1.5 flex items-center justify-between">
                  <span className="text-sm text-gray-600">Schedule Delay Probability</span>
                  <span className="text-sm font-semibold text-gray-800">
                    {project.delayProbability}%
                  </span>
                </div>
                <ProgressBar
                  value={project.delayProbability}
                  color={
                    project.delayProbability > 80
                      ? 'red'
                      : getProgressColor(project.delayProbability)
                  }
                  size="sm"
                />
              </div>
              <div>
                <div className="mb-1.5 flex items-center justify-between">
                  <span className="text-sm text-gray-600">Implementation Risk</span>
                  <span className="text-sm font-semibold text-gray-800">
                    {project.implementationRisk}%
                  </span>
                </div>
                <ProgressBar
                  value={project.implementationRisk}
                  color={getProgressColor(project.implementationRisk)}
                  size="sm"
                />
              </div>
            </div>
          </div>

          <div className="space-y-6 lg:col-span-2">
            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <p className="text-xs font-semibold uppercase tracking-widest text-orange-600">
                Risk Analysis
              </p>
              <h3 className="mb-4 mt-1 text-base font-semibold text-navy-900 lg:text-lg">
                Why is this project at risk?
              </h3>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {(report?.explanations?.length ? report.explanations : project.riskFactors).map(
                  (factor: string, index: number) => (
                    <div
                      key={index}
                      className="flex items-start gap-3 rounded-lg bg-orange-50/60 p-3"
                    >
                      <AlertTriangle size={16} className="mt-0.5 shrink-0 text-orange-500" />
                      <span className="text-sm leading-relaxed text-gray-700">{factor}</span>
                    </div>
                  ),
                )}
              </div>

              {(report?.topRiskFactors?.length || 0) > 0 && (
                <div className="mt-4">
                  <p className="text-xs font-semibold uppercase tracking-widest text-red-600">
                    Top risk drivers
                  </p>
                  <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-3">
                    {report!.topRiskFactors.map((factor) => (
                      <div key={factor.key} className="rounded-lg border border-red-100 bg-red-50/60 p-3">
                        <p className="text-sm font-semibold text-navy-900">{factor.name}</p>
                        <p className="mt-0.5 text-xs font-medium text-red-700">
                          {factor.score}/100 · {factor.severity} · {Math.round(factor.probability * 100)}% probability
                        </p>
                        <p className="mt-1 text-xs leading-relaxed text-gray-600">{factor.explanation}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {report?.dataQuality && (
                <div className="mt-4 rounded-lg border border-blue-100 bg-blue-50/50 p-3">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold text-blue-700">Data completeness</span>
                    <span className="font-semibold text-blue-700">{report.dataQuality.completeness}%</span>
                  </div>
                  <ProgressBar
                    value={report.dataQuality.completeness}
                    color={getProgressColor(report.dataQuality.completeness)}
                    size="sm"
                  />
                  <p className="mt-1 text-xs text-gray-600">
                    {report.dataQuality.availableFactors}/{report.dataQuality.totalFactors} factors have evidence · weighted confidence {report.confidence}%
                  </p>
                </div>
              )}

              {(report?.interactions?.length || 0) > 0 && (
                <div className="mt-4 space-y-1.5">
                  <p className="text-xs font-semibold uppercase tracking-widest text-purple-600">
                    Risk interactions & compounding effects
                  </p>
                  {report!.interactions.map((it) => (
                    <div
                      key={it.key}
                      className="flex items-start gap-2 rounded-lg bg-purple-50/60 p-2.5 text-sm text-gray-700"
                    >
                      <span className="mt-0.5 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-purple-500" />
                      <span>
                        <span className="font-semibold">{it.name}</span> (+{it.penalty} risk points)
                        {' — '}
                        {it.explanation}
                        {it.triggeredConditions.length > 0 && (
                          <span className="mt-1 block text-xs text-gray-500">
                            Conditions: {it.triggeredConditions.join(', ')}
                          </span>
                        )}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {(report?.blockers?.length || 0) > 0 && (
                <div className="mt-4 space-y-1.5">
                  <p className="text-xs font-semibold uppercase tracking-widest text-red-600">
                    Blockers and minimum scores
                  </p>
                  {report!.blockers.map((blocker) => (
                    <div key={blocker.key} className="rounded-lg border border-red-100 bg-red-50/60 p-2.5">
                      <p className="text-xs font-semibold text-red-700">
                        {blocker.level} blocker · minimum score {blocker.minimumScore}/100
                      </p>
                      <p className="mt-0.5 text-xs text-gray-700">{blocker.explanation}</p>
                      <p className="mt-0.5 text-xs text-gray-600">Action: {blocker.recommendation}</p>
                    </div>
                  ))}
                </div>
              )}

              <div className="mt-4">
                <p className="text-xs font-semibold uppercase tracking-widest text-gray-500">
                  Factor scores
                </p>
                <div className="mt-2 space-y-2">
                  {(report?.factors || []).map((factor) => (
                    <details key={factor.key} className="rounded-lg border border-gray-200 bg-white p-3">
                      <summary className="flex cursor-pointer flex-wrap items-center justify-between gap-2 text-sm">
                        <span className="font-semibold text-navy-900">{factor.name}</span>
                        <span className="flex flex-wrap items-center gap-2 text-xs">
                          <span className="font-semibold text-gray-700">{factor.score}/100</span>
                          <span className="rounded-full bg-gray-100 px-1.5 py-0.5 text-[10px] font-semibold text-gray-600">
                            {factor.severity}
                          </span>
                          <span className={factor.dataAvailable ? 'text-green-600' : 'text-amber-600'}>
                            {factor.dataAvailable ? 'Evidence available' : 'Data missing'}
                          </span>
                        </span>
                      </summary>
                      <div className="mt-2 space-y-1 text-xs text-gray-600">
                        <p>
                          Probability {Math.round(factor.probability * 100)}% · Impact {Math.round(factor.impact * 100)}% · Weight {factor.weight}% · Contribution {factor.contribution}
                        </p>
                        <p>{factor.explanation}</p>
                        {factor.triggeredConditions.length > 0 && (
                          <p>Triggered conditions: {factor.triggeredConditions.join('; ')}</p>
                        )}
                      </div>
                    </details>
                  ))}
                </div>
              </div>

              {(report?.missingData?.length || 0) > 0 && (
                <div className="mt-4 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3">
                  <AlertTriangle size={15} className="mt-0.5 shrink-0 text-amber-500" />
                  <p className="text-xs text-amber-700">
                    Limited data for: {(report?.dataQuality?.missingFactorNames || report!.missingData).join(', ')}. Neutral
                    baselines applied - dry up these fields to raise confidence.
                  </p>
                </div>
              )}
            </div>

            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <p className="text-xs font-semibold uppercase tracking-widest text-blue-600">
                Recommended Interventions
              </p>
              <h3 className="mb-4 mt-1 text-base font-semibold text-navy-900 lg:text-lg">
                Recommended actions for the implementing agency
              </h3>
              <div className="space-y-3">
                {project.recommendations.map((rec: string, index: number) => (
                  <div key={index} className="flex items-start gap-3">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-navy-900 text-xs font-bold text-white">
                      {index + 1}
                    </span>
                    <span className="text-sm leading-relaxed text-gray-700">{rec}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="mb-8 rounded-xl border border-gray-200 bg-white p-5 lg:p-6">
        <p className="text-xs font-semibold uppercase tracking-widest text-blue-600">
          Cost Prediction
        </p>
        <h3 className="mb-2 mt-1 text-base font-semibold text-navy-900 lg:text-lg">
          Predicted final cost
        </h3>
        <p className="mb-5 text-xs text-gray-500 lg:text-sm">
          Projected cost trajectory based on current escalation trend.
        </p>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={projectCostData} margin={{ top: 10, right: 16, left: -8, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                <XAxis
                  dataKey="name"
                  tick={{ fontSize: 12, fill: '#6b7280' }}
                  axisLine={{ stroke: '#e5e7eb' }}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: '#6b7280' }}
                  axisLine={false}
                  tickLine={false}
                  width={70}
                  tickFormatter={(v) => `₹${(v / 100).toFixed(0)}Cr`}
                />
                <Tooltip
                  formatter={(value) => [formatCurrency(value as number), 'Amount']}
                  contentStyle={{
                    borderRadius: 8,
                    border: '1px solid #e5e7eb',
                    boxShadow: '0 4px 12px rgba(0,0,0,0.06)',
                    fontSize: 12,
                  }}
                  cursor={{ fill: '#f8fafc' }}
                />
                <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={64}>
                  {projectCostData.map((entry) => (
                    <Cell key={entry.name} fill={getBarColor(entry.name)} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="flex flex-col justify-center">
            <p className="text-sm text-gray-500">Predicted Cost Overrun</p>
            <p className="mt-1 text-4xl font-bold tracking-tight text-red-600">
              +{costOverrunPercent}%
            </p>
            <p className="mt-1 text-sm text-gray-500">from original estimate</p>
            <div className="mt-5 space-y-2.5 border-t border-gray-100 pt-4">
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-500">Original</span>
                <span className="font-medium text-gray-700">
                  {formatCurrency(project.originalCost)}
                </span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-500">Predicted Final</span>
                <span className="font-semibold text-red-600">{formatCurrency(predictedCost)}</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-500">Potential Overspend</span>
                <span className="font-semibold text-red-600">
                  {formatCurrency(predictedCost - project.originalCost)}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="mb-8 rounded-xl border border-gray-200 bg-white p-5 lg:p-6">
        <p className="text-xs font-semibold uppercase tracking-widest text-orange-600">
          Schedule Prediction
        </p>
        <h3 className="mb-2 mt-1 text-base font-semibold text-navy-900 lg:text-lg">
          Predicted completion vs original plan
        </h3>
        <p className="mb-5 text-xs text-gray-500 lg:text-sm">
          {buildStatus(project)} risk project with estimated{' '}
          {delayMonths > 0 ? `${delayMonths} month` : ''} expected schedule slippage.
        </p>
        <ProjectTimeline
          expectedCompletion={project.expectedCompletion}
          predictedCompletion={project.predictedCompletion}
          delayMonths={delayMonths}
          delayProbability={project.delayProbability}
          progressGap={
            project.plannedProgress !== null && project.physicalProgress !== null
              ? project.plannedProgress - project.physicalProgress
              : null
          }
        />
      </div>

      {/* ── AI Early-Warning Section ──────────────────────────────── */}
      <section className="mb-8 rounded-xl border border-purple-200 bg-gradient-to-br from-purple-50/60 to-white p-5 lg:p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-purple-600">
              AI Early Warning
            </p>
            <h3 className="mt-1 text-base font-semibold text-navy-900 lg:text-lg">
              AI-Enhanced Risk Intelligence
            </h3>
            <p className="mt-0.5 text-xs text-gray-500">
              Hybrid statistical + LLM early-warning analysis. Updated periodically.
            </p>
          </div>
          {aiInsights && (
            <button
              onClick={() => {
                if (!id) return;
                setAiLoading(true);
                getAiInsights(id, true)
                  .then(setAiInsights)
                  .catch(() => setAiError(true))
                  .finally(() => setAiLoading(false));
              }}
              className="inline-flex items-center gap-1.5 rounded-lg border border-purple-200 bg-white px-3 py-2 text-xs font-medium text-purple-700 transition-colors hover:bg-purple-50"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </button>
          )}
        </div>

        {aiLoading ? (
          <div className="flex items-center justify-center gap-2 py-10 text-sm text-gray-400">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-purple-300 border-t-purple-600" />
            Loading AI analysis...
          </div>
        ) : aiError || !aiInsights ? (
          <div className="rounded-lg border border-dashed border-gray-300 py-8 text-center">
            <Brain className="mx-auto mb-2 h-8 w-8 text-gray-300" />
            <p className="text-sm font-medium text-navy-900">AI analysis unavailable</p>
            <p className="mt-1 text-xs text-gray-500">No AI insights yet. Run analysis later or check the AI Health panel.</p>
          </div>
        ) : !aiInsights.ai_available ? (
          <div className="rounded-lg border border-dashed border-gray-300 py-8 text-center">
            <Brain className="mx-auto mb-2 h-8 w-8 text-gray-300" />
            <p className="text-sm font-medium text-navy-900">AI engine not configured</p>
            <p className="mt-1 text-xs text-gray-500">Deterministic predictions only. Configure an LLM provider for enhanced analysis.</p>
          </div>
        ) : (
          <>
            {/* Future Score + Current Score side-by-side */}
            {aiInsights.prediction && (
              <div className="mb-5 grid grid-cols-2 gap-4 sm:grid-cols-4">
                {[
                  {
                    label: 'Current Risk',
                    value: aiInsights.prediction.current_score ?? '—',
                    color: 'text-navy-900',
                    sub: 'Rule-based deterministic score',
                  },
                  {
                    label: 'Future Risk (90d)',
                    value: aiInsights.prediction.future_score ?? '—',
                    color:
                      (aiInsights.prediction.future_score ?? 0) >= 80
                        ? 'text-red-600'
                        : (aiInsights.prediction.future_score ?? 0) >= 60
                          ? 'text-orange-600'
                          : 'text-green-600',
                    sub: aiInsights.prediction.prediction_method,
                  },
                  {
                    label: 'Delay Risk',
                    value: `${Math.round(aiInsights.prediction.schedule_delay_probability * 100)}%`,
                    color:
                      aiInsights.prediction.schedule_delay_probability >= 0.7
                        ? 'text-red-600'
                        : aiInsights.prediction.schedule_delay_probability >= 0.4
                          ? 'text-orange-600'
                          : 'text-green-600',
                    sub: 'Within 90-day horizon',
                  },
                  {
                    label: 'Cost Overrun Risk',
                    value: `${Math.round(aiInsights.prediction.cost_overrun_probability * 100)}%`,
                    color:
                      aiInsights.prediction.cost_overrun_probability >= 0.7
                        ? 'text-red-600'
                        : aiInsights.prediction.cost_overrun_probability >= 0.4
                          ? 'text-orange-600'
                          : 'text-green-600',
                    sub: `${aiInsights.prediction.data_points_used} data points`,
                  },
                ].map((kpi) => (
                  <div
                    key={kpi.label}
                    className="rounded-lg border border-purple-100 bg-white p-3"
                  >
                    <p className="text-[11px] font-medium uppercase tracking-wider text-gray-500">
                      {kpi.label}
                    </p>
                    <p className={`mt-1 text-xl font-bold ${kpi.color}`}>{kpi.value}</p>
                    <p className="mt-0.5 text-[11px] text-gray-400">{kpi.sub}</p>
                  </div>
                ))}
              </div>
            )}

            {/* ML Risk Forecast - availability is reported from the backend,
                never inferred from the presence of a stale cached forecast. */}
            {aiInsights.prediction?.ml_forecast && mlStatus?.available ? (
              <MlRiskForecast forecast={aiInsights.prediction.ml_forecast} />
            ) : (
              <div className="mb-5 rounded-lg border border-dashed border-gray-300 bg-gray-50 px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-gray-200 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-gray-600">
                    ML Unavailable
                  </span>
                  <p className="text-xs text-gray-600">
                    The PARIKSHAN model is not loaded, so no ML forecast is shown.
                    {mlStatus?.error ? ` (${mlStatus.error})` : ''}
                  </p>
                </div>
                <p className="mt-1 text-[11px] text-gray-500">
                  Risk scores above are the deterministic Layer 1 engine and are unaffected.
                </p>
              </div>
            )}
            {aiInsights.explanation && (
              <div className="mb-5 rounded-lg border border-purple-100 bg-white p-4">
                <p className="text-xs font-semibold uppercase tracking-wider text-purple-600">Explanation</p>
                <p className="mt-2 text-sm leading-relaxed text-gray-700">
                  {aiInsights.explanation.summary}
                </p>
                {aiInsights.explanation.main_drivers.length > 0 && (
                  <div className="mt-3">
                    <p className="text-[11px] font-semibold text-gray-500">Main Drivers</p>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {aiInsights.explanation.main_drivers.map((d) => (
                        <span
                          key={d}
                          className="rounded-full bg-purple-100 px-2 py-0.5 text-[11px] font-medium text-purple-700"
                        >
                          {d}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Anomalies */}
            {aiInsights.anomalies.length > 0 && (
              <div className="mb-5">
                <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-orange-600">
                  Detected Anomalies ({aiInsights.anomalies.length})
                </p>
                <div className="space-y-2">
                  {aiInsights.anomalies.slice(0, 5).map((anomaly, i) => {
                    const sevColors: Record<string, string> = {
                      CRITICAL: 'border-red-300 bg-red-50',
                      HIGH: 'border-orange-300 bg-orange-50',
                      MEDIUM: 'border-amber-300 bg-amber-50',
                      LOW: 'border-gray-200 bg-gray-50',
                    };
                    const sevText: Record<string, string> = {
                      CRITICAL: 'text-red-700',
                      HIGH: 'text-orange-700',
                      MEDIUM: 'text-amber-700',
                      LOW: 'text-gray-600',
                    };
                    const Icon = anomaly.severity === 'CRITICAL' ? AlertOctagon : anomaly.severity === 'HIGH' ? AlertTriangle : AlertCircle;
                    return (
                      <div
                        key={anomaly.id || i}
                        className={`rounded-lg border p-3 ${sevColors[anomaly.severity] || sevColors.MEDIUM}`}
                      >
                        <div className="flex items-start gap-2">
                          <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${sevText[anomaly.severity] || sevText.MEDIUM}`} />
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-sm font-semibold text-navy-900">{anomaly.title}</span>
                              <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${sevText[anomaly.severity] || sevText.MEDIUM}`}>
                                {anomaly.severity}
                              </span>
                            </div>
                            <p className="mt-0.5 text-xs text-gray-600">{anomaly.description}</p>
                          </div>
                          {anomaly.id && !anomaly.resolved && (
                            <button
                              onClick={() => handleResolveAnomaly(anomaly.id)}
                              disabled={resolvingId === anomaly.id}
                              className="shrink-0 rounded border border-gray-300 bg-white px-2 py-1 text-[10px] font-semibold text-gray-600 transition-colors hover:bg-gray-50 disabled:opacity-50"
                            >
                              {resolvingId === anomaly.id ? 'Resolving...' : 'Resolve'}
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Emerging Risks */}
            {aiInsights.emerging_risks.length > 0 && (
              <div className="mb-5">
                <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-red-600">
                  Emerging Risks ({aiInsights.emerging_risks.length})
                </p>
                <div className="space-y-2">
                  {aiInsights.emerging_risks.slice(0, 5).map((er, i) => {
                    const sevColors: Record<string, string> = {
                      CRITICAL: 'border-red-300 bg-red-50',
                      HIGH: 'border-orange-300 bg-orange-50',
                      MEDIUM: 'border-amber-300 bg-amber-50',
                      LOW: 'border-gray-200 bg-gray-50',
                    };
                    const Icon = er.severity === 'CRITICAL' ? AlertOctagon : er.severity === 'HIGH' ? AlertTriangle : AlertCircle;
                    return (
                      <div
                        key={er.id || i}
                        className={`rounded-lg border p-3 ${sevColors[er.severity] || sevColors.MEDIUM}`}
                      >
                        <div className="flex items-start gap-2">
                          <Icon className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-sm font-semibold text-navy-900">{er.title}</span>
                              <span className="rounded-full bg-purple-100 px-1.5 py-0.5 text-[10px] font-medium text-purple-700">
                                {er.category.replace(/_/g, ' ')}
                              </span>
                              <span className="rounded-full bg-red-100 px-1.5 py-0.5 text-[10px] font-semibold text-red-700">
                                {er.severity}
                              </span>
                            </div>
                            <p className="mt-0.5 text-xs text-gray-600">{er.description}</p>
                            {er.recommended_actions.length > 0 && (
                              <div className="mt-2 rounded bg-white/60 px-2 py-1.5">
                                <p className="text-[10px] font-semibold text-gray-500">Suggested Actions</p>
                                <ul className="mt-0.5 space-y-0.5">
                                  {er.recommended_actions.map((a, j) => (
                                    <li key={j} className="text-xs text-gray-600">
                                      • {a}
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}
                          </div>
                          {er.id && er.status !== 'RESOLVED' && (
                            <button
                              onClick={() => handleResolveEmergingRisk(er.id)}
                              disabled={resolvingId === er.id}
                              className="shrink-0 rounded border border-gray-300 bg-white px-2 py-1 text-[10px] font-semibold text-gray-600 transition-colors hover:bg-gray-50 disabled:opacity-50"
                            >
                              {resolvingId === er.id ? 'Resolving...' : 'Resolve'}
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Predicted Events + Interventions */}
            {aiInsights.explanation &&
              (aiInsights.explanation.predicted_events.length > 0 ||
                aiInsights.explanation.recommended_interventions.length > 0) && (
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  {aiInsights.explanation.predicted_events.length > 0 && (
                    <div className="rounded-lg border border-purple-100 bg-white p-4">
                      <p className="text-[11px] font-semibold uppercase tracking-wider text-orange-600">
                        Predicted Events
                      </p>
                      <ul className="mt-2 space-y-1">
                        {aiInsights.explanation.predicted_events.map((e, i) => (
                          <li key={i} className="flex items-start gap-1.5 text-xs text-gray-700">
                            <TrendingDown className="mt-0.5 h-3 w-3 shrink-0 text-orange-500" />
                            {e}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {aiInsights.explanation.recommended_interventions.length > 0 && (
                    <div className="rounded-lg border border-purple-100 bg-white p-4">
                      <p className="text-[11px] font-semibold uppercase tracking-wider text-green-600">
                        Recommended Interventions
                      </p>
                      <ul className="mt-2 space-y-1">
                        {aiInsights.explanation.recommended_interventions.map((r, i) => (
                          <li key={i} className="flex items-start gap-1.5 text-xs text-gray-700">
                            <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-green-500" />
                            {r}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}

            {/* Footer */}
            <p className="mt-4 text-[11px] text-gray-400">
              Generated: {aiInsights.prediction ? new Date(aiInsights.prediction.generated_at).toLocaleString('en-GB') : '—'} ·
              Analysis: {aiInsights.analysis_kind} ·
              Method: {aiInsights.prediction?.prediction_method ?? '—'} ·
              Model: {aiInsights.prediction?.model_version ?? '—'}
            </p>
          </>
        )}
      </section>

      <section className="mb-8 rounded-xl border border-gray-200 bg-white p-5 lg:p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-blue-600">
              Project Updates
            </p>
            <h3 className="mt-1 text-base font-semibold text-navy-900 lg:text-lg">
              Notes and updates from the team
            </h3>
          </div>
          <button
            onClick={() => setNoteModal({ open: true, edit: null })}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-blue-500"
          >
            <Plus className="h-4 w-4" />
            Add Note / Update
          </button>
        </div>

        {noteToast && (
          <div className="mb-4 flex items-start gap-2 rounded-lg border border-green-200 bg-green-50 p-3">
            <MessageSquare className="mt-0.5 h-4 w-4 flex-shrink-0 text-green-600" />
            <p className="text-sm text-green-700">{noteToast}</p>
          </div>
        )}

        {updatesLoading ? (
          <LoadingState text="Loading updates..." />
        ) : updates.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-gray-300 py-10 text-center">
            <MessageSquare className="mb-3 h-8 w-8 text-gray-300" />
            <p className="text-sm font-medium text-navy-900">No updates yet</p>
            <p className="mt-1 text-sm text-gray-500">
              Be the first to add a note or update for this project.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {updates.map((u) => (
              <div key={u.id} className="rounded-xl border border-gray-200 p-4">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-navy-900">{u.userName}</span>
                    <span className="text-sm text-gray-500">&middot; {roleLabel(u.userRole)}</span>
                    <span
                      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${
                        UPDATE_TYPE_COLORS[u.updateType] || UPDATE_TYPE_COLORS.GENERAL
                      }`}
                    >
                      {UPDATE_TYPE_LABELS[u.updateType] || u.updateType}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-400">{formatUpdateTime(u.createdAt)}</span>
                    {canModifyUpdate(u) && (
                      <>
                        <button
                          onClick={() => setNoteModal({ open: true, edit: u })}
                          className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2 py-1 text-xs font-medium text-navy-900 hover:bg-gray-50"
                        >
                          <PenSquare className="h-3 w-3" />
                          Edit
                        </button>
                        <button
                          onClick={() => handleDeleteUpdate(u)}
                          className="inline-flex items-center gap-1 rounded-lg border border-red-200 bg-white px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50"
                        >
                          <Trash2 className="h-3 w-3" />
                          Delete
                        </button>
                      </>
                    )}
                  </div>
                </div>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-700">
                  {u.content}
                </p>
              </div>
            ))}
          </div>
        )}
      </section>

      <RiskFactorChart
        data={riskFactorChartData}
        title="Top risk factors"
        description="Factor scores ranked by the server risk engine; missing evidence is shown in grey."
      />

      {id && (
        <AddUpdateModal
          projectId={id}
          open={noteModal.open}
          initial={noteModal.edit}
          onClose={() => setNoteModal({ open: false, edit: null })}
          onSaved={() => {
            setNoteToast(noteModal.edit ? 'Update saved.' : 'Update added successfully.');
            fetchUpdates();
          }}
        />
      )}

      <AddProjectModal
        open={editProjectOpen}
        mode="edit"
        initial={project}
        onClose={() => setEditProjectOpen(false)}
        onCreated={(p) => {
          setProject(p);
          setEditProjectOpen(false);
        }}
      />
    </div>
  );
}

function MlRiskForecast({ forecast }: { forecast: AiMlForecast }) {
  const bandStyles: Record<string, string> = {
    Red: 'bg-red-100 text-red-700',
    Amber: 'bg-amber-100 text-amber-700',
    Green: 'bg-green-100 text-green-700',
  };
  const sevStyles: Record<string, string> = {
    High: 'border-red-200 bg-red-50 text-red-700',
    Medium: 'border-amber-200 bg-amber-50 text-amber-700',
    Low: 'border-green-200 bg-green-50 text-green-700',
  };

  const intervalBar = (p10: number, p50: number, p90: number) => {
    const hi = Math.max(p10, p50, p90, 0);
    const lo = Math.min(p10, p50, p90);
    const span = hi - lo || 1;
    const left = ((p10 - lo) / span) * 100;
    const width = ((p90 - p10) / span) * 100;
    const midPos = ((p50 - lo) / span) * 100;
    return { left, width, midPos };
  };

  const costRange = intervalBar(
    forecast.cost_prediction_p10,
    forecast.cost_prediction_p50,
    forecast.cost_prediction_p90
  );
  const timeRange = intervalBar(
    forecast.time_prediction_p10,
    forecast.time_prediction_p50,
    forecast.time_prediction_p90
  );

  return (
    <div className="mb-5 rounded-xl border border-indigo-200 bg-gradient-to-br from-indigo-50/60 to-white p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-widest text-indigo-600">
            ML Risk Forecast
          </p>
          <p className="mt-0.5 text-[11px] text-gray-500">
            Trained PARIKSHAN model (synthetic PAIMANA-style data) · {forecast.model_version}
          </p>
        </div>
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
            bandStyles[forecast.risk_band] || bandStyles.Amber
          }`}
        >
          ML {forecast.risk_band} · {Math.round(forecast.risk_score)}/100
        </span>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-indigo-100 bg-white p-3">
          <p className="text-[11px] font-medium uppercase tracking-wider text-gray-500">
            Cost Overrun Probability
          </p>
          <p className="mt-1 text-xl font-bold text-navy-900">
            {Math.round(forecast.cost_overrun_probability * 100)}%
          </p>
          <p className="mt-0.5 text-[11px] text-gray-400">
            Est. overrun {forecast.expected_cost_overrun_pct.toFixed(0)}%
          </p>
        </div>
        <div className="rounded-lg border border-indigo-100 bg-white p-3">
          <p className="text-[11px] font-medium uppercase tracking-wider text-gray-500">
            Schedule Overrun Probability
          </p>
          <p className="mt-1 text-xl font-bold text-navy-900">
            {Math.round(forecast.time_overrun_probability * 100)}%
          </p>
          <p className="mt-0.5 text-[11px] text-gray-400">
            Est. delay {forecast.expected_time_overrun_months.toFixed(1)} months
          </p>
        </div>
        <div className="rounded-lg border border-indigo-100 bg-white p-3">
          <p className="text-[11px] font-medium uppercase tracking-wider text-gray-500">
            Severe Overrun Probability
          </p>
          <p className="mt-1 text-xl font-bold text-navy-900">
            {Math.round(forecast.severe_overrun_probability * 100)}%
          </p>
          <p className="mt-0.5 text-[11px] text-gray-400">
            Combined cost & schedule
          </p>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-indigo-100 bg-white p-3">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-500">
            Cost Overrun Interval (P10-P50-P90)
          </p>
          <div className="relative mt-3 h-1.5 rounded-full bg-indigo-100">
            <div
              className="absolute top-0 h-1.5 rounded-full bg-indigo-400"
              style={{ left: `${costRange.left}%`, width: `${costRange.width}%` }}
            />
            <div
              className="absolute top-[-3px] h-3 w-0.5 rounded bg-indigo-700"
              style={{ left: `${costRange.midPos}%` }}
            />
          </div>
          <div className="mt-1.5 flex justify-between text-[11px] text-gray-500">
            <span>P10 {forecast.cost_prediction_p10.toFixed(0)}%</span>
            <span>P50 {forecast.cost_prediction_p50.toFixed(0)}%</span>
            <span>P90 {forecast.cost_prediction_p90.toFixed(0)}%</span>
          </div>
        </div>
        <div className="rounded-lg border border-indigo-100 bg-white p-3">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-500">
            Schedule Interval (P10-P50-P90 months)
          </p>
          <div className="relative mt-3 h-1.5 rounded-full bg-indigo-100">
            <div
              className="absolute top-0 h-1.5 rounded-full bg-indigo-400"
              style={{ left: `${timeRange.left}%`, width: `${timeRange.width}%` }}
            />
            <div
              className="absolute top-[-3px] h-3 w-0.5 rounded bg-indigo-700"
              style={{ left: `${timeRange.midPos}%` }}
            />
          </div>
          <div className="mt-1.5 flex justify-between text-[11px] text-gray-500">
            <span>P10 {forecast.time_prediction_p10.toFixed(1)}m</span>
            <span>P50 {forecast.time_prediction_p50.toFixed(1)}m</span>
            <span>P90 {forecast.time_prediction_p90.toFixed(1)}m</span>
          </div>
        </div>
      </div>

      {forecast.top_drivers.length > 0 && (
        <div className="mt-3">
          <p className="text-[11px] font-semibold text-gray-500">Top Risk Drivers</p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {forecast.top_drivers.map((d) => (
              <span
                key={d}
                className="rounded-full bg-indigo-100 px-2 py-0.5 text-[11px] font-medium text-indigo-700"
              >
                {d.replace(/_/g, ' ')}
              </span>
            ))}
          </div>
        </div>
      )}

      {forecast.early_warnings.length > 0 && (
        <div className="mt-3">
          <p className="text-[11px] font-semibold text-gray-500">Early Warnings</p>
          <div className="mt-1 space-y-1.5">
            {forecast.early_warnings.map((ew) => (
              <div
                key={ew.rule_id}
                className={`rounded-md border px-2 py-1.5 text-xs ${
                  sevStyles[ew.severity] || sevStyles.Medium
                }`}
              >
                <span className="mr-1.5 font-mono font-semibold">{ew.rule_id}</span>
                {ew.description}
              </div>
            ))}
          </div>
        </div>
      )}

      {forecast.recommended_actions.length > 0 && (
        <div className="mt-3">
          <p className="text-[11px] font-semibold text-gray-500">Recommended Attention</p>
          <ul className="mt-1 space-y-0.5">
            {forecast.recommended_actions.map((a, i) => (
              <li key={i} className="text-xs text-gray-700">
                • {a}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
