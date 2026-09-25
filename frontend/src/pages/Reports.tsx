import { useState, useEffect } from 'react';
import { FileText, Download, BarChart3, AlertTriangle, PieChart } from 'lucide-react';
import { getProjects } from '../services/api';
import { SearchBar } from '../components/ui/SearchBar';
import { FilterBar, FilterSelect } from '../components/ui/FilterBar';
import { LoadingState } from '../components/ui/LoadingState';
import { useI18n } from '../i18n';

const reportTypes = [
  {
    titleKey: 'reports.reportType.project.title',
    descKey: 'reports.reportType.project.desc',
    icon: FileText,
    iconBg: 'bg-blue-50',
    iconColor: 'text-blue-600',
  },
  {
    titleKey: 'reports.reportType.portfolio.title',
    descKey: 'reports.reportType.portfolio.desc',
    icon: PieChart,
    iconBg: 'bg-green-50',
    iconColor: 'text-green-600',
  },
  {
    titleKey: 'reports.reportType.sector.title',
    descKey: 'reports.reportType.sector.desc',
    icon: BarChart3,
    iconBg: 'bg-orange-50',
    iconColor: 'text-orange-600',
  },
  {
    titleKey: 'reports.reportType.early.title',
    descKey: 'reports.reportType.early.desc',
    icon: AlertTriangle,
    iconBg: 'bg-red-50',
    iconColor: 'text-red-600',
  },
] as const;

export default function Reports() {
  const { t, riskLabel } = useI18n();
  const [projects, setProjects] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [sectorFilter, setSectorFilter] = useState('all');
  const [riskFilter, setRiskFilter] = useState('all');
  const [dateFilter, setDateFilter] = useState('');
  const [viewingReport, setViewingReport] = useState<string | null>(null);

  useEffect(() => {
    getProjects()
      .then(setProjects)
      .catch((err: any) => setError(err?.message || t('reports.failed')))
      .finally(() => setLoading(false));
  }, []);

  const handleExport = (title: string) => {
    const createdAt = new Date().toLocaleDateString('en-GB', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    });
    const highRiskCount = projects.filter(
      (p) => p.riskLevel === 'HIGH' || p.riskLevel === 'CRITICAL',
    ).length;
    const totalCost = projects.reduce((sum, p) => sum + p.currentCost, 0);

    const lines = [
      'SANKALP - AI-POWERED INFRASTRUCTURE RISK INTELLIGENCE',
      '====================================================',
      `Report: ${title}`,
      t('reports.generated', { date: createdAt }),
      `Filters: Sector=${sectorFilter === 'all' ? t('common.all') : sectorFilter} | Risk=${riskFilter === 'all' ? t('common.all') : riskFilter} | Date=${dateFilter || t('common.all')}`,
      '',
      'PORTFOLIO SUMMARY',
      `  ${t('admin.totalProjects')}: ${projects.length}`,
      `  High/Critical Risk Projects: ${highRiskCount}`,
      `  Total Current Cost: Rs. ${totalCost.toLocaleString('en-IN')} Cr`,
      '',
      'TOP 10 HIGH-RISK PROJECTS',
      '  ' + '-'.repeat(70),
      ...projects
        .filter((p) => p.riskLevel === 'HIGH' || p.riskLevel === 'CRITICAL')
        .sort((a, b) => b.riskScore - a.riskScore)
        .slice(0, 10)
        .map((p) => {
          const overrun = (((p.currentCost - p.originalCost) / p.originalCost) * 100).toFixed(1);
          return `  ${p.name} (${p.state})\n    Risk: ${p.riskScore}/100 ${p.riskLevel} | Progress: ${p.physicalProgress}% | Cost Overrun: ${overrun}% | Delay Prob: ${p.delayProbability}%`;
        }),
      '',
      'End of report. For more details, contact the monitoring committee.',
    ].join('\n');

    const blob = new Blob([lines], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${title.toLowerCase().replace(/\s+/g, '-')}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  if (loading) {
    return (
      <div className="mx-auto min-w-0 max-w-[1200px]">
        <div className="mb-6">
          <h1 className="text-2xl font-bold tracking-tight text-navy-900 lg:text-3xl">
            {t('reports.title')}
          </h1>
          <p className="mt-1 text-sm text-gray-500 lg:text-base">
            {t('reports.subtitle')}
          </p>
        </div>
        <LoadingState text={t('reports.loading')} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto min-w-0 max-w-[1200px]">
        <div className="mb-6">
          <h1 className="text-2xl font-bold tracking-tight text-navy-900 lg:text-3xl">
            {t('reports.title')}
          </h1>
          <p className="mt-1 text-sm text-gray-500 lg:text-base">
            {t('reports.subtitle')}
          </p>
        </div>
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
          <p className="text-sm font-medium text-red-600">{error}</p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-3 text-sm font-medium text-red-700 underline hover:text-red-800"
          >
            {t('common.retry')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto min-w-0 max-w-[1200px]">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight text-navy-900 lg:text-3xl">
          {t('reports.title')}
        </h1>
        <p className="mt-1 text-sm text-gray-500 lg:text-base">
          {t('reports.subtitle')}
        </p>
      </div>

      <div className="mb-6 rounded-xl border border-gray-200 bg-white p-4 lg:p-5">
        <FilterBar>
          <div className="w-full sm:w-72">
            <SearchBar value={search} onChange={setSearch} placeholder={t('reports.searchPlaceholder')} />
          </div>
          <FilterSelect
            label={t('reports.filterSector')}
            value={sectorFilter}
            onChange={setSectorFilter}
            options={[
              { value: 'all', label: t('projects.allSectors') },
              { value: 'Transport', label: 'Transport' },
              { value: 'Energy', label: 'Energy' },
              { value: 'Water', label: 'Water' },
              { value: 'Mining', label: 'Mining' },
              { value: 'Communication', label: 'Communication' },
              { value: 'Social Infrastructure', label: 'Social Infrastructure' },
            ]}
          />
          <FilterSelect
            label={t('reports.filterRiskLevel')}
            value={riskFilter}
            onChange={setRiskFilter}
            options={[
              { value: 'all', label: t('reports.allLevels') },
              { value: 'LOW', label: riskLabel('LOW') },
              { value: 'MEDIUM', label: riskLabel('MEDIUM') },
              { value: 'HIGH', label: riskLabel('HIGH') },
              { value: 'CRITICAL', label: riskLabel('CRITICAL') },
            ]}
          />
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-500">{t('reports.dateRange')}</label>
            <input
              type="text"
              value={dateFilter}
              onChange={(e) => setDateFilter(e.target.value)}
              placeholder={t('reports.datePlaceholder')}
              className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
            />
          </div>
        </FilterBar>
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        {reportTypes.map((report) => {
          const Icon = report.icon;
          const title = t(report.titleKey);
          const desc = t(report.descKey);
          return (
            <div
              key={report.titleKey}
              className="rounded-xl border border-gray-200 bg-white p-5 lg:p-6"
            >
              <div className="flex items-start gap-4">
                <div className={`rounded-lg p-3 ${report.iconBg}`}>
                  <Icon className={`h-6 w-6 ${report.iconColor}`} />
                </div>
                <div className="flex-1">
                  <h3 className="text-lg font-semibold text-navy-900">{title}</h3>
                  <p className="text-sm text-gray-500 mt-1">{desc}</p>
                  <div className="flex gap-3 mt-4">
                    <button
                      type="button"
                      onClick={() => setViewingReport(title)}
                      className="bg-blue-600 text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-blue-700 transition-colors"
                    >
                      {t('reports.viewReport')}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleExport(title)}
                      className="border border-gray-200 rounded-lg px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 transition-colors inline-flex items-center gap-2"
                    >
                      <Download className="h-4 w-4" />
                      {t('reports.export')}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {viewingReport && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-navy-950/50 p-4"
          onClick={() => setViewingReport(null)}
        >
          <div
            className="max-h-[85vh] w-full max-w-3xl overflow-y-auto rounded-xl bg-white shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="border-b border-gray-200 bg-navy-900 px-6 py-5 sm:px-8">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-navy-300">
                    {t('reports.officialHeader')}
                  </p>
                  <h3 className="mt-1.5 text-lg font-bold text-white sm:text-xl">
                    {viewingReport}
                  </h3>
                  <p className="mt-0.5 text-xs text-navy-300">
                    {t('reports.generated', {
                      date: new Date().toLocaleDateString('en-GB', {
                        day: 'numeric',
                        month: 'long',
                        year: 'numeric',
                      }),
                    })}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setViewingReport(null)}
                  className="rounded-lg bg-white/10 px-3 py-1.5 text-sm text-white hover:bg-white/20"
                >
                  {t('reports.close')}
                </button>
              </div>
            </div>
            <div className="p-6 sm:p-8">
              <div className="mb-6 rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm leading-relaxed text-gray-600">
                <span className="font-semibold text-navy-900">{t('reports.execSummary')}</span>{' '}
                {t('reports.execSummaryBody')}
              </div>
              <div className="space-y-3">
                {projects
                  .filter((p) => p.riskLevel === 'HIGH' || p.riskLevel === 'CRITICAL')
                  .sort((a, b) => b.riskScore - a.riskScore)
                  .slice(0, 8)
                  .map((p, i) => {
                    const overrun = (
                      ((p.currentCost - p.originalCost) / p.originalCost) *
                      100
                    ).toFixed(1);
                    return (
                      <div
                        key={p.id}
                        className="flex items-start justify-between gap-4 rounded-lg border border-gray-100 p-4"
                      >
                        <div className="min-w-0">
                          <p className="text-sm font-semibold text-navy-900">
                            <span className="mr-2 inline-flex h-5 w-5 items-center justify-center rounded-full bg-gray-100 text-xs font-bold text-gray-600">
                              {i + 1}
                            </span>
                            {p.name}
                          </p>
                          <p className="mt-1 truncate text-xs text-gray-500">
                            {p.state} · {p.sector} · {p.ministry}
                          </p>
                          <p className="mt-1.5 text-xs text-gray-600">
                            Progress: {p.physicalProgress}% · Cost Overrun: {overrun}% · Delay
                            Probability: {p.delayProbability}%
                          </p>
                        </div>
                        <div className="shrink-0 text-right">
                          <p
                            className={`text-lg font-bold ${p.riskLevel === 'CRITICAL' ? 'text-red-600' : 'text-orange-600'}`}
                          >
                            {p.riskScore}/100
                          </p>
                          <p className="text-xs font-semibold text-gray-500">{riskLabel(p.riskLevel)}</p>
                        </div>
                      </div>
                    );
                  })}
              </div>
              <div className="mt-6 border-t border-gray-100 pt-4 text-center text-xs text-gray-400">
                GovRisk · AI-Powered Infrastructure Risk Intelligence · For official monitoring use
              </div>
            </div>
            <div className="flex justify-end border-t border-gray-200 px-6 py-4 sm:px-8">
              <button
                type="button"
                onClick={() => handleExport(viewingReport)}
                className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
              >
                <Download className="h-4 w-4" />
                {t('reports.exportReport')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
