import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Bell, Menu, LogOut, BellOff, ArrowRight } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { getAlerts } from '../../services/api';
import { useI18n } from '../../i18n';
import LanguageSwitcher from './LanguageSwitcher';

interface TopbarProps {
  onToggleSidebar?: () => void;
}

const severityConfig: Record<string, { dot: string; badge: string }> = {
  CRITICAL: {
    dot: 'bg-red-500',
    badge: 'bg-red-50 text-red-700 ring-1 ring-inset ring-red-100',
  },
  HIGH: {
    dot: 'bg-orange-500',
    badge: 'bg-orange-50 text-orange-700 ring-1 ring-inset ring-orange-100',
  },
  MEDIUM: {
    dot: 'bg-yellow-500',
    badge: 'bg-yellow-50 text-yellow-700 ring-1 ring-inset ring-yellow-100',
  },
  RESOLVED: {
    dot: 'bg-green-500',
    badge: 'bg-green-50 text-green-700 ring-1 ring-inset ring-green-100',
  },
};

function getInitials(name: string): string {
  return name
    .split(' ')
    .filter(Boolean)
    .map((n) => n[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();
}

function formatDate(date: string) {
  if (!date) return '';
  const d = new Date(date);
  if (isNaN(d.getTime())) return date;
  return d.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

export default function Topbar({ onToggleSidebar }: TopbarProps) {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const { t, sevLabel } = useI18n();
  const formattedDate = new Date().toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });

  const initials = user ? getInitials(user.fullName) : 'GR';

  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [alertsLoaded, setAlertsLoaded] = useState(false);
  const [notifLoading, setNotifLoading] = useState(false);
  const notifRef = useRef<HTMLDivElement>(null);

  const toggleNotifications = async () => {
    if (!notificationsOpen && !alertsLoaded) {
      setNotifLoading(true);
      try {
        setAlerts(await getAlerts());
        setAlertsLoaded(true);
      } catch {
        setAlerts([]);
      } finally {
        setNotifLoading(false);
      }
    }
    setNotificationsOpen((open) => !open);
  };

  const activeAlerts = alerts.filter((a) => a.severity !== 'RESOLVED');
  const recentAlerts = [...activeAlerts].slice(0, 5);
  const unreadCount = activeAlerts.length;

  useEffect(() => {
    if (!notificationsOpen) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) {
        setNotificationsOpen(false);
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setNotificationsOpen(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [notificationsOpen]);

  const handleSearch = (value: string) => {
    if (value.trim().length > 0) {
      navigate(`/projects?search=${encodeURIComponent(value)}`, { replace: true });
    }
  };

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  return (
    <header className="sticky top-0 z-20 grid h-16 shrink-0 grid-cols-[1fr_auto_1fr] items-center gap-3 border-b border-gray-200 bg-white/95 px-5 sm:gap-4 sm:px-6 lg:h-[72px] lg:gap-5 lg:px-8">
      {/* Left: Emblem + branding */}
      <div className="hidden shrink-0 items-center gap-3 sm:flex">
        <img
          src="/emblem_of_india.svg"
          alt="Indian National Emblem"
          className="h-10 w-auto shrink-0"
        />
        <div className="min-w-0 border-l border-gray-200 pl-3">
          <p className="text-sm font-bold tracking-wide text-navy-900 font-heading">GovRisk</p>
          <p className="text-[11px] text-gray-500">Government of India</p>
        </div>
      </div>

      {/* Center: Search bar (dead-centered) */}
      <div className="w-full max-w-sm justify-self-center sm:max-w-md lg:max-w-lg">
        <div className="relative w-full">
          <Search className="pointer-events-none absolute left-4 top-1/2 z-10 h-[18px] w-[18px] -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder={t('topbar.searchPlaceholder')}
            onChange={(e) => handleSearch(e.target.value)}
            className="h-11 w-full rounded-lg border border-gray-200 bg-gray-50 pl-12 pr-4 text-sm text-navy-900 outline-none transition-all placeholder:text-gray-400 focus:border-blue-500 focus:bg-white focus:ring-2 focus:ring-blue-500/10"
          />
        </div>
      </div>

      {/* Right: actions */}
      <div className="flex min-w-0 shrink-0 items-center justify-self-end gap-2 sm:gap-3">
        <span className="hidden whitespace-nowrap text-sm font-medium text-gray-500 sm:block">
          {formattedDate}
        </span>

        <LanguageSwitcher />

        <div ref={notifRef} className="relative">
          <button
            type="button"
            onClick={toggleNotifications}
            className={`relative rounded-lg p-2 transition-colors hover:bg-gray-100 ${
              notificationsOpen ? 'bg-gray-100 text-navy-900' : 'text-gray-500 hover:text-navy-900'
            }`}
            aria-label={t('topbar.notifications')}
            aria-expanded={notificationsOpen}
          >
            <Bell size={18} />
            {unreadCount > 0 && (
              <span className="absolute right-0.5 top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white ring-2 ring-white">
                {unreadCount > 99 ? '99+' : unreadCount}
              </span>
            )}
          </button>

          {notificationsOpen && (
            <div className="absolute right-0 top-full z-50 mt-2 w-[min(90vw,380px)] overflow-hidden rounded-xl border border-gray-200 bg-white shadow-xl">
              <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
                <p className="text-sm font-semibold text-navy-900">{t('topbar.notifications')}</p>
                <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-500">
                  {unreadCount} {t('topbar.active')}
                </span>
              </div>

              <div className="max-h-[320px] overflow-y-auto">
                {notifLoading ? (
                  <div className="flex items-center justify-center gap-2 px-4 py-8 text-sm text-gray-400">
                    <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-gray-300 border-t-blue-600" />
                    {t('topbar.loadingAlerts')}
                  </div>
                ) : activeAlerts.length === 0 ? (
                  <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
                    <BellOff size={22} className="text-gray-300" />
                    <p className="text-sm font-medium text-navy-900">{t('topbar.noActiveAlerts')}</p>
                    <p className="text-xs text-gray-500">{t('topbar.allCaughtUp')}</p>
                  </div>
                ) : (
                  <ul className="divide-y divide-gray-50">
                    {recentAlerts.map((alert: any) => {
                      const config = severityConfig[alert.severity] || severityConfig.MEDIUM;
                      return (
                        <li key={alert.id}>
                          <button
                            type="button"
                            onClick={() => {
                              setNotificationsOpen(false);
                              navigate(`/projects/${alert.projectId}`);
                            }}
                            className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-gray-50"
                          >
                            <span
                              className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${config.dot}`}
                            />
                            <span className="min-w-0 flex-1">
                              <span className="flex flex-wrap items-center gap-1.5">
                                <span
                                  className={`rounded-full px-2 py-px text-[10px] font-semibold ${config.badge}`}
                                >
                                  {sevLabel(alert.severity)}
                                </span>
                                <span className="truncate text-xs font-semibold text-navy-900">
                                  {alert.type}
                                </span>
                              </span>
                              <span className="mt-0.5 block truncate text-sm text-blue-600">
                                {alert.projectName}
                              </span>
                              <span className="mt-0.5 block text-xs text-gray-400">
                                {formatDate(alert.detectedDate)}
                              </span>
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>

              <button
                type="button"
                onClick={() => {
                  setNotificationsOpen(false);
                  navigate('/alerts');
                }}
                className="flex w-full items-center justify-center gap-1.5 border-t border-gray-100 bg-gray-50/60 px-4 py-3 text-sm font-medium text-navy-900 transition-colors hover:bg-gray-100"
              >
                {t('topbar.viewAllAlerts')}
                <ArrowRight size={14} />
              </button>
            </div>
          )}
        </div>

        <div className="flex h-11 w-11 items-center justify-center rounded-full bg-navy-700 text-sm font-semibold text-white">
          {initials}
        </div>

        <button
          type="button"
          onClick={handleLogout}
          className="rounded-lg p-2 text-gray-500 transition-colors hover:bg-gray-100 hover:text-red-500"
          aria-label={t('topbar.logOut')}
          title={t('topbar.logOut')}
        >
          <LogOut size={18} />
        </button>
      </div>
    </header>
  );
}