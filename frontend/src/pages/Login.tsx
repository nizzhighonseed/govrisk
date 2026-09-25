import { useState, FormEvent } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { Eye, EyeOff, AlertCircle, Clock, Lock, ShieldCheck } from 'lucide-react';
import { login } from '../services/api';
import { useAuth } from '../context/AuthContext';
import LandmarkSlider from '../components/hero/LandmarkSlider';
import LanguageSwitcher from '../components/layout/LanguageSwitcher';
import { useI18n } from '../i18n';

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { setUser } = useAuth();
  const { t } = useI18n();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [pending, setPending] = useState('');

  const from = (location.state as { from?: { pathname: string } })?.from?.pathname || '/';

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setPending('');
    if (!email.trim() || !password) {
      setError('Please enter both email and password to continue.');
      return;
    }
    setLoading(true);
    try {
      const data = await login(email.trim(), password);
      if (data.user?.isApproved === false) {
        setError('');
        setPending(`Your account is awaiting administrator approval. You will be able to sign in once it is approved.`);
        return;
      }
      setUser(data.user);
      // Accounts with an outstanding temporary password must choose a
      // permanent password before they can use the portfolio.
      if (data.user?.mustChangePassword) {
        navigate('/change-password', { replace: true });
        return;
      }
      navigate(from, { replace: true });
    } catch (err: any) {
      setError(err.message || 'Sign in failed. Please verify your credentials and try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-[#f5f6f9]">
      {/* Sliding landmark photo background */}
      <LandmarkSlider variant="background" />

      {/* Faint geometric background pattern */}
      <div
        aria-hidden="true"
        className="pointer-events-none fixed inset-0"
        style={{
          backgroundImage: 'radial-gradient(circle, rgba(20,30,53,0.06) 1px, transparent 1px)',
          backgroundSize: '24px 24px',
        }}
      />

      {/* Top accent line */}
      <div className="relative z-10 flex h-1 w-full shrink-0">
        <div className="w-24 bg-[#C9A227]" />
        <div className="flex-1 bg-navy-800" />
      </div>

      {/* Government header */}
      <header className="relative z-20 shrink-0 border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-4 gap-y-1 px-4 py-4 sm:px-6">
          <img
            src="/emblem_of_india.svg"
            alt="Indian National Emblem"
            className="h-12 w-auto shrink-0"
          />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="text-base font-bold tracking-wide text-navy-900 sm:text-lg font-heading">
                Sankalp
              </span>
              <span className="hidden text-xs text-gray-400 sm:inline">|</span>
              <span className="text-sm font-medium text-gray-600">{t('login.governmentLine')}</span>
            </div>
            <p className="text-xs text-gray-500">{t('login.ministryLine')}</p>
          </div>
          <div className="flex items-center gap-2">
            <LanguageSwitcher variant="light" />
            <div className="hidden h-9 items-center gap-1.5 rounded-lg border border-gray-200 px-3 text-xs font-medium text-navy-700 md:flex">
              <Lock size={13} aria-hidden="true" />
              {t('login.live')}
            </div>
          </div>
        </div>
      </header>

      {/* Main */}
      <main className="relative z-10 flex flex-1 items-center justify-center px-4 py-10 sm:py-14">
        <div className="w-full max-w-md">
          <div className="mb-7 text-center">
            <h1 className="text-2xl font-semibold text-navy-900">{t('login.title')}</h1>
            <p className="mt-1.5 text-sm text-white drop-shadow-sm">{t('login.subtitle')}</p>
          </div>

          {/* Login card */}
          <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm sm:p-8">
            <h2 className="text-lg font-semibold text-navy-900">{t('login.signIn')}</h2>
            <p className="mt-1 text-sm text-gray-500">{t('login.credentialsLine')}</p>

            {error && (
              <div
                role="alert"
                className="mt-4 flex items-start gap-2.5 rounded-md border border-red-300 bg-red-50 p-3"
              >
                <AlertCircle size={16} className="mt-0.5 shrink-0 text-red-700" />
                <p className="text-sm text-red-700">{error}</p>
              </div>
            )}

            {pending && (
              <div
                role="status"
                className="mt-4 flex items-start gap-2.5 rounded-md border border-amber-300 bg-amber-50 p-3"
              >
                <Clock size={16} className="mt-0.5 shrink-0 text-amber-700" />
                <p className="text-sm text-amber-800">{pending}</p>
              </div>
            )}

            {showHelp && (
              <div className="mt-4 rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-navy-800">
                {t('login.helpReset')}
              </div>
            )}

            <form onSubmit={handleSubmit} className="mt-6 space-y-5">
              <div>
                <label htmlFor="email" className="mb-1.5 block text-sm font-medium text-navy-900">
                  {t('login.emailLabel')}
                </label>
                <input
                  id="email"
                  type="email"
                  name="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@sankalp.gov.in"
                  className="h-11 w-full rounded-md border border-gray-300 bg-white px-3.5 text-sm text-navy-900 outline-none transition-colors placeholder:text-gray-400 focus:border-navy-700 focus:ring-2 focus:ring-navy-700/20"
                />
              </div>

              <div>
                <label
                  htmlFor="password"
                  className="mb-1.5 block text-sm font-medium text-navy-900"
                >
                  {t('login.passwordLabel')}
                </label>
                <div className="relative">
                  <input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    name="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder={t('login.passwordPlaceholder')}
                    className="h-11 w-full rounded-md border border-gray-300 bg-white px-3.5 pr-11 text-sm text-navy-900 outline-none transition-colors placeholder:text-gray-400 focus:border-navy-700 focus:ring-2 focus:ring-navy-700/20"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((s) => !s)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 rounded p-1 text-gray-400 hover:text-navy-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-navy-700/40"
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                  >
                    {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>

              <div className="flex items-center justify-between">
                <label className="flex items-center gap-2 text-sm text-gray-600">
                  <input
                    type="checkbox"
                    checked={remember}
                    onChange={(e) => setRemember(e.target.checked)}
                    className="h-4 w-4 rounded border-gray-300 accent-navy-800 focus:ring-navy-700/30"
                  />
                  {t('login.rememberMe')}
                </label>
                <button
                  type="button"
                  onClick={() => setShowHelp((s) => !s)}
                  className="text-sm font-medium text-navy-800 underline-offset-2 hover:underline focus:outline-none focus-visible:underline"
                >
                  {t('login.forgotPassword')}
                </button>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="h-11 w-full rounded-md bg-navy-800 text-sm font-semibold tracking-wide text-white transition-colors hover:bg-navy-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-navy-700/40 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? t('login.signingIn') : t('login.signIn')}
              </button>
            </form>

            <div className="mt-6 flex items-start gap-2 text-xs text-gray-500">
              <ShieldCheck size={15} className="mt-0.5 shrink-0 text-navy-700" aria-hidden="true" />
              <p>{t('login.protected')}</p>
            </div>

            <div className="mt-6 border-t border-gray-100 pt-4 text-center text-sm text-gray-500">
              {t('login.noAccount')}{' '}
              <Link
                to="/register"
                className="font-medium text-navy-800 underline-offset-2 hover:underline"
              >
                {t('login.requestAccess')}
              </Link>
            </div>
          </div>

          {/* Demo credentials */}
          <div className="mt-6 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
            <p className="text-xs font-semibold uppercase tracking-wider text-gray-500">
              {t('login.demoCredentials')}
            </p>
            <div className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 font-mono text-xs text-gray-600 sm:grid-cols-2">
              <span>admin@sankalp.gov.in / admin123</span>
              <span>officer@sankalp.gov.in / officer123</span>
              <span>analyst@sankalp.gov.in / analyst123</span>
              <span>viewer@sankalp.gov.in / viewer123</span>
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="relative z-10 shrink-0 border-t border-gray-200 bg-white">
        <div className="mx-auto flex max-w-5xl flex-col items-center justify-between gap-2 px-4 py-4 text-xs text-gray-500 sm:flex-row sm:px-6">
          <nav className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1">
            <a href="#help" className="hover:text-navy-800 hover:underline">
              Help
            </a>
            <a href="#accessibility" className="hover:text-navy-800 hover:underline">
              Accessibility
            </a>
            <a href="#privacy" className="hover:text-navy-800 hover:underline">
              Privacy
            </a>
            <a href="#terms" className="hover:text-navy-800 hover:underline">
              Terms
            </a>
          </nav>
          <p className="text-center">
            © {new Date().getFullYear()} Government of India · GovRisk
          </p>
        </div>
      </footer>
    </div>
  );
}
