import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Users,
  UserCheck,
  UserX,
  ShieldCheck,
  UserCog,
  BarChart3,
  Eye,
  Plus,
  Search,
  X,
  ChevronLeft,
  ChevronRight,
  Copy,
  Check,
  AlertTriangle,
  RefreshCw,
  Shield,
  Briefcase,
  LineChart,
  FileText,
  FolderOpen,
  Activity,
  Brain,
  AlertOctagon,
  Sparkles,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { LoadingState } from '../components/ui/LoadingState';
import { EmptyState } from '../components/ui/EmptyState';
import {
  getUserStats,
  getUsers,
  createUser,
  adminUpdateUser,
  updateUserRole,
  updateUserStatus,
  updateUserApproval,
  resetUserPassword,
  getAuditLogs,
  getProjects,
  getAiHealth,
  getAiInsights,
} from '../services/api';
import type { AiInsights } from '../services/api';

interface User {
  id: string;
  userId?: string;
  fullName: string;
  email: string;
  role: string;
  department?: string;
  designation?: string;
  isActive: boolean;
  isApproved?: boolean;
  createdAt?: string;
  updatedAt?: string;
  lastLogin?: string;
}

interface AuditLogItem {
  id?: string;
  timestamp?: string;
  createdAt?: string;
  actorUserId?: string;
  actorName?: string;
  action?: string;
  targetUserId?: string;
  targetType?: string;
  details?: string;
  meta?: Record<string, unknown>;
}

interface UserStats {
  total: number;
  active: number;
  inactive: number;
  admins: number;
  officers: number;
  analysts: number;
  viewers: number;
}

interface AdminProject {
  id: string;
  name: string;
  ministry: string;
  agency: string;
  sector: string;
  state: string;
  riskScore: number;
  riskLevel: string;
  physicalProgress: number;
  createdAt?: string;
}

const roleLabels: Record<string, string> = {
  admin: 'Admin',
  officer: 'Officer',
  analyst: 'Analyst',
  viewer: 'Viewer',
};

const ROLE_DESCRIPTIONS: Record<string, { label: string; desc: string; icon: React.ReactNode }> = {
  admin: {
    label: 'Admin',
    desc: 'Full administrative access including user management.',
    icon: <ShieldCheck className="h-5 w-5 text-red-600" />,
  },
  officer: {
    label: 'Officer',
    desc: 'Can manage and monitor project information and operational workflows.',
    icon: <Briefcase className="h-5 w-5 text-blue-600" />,
  },
  analyst: {
    label: 'Analyst',
    desc: 'Can access project analytics, risk analysis, and reports.',
    icon: <LineChart className="h-5 w-5 text-amber-600" />,
  },
  viewer: {
    label: 'Viewer',
    desc: 'Read-only access to permitted monitoring information.',
    icon: <Eye className="h-5 w-5 text-gray-500" />,
  },
};

const ROLE_BADGE: Record<string, string> = {
  admin: 'bg-red-50 text-red-700 ring-1 ring-red-200',
  officer: 'bg-blue-50 text-blue-700 ring-1 ring-blue-200',
  analyst: 'bg-amber-50 text-amber-700 ring-1 ring-amber-200',
  viewer: 'bg-gray-100 text-gray-600 ring-1 ring-gray-200',
};

function formatDate(iso?: string) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '—';
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

