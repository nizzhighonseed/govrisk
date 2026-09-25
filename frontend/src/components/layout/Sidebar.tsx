import { NavLink, useNavigate } from 'react-router-dom';
import {
  BarChart3,
  FolderOpen,
  MapPin,
  TrendingUp,
  AlertTriangle,
  Bot,
  FileText,
  Settings,
  ShieldCheck,
  LogOut,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useI18n, TranslationKey } from '../../i18n';

const navItems: { to: string; icon: typeof BarChart3; labelKey: TranslationKey }[] = [
  { to: '/', icon: BarChart3, labelKey: 'nav.dashboard' },
  { to: '/projects', icon: FolderOpen, labelKey: 'nav.projects' },
  { to: '/risk-map', icon: MapPin, labelKey: 'nav.riskMap' },
  { to: '/analytics', icon: TrendingUp, labelKey: 'nav.analytics' },
  { to: '/alerts', icon: AlertTriangle, labelKey: 'nav.earlyWarnings' },
  { to: '/assistant', icon: Bot, labelKey: 'nav.aiAssistant' },
  { to: '/reports', icon: FileText, labelKey: 'nav.reports' },
];

function AshokaChakra({ size = 11 }: { size?: number }) {
  const spokes = Array.from({ length: 24 }, (_, i) => i * 15);
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="11.5" fill="#1a237e" />
      <g stroke="#fff" strokeWidth="0.7">
        {spokes.map((angle) => (
          <line key={angle} x1="12" y1="12" x2="12" y2="1.6" transform={`rotate(${angle} 12 12)`} />
        ))}
      </g>
      <circle cx="12" cy="12" r="1.2" fill="#fff" />
    </svg>
  );
}

function BottomNavItem({
  to,
  icon: Icon,
  labelKey,
  t,
}: {
  to: string;
  icon: typeof BarChart3;
  labelKey: TranslationKey;
  t: (key: TranslationKey) => string;
}) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        `group relative flex min-w-[76px] flex-1 flex-col items-center gap-1.5 px-3 py-4 text-[11px] font-medium transition-colors duration-200 ${
          isActive ? 'text-navy-900' : 'text-gray-500 hover:text-navy-900'
        }`
      }
    >
      {({ isActive }) => (
        <>
          <Icon
            size={20}
            className={`shrink-0 transition-colors ${
              isActive ? 'text-blue-600' : 'text-gray-400 group-hover:text-blue-600'
            }`}
          />
          <span className="whitespace-nowrap">{t(labelKey)}</span>
          {isActive && (
            <span className="absolute inset-x-3 top-0 h-0.5 rounded-full bg-[#C9A227]" />
          )}
        </>
      )}
    </NavLink>
  );
}

export default function BottomBar() {
  const { user, logout } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();

  const displayName = user?.fullName || "GovRisk User";

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  return (
    <aside className="fixed inset-x-0 bottom-0 z-50 border-t border-gray-300 bg-[#e9eaef] shadow-[0_-4px_20px_rgba(15,23,42,0.08)]">
      <div className="flex items-stretch overflow-x-auto">
        <button
          type="button"
          onClick={handleLogout}
          className="group hidden min-w-0 shrink-0 items-center gap-2.5 px-4 py-4 md:flex"
          title={t('nav.logOut')}
          aria-label={t('nav.logOut')}
        >
          <span
            className="relative h-12 w-12 shrink-0 rounded-full"
            title={user?.role === 'admin' ? t('nav.administrator') : undefined}
          >
            {user?.role === 'admin' ? (
              <>
                <span className="block h-12 w-12 rounded-full bg-[conic-gradient(from_0deg,#FF9933_0deg_30deg,#FFFFFF_30deg_150deg,#138808_150deg_270deg,#FF9933_270deg_360deg)] shadow-sm [mask-image:radial-gradient(circle,transparent_0_13px,#000_13.5px)]" />
                <img
                  src="/emblem_of_india.svg"
                  alt=""
                  className="absolute left-1/2 top-1/2 h-[20px] w-[20px] -translate-x-1/2 -translate-y-1/2"
                />
                <span className="absolute right-[1px] top-1/2 -translate-y-1/2">
                  <AshokaChakra size={10} />
                </span>
              </>
            ) : (
              <span className="block h-12 w-12 rounded-full bg-gray-300" />
            )}
          </span>
          <span className="min-w-0 max-w-[110px]">
            <span className="block truncate text-xs font-semibold text-navy-900">
              {displayName}
            </span>
            <span className="block truncate text-[10px] text-gray-500">
              {t('nav.logOut')}
            </span>
          </span>
        </button>

        <div className="mx-1 my-2 hidden h-auto w-px shrink-0 bg-gray-300 md:block" />

        <nav className="flex min-w-0 flex-1 items-stretch">
          {navItems.map((item) => (
            <BottomNavItem key={item.to} {...item} t={t} />
          ))}
          {user?.role === 'admin' && (
            <BottomNavItem to="/admin" icon={ShieldCheck} labelKey="nav.admin" t={t} />
          )}
          <BottomNavItem to="/settings" icon={Settings} labelKey="nav.settings" t={t} />
        </nav>

        <button
          type="button"
          onClick={handleLogout}
          className="group flex shrink-0 items-center gap-1 px-3 py-4 text-[11px] font-medium text-gray-500 transition-colors hover:text-navy-900 md:hidden"
          title={t('nav.logOut')}
          aria-label={t('nav.logOut')}
        >
          <LogOut size={20} className="text-gray-400 transition-colors group-hover:text-blue-600" />
          <span className="hidden sm:block">{t('nav.logOut')}</span>
        </button>
      </div>
    </aside>
  );
}
