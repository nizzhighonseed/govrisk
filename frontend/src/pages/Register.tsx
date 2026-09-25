import { useState, FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { Eye, EyeOff, AlertCircle, Clock } from 'lucide-react';
import { register } from '../services/api';

export default function Register() {
  const [submittedEmail, setSubmittedEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [department, setDepartment] = useState('');
  const [designation, setDesignation] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    if (!fullName.trim() || !email.trim() || !password) {
      setError('Full name, email, and password are required.');
      return;
    }
    if (password.length < 6) {
      setError('Password must be at least 6 characters long.');
      return;
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }
    setLoading(true);
    try {
      const data = await register({
        fullName: fullName.trim(),
        email: email.trim(),
        password,
        department: department.trim() || undefined,
        designation: designation.trim() || undefined,
      });
      // Self-registered accounts are PENDING administrator approval. They have
      // no portfolio access until an admin approves them, so there is nothing
      // to auto-login into - show the pending confirmation instead.
      setSubmittedEmail(data.user?.email || email.trim());
    } catch (err: any) {
      setError(err.message || 'Registration failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const inputClass =
    'h-11 w-full rounded-lg border border-navy-700 bg-navy-800 px-4 text-sm text-white outline-none transition-all placeholder:text-navy-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/30';

  return (
    <div className="flex min-h-screen bg-navy-950">
      <div className="hidden w-1/2 lg:block">
        <div className="flex h-full flex-col justify-between bg-gradient-to-br from-navy-900 via-navy-900 to-navy-800 p-12">
          <div className="flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-600 text-base font-bold text-white">
              S
            </div>
            <div>
              <h1 className="text-xl font-bold uppercase tracking-wide text-white">Sankalp</h1>
              <p className="text-xs text-navy-300">AI Infrastructure Intelligence</p>
            </div>
          </div>
          <div className="max-w-md">
            <h2 className="text-3xl font-bold leading-tight text-white">
              Join the platform keeping India's infrastructure on track.
            </h2>
            <p className="mt-4 text-sm leading-relaxed text-navy-300">
              Government officers, analysts, and stakeholders can register to access
              AI-powered risk monitoring for infrastructure projects across ministries.
              New accounts are reviewed and approved by an administrator before access
              is granted.
            </p>
          </div>
          <p className="text-xs text-navy-500">
            Ministry of Electronics &amp; Information Technology · SIH 2026
          </p>
        </div>
      </div>

      <div className="flex w-full items-center justify-center px-6 py-12 lg:w-1/2">
        <div className="w-full max-w-md">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-600 text-sm font-bold text-white">
              S
            </div>
            <div>
              <h1 className="text-lg font-bold uppercase tracking-wide text-white">Sankalp</h1>
              <p className="text-xs text-navy-300">AI Infrastructure Intelligence</p>
            </div>
          </div>

          <div className="rounded-2xl border border-navy-800 bg-navy-900 p-8 shadow-2xl">
            <h2 className="text-2xl font-bold text-white">Create your account</h2>
            <p className="mt-1.5 text-sm text-navy-300">
              Register to access the Sankalp monitoring platform
            </p>

            {submittedEmail ? (
              <div className="mt-6">
                <div className="flex items-start gap-3 rounded-2xl border border-blue-500/30 bg-blue-500/10 p-5">
                  <span className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-500/20">
                    <Clock size={18} className="text-blue-300" />
                  </span>
                  <div>
                    <h3 className="text-sm font-semibold text-white">
                      Registration submitted for approval
                    </h3>
                    <p className="mt-1.5 text-sm leading-relaxed text-navy-200">
                      Your request for <span className="font-medium text-white">{submittedEmail}</span>{' '}
                      has been received. An administrator must approve your account before
                      you can sign in to the Sankalp portfolio.
                    </p>
                  </div>
                </div>
                <Link
                  to="/login"
                  className="mt-5 inline-flex h-11 w-full items-center justify-center rounded-lg bg-blue-600 text-sm font-semibold text-white transition-colors hover:bg-blue-500"
                >
                  Return to sign in
                </Link>
                <p className="mt-3 text-center text-xs text-navy-400">
                  You can sign in as soon as your account is approved.
                </p>
              </div>
            ) : (
              <>
                {error && (
                  <div className="mt-5 flex items-start gap-2.5 rounded-lg border border-red-500/30 bg-red-500/10 p-3">
                    <AlertCircle size={16} className="mt-0.5 shrink-0 text-red-400" />
                    <p className="text-sm text-red-300">{error}</p>
                  </div>
                )}

            <form onSubmit={handleSubmit} className="mt-6 space-y-4">
              <div>
                <label htmlFor="fullName" className="mb-1.5 block text-sm font-medium text-navy-100">
                  Full Name
                </label>
                <input
                  id="fullName"
                  type="text"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="e.g. Aarav Patel"
                  className={inputClass}
                />
              </div>

              <div>
                <label htmlFor="email" className="mb-1.5 block text-sm font-medium text-navy-100">
                  Email
                </label>
                <input
                  id="email"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@sankalp.gov.in"
                  className={inputClass}
                />
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <label htmlFor="password" className="mb-1.5 block text-sm font-medium text-navy-100">
                    Password
                  </label>
                  <div className="relative">
                    <input
                      id="password"
                      type={showPassword ? 'text' : 'password'}
                      autoComplete="new-password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="Min 6 characters"
                      className="h-11 w-full rounded-lg border border-navy-700 bg-navy-800 px-4 pr-11 text-sm text-white outline-none transition-all placeholder:text-navy-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/30"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((s) => !s)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-navy-400 hover:text-navy-200"
                      aria-label={showPassword ? 'Hide password' : 'Show password'}
                    >
                      {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                    </button>
                  </div>
                </div>
                <div>
                  <label htmlFor="confirmPassword" className="mb-1.5 block text-sm font-medium text-navy-100">
                    Confirm Password
                  </label>
                  <input
                    id="confirmPassword"
                    type={showPassword ? 'text' : 'password'}
                    autoComplete="new-password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Re-enter password"
                    className="h-11 w-full rounded-lg border border-navy-700 bg-navy-800 px-4 text-sm text-white outline-none transition-all placeholder:text-navy-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/30"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <label htmlFor="department" className="mb-1.5 block text-sm font-medium text-navy-100">
                    Department <span className="text-navy-500">(optional)</span>
                  </label>
                  <input
                    id="department"
                    type="text"
                    value={department}
                    onChange={(e) => setDepartment(e.target.value)}
                    placeholder="e.g. Ministry of Railways"
                    className={inputClass}
                  />
                </div>
                <div>
                  <label htmlFor="designation" className="mb-1.5 block text-sm font-medium text-navy-100">
                    Designation <span className="text-navy-500">(optional)</span>
                  </label>
                  <input
                    id="designation"
                    type="text"
                    value={designation}
                    onChange={(e) => setDesignation(e.target.value)}
                    placeholder="e.g. Project Officer"
                    className={inputClass}
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="h-11 w-full rounded-lg bg-blue-600 text-sm font-semibold text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? 'Creating account...' : 'Create account'}
              </button>
            </form>
              </>
            )}
          </div>

          <p className="mt-6 text-center text-sm text-navy-300">
            Already have an account?{' '}
            <Link to="/login" className="font-semibold text-blue-400 hover:text-blue-300">
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}