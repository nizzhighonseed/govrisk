import { useState, FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertCircle, CheckCircle2, KeyRound, LogOut, ShieldCheck } from 'lucide-react';
import { changePassword } from '../services/api';
import { useAuth } from '../context/AuthContext';
import LanguageSwitcher from '../components/layout/LanguageSwitcher';

export default function ChangePassword() {
  const navigate = useNavigate();
  const { user, logout, setUser } = useAuth();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    if (!currentPassword) {
      setError('Please enter your current (temporary) password.');
      return;
    }
    if (newPassword.length < 6) {
      setError('New password must be at least 6 characters.');
      return;
    }
    if (newPassword !== confirmPassword) {
      setError('New passwords do not match.');
      return;
    }
    if (newPassword === currentPassword) {
      setError('New password must be different from the current password.');
      return;
    }
    setSaving(true);
    try {
      await changePassword({ currentPassword, newPassword });
      if (user) {
        setUser({ ...user, mustChangePassword: false });
      }
      setSuccess('Password changed successfully. You can now access the portfolio.');
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setTimeout(() => navigate('/', { replace: true }), 1200);
    } catch (err: any) {
      setError(err.message || 'Failed to change password.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-[#f5f6f9]">
      <div className="relative z-10 flex h-1 w-full shrink-0">
        <div className="w-24 bg-[#C9A227]" />
        <div className="flex-1 bg-navy-800" />
      </div>

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
              <span className="text-sm font-medium text-gray-600">Account Security</span>
            </div>
            <p className="text-xs text-gray-500">Government Portfolio Risk Management</p>
          </div>
          <div className="flex items-center gap-2">
            <LanguageSwitcher variant="light" />
            <button
              type="button"
              onClick={logout}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-gray-200 px-3 text-xs font-medium text-navy-700 hover:bg-gray-50"
            >
              <LogOut size={13} aria-hidden="true" />
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="flex flex-1 items-center justify-center px-4 py-10 sm:py-14">
        <div className="w-full max-w-md">
          <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm sm:p-8">
            <div className="mb-5 flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-navy-800 text-white">
                <KeyRound size={18} aria-hidden="true" />
              </div>
              <div>
                <h1 className="text-lg font-semibold text-navy-900">Password change required</h1>
                <p className="mt-1 text-sm text-gray-500">
                  Your account is using a temporary password. Set a permanent
                  password before continuing to the portfolio. This must be a
                  different passphrase you have not used on this account before.
                </p>
              </div>
            </div>

            {error && (
              <div
                role="alert"
                className="mt-4 flex items-start gap-2.5 rounded-md border border-red-300 bg-red-50 p-3"
              >
                <AlertCircle size={16} className="mt-0.5 shrink-0 text-red-700" />
                <p className="text-sm text-red-700">{error}</p>
              </div>
            )}

            {success && (
              <div
                role="status"
                className="mt-4 flex items-start gap-2.5 rounded-md border border-green-300 bg-green-50 p-3"
              >
                <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-green-700" />
                <p className="text-sm text-green-800">{success}</p>
              </div>
            )}

            <form onSubmit={handleSubmit} className="mt-6 space-y-5">
              <div>
                <label htmlFor="currentPassword" className="mb-1.5 block text-sm font-medium text-navy-900">
                  Current (temporary) password
                </label>
                <input
                  id="currentPassword"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  className="h-11 w-full rounded-md border border-gray-300 bg-white px-3.5 text-sm text-navy-900 outline-none transition-colors placeholder:text-gray-400 focus:border-navy-700 focus:ring-2 focus:ring-navy-700/20"
                  placeholder="Temporary password from your administrator"
                />
              </div>

              <div>
                <label htmlFor="newPassword" className="mb-1.5 block text-sm font-medium text-navy-900">
                  New password
                </label>
                <input
                  id="newPassword"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="h-11 w-full rounded-md border border-gray-300 bg-white px-3.5 text-sm text-navy-900 outline-none transition-colors placeholder:text-gray-400 focus:border-navy-700 focus:ring-2 focus:ring-navy-700/20"
                  placeholder="Choose a strong passphrase (min 6 characters)"
                />
              </div>

              <div>
                <label htmlFor="confirmPassword" className="mb-1.5 block text-sm font-medium text-navy-900">
                  Confirm new password
                </label>
                <input
                  id="confirmPassword"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="h-11 w-full rounded-md border border-gray-300 bg-white px-3.5 text-sm text-navy-900 outline-none transition-colors placeholder:text-gray-400 focus:border-navy-700 focus:ring-2 focus:ring-navy-700/20"
                  placeholder="Re-enter your new password"
                />
              </div>

              <label className="flex items-center gap-2 text-sm text-gray-600">
                <input
                  type="checkbox"
                  checked={showPassword}
                  onChange={(e) => setShowPassword(e.target.checked)}
                  className="h-4 w-4 rounded border-gray-300 accent-navy-800 focus:ring-navy-700/30"
                />
                Show passwords
              </label>

              <button
                type="submit"
                disabled={saving}
                className="h-11 w-full rounded-md bg-navy-800 text-sm font-semibold tracking-wide text-white transition-colors hover:bg-navy-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-navy-700/40 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {saving ? 'Saving...' : 'Set permanent password'}
              </button>
            </form>

            <div className="mt-6 flex items-start gap-2 text-xs text-gray-500">
              <ShieldCheck size={15} className="mt-0.5 shrink-0 text-navy-700" aria-hidden="true" />
              <p>
                Your password is hashed and only stored as a bcrypt digest. It is
                never returned after this flow completes.
              </p>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}