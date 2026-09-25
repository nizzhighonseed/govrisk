import { useState, useEffect } from 'react';
import { getAlerts } from '../services/api';
import { AlertCard } from '../components/alerts/AlertCard';
import { EmptyState } from '../components/ui/EmptyState';
import { LoadingState } from '../components/ui/LoadingState';
import { BellOff } from 'lucide-react';
import { useI18n, TranslationKey } from '../i18n';

const tabs = ['All', 'Critical', 'High', 'Medium', 'Resolved'] as const;

type Tab = (typeof tabs)[number];

const tabLabels: Record<Tab, TranslationKey> = {
  All: 'alerts.all',
  Critical: 'alerts.critical',
  High: 'alerts.high',
  Medium: 'alerts.medium',
  Resolved: 'alerts.resolved',
};

export default function Alerts() {
  const { t } = useI18n();
  const [alerts, setAlerts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>('All');

  useEffect(() => {
    getAlerts()
      .then(setAlerts)
      .catch((err) => setError(err.message ?? t('alerts.failed')))
      .finally(() => setLoading(false));
  }, []);

  const tabCounts: Record<Tab, number> = {
    All: alerts.length,
    Critical: alerts.filter((a) => a.severity === 'CRITICAL').length,
    High: alerts.filter((a) => a.severity === 'HIGH').length,
    Medium: alerts.filter((a) => a.severity === 'MEDIUM').length,
    Resolved: alerts.filter((a) => a.severity === 'RESOLVED').length,
  };

  const filteredAlerts =
    activeTab === 'All'
      ? alerts
      : alerts.filter((alert) => alert.severity === activeTab.toUpperCase());

  return (
    <div className="mx-auto min-w-0 max-w-[1100px]">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight text-navy-900 lg:text-3xl">
          {t('alerts.title')}
        </h1>
        <p className="mt-1 text-sm text-gray-500 lg:text-base">
          Potential project risks detected by GovRisk
        </p>
      </div>

      {loading ? (
        <LoadingState text={t('alerts.loading')} />
      ) : error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      ) : (
        <>
          <div className="mb-6 flex flex-wrap gap-2">
            {tabs.map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => setActiveTab(tab)}
                className={`rounded-lg px-3.5 py-2 text-sm font-medium transition-colors ${
                  activeTab === tab
                    ? 'bg-navy-900 text-white'
                    : 'border border-gray-200 bg-white text-gray-600 hover:border-navy-300 hover:text-navy-900'
                }`}
              >
                {t(tabLabels[tab])}
                <span
                  className={`ml-2 rounded-full px-1.5 text-xs ${activeTab === tab ? 'bg-white/20' : 'bg-gray-100 text-gray-500'}`}
                >
                  {tabCounts[tab]}
                </span>
              </button>
            ))}
          </div>

          <p className="mb-4 text-sm text-gray-500">
            {t('alerts.showing', { count: filteredAlerts.length })}
          </p>

          {filteredAlerts.length === 0 ? (
            <EmptyState
              title={t('alerts.noTitle')}
              description={t('alerts.noDesc')}
              icon={<BellOff size={40} />}
            />
          ) : (
            <div className="space-y-4">
              {filteredAlerts.map((alert) => (
                <AlertCard key={alert.id} alert={alert} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