function formatDateTime(iso?: string) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '—';
  return d.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function capitalize(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function ModalShell({
  open,
  onClose,
  children,
  maxWidth = 'max-w-md',
}: {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  maxWidth?: string;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div
        className={`relative rounded-2xl bg-white p-6 shadow-2xl max-h-[90vh] overflow-y-auto w-full ${maxWidth}`}
      >
        <button
          onClick={onClose}
          className="absolute right-4 top-4 rounded-lg p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
        >
          <X className="h-5 w-5" />
        </button>
        {children}
      </div>
    </div>
  );
}

export default function AdminPanel() {
  const { user: currentUser } = useAuth();
  const navigate = useNavigate();

  const [stats, setStats] = useState<UserStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);

  const [projects, setProjects] = useState<AdminProject[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(true);

  const [users, setUsers] = useState<User[]>([]);
  const [usersPage, setUsersPage] = useState(1);
  const [usersTotalPages, setUsersTotalPages] = useState(1);
  const [usersTotal, setUsersTotal] = useState(0);
  const [usersLoading, setUsersLoading] = useState(true);
  const [usersError, setUsersError] = useState('');

  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [approvalFilter, setApprovalFilter] = useState('');
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchRef = useRef(search);

  const [logs, setLogs] = useState<AuditLogItem[]>([]);
  const [logsPage, setLogsPage] = useState(1);
  const [logsTotalPages, setLogsTotalPages] = useState(1);
  const [logsLoading, setLogsLoading] = useState(true);

  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [createStep, setCreateStep] = useState<'form' | 'success'>('form');
  const [createdUser, setCreatedUser] = useState<{
    userId: string;
    fullName: string;
    email: string;
    role: string;
    temporaryPassword: string;
  } | null>(null);
  const [createForm, setCreateForm] = useState({
    fullName: '',
    email: '',
    department: '',
    designation: '',
    role: 'viewer',
    isActive: true,
  });
  const [createError, setCreateError] = useState('');
  const [createSaving, setCreateSaving] = useState(false);

  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<User | null>(null);
  const [editForm, setEditForm] = useState({
    fullName: '',
    email: '',
    department: '',
    designation: '',
  });
  const [editError, setEditError] = useState('');
  const [editSaving, setEditSaving] = useState(false);

  const [detailsModalOpen, setDetailsModalOpen] = useState(false);
  const [detailsTarget, setDetailsTarget] = useState<User | null>(null);

  const [copied, setCopied] = useState(false);

  const fetchStats = useCallback(async () => {
    try {
      const s = await getUserStats();
      setStats(s);
    } catch {
      setStats(null);
    } finally {
      setStatsLoading(false);
    }
  }, []);

  const fetchUsers = useCallback(async () => {
    setUsersLoading(true);
    setUsersError('');
    try {
      const params: Record<string, string | number> = { page: usersPage, limit: 10 };
      if (searchRef.current) params.search = searchRef.current;
      if (roleFilter) params.role = roleFilter;
      if (statusFilter) params.status = statusFilter;
      if (approvalFilter) params.approval = approvalFilter;
      const res = await getUsers(params as any);
      setUsers(res.items);
      setUsersTotalPages(res.totalPages);
      setUsersTotal(res.total);
    } catch (e: any) {
      setUsersError(e.message || 'Failed to load users');
    } finally {
      setUsersLoading(false);
    }
  }, [usersPage, roleFilter, statusFilter, approvalFilter]);

  const fetchLogs = useCallback(async () => {
    setLogsLoading(true);
    try {
      const res = await getAuditLogs({ page: logsPage, limit: 15 });
      setLogs(res.items);
      setLogsTotalPages(res.totalPages);
    } catch {
      setLogs([]);
    } finally {
      setLogsLoading(false);
    }
  }, [logsPage]);

  const fetchProjects = useCallback(async () => {
    setProjectsLoading(true);
    try {
      const res = await getProjects();
      setProjects(res as AdminProject[]);
    } catch {
      setProjects([]);
    } finally {
      setProjectsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  const [aiHealth, setAiHealth] = useState<{ available: boolean; provider: string; model: string; fallback_enabled: boolean } | null>(null);
  const [aiHealthLoading, setAiHealthLoading] = useState(true);
  const [aiMap, setAiMap] = useState<Record<string, AiInsights>>({});
  const [aiLoading, setAiLoading] = useState(false);

  useEffect(() => {
    getAiHealth()
      .then(setAiHealth)
      .catch(() => setAiHealth(null))
      .finally(() => setAiHealthLoading(false));
  }, []);

  useEffect(() => {
    if (!projects.length) return;
    const top = [...projects]
      .sort((a: any, b: any) => b.riskScore - a.riskScore)
      .slice(0, 6);
    setAiLoading(true);
    Promise.allSettled(
      top.map(async (p: any) => ({ name: p.name, id: p.id, ins: await getAiInsights(p.id, false) }))
    )
      .then((results) => {
        const map: Record<string, AiInsights> = {};
        results.forEach((r) => {
          if (r.status === 'fulfilled' && r.value.ins.ai_available) map[r.value.name] = r.value.ins;
        });
        setAiMap(map);
      })
      .finally(() => setAiLoading(false));
  }, [projects]);

  function refreshAll() {
    fetchStats();
    fetchUsers();
    fetchLogs();
    fetchProjects();
  }

  function handleSearchChange(val: string) {
    setSearch(val);
    searchRef.current = val;
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    searchDebounceRef.current = setTimeout(() => {
      setUsersPage(1);
      fetchUsers();
    }, 300);
  }

  function openCreate() {
    setCreateForm({
      fullName: '',
      email: '',
      department: '',
      designation: '',
      role: 'viewer',
      isActive: true,
    });
    setCreateError('');
    setCreateStep('form');
    setCreatedUser(null);
    setCreateModalOpen(true);
  }

  async function handleCreate() {
    setCreateError('');
    const f = createForm;
    if (!f.fullName.trim()) { setCreateError('Full name is required'); return; }
    if (!f.email.trim()) { setCreateError('Email is required'); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(f.email)) { setCreateError('Invalid email format'); return; }
    setCreateSaving(true);
    try {
      // The server generates the temporary password (CSPRNG) and returns it
      // exactly once in the response - the browser never invents one.
      const created = await createUser({
        fullName: f.fullName.trim(),
        email: f.email.trim(),
        role: f.role,
        department: f.department.trim() || undefined,
        designation: f.designation.trim() || undefined,
        isActive: f.isActive,
      });
      setCreatedUser({
        userId: created.userId || created.id,
        fullName: created.fullName,
        email: created.email,
        role: created.role,
        temporaryPassword: created.temporaryPassword,
      });
      setCreateStep('success');
      refreshAll();
    } catch (e: any) {
      setCreateError(e.message || 'Failed to create user');
    } finally {
      setCreateSaving(false);
    }
  }

  function openEdit(u: User) {
    setEditTarget(u);
    setEditForm({
      fullName: u.fullName,
      email: u.email,
      department: u.department ?? '',
      designation: u.designation ?? '',
    });
    setEditError('');
    setEditModalOpen(true);
  }

  async function handleEdit() {
    if (!editTarget) return;
    setEditError('');
    const f = editForm;
    if (!f.fullName.trim()) { setEditError('Full name is required'); return; }
    if (!f.email.trim()) { setEditError('Email is required'); return; }
    setEditSaving(true);
    try {
      await adminUpdateUser(editTarget.id, {
        fullName: f.fullName.trim(),
        email: f.email.trim(),
        department: f.department.trim() || undefined,
        designation: f.designation.trim() || undefined,
      });
      setEditModalOpen(false);
      refreshAll();
    } catch (e: any) {
      setEditError(e.message || 'Failed to update user');
    } finally {
      setEditSaving(false);
    }
  }

  function openDetails(u: User) {
    setDetailsTarget(u);
    setDetailsModalOpen(true);
  }

  async function handleRoleChange(u: User, newRole: string) {
    if (u.id === currentUser?.id) return;
    const confirmed = window.confirm(
      `Are you sure you want to change ${u.fullName} from ${roleLabels[u.role] || u.role} to ${roleLabels[newRole] || newRole}?`
    );
    if (!confirmed) return;
    try {
      await updateUserRole(u.id, newRole);
      refreshAll();
    } catch (e: any) {
      alert(e.message || 'Failed to update role');
    }
  }

  async function handleStatusToggle(u: User) {
    if (u.id === currentUser?.id) return;
    if (u.isActive) {
      const confirmed = window.confirm(`Are you sure you want to deactivate ${u.fullName}?`);
      if (!confirmed) return;
    }
    try {
      await updateUserStatus(u.id, !u.isActive);
      refreshAll();
    } catch (e: any) {
      alert(e.message || 'Failed to update status');
    }
  }

  async function handleApprovalToggle(u: User) {
    if (u.id === currentUser?.id) return;
    const approve = u.isApproved === false;
    const confirmed = window.confirm(
      approve
        ? `Approve ${u.fullName}? They will gain portfolio access.`
        : `Revoke approval for ${u.fullName}? They will immediately lose portfolio access.`
    );
    if (!confirmed) return;
    try {
      await updateUserApproval(u.id, approve);
      refreshAll();
    } catch (e: any) {
      alert(e.message || 'Failed to update approval');
    }
  }

  async function handleResetPassword(u: User) {
    const confirmed = window.confirm(`Generate a temporary password for ${u.fullName}?`);
    if (!confirmed) return;
    try {
      const res = await resetUserPassword(u.id);
      setCreatedUser({
        userId: u.userId || u.id,
        fullName: u.fullName,
        email: u.email,
        role: u.role,
        temporaryPassword: res.temporaryPassword,
      });
      setCreateStep('success');
      setCreateModalOpen(true);
      refreshAll();
    } catch (e: any) {
      alert(e.message || 'Failed to reset password');
    }
  }

  async function handleCopy(text: string) {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  const kpiCards = stats
    ? [
        { label: 'Total Users', value: stats.total, icon: Users },
        { label: 'Active Users', value: stats.active, icon: UserCheck },
        { label: 'Inactive Users', value: stats.inactive, icon: UserX },
        { label: 'Admins', value: stats.admins, icon: ShieldCheck },
        { label: 'Officers', value: stats.officers, icon: UserCog },
        { label: 'Analysts', value: stats.analysts, icon: BarChart3 },
        { label: 'Viewers', value: stats.viewers, icon: Eye },
      ]
    : [];

  const projCards = projectsLoading
    ? []
    : [
        { label: 'Total Projects', value: projects.length, icon: FolderOpen },
        {
          label: 'High Risk Projects',
          value: projects.filter((p) => p.riskLevel === 'HIGH').length,
          icon: AlertTriangle,
        },
        {
          label: 'Critical Projects',
          value: projects.filter((p) => p.riskLevel === 'CRITICAL').length,
          icon: Shield,
        },
        {
          label: 'Recently Added',
          value: projects.filter((p) => p.createdAt).length,
          icon: Activity,
        },
      ];

  const recentProjects = [...projects]
    .sort((a, b) => (b.createdAt || '').localeCompare(a.createdAt || ''))
    .slice(0, 5);

  return (
    <div className="mx-auto min-w-0 max-w-[1200px] px-4 py-6 lg:px-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight text-navy-900 lg:text-3xl">
          Admin Panel
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          User management, roles, and system activity
        </p>
      </div>

      <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-7 lg:gap-4">
        {statsLoading
          ? Array.from({ length: 7 }).map((_, i) => (
              <div
                key={i}
                className="rounded-xl border border-gray-200 bg-white p-5 animate-pulse"
              >
                <div className="mb-3 h-9 w-9 rounded-lg bg-gray-100" />
                <div className="mb-1 h-7 w-12 rounded bg-gray-100" />
                <div className="h-3 w-16 rounded bg-gray-100" />
              </div>
            ))
          : kpiCards.map((kpi) => {
              const Icon = kpi.icon;
              return (
                <div
                  key={kpi.label}
                  className="rounded-xl border border-gray-200 bg-white p-5"
                >
                  <div className="mb-2 rounded-lg bg-blue-50 p-2 inline-flex">
                    <Icon className="h-5 w-5 text-blue-600" />
                  </div>
                  <p className="text-2xl font-bold text-navy-900">{kpi.value}</p>
                  <p className="text-xs font-medium text-gray-500">{kpi.label}</p>
                </div>
              );
            })}
      </div>

      {/* ── AI Monitoring ──────────────────────────────────────────── */}
      <section className="mb-8 rounded-xl border border-purple-200 bg-gradient-to-br from-purple-50/60 to-white p-5 lg:p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <div className="rounded-lg bg-purple-100 p-2">
              <Brain className="h-5 w-5 text-purple-700" />
            </div>
            <h2 className="text-base font-semibold text-navy-900 lg:text-lg">
              AI Monitoring &amp; Early-Warning Engine
            </h2>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {aiHealth && (
              <span
                className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${
                  aiHealth.available
                    ? 'bg-green-100 text-green-700'
                    : 'bg-amber-100 text-amber-700'
                }`}
              >
                <Sparkles className="h-3 w-3" />
                {aiHealth.available ? 'LLM Connected' : 'Deterministic Only'}
              </span>
            )}
            {aiHealth?.provider && (
              <span className="rounded-full bg-white px-2.5 py-1 text-xs font-medium text-gray-600 ring-1 ring-purple-100">
                {aiHealth.provider}{aiHealth.model ? ` / ${aiHealth.model}` : ''}
              </span>
            )}
          </div>
        </div>

        {aiHealthLoading ? (
          <LoadingState text="Loading AI health..." />
        ) : aiHealth ? (
          <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-xl border border-purple-100 bg-white p-4">
              <p className="text-xs font-medium text-gray-500">LLM Availability</p>
              <p className={`mt-1 text-xl font-bold ${aiHealth.available ? 'text-green-600' : 'text-amber-600'}`}>
                {aiHealth.available ? 'Available' : 'Unavailable'}
              </p>
              <p className="mt-0.5 text-[11px] text-gray-400">
                {aiHealth.available
                  ? 'Emerging-risk & explanation enrichment live'
                  : 'Deterministic engine only — keyword fallback active'}
              </p>
            </div>
            <div className="rounded-xl border border-purple-100 bg-white p-4">
              <p className="text-xs font-medium text-gray-500">Fallback Engine</p>
              <p className="mt-1 text-xl font-bold text-navy-900">
                {aiHealth.fallback_enabled ? 'Enabled' : 'Disabled'}
              </p>
              <p className="mt-0.5 text-[11px] text-gray-400">
                Statistical predictor + rule-based detector
              </p>
            </div>
            <div className="rounded-xl border border-purple-100 bg-white p-4">
              <p className="text-xs font-medium text-gray-500">Projects Analyzed</p>
              <p className="mt-1 text-xl font-bold text-navy-900">{Object.keys(aiMap).length}</p>
              <p className="mt-0.5 text-[11px] text-gray-400">Top-risk portfolio monitored</p>
            </div>
            <div className="rounded-xl border border-purple-100 bg-white p-4">
              <p className="text-xs font-medium text-gray-500">Active Signals</p>
              <p className="mt-1 text-xl font-bold text-red-600">
                {aiLoading
                  ? '…'
                  : Object.values(aiMap).reduce(
                      (sum, ai) => sum + ai.anomalies.length + ai.emerging_risks.length,
                      0
                    )}
              </p>
              <p className="mt-0.5 text-[11px] text-gray-400">Anomalies + emerging risks</p>
            </div>
          </div>
        ) : (
          <p className="mb-5 rounded-lg border border-dashed border-gray-300 py-6 text-center text-xs text-gray-500">
            AI health endpoint unavailable. Confirm the backend /api/ai/health route is reachable.
          </p>
        )}

        {aiLoading ? (
          <LoadingState text="Loading AI insights for top-risk projects..." />
        ) : Object.keys(aiMap).length === 0 ? (
          <EmptyState
            title="No AI signals yet"
            description="Run an initial analysis (or reseed) so predictions, anomalies, and emerging risks appear here."
            icon={<Brain className="h-10 w-10" />}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead>
                <tr className="bg-purple-50/60 text-xs uppercase tracking-wider text-gray-500">
                  <th className="px-4 py-3 font-semibold lg:px-6">Project</th>
                  <th className="px-4 py-3 font-semibold">Anomalies</th>
                  <th className="px-4 py-3 font-semibold">Emerging Risks</th>
                  <th className="px-4 py-3 font-semibold">Future Risk (90d)</th>
                  <th className="px-4 py-3 font-semibold">Method</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {Object.entries(aiMap).map(([name, ai]) => (
                  <tr key={name} className="transition-colors hover:bg-purple-50/40">
                    <td className="max-w-[280px] px-4 py-3 lg:px-6">
                      <span className="block truncate font-medium text-navy-900" title={name}>{name}</span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center gap-1 text-orange-700">
                        <AlertOctagon className="h-3.5 w-3.5" />
                        {ai.anomalies.length}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center gap-1 text-purple-700">
                        <AlertTriangle className="h-3.5 w-3.5" />
                        {ai.emerging_risks.length}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`font-semibold ${
                          (ai.prediction?.future_score ?? 0) >= 80
                            ? 'text-red-600'
                            : (ai.prediction?.future_score ?? 0) >= 60
                              ? 'text-orange-600'
                              : 'text-green-600'
                        }`}
                      >
                        {ai.prediction?.future_score ?? '—'}
                        <span className="ml-1 text-[11px] font-normal text-gray-400">
                          {ai.prediction ? `(${ai.prediction.current_score ?? '—'} now)` : ''}
                        </span>
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-600">
                        {(ai.prediction?.prediction_method || '—').replace(/_/g, ' ')}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="mb-8 rounded-xl border border-gray-200 bg-white p-5 lg:p-6">
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <div className="rounded-lg bg-blue-50 p-2">
              <FolderOpen className="h-5 w-5 text-blue-600" />
            </div>
            <h2 className="text-base font-semibold text-navy-900 lg:text-lg">
              Project Administration
            </h2>
            <span className="ml-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
              {projects.length}
            </span>
          </div>
          <button
            onClick={() => navigate('/projects')}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm font-semibold text-navy-900 hover:bg-gray-50"
          >
            <FolderOpen className="h-4 w-4" />
            View All Projects
          </button>
        </div>

        <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {projectsLoading
            ? Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="rounded-xl border border-gray-200 bg-gray-50 p-4 animate-pulse">
                  <div className="mb-2 h-6 w-6 rounded-lg bg-gray-200" />
                  <div className="mb-1 h-6 w-10 rounded bg-gray-200" />
                  <div className="h-3 w-14 rounded bg-gray-200" />
                </div>
              ))
            : projCards.map((kpi) => {
                const Icon = kpi.icon;
                return (
                  <div key={kpi.label} className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                    <div className="mb-2 inline-flex rounded-lg bg-white p-1.5 ring-1 ring-navy-100">
                      <Icon className="h-5 w-5 text-blue-600" />
                    </div>
                    <p className="text-xl font-bold text-navy-900">{kpi.value}</p>
                    <p className="text-xs font-medium text-gray-500">{kpi.label}</p>
                  </div>
                );
              })}
        </div>

        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_300px]">
          <div className="min-w-0">
            {projectsLoading ? (
              <LoadingState text="Loading projects..." />
            ) : projects.length === 0 ? (
              <EmptyState
                title="No projects found"
                description="Projects registered in the system will appear here."
                icon={<FolderOpen className="h-10 w-10" />}
              />
            ) : (
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                  <p className="text-2xl font-bold text-navy-900">
                    {projects.filter((p) => p.riskLevel === 'HIGH').length}
                  </p>
                  <AlertTriangle className="mb-1 mt-1 h-4 w-4 text-orange-500" />
                  <p className="text-xs font-medium text-gray-500">High Risk Projects</p>
                  <button
                    onClick={() => navigate('/projects')}
                    className="mt-3 inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-navy-900 hover:bg-gray-50"
                  >
                    View High Risk
                  </button>
                </div>
                <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                  <p className="text-2xl font-bold text-navy-900">
                    {projects.filter((p) => p.riskLevel === 'CRITICAL').length}
                  </p>
                  <Shield className="mb-1 mt-1 h-4 w-4 text-red-500" />
                  <p className="text-xs font-medium text-gray-500">Critical Projects</p>
                  <button
                    onClick={() => navigate('/projects')}
                    className="mt-3 inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-navy-900 hover:bg-gray-50"
                  >
                    View Critical
                  </button>
                </div>
              </div>
            )}
          </div>

          <div className="min-w-0">
            <h3 className="mb-3 text-sm font-semibold text-navy-900">Recently Added</h3>
            <div className="rounded-xl border border-gray-200">
              {recentProjects.length === 0 ? (
                <p className="p-4 text-sm text-gray-500">No projects added yet.</p>
              ) : (
                <ul className="divide-y divide-gray-100">
                  {recentProjects.map((p) => (
                    <li key={p.id} className="px-4 py-3">
                      <button
                        onClick={() => navigate(`/projects/${p.id}`)}
                        className="block w-full text-left"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-medium text-gray-500" style={{ fontFamily: 'ui-monospace, monospace' }}>
                            {p.id}
                          </span>
                          <span
                            className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                              p.riskLevel === 'CRITICAL'
                                ? 'bg-red-50 text-red-700'
                                : p.riskLevel === 'HIGH'
                                  ? 'bg-orange-50 text-orange-700'
                                  : p.riskLevel === 'MEDIUM'
                                    ? 'bg-yellow-50 text-yellow-700'
                                    : 'bg-green-50 text-green-700'
                            }`}
                          >
                            {p.riskLevel}
                          </span>
                        </div>
                        <p className="mt-0.5 truncate text-sm font-medium text-navy-900" title={p.name}>
                          {p.name}
                        </p>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="mb-8 rounded-xl border border-gray-200 bg-white p-5 lg:p-6">
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <div className="rounded-lg bg-blue-50 p-2">
              <Users className="h-5 w-5 text-blue-600" />
            </div>
            <h2 className="text-base font-semibold text-navy-900 lg:text-lg">
              User Management
            </h2>
            <span className="ml-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
              {usersTotal}
            </span>
          </div>
          <button onClick={openCreate} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500">
            <Plus className="h-4 w-4" />
            Create User
          </button>
        </div>

        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              placeholder="Search users..."
              value={search}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="h-11 w-full rounded-lg border border-gray-200 bg-white pl-10 pr-3.5 text-sm text-gray-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
            />
          </div>
          <select
            value={roleFilter}
            onChange={(e) => { setRoleFilter(e.target.value); setUsersPage(1); }}
            className="h-11 rounded-lg border border-gray-200 bg-white px-3.5 text-sm text-gray-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
          >
            <option value="">All Roles</option>
            <option value="admin">Admin</option>
            <option value="officer">Officer</option>
            <option value="analyst">Analyst</option>
            <option value="viewer">Viewer</option>
          </select>
          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setUsersPage(1); }}
            className="h-11 rounded-lg border border-gray-200 bg-white px-3.5 text-sm text-gray-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
          >
            <option value="">All Status</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
          <select
            value={approvalFilter}
            onChange={(e) => { setApprovalFilter(e.target.value); setUsersPage(1); }}
            className="h-11 rounded-lg border border-gray-200 bg-white px-3.5 text-sm text-gray-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
          >
            <option value="">All Approvals</option>
            <option value="pending">Pending Approval</option>
            <option value="approved">Approved</option>
          </select>
        </div>

        {usersLoading ? (
          <LoadingState text="Loading users..." />
        ) : usersError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4">
            <p className="text-sm text-red-700">{usersError}</p>
            <button
              onClick={fetchUsers}
              className="mt-2 inline-flex items-center gap-1 rounded-lg bg-red-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-500"
            >
              <RefreshCw className="h-3 w-3" />
              Retry
            </button>
          </div>
        ) : users.length === 0 ? (
          <EmptyState title="No users found" description="Try adjusting your search or filters." icon={<Users className="h-10 w-10" />} />
        ) : (
          <>
            <div className="overflow-x-auto rounded-xl border border-gray-200">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50">
                    <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500">User ID</th>
                    <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500">Name</th>
                    <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500">Email</th>
                    <th className="hidden px-4 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500 lg:table-cell">Department</th>
                    <th className="hidden px-4 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500 lg:table-cell">Designation</th>
                    <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500">Role</th>
                    <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500">Status</th>
                    <th className="hidden px-4 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500 xl:table-cell">Created</th>
                    <th className="hidden px-4 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500 xl:table-cell">Last Login</th>
                    <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {users.map((u, i) => (
                    <tr
                      key={u.id}
                      className={`cursor-pointer transition-colors hover:bg-blue-50/40 ${i % 2 === 1 ? 'bg-gray-50/50' : ''}`}
                      onClick={() => openDetails(u)}
                    >
                      <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-navy-900" style={{ fontFamily: 'ui-monospace, monospace' }}>
                        {u.userId || u.id.slice(0, 8)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 font-medium text-navy-900">{u.fullName}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">{u.email}</td>
                      <td className="hidden whitespace-nowrap px-4 py-3 text-sm text-gray-600 lg:table-cell">{u.department || '—'}</td>
                      <td className="hidden whitespace-nowrap px-4 py-3 text-sm text-gray-600 lg:table-cell">{u.designation || '—'}</td>
                      <td className="whitespace-nowrap px-4 py-3">
                        {u.id === currentUser?.id ? (
                          <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${ROLE_BADGE[u.role] || ''}`}>
                            {roleLabels[u.role] || u.role}
                          </span>
                        ) : (
                          <select
                            value={u.role}
                            onChange={(e) => { e.stopPropagation(); handleRoleChange(u, e.target.value); }}
                            onClick={(e) => e.stopPropagation()}
                            className="cursor-pointer rounded-full border-0 px-2 py-0.5 text-xs font-medium outline-none"
                            style={{ backgroundColor: 'transparent' }}
                          >
                            {Object.entries(roleLabels).map(([val, lbl]) => (
                              <option key={val} value={val}>{lbl}</option>
                            ))}
                          </select>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <div className="flex flex-col items-start gap-1">
                          <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${u.isActive ? 'bg-green-50 text-green-700 ring-green-200' : 'bg-gray-100 text-gray-600 ring-gray-200'}`}>
                            {u.isActive ? 'Active' : 'Inactive'}
                          </span>
                          {u.isApproved === false && (
                            <span className="inline-flex rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700 ring-1 ring-amber-200">
                              Pending approval
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="hidden whitespace-nowrap px-4 py-3 text-sm text-gray-600 xl:table-cell">{formatDate(u.createdAt)}</td>
                      <td className="hidden whitespace-nowrap px-4 py-3 text-sm text-gray-600 xl:table-cell">{formatDate(u.lastLogin)}</td>
                      <td className="whitespace-nowrap px-4 py-3" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center gap-1.5">
                          {u.isApproved === false && u.id !== currentUser?.id && (
                            <button
                              onClick={() => handleApprovalToggle(u)}
                              className="rounded-lg bg-blue-600 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-blue-500"
                              title="Approve this account"
                            >
                              Approve
                            </button>
                          )}
                          {u.isApproved !== false && u.id !== currentUser?.id && (
                            <button
                              onClick={() => handleApprovalToggle(u)}
                              className="rounded-lg border border-amber-300 bg-white px-2.5 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-50"
                              title="Revoke portfolio access for this account"
                            >
                              Revoke
                            </button>
                          )}
                          <button
                            onClick={() => openEdit(u)}
                            className="rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-navy-900 hover:bg-gray-50"
                          >
                            Edit
                          </button>
                          {u.isApproved !== false && (
                            <button
                              onClick={() => handleResetPassword(u)}
                              className="rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-navy-900 hover:bg-gray-50"
                            >
                              Reset Pwd
                            </button>
                          )}
                          {u.id !== currentUser?.id && (
                            <button
                              onClick={() => handleStatusToggle(u)}
                              className={`rounded-lg px-2.5 py-1.5 text-xs font-semibold text-white ${u.isActive ? 'bg-red-600 hover:bg-red-500' : 'bg-green-600 hover:bg-green-500'}`}
                            >
                              {u.isActive ? 'Deactivate' : 'Activate'}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex items-center justify-between">
              <p className="text-sm text-gray-500">
                Page {usersPage} of {usersTotalPages} &middot; {usersTotal} users
              </p>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setUsersPage((p) => Math.max(1, p - 1))}
                  disabled={usersPage <= 1}
                  className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-navy-900 hover:bg-gray-50 disabled:opacity-40"
                >
                  <ChevronLeft className="h-4 w-4" />
                  Prev
                </button>
                <button
                  onClick={() => setUsersPage((p) => Math.min(usersTotalPages, p + 1))}
                  disabled={usersPage >= usersTotalPages}
                  className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-navy-900 hover:bg-gray-50 disabled:opacity-40"
                >
                  Next
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          </>
        )}
      </section>

      <section className="mb-8">
        <div className="mb-4 flex items-center gap-2">
          <div className="rounded-lg bg-blue-50 p-2">
            <Shield className="h-5 w-5 text-blue-600" />
          </div>
          <h2 className="text-base font-semibold text-navy-900 lg:text-lg">
            Role Management
          </h2>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {(['admin', 'officer', 'analyst', 'viewer'] as const).map((role) => {
            const info = ROLE_DESCRIPTIONS[role];
            return (
              <div key={role} className="rounded-xl border border-gray-200 bg-white p-5">
                <div className="mb-3 flex items-center gap-2">
                  {info.icon}
                  <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${ROLE_BADGE[role]}`}>
                    {info.label}
                  </span>
                </div>
                <p className="text-sm text-gray-600">{info.desc}</p>
              </div>
            );
          })}
        </div>
      </section>

      <section className="mb-8 rounded-xl border border-gray-200 bg-white p-5 lg:p-6">
        <div className="mb-4 flex items-center gap-2">
          <div className="rounded-lg bg-blue-50 p-2">
            <FileText className="h-5 w-5 text-blue-600" />
          </div>
          <h2 className="text-base font-semibold text-navy-900 lg:text-lg">
            Recent Activity
          </h2>
        </div>
        {logsLoading ? (
          <LoadingState text="Loading activity..." />
        ) : logs.length === 0 ? (
          <EmptyState
            title="No activity recorded"
            description="Audit log entries will appear here."
            icon={<FileText className="h-10 w-10" />}
          />
        ) : (
          <>
            <div className="overflow-x-auto rounded-xl border border-gray-200">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50">
                    <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500">Time</th>
                    <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500">Admin</th>
                    <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500">Action</th>
                    <th className="hidden px-4 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500 md:table-cell">Target</th>
                    <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500">Details</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {logs.map((log, i) => (
                    <tr key={log.id || i} className={i % 2 === 1 ? 'bg-gray-50/50' : ''}>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600">
                        {formatDateTime(log.timestamp || log.createdAt)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-navy-900">
                        {log.actorName || log.actorUserId || '—'}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <span className="inline-flex rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 ring-1 ring-blue-200">
                          {log.action || '—'}
                        </span>
                      </td>
                      <td className="hidden whitespace-nowrap px-4 py-3 text-sm text-gray-600 md:table-cell">
                        {log.targetUserId || '—'}
                      </td>
                      <td className="max-w-xs truncate px-4 py-3 text-sm text-gray-600">
                        {log.details || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex items-center justify-between">
              <p className="text-sm text-gray-500">
                Page {logsPage} of {logsTotalPages}
              </p>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setLogsPage((p) => Math.max(1, p - 1))}
                  disabled={logsPage <= 1}
                  className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-navy-900 hover:bg-gray-50 disabled:opacity-40"
                >
                  <ChevronLeft className="h-4 w-4" />
                  Prev
                </button>
                <button
                  onClick={() => setLogsPage((p) => Math.min(logsTotalPages, p + 1))}
                  disabled={logsPage >= logsTotalPages}
                  className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-navy-900 hover:bg-gray-50 disabled:opacity-40"
                >
                  Next
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          </>
        )}
      </section>

      <ModalShell open={createModalOpen} onClose={() => setCreateModalOpen(false)}>
        {createStep === 'success' && createdUser ? (
          <div className="text-center">
            <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-green-100">
              <Check className="h-8 w-8 text-green-600" />
            </div>
            <h3 className="mb-1 text-lg font-semibold text-navy-900">
              {createdUser.temporaryPassword ? 'User Created Successfully' : 'Password Generated'}
            </h3>
            <p className="mb-6 text-sm text-gray-500">
              {createdUser.temporaryPassword
                ? 'The account has been created. Share these credentials securely.'
                : 'A new temporary password has been generated.'}
            </p>
            <div className="mb-4 rounded-lg bg-gray-50 p-4 text-left space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-gray-500">User ID</span>
                <span className="font-medium text-navy-900" style={{ fontFamily: 'ui-monospace, monospace' }}>{createdUser.userId}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-500">Name</span>
                <span className="font-medium text-navy-900">{createdUser.fullName}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-500">Email</span>
                <span className="font-medium text-navy-900">{createdUser.email}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-500">Role</span>
                <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${ROLE_BADGE[createdUser.role] || ''}`}>
                  {roleLabels[createdUser.role] || capitalize(createdUser.role)}
                </span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-500">Temporary Password</span>
                <span className="font-medium text-navy-900" style={{ fontFamily: 'ui-monospace, monospace' }}>
                  {createdUser.temporaryPassword}
                </span>
              </div>
            </div>
            <div className="mb-6 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-left">
              <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-600" />
              <p className="text-xs text-amber-700">
                Save these credentials securely. The temporary password will not be shown again.
              </p>
            </div>
            <div className="flex gap-3">
              <button
                onClick={() => {
                  const text = `User ID: ${createdUser.userId}\nEmail: ${createdUser.email}\nTemporary Password: ${createdUser.temporaryPassword}`;
                  handleCopy(text);
                }}
                className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-500"
              >
                {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                {copied ? 'Copied' : 'Copy Credentials'}
              </button>
              <button
                onClick={() => setCreateModalOpen(false)}
                className="flex-1 rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-navy-900 hover:bg-gray-50"
              >
                Close
              </button>
            </div>
          </div>
        ) : (
          <>
            <h3 className="mb-5 text-lg font-semibold text-navy-900">Create User</h3>
            {createError && (
              <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {createError}
              </div>
            )}
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">Full Name *</label>
                <input
                  type="text"
                  value={createForm.fullName}
                  onChange={(e) => setCreateForm((f) => ({ ...f, fullName: e.target.value }))}
                  className="h-11 w-full rounded-lg border border-gray-200 bg-white px-3.5 text-sm text-gray-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">Email *</label>
                <input
                  type="email"
                  value={createForm.email}
                  onChange={(e) => setCreateForm((f) => ({ ...f, email: e.target.value }))}
                  className="h-11 w-full rounded-lg border border-gray-200 bg-white px-3.5 text-sm text-gray-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700">Department</label>
                  <input
                    type="text"
                    value={createForm.department}
                    onChange={(e) => setCreateForm((f) => ({ ...f, department: e.target.value }))}
                    className="h-11 w-full rounded-lg border border-gray-200 bg-white px-3.5 text-sm text-gray-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700">Designation</label>
                  <input
                    type="text"
                    value={createForm.designation}
                    onChange={(e) => setCreateForm((f) => ({ ...f, designation: e.target.value }))}
                    className="h-11 w-full rounded-lg border border-gray-200 bg-white px-3.5 text-sm text-gray-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                  />
                </div>
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">Role</label>
                <select
                  value={createForm.role}
                  onChange={(e) => setCreateForm((f) => ({ ...f, role: e.target.value }))}
                  className="h-11 w-full rounded-lg border border-gray-200 bg-white px-3.5 text-sm text-gray-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                >
                  {Object.entries(roleLabels).map(([val, lbl]) => (
                    <option key={val} value={val}>{lbl}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">Temporary Password</label>
                <div className="rounded-lg border border-blue-100 bg-blue-50 px-3.5 py-2.5 text-xs text-blue-800">
                  A cryptographically secure temporary password will be generated
                  by the server and shown once after creation. The user must
                  change it on their first login.
                </div>
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">Account Status</label>
                <select
                  value={createForm.isActive ? 'active' : 'inactive'}
                  onChange={(e) => setCreateForm((f) => ({ ...f, isActive: e.target.value === 'active' }))}
                  className="h-11 w-full rounded-lg border border-gray-200 bg-white px-3.5 text-sm text-gray-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                >
                  <option value="active">Active</option>
                  <option value="inactive">Inactive</option>
                </select>
              </div>
            </div>
            <div className="mt-6 flex gap-3">
              <button
                onClick={handleCreate}
                disabled={createSaving}
                className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-50"
              >
                {createSaving ? 'Creating...' : 'Create User'}
              </button>
              <button
                onClick={() => setCreateModalOpen(false)}
                className="rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-navy-900 hover:bg-gray-50"
              >
                Cancel
              </button>
            </div>
          </>
        )}
      </ModalShell>

      <ModalShell open={editModalOpen} onClose={() => setEditModalOpen(false)}>
        <h3 className="mb-5 text-lg font-semibold text-navy-900">Edit User</h3>
        {editError && (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {editError}
          </div>
        )}
        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Full Name</label>
            <input
              type="text"
              value={editForm.fullName}
              onChange={(e) => setEditForm((f) => ({ ...f, fullName: e.target.value }))}
              className="h-11 w-full rounded-lg border border-gray-200 bg-white px-3.5 text-sm text-gray-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Email</label>
            <input
              type="email"
              value={editForm.email}
              onChange={(e) => setEditForm((f) => ({ ...f, email: e.target.value }))}
              className="h-11 w-full rounded-lg border border-gray-200 bg-white px-3.5 text-sm text-gray-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Department</label>
            <input
              type="text"
              value={editForm.department}
              onChange={(e) => setEditForm((f) => ({ ...f, department: e.target.value }))}
              className="h-11 w-full rounded-lg border border-gray-200 bg-white px-3.5 text-sm text-gray-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Designation</label>
            <input
              type="text"
              value={editForm.designation}
              onChange={(e) => setEditForm((f) => ({ ...f, designation: e.target.value }))}
              className="h-11 w-full rounded-lg border border-gray-200 bg-white px-3.5 text-sm text-gray-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
            />
          </div>
        </div>
        <div className="mt-6 flex gap-3">
          <button
            onClick={handleEdit}
            disabled={editSaving}
            className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-50"
          >
            {editSaving ? 'Saving...' : 'Save Changes'}
          </button>
          <button
            onClick={() => setEditModalOpen(false)}
            className="rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-navy-900 hover:bg-gray-50"
          >
            Cancel
          </button>
        </div>
      </ModalShell>

      <ModalShell open={detailsModalOpen} onClose={() => setDetailsModalOpen(false)} maxWidth="max-w-lg">
        {detailsTarget && (
          <>
            <h3 className="mb-5 text-lg font-semibold text-navy-900">User Details</h3>
            <div className="space-y-3">
              {[
                { label: 'User ID', value: detailsTarget.userId || detailsTarget.id, mono: true },
                { label: 'Full Name', value: detailsTarget.fullName },
                { label: 'Email', value: detailsTarget.email },
                { label: 'Department', value: detailsTarget.department || '—' },
                { label: 'Designation', value: detailsTarget.designation || '—' },
                { label: 'Created At', value: formatDateTime(detailsTarget.createdAt) },
                { label: 'Updated At', value: formatDateTime(detailsTarget.updatedAt) },
                { label: 'Last Login', value: formatDateTime(detailsTarget.lastLogin) },
              ].map((row) => (
                <div key={row.label} className="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2">
                  <span className="text-sm text-gray-500">{row.label}</span>
                  <span className={`text-sm font-medium text-navy-900 ${row.mono ? '' : ''}`} style={row.mono ? { fontFamily: 'ui-monospace, monospace' } : undefined}>
                    {row.value}
                  </span>
                </div>
              ))}
              <div className="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2">
                <span className="text-sm text-gray-500">Role</span>
                <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${ROLE_BADGE[detailsTarget.role] || ''}`}>
                  {roleLabels[detailsTarget.role] || detailsTarget.role}
                </span>
              </div>
              <div className="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2">
                <span className="text-sm text-gray-500">Status</span>
                <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${detailsTarget.isActive ? 'bg-green-50 text-green-700 ring-green-200' : 'bg-gray-100 text-gray-600 ring-gray-200'}`}>
                  {detailsTarget.isActive ? 'Active' : 'Inactive'}
                </span>
              </div>
              <div className="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2">
                <span className="text-sm text-gray-500">Approval</span>
                <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${detailsTarget.isApproved === false ? 'bg-amber-50 text-amber-700 ring-amber-200' : 'bg-green-50 text-green-700 ring-green-200'}`}>
                  {detailsTarget.isApproved === false ? 'Pending approval' : 'Approved'}
                </span>
              </div>
            </div>
            <div
                className="mt-6 flex flex-wrap gap-2"
              >
              {detailsTarget.id !== currentUser?.id && (
                <button
                  onClick={() => { setDetailsModalOpen(false); handleApprovalToggle(detailsTarget); }}
                  className={`rounded-lg px-3 py-2 text-sm font-semibold text-white ${detailsTarget.isApproved === false ? 'bg-blue-600 hover:bg-blue-500' : 'border border-amber-300 bg-white text-amber-700 hover:bg-amber-50 font-medium'}`}
                >
                  {detailsTarget.isApproved === false ? 'Approve Account' : 'Revoke Approval'}
                </button>
              )}
              <button
                onClick={() => { setDetailsModalOpen(false); openEdit(detailsTarget); }}
                className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-navy-900 hover:bg-gray-50"
              >
                Edit User
              </button>
              <button
                onClick={() => { setDetailsModalOpen(false); handleResetPassword(detailsTarget); }}
                className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-navy-900 hover:bg-gray-50"
              >
                Reset Password
              </button>
              {detailsTarget.id !== currentUser?.id && (
                <button
                  onClick={() => { setDetailsModalOpen(false); handleStatusToggle(detailsTarget); }}
                  className={`rounded-lg px-3 py-2 text-sm font-semibold text-white ${detailsTarget.isActive ? 'bg-red-600 hover:bg-red-500' : 'bg-green-600 hover:bg-green-500'}`}
                >
                  {detailsTarget.isActive ? 'Deactivate' : 'Activate'}
                </button>
              )}
            </div>
          </>
        )}
      </ModalShell>
    </div>
  );
}
