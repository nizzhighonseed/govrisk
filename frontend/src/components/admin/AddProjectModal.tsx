import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  X,
  Check,
  AlertTriangle,
  Building2,
  Database,
  TrendingUp,
  Calendar,
  ShieldAlert,
  MapPin,
  Info,
  Loader2,
} from 'lucide-react';
import { createProject, updateProject, ProjectCreateData } from '../../services/api';
import { RiskBadge } from '../ui/RiskBadge';
import { RiskInputs } from '../../types';
import RiskInputsFields from '../project/RiskInputsFields';

const SECTORS = [
  'Transport',
  'Energy',
  'Water',
  'Communication',
  'Social Infrastructure',
  'Mining',
];

const EMPTY_FORM = {
  name: '',
  ministry: '',
  agency: '',
  sector: SECTORS[0],
  state: '',
  district: '',
  originalCost: '',
  revisedCost: '',
  expenditure: '',
  physicalProgress: '',
  financialProgress: '',
  startDate: '',
  completionDate: '',
  predictedCompletionDate: '',
  description: '',
  nodalOfficer: '',
  contactInfo: '',
  lat: '',
  lng: '',
  riskInputs: {} as RiskInputs,
};

type FormState = typeof EMPTY_FORM;

function parseNum(s: string): number {
  const n = Number(s.replace(/,/g, ''));
  return isNaN(n) ? Number.NaN : n;
}

