import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  BarChart3,
  AlertTriangle,
  Clock,
  DollarSign,
  FolderOpen,
  TrendingUp,
  ArrowRight,
  AlertCircle,
} from 'lucide-react';
import { getDashboard, getProjects, getAnalytics, getAiInsights } from '../services/api';
import type { AiInsights } from '../services/api';
import type { DashboardResponse, Project } from '../types';
import { KpiCard } from '../components/ui/KpiCard';
import { RiskBadge } from '../components/ui/RiskBadge';
import { RiskScore } from '../components/ui/RiskScore';
import { ProgressBar } from '../components/ui/ProgressBar';
import { RiskChart } from '../components/charts/RiskChart';
import { RiskTrendChart } from '../components/charts/RiskTrendChart';
import { LoadingState } from '../components/ui/LoadingState';
import { useI18n } from '../i18n';

const sectorFilters = [
  'All Sectors',
  'Transport',
  'Energy',
  'Water',
  'Communication',
  'Social Infrastructure',
];

function getCostOverrunColor(overrun: number) {
  if (overrun > 15) return 'text-red-600';
  if (overrun > 10) return 'text-orange-600';
  return 'text-gray-600';
}

function getDelayColor(probability: number) {
  if (probability >= 85) return 'text-red-600';
  if (probability >= 70) return 'text-orange-600';
  return 'text-gray-600';
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { t } = useI18n();
  const [activeSector, setActiveSector] = useState('All Sectors');
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [analytics, setAnalytics] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [aiMap, setAiMap] = useState<Record<string, AiInsights>>({});
  const [aiLoading, setAiLoading] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const [dash, proj, an] = await Promise.all([getDashboard(), getProjects(), getAnalytics()]);
        setDashboard(dash);
        setProjects(proj);
        setAnalytics(an);
      } catch (err: any) {
        setError(err.message || t('dashboard.failed'));
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  // Fetch AI insights for top-risk projects (up to 4)
  useEffect(() => {
    if (!projects.length) return;
    const topProjects = [...projects]
      .sort((a, b) => b.riskScore - a.riskScore)
      .slice(0, 4);
    setAiLoading(true);
    Promise.allSettled(
      topProjects.map((p) =>
        getAiInsights(p.id, false).then((ins) => ({ id: p.id, ins }))
      )
    )
      .then((results) => {
        const map: Record<string, AiInsights> = {};
        results.forEach((r) => {
          if (r.status === 'fulfilled') map[r.value.id] = r.value.ins;
        });
        setAiMap(map);
      })
      .finally(() => setAiLoading(false));
  }, [projects]);

  if (loading || !dashboard) {
    return (
      <div className="min-w-0">
        <div className="mb-6">
          <h1 className="text-2xl font-bold tracking-tight text-navy-900 lg:text-3xl">
            {t('dashboard.title')}
          </h1>
          <p className="mt-1 text-sm text-gray-600 lg:text-base">{t('dashboard.subtitle')}</p>
        </div>
        <LoadingState text={t('dashboard.loading')} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-w-0">
        <div className="mb-6">
          <h1 className="text-2xl font-bold tracking-tight text-navy-900 lg:text-3xl">
            {t('dashboard.title')}
          </h1>
          <p className="mt-1 text-sm text-gray-600 lg:text-base">{t('dashboard.subtitle')}</p>
        </div>
        <div className="flex flex-col items-center py-12">
          <AlertTriangle className="h-10 w-10 text-red-500" />
          <p className="mt-3 text-sm font-medium text-red-600">{error}</p>
          <button
            onClick={() => window.location.reload()}
            className="mt-4 rounded-lg bg-navy-900 px-4 py-2 text-sm font-medium text-white hover:bg-navy-800"
          >
            {t('common.retry')}
          </button>
        </div>
      </div>
    );
  }

  const highRiskProjects = dashboard.highRiskTable || [];

  const riskDistribution = [
    { name: t('risk.LOW'), value: dashboard.riskDistribution?.low ?? 0, color: '#22c55e' },
    { name: t('risk.MEDIUM'), value: dashboard.riskDistribution?.medium ?? 0, color: '#eab308' },
    { name: t('risk.HIGH'), value: dashboard.riskDistribution?.high ?? 0, color: '#f97316' },
    { name: t('risk.CRITICAL'), value: dashboard.riskDistribution?.critical ?? 0, color: '#ef4444' },
  ];

  const formatCurrency = (value: number) => {
    if (value >= 100) {
      return `₹${(value / 100).toFixed(1)} Lakh Cr`;
    }
    return `₹${value.toFixed(1)} Cr`;
  };

  const secondaryKpis = [
    {
      title: t('kpi.portfolioValue'),
      value: formatCurrency(dashboard.portfolioValue ?? 0),
      subtitle: t('kpi.portfolioValueSub'),
      icon: <TrendingUp className="h-5 w-5 text-blue-600" />,
    },
    {
      title: t('kpi.revisedValue'),
      value: formatCurrency(dashboard.revisedValue ?? 0),
      subtitle: t('kpi.revisedValueSub'),
      icon: <BarChart3 className="h-5 w-5 text-blue-600" />,
    },
  ];

  return (
    <div className="min-w-0">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight text-navy-900 lg:text-3xl">
          {t('dashboard.title')}
        </h1>
        <p className="mt-1 text-sm text-gray-600 lg:text-base">{t('dashboard.subtitle')}</p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          title={t('kpi.totalProjects')}
          value={String(dashboard.totalProjects ?? 0)}
          subtitle={t('kpi.totalProjectsSub')}
          icon={<FolderOpen className="h-5 w-5 text-blue-600" />}
        />
        <KpiCard
          title={t('kpi.highRisk')}
          value={String(dashboard.highRiskProjects ?? 0)}
          subtitle={t('kpi.highRiskSub')}
          icon={<AlertTriangle className="h-5 w-5 text-red-600" />}
          trend={{ value: 4.2, isPositive: false }}
        />
        <KpiCard
          title={t('kpi.scheduleRisk')}
          value={String(dashboard.scheduleRiskCount ?? 0)}
          subtitle={t('kpi.scheduleRiskSub')}
          icon={<Clock className="h-5 w-5 text-orange-600" />}
        />
        <KpiCard
          title={t('kpi.costRisk')}
          value={String(dashboard.costRiskCount ?? 0)}
          subtitle={t('kpi.costRiskSub')}
          icon={<DollarSign className="h-5 w-5 text-yellow-600" />}
        />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {secondaryKpis.map((kpi) => (
          <div
            key={kpi.title}
            className="flex items-center justify-between rounded-xl border border-gray-200 bg-gradient-to-r from-navy-50 to-white px-5 py-4"
          >
            <div className="min-w-0">
              <p className="text-sm font-medium text-gray-500">{kpi.title}</p>
              <p className="mt-1 text-lg font-bold tracking-tight text-navy-900 lg:text-xl">
                {kpi.value}
              </p>
              <p className="mt-0.5 text-xs text-gray-400">{kpi.subtitle}</p>
            </div>
            <div className="shrink-0 rounded-lg bg-white p-2.5 ring-1 ring-inset ring-navy-100">
              {kpi.icon}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-8 overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 px-5 py-4 lg:px-6">
          <div>
            <h3 className="text-base font-semibold text-navy-900 lg:text-lg">
              {t('dashboard.attentionTitle')}
            </h3>
            <p className="mt-0.5 text-xs text-gray-500 lg:text-sm">{t('dashboard.attentionSub')}</p>
          </div>
          <button
            onClick={() => navigate('/projects')}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3.5 py-2 text-sm font-medium text-navy-900 transition-colors hover:bg-gray-50 hover:text-blue-700"
          >
            {t('dashboard.viewAll')}
            <ArrowRight size={14} />
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1120px] text-left text-sm">
            <thead>
              <tr className="bg-gray-50 text-xs uppercase tracking-wider text-gray-500">
                <th className="px-4 py-3 font-semibold lg:px-6">{t('table.project')}</th>
                <th className="px-4 py-3 font-semibold">{t('table.ministry')}</th>
                <th className="px-4 py-3 font-semibold">{t('table.sector')}</th>
                <th className="px-4 py-3 font-semibold">{t('table.state')}</th>
                <th className="px-4 py-3 font-semibold">{t('table.progress')}</th>
                <th className="px-4 py-3 font-semibold">{t('table.costOverrun')}</th>
                <th className="px-4 py-3 font-semibold">{t('table.delayProb')}</th>
                <th className="px-4 py-3 font-semibold">{t('table.riskScore')}</th>
                <th className="px-4 py-3 font-semibold">{t('table.topDriver')}</th>
                <th className="px-4 py-3 font-semibold">{t('table.dataQuality')}</th>
                <th className="px-4 py-3 font-semibold">{t('table.status')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {highRiskProjects.map((project: Project) => {
                const costOverrun =
                  ((project.currentCost - project.originalCost) / project.originalCost) * 100;
                const topFactor = project.riskReport?.topRiskFactors?.[0];
                const dataQuality = project.riskReport?.dataQuality;
                return (
                  <tr
                    key={project.id}
                    className="cursor-pointer transition-colors hover:bg-blue-50/40"
                    onClick={() => navigate(`/projects/${project.id}`)}
                  >
                    <td className="max-w-[240px] px-4 py-3 lg:px-6">
                      <div className="truncate font-medium text-navy-900" title={project.name}>
                        {project.name}
                      </div>
                      <div className="text-xs text-gray-400">{project.id}</div>
                    </td>
                    <td
                      className="max-w-[180px] truncate px-4 py-3 text-gray-600"
                      title={project.ministry}
                    >
                      {project.ministry}
                    </td>
                    <td className="px-4 py-3 text-gray-700">{project.sector}</td>
                    <td className="px-4 py-3 text-gray-700">{project.state}</td>
                    <td className="min-w-[110px] px-4 py-3">
                      <ProgressBar value={project.physicalProgress} showLabel />
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-sm font-semibold ${getCostOverrunColor(costOverrun)}`}>
                        {costOverrun.toFixed(1)}%
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`text-sm font-semibold ${getDelayColor(project.delayProbability)}`}
                      >
                        {project.delayProbability}%
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <RiskScore score={project.riskScore} size="sm" />
                    </td>
                    <td className="max-w-[200px] px-4 py-3 text-xs text-gray-700">
                      {topFactor ? `${topFactor.name} (${topFactor.score}/100)` : '—'}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-700">
                      {dataQuality ? `${dataQuality.completeness}% complete` : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <RiskBadge level={project.riskLevel} size="sm" />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── AI Early-Warning Section ───────────────────────────────── */}
      {aiLoading ? (
        <div className="mt-8 rounded-xl border border-purple-200 bg-gradient-to-br from-purple-50/60 to-white p-5">
          <div className="flex items-center gap-2 text-sm text-gray-400">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-purple-300 border-t-purple-600" />
            {t('dashboard.loadingAi')}
          </div>
        </div>
      ) : Object.keys(aiMap).length > 0 ? (
        <div className="mt-8 rounded-xl border border-purple-200 bg-gradient-to-br from-purple-50/60 to-white p-5 lg:p-6">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-widest text-purple-600">
                {t('dashboard.aiEarlyWarnings')}
              </p>
              <h3 className="mt-1 text-base font-semibold text-navy-900 lg:text-lg">
                {t('dashboard.aiEnhanced')}
              </h3>
              <p className="mt-0.5 text-xs text-gray-500">
                {t('dashboard.aiSub')}
              </p>
            </div>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {projects
              .filter((p) => aiMap[p.id])
              .sort((a, b) => b.riskScore - a.riskScore)
              .slice(0, 4)
              .map((project) => {
                const ai = aiMap[project.id];
                if (!ai) return null;
                const pred = ai.prediction;
                const topEr = ai.emerging_risks[0];
                const topAnomaly = ai.anomalies[0];
                const futureScore = pred?.future_score ?? project.riskScore;
                return (
                  <div
                    key={project.id}
                    className="cursor-pointer rounded-lg border border-purple-100 bg-white p-4 transition-colors hover:border-purple-300 hover:shadow-sm"
                    onClick={() => navigate(`/projects/${project.id}`)}
                  >
                    <div className="mb-3 flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-navy-900">{project.name}</p>
                        <p className="mt-0.5 text-xs text-gray-500">
                          {t('dashboard.sectorJoined', { id: project.id, sector: project.sector })}
                        </p>
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="text-[10px] font-medium uppercase tracking-wider text-gray-400">{t('dashboard.futureRisk')}</p>
                        <p
                          className={`text-xl font-bold ${
                            futureScore >= 80
                              ? 'text-red-600'
                              : futureScore >= 60
                                ? 'text-orange-600'
                                : futureScore >= 40
                                  ? 'text-amber-600'
                                  : 'text-green-600'
                          }`}
                        >
                          {futureScore}
                        </p>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-3 text-xs text-gray-500">
                      {pred && (
                        <span className="inline-flex items-center gap-1">
                          <Clock className="h-3 w-3 text-orange-400" />
                          {Math.round(pred.schedule_delay_probability * 100)}% {t('dashboard.delayRiskShort')}
                        </span>
                      )}
                      {pred && (
                        <span className="inline-flex items-center gap-1">
                          <DollarSign className="h-3 w-3 text-yellow-400" />
                          {Math.round(pred.cost_overrun_probability * 100)}% {t('dashboard.costRiskShort')}
                        </span>
                      )}
                      {ai.anomalies.length > 0 && (
                        <span className="inline-flex items-center gap-1 text-orange-600">
                          <AlertCircle className="h-3 w-3" />
                          {ai.anomalies.length} anomal{ai.anomalies.length === 1 ? 'y' : 'ies'}
                        </span>
                      )}
                    </div>
                    {topEr && (
                      <div className="mt-2.5 rounded bg-purple-50/80 px-2.5 py-1.5">
                        <p className="text-[11px] font-medium text-purple-700">
                          🚨 {topEr.title}
                          <span className="ml-1 text-[10px] text-purple-500">
                            ({topEr.severity})
                          </span>
                        </p>
                      </div>
                    )}
                    {!topEr && topAnomaly && (
                      <div className="mt-2.5 rounded bg-orange-50/80 px-2.5 py-1.5">
                        <p className="text-[11px] font-medium text-orange-700">
                          ⚠ {topAnomaly.title}
                          <span className="ml-1 text-[10px] text-orange-500">
                            ({topAnomaly.severity})
                          </span>
                        </p>
                      </div>
                    )}
                  </div>
                );
              })}
          </div>
        </div>
      ) : null}

      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <RiskChart
          title={t('chart.riskDistribution')}
          description={t('chart.riskDistributionSub')}
          data={riskDistribution}
        />
        <RiskTrendChart
          title={t('chart.riskTrend')}
          description={t('chart.riskTrendSub')}
          data={analytics?.riskTrends ?? []}
          filters={sectorFilters}
          activeFilter={activeSector}
          onFilterChange={setActiveSector}
        />
      </div>

      <div className="mt-8 flex flex-wrap items-center justify-between gap-4 rounded-2xl bg-white px-6 py-3 shadow-md">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-navy-900">{t('dashboard.analyticsCta')}</p>
          <p className="mt-0.5 text-xs text-gray-600 lg:text-sm">
            {t('dashboard.analyticsCtaSub')}
          </p>
        </div>
        <button
          onClick={() => navigate('/analytics')}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-xl bg-navy-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-navy-800"
        >
          {t('dashboard.openAnalytics')}
          <ArrowRight size={14} />
        </button>
      </div>
    </div>
  );
}