function ModalShell({
  open,
  onClose,
  children,
}: {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[60] overflow-y-auto p-4">
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative mx-auto my-8 w-full max-w-3xl rounded-2xl bg-white p-6 pb-12 shadow-2xl sm:my-12">
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

function Section({
  number,
  icon,
  title,
  children,
}: {
  number: number;
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5">
      <div className="mb-4 flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-blue-50 text-sm font-bold text-blue-600">
          {number}
        </span>
        <span className="rounded-lg bg-blue-50 p-1">{icon}</span>
        <h4 className="text-sm font-semibold text-navy-900">{title}</h4>
      </div>
      {children}
    </section>
  );
}

function Field({
  label,
  required,
  hint,
  error,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1.5 block text-xs font-medium text-gray-500">
        {label} {required && <span className="text-red-500">*</span>}
      </label>
      {children}
      {hint && !error && <p className="mt-1 text-xs text-gray-400">{hint}</p>}
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  );
}

const inputClass =
  'h-11 w-full rounded-lg border border-gray-200 bg-white px-3.5 text-sm text-gray-700 outline-none transition-all placeholder:text-gray-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20';

export default function AddProjectModal({
  open,
  onClose,
  onCreated,
  mode = 'create',
  initial,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (project: any) => void;
  mode?: 'create' | 'edit';
  initial?: any;
}) {
  const navigate = useNavigate();
  const isEdit = mode === 'edit';
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [step, setStep] = useState<'form' | 'success'>('form');
  const [created, setCreated] = useState<any>(null);
  const touchedRef = useRef(false);

  useEffect(() => {
    if (open && isEdit && initial) {
      const p = initial;
      const sameCost =
        p.currentCost != null && p.originalCost != null && p.currentCost === p.originalCost;
      setForm({
        name: p.name || '',
        ministry: p.ministry || '',
        agency: p.agency || '',
        sector: p.sector || SECTORS[0],
        state: p.state || '',
        district: p.district || '',
        originalCost: p.originalCost != null ? String(p.originalCost) : '',
        revisedCost: sameCost ? '' : p.currentCost != null ? String(p.currentCost) : '',
        expenditure: p.expenditure != null ? String(p.expenditure) : '',
        physicalProgress: p.physicalProgress != null ? String(p.physicalProgress) : '',
        financialProgress: p.financialProgress != null ? String(p.financialProgress) : '',
        startDate: p.startDate || '',
        completionDate: p.expectedCompletion || '',
        predictedCompletionDate: p.predictedCompletion || '',
        description: p.description || '',
        nodalOfficer: p.nodalOfficer || '',
        contactInfo: p.contactInfo || '',
        lat: p.lat != null ? String(p.lat) : '',
        lng: p.lng != null ? String(p.lng) : '',
        riskInputs: p.riskInputs || {},
      });
      setErrors({});
      setSubmitError('');
      setStep('form');
      setCreated(null);
      touchedRef.current = false;
    }
  }, [open, isEdit, initial]);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    touchedRef.current = true;
    setForm((f) => ({ ...f, [key]: value }));
    setErrors((e) => ({ ...e, [key]: '' }));
    setSubmitError('');
  }

  function handleClose() {
    if (step === 'success') {
      setStep('form');
      setCreated(null);
      setForm(EMPTY_FORM);
      touchedRef.current = false;
      onClose();
      return;
    }
    if (touchedRef.current && !window.confirm('Discard the entered project information?')) return;
    setForm(EMPTY_FORM);
    setErrors({});
    setSubmitError('');
    touchedRef.current = false;
    onClose();
  }

  function validate(): boolean {
    const e: Record<string, string> = {};
    if (!form.name.trim()) e.name = 'Project name is required';
    if (!form.ministry.trim()) e.ministry = 'Ministry is required';
    if (!form.agency.trim()) e.agency = 'Implementing agency is required';
    if (!form.state.trim()) e.state = 'State is required';

    const oc = parseNum(form.originalCost);
    if (form.originalCost === '' || isNaN(oc) || oc <= 0)
      e.originalCost = 'Enter an approved cost greater than 0';

    if (form.revisedCost !== '') {
      const rc = parseNum(form.revisedCost);
      if (isNaN(rc) || rc < 0) e.revisedCost = 'Revised cost must be 0 or more';
    }
    if (form.expenditure !== '') {
      const ex = parseNum(form.expenditure);
      if (isNaN(ex) || ex < 0) e.expenditure = 'Expenditure must be 0 or more';
    }

    const pp = parseNum(form.physicalProgress);
    if (form.physicalProgress === '' || isNaN(pp))
      e.physicalProgress = 'Physical progress is required';
    else if (pp < 0 || pp > 100) e.physicalProgress = 'Must be between 0 and 100';

    if (form.financialProgress !== '') {
      const fp = parseNum(form.financialProgress);
      if (isNaN(fp) || fp < 0 || fp > 100) e.financialProgress = 'Must be between 0 and 100';
    }

    if (!form.startDate) e.startDate = 'Start date is required';
    if (!form.completionDate) e.completionDate = 'Completion date is required';
    if (form.startDate && form.completionDate && form.completionDate < form.startDate) {
      e.completionDate = 'Completion date cannot be before start date';
    }
    if (
      form.predictedCompletionDate &&
      form.startDate &&
      form.predictedCompletionDate < form.startDate
    ) {
      e.predictedCompletionDate = 'Cannot be before start date';
    }

    if (form.lat !== '') {
      const lat = parseNum(form.lat);
      if (isNaN(lat) || lat < -90 || lat > 90) e.lat = 'Latitude must be between -90 and 90';
    }
    if (form.lng !== '') {
      const lng = parseNum(form.lng);
      if (isNaN(lng) || lng < -180 || lng > 180) e.lng = 'Longitude must be between -180 and 180';
    }

    if (form.lat !== '' && form.lng === '') e.lng = 'Longitude is required when latitude is given';
    if (form.lng !== '' && form.lat === '') e.lat = 'Latitude is required when longitude is given';

    setErrors(e);
    return Object.keys(e).length === 0;
  }

  function buildPayload(): ProjectCreateData {
    const numOrDefault = (s: string): number | null => (s === '' ? null : parseNum(s));
    const strOrUndef = (s: string): string | undefined => (s.trim() === '' ? undefined : s.trim());
    return {
      name: form.name.trim(),
      ministry: form.ministry.trim(),
      agency: form.agency.trim(),
      sector: form.sector,
      state: form.state.trim(),
      district: strOrUndef(form.district),
      originalCost: parseNum(form.originalCost),
      revisedCost: numOrDefault(form.revisedCost),
      expenditure: numOrDefault(form.expenditure),
      physicalProgress: parseNum(form.physicalProgress),
      financialProgress: numOrDefault(form.financialProgress),
      startDate: form.startDate,
      completionDate: form.completionDate,
      predictedCompletionDate: strOrUndef(form.predictedCompletionDate) ?? null,
      description: strOrUndef(form.description),
      nodalOfficer: strOrUndef(form.nodalOfficer),
      contactInfo: strOrUndef(form.contactInfo),
      lat: numOrDefault(form.lat),
      lng: numOrDefault(form.lng),
      riskInputs: form.riskInputs,
    };
  }

  async function handleSubmit() {
    if (!validate()) return;
    setSaving(true);
    setSubmitError('');
    try {
      const payload = buildPayload();
      const res =
        isEdit && initial ? await updateProject(initial.id, payload) : await createProject(payload);
      setCreated(res);
      setStep('success');
      onCreated(res);
    } catch (e: any) {
      setSubmitError(e.message || 'Failed to save project');
    } finally {
      setSaving(false);
    }
  }

  function handleViewProject() {
    if (!created) return;
    handleClose();
    navigate(`/projects/${created.id}`);
  }

  return (
    <ModalShell open={open} onClose={handleClose}>
      {step === 'success' && created ? (
        <div className="text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-green-100">
            <Check className="h-8 w-8 text-green-600" />
          </div>
          <h3 className="mb-1 text-lg font-semibold text-navy-900">
            {isEdit ? 'Project updated successfully' : 'Project created successfully'}
          </h3>
          <p className="mb-6 text-sm text-gray-500">The project has been saved to the database.</p>
          <div className="mb-4 space-y-2 rounded-lg bg-gray-50 p-4 text-left">
            <div className="flex justify-between text-sm">
              <span className="text-gray-500">Project ID</span>
              <span
                className="font-medium text-navy-900"
                style={{ fontFamily: 'ui-monospace, monospace' }}
              >
                {created.id}
              </span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-gray-500">Project Name</span>
              <span className="font-medium text-navy-900">{created.name}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-gray-500">Risk Level</span>
              <RiskBadge level={created.riskLevel} size="sm" />
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-gray-500">Risk Score</span>
              <span className="font-medium text-navy-900">{created.riskScore}/100</span>
            </div>
          </div>
          {created.riskLevel === 'HIGH' || created.riskLevel === 'CRITICAL' ? (
            <div className="mb-6 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-left">
              <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-600" />
              <p className="text-xs text-amber-700">
                A {created.riskLevel} risk alert has been generated automatically for this project.
              </p>
            </div>
          ) : null}
          <div className="flex gap-3">
            <button
              onClick={handleViewProject}
              className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-500"
            >
              View Project
            </button>
            <button
              onClick={handleClose}
              className="rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-navy-900 hover:bg-gray-50"
            >
              Close
            </button>
          </div>
        </div>
      ) : (
        <>
          <h3 className="mb-1 text-lg font-semibold text-navy-900">
            {isEdit ? 'Edit Project' : 'Add New Project'}
          </h3>
          <p className="mb-5 text-sm text-gray-500">
            {isEdit
              ? 'Update the project information. Risk is recalculated automatically by the backend.'
              : 'Register a new infrastructure project. Risk is calculated automatically by the backend.'}
          </p>

          {submitError && (
            <div className="mb-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3">
              <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-red-500" />
              <p className="text-sm text-red-700">{submitError}</p>
            </div>
          )}

          <div className="grid grid-cols-1 gap-5">
            <Section
              number={1}
              icon={<Building2 className="h-4 w-4 text-blue-600" />}
              title="Basic Information"
            >
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <Field label="Project Name" required error={errors.name}>
                    <input
                      value={form.name}
                      onChange={(e) => set('name', e.target.value)}
                      placeholder="e.g. National Highway Expansion Phase II"
                      className={inputClass}
                    />
                  </Field>
                </div>
                <Field label="Ministry" required error={errors.ministry}>
                  <input
                    value={form.ministry}
                    onChange={(e) => set('ministry', e.target.value)}
                    placeholder="e.g. Ministry of Road Transport"
                    className={inputClass}
                  />
                </Field>
                <Field label="Department / Implementing Agency" required error={errors.agency}>
                  <input
                    value={form.agency}
                    onChange={(e) => set('agency', e.target.value)}
                    placeholder="e.g. National Highways Authority of India"
                    className={inputClass}
                  />
                </Field>
                <Field label="Sector" required>
                  <select
                    value={form.sector}
                    onChange={(e) => set('sector', e.target.value)}
                    className={inputClass}
                  >
                    {SECTORS.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </Field>
                <div className="grid grid-cols-2 gap-4">
                  <Field label="State" required error={errors.state}>
                    <input
                      value={form.state}
                      onChange={(e) => set('state', e.target.value)}
                      placeholder="e.g. Gujarat"
                      className={inputClass}
                    />
                  </Field>
                  <Field label="District / Location">
                    <input
                      value={form.district}
                      onChange={(e) => set('district', e.target.value)}
                      placeholder="e.g. Ahmedabad"
                      className={inputClass}
                    />
                  </Field>
                </div>
              </div>
            </Section>

            <Section
              number={2}
              icon={<Database className="h-4 w-4 text-blue-600" />}
              title="Financial Information"
            >
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <Field label="Approved Cost (₹ Cr)" required error={errors.originalCost}>
                  <input
                    inputMode="decimal"
                    value={form.originalCost}
                    onChange={(e) => set('originalCost', e.target.value)}
                    placeholder="e.g. 18000"
                    className={inputClass}
                  />
                </Field>
                <Field label="Revised Cost (₹ Cr)" error={errors.revisedCost}>
                  <input
                    inputMode="decimal"
                    value={form.revisedCost}
                    onChange={(e) => set('revisedCost', e.target.value)}
                    placeholder="Optional"
                    className={inputClass}
                  />
                </Field>
                <Field label="Expenditure to Date (₹ Cr)" error={errors.expenditure}>
                  <input
                    inputMode="decimal"
                    value={form.expenditure}
                    onChange={(e) => set('expenditure', e.target.value)}
                    placeholder="Optional"
                    className={inputClass}
                  />
                </Field>
              </div>
            </Section>

            <Section
              number={3}
              icon={<TrendingUp className="h-4 w-4 text-blue-600" />}
              title="Progress"
            >
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <Field label="Physical Progress %" required error={errors.physicalProgress}>
                  <input
                    inputMode="decimal"
                    value={form.physicalProgress}
                    onChange={(e) => set('physicalProgress', e.target.value)}
                    placeholder="0 - 100"
                    className={inputClass}
                  />
                </Field>
                <Field label="Financial Progress %" error={errors.financialProgress}>
                  <input
                    inputMode="decimal"
                    value={form.financialProgress}
                    onChange={(e) => set('financialProgress', e.target.value)}
                    placeholder="0 - 100"
                    className={inputClass}
                  />
                </Field>
              </div>
            </Section>

            <Section
              number={4}
              icon={<Calendar className="h-4 w-4 text-blue-600" />}
              title="Timeline"
            >
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <Field label="Start Date" required error={errors.startDate}>
                  <input
                    type="date"
                    value={form.startDate}
                    onChange={(e) => set('startDate', e.target.value)}
                    className={inputClass}
                  />
                </Field>
                <Field label="Original Completion Date" required error={errors.completionDate}>
                  <input
                    type="date"
                    value={form.completionDate}
                    onChange={(e) => set('completionDate', e.target.value)}
                    className={inputClass}
                  />
                </Field>
                <Field label="Expected Completion Date" error={errors.predictedCompletionDate}>
                  <input
                    type="date"
                    value={form.predictedCompletionDate}
                    onChange={(e) => set('predictedCompletionDate', e.target.value)}
                    className={inputClass}
                  />
                </Field>
              </div>
            </Section>

            <Section
              number={5}
              icon={<ShieldAlert className="h-4 w-4 text-blue-600" />}
              title="Risk Assessment (server-calculated)"
            >
              <div className="flex items-start gap-3 rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm text-gray-500">
                <ShieldAlert className="mt-0.5 h-5 w-5 flex-shrink-0 text-gray-400" />
                <div>
                  <p className="text-sm text-gray-600">
                    Risk is calculated by the backend after this project is saved.
                  </p>
                  <p className="mt-1 text-xs text-gray-400">
                    The canonical score, level, factors, recommendations, and confidence are
                    returned in the saved project response.
                  </p>
                </div>
              </div>
            </Section>

            <Section
              number={6}
              icon={<ShieldAlert className="h-4 w-4 text-blue-600" />}
              title="On-Ground Risk Inputs (optional)"
            >
              <RiskInputsFields value={form.riskInputs} onChange={(v) => set('riskInputs', v)} />
            </Section>

            <Section
              number={7}
              icon={<MapPin className="h-4 w-4 text-blue-600" />}
              title="Location (for Risk Map)"
            >
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <Field label="Latitude" error={errors.lat} hint="Between -90 and 90">
                  <input
                    inputMode="decimal"
                    value={form.lat}
                    onChange={(e) => set('lat', e.target.value)}
                    placeholder="e.g. 23.0225"
                    className={inputClass}
                  />
                </Field>
                <Field label="Longitude" error={errors.lng} hint="Between -180 and 180">
                  <input
                    inputMode="decimal"
                    value={form.lng}
                    onChange={(e) => set('lng', e.target.value)}
                    placeholder="e.g. 72.5714"
                    className={inputClass}
                  />
                </Field>
              </div>
            </Section>

            <Section
              number={8}
              icon={<Info className="h-4 w-4 text-blue-600" />}
              title="Additional Information"
            >
              <div className="grid grid-cols-1 gap-4">
                <Field label="Project Description">
                  <textarea
                    value={form.description}
                    onChange={(e) => set('description', e.target.value)}
                    placeholder="Brief description of the project scope and objectives"
                    className="w-full rounded-lg border border-gray-200 bg-white px-3.5 py-2.5 text-sm text-gray-700 outline-none transition-all placeholder:text-gray-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                    rows={3}
                  />
                </Field>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <Field label="Project Director / Nodal Officer">
                    <input
                      value={form.nodalOfficer}
                      onChange={(e) => set('nodalOfficer', e.target.value)}
                      placeholder="e.g. S. K. Patel"
                      className={inputClass}
                    />
                  </Field>
                  <Field label="Contact Information">
                    <input
                      value={form.contactInfo}
                      onChange={(e) => set('contactInfo', e.target.value)}
                      placeholder="Email or phone"
                      className={inputClass}
                    />
                  </Field>
                </div>
              </div>
            </Section>
          </div>

          <div className="mt-6 flex gap-3">
            <button
              onClick={handleSubmit}
              disabled={saving}
              className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {saving ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {isEdit ? 'Saving Changes...' : 'Creating Project...'}
                </>
              ) : isEdit ? (
                'Save Changes'
              ) : (
                'Create Project'
              )}
            </button>
            <button
              onClick={handleClose}
              disabled={saving}
              className="rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-navy-900 hover:bg-gray-50 disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </>
      )}
    </ModalShell>
  );
}
