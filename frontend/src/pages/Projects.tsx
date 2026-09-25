import { useState, useEffect, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { LayoutGrid, Table as TableIcon, Plus } from 'lucide-react';
import { getProjects } from '../services/api';
import type { Project } from '../types';
import { useAuth } from '../context/AuthContext';
import AddProjectModal from '../components/admin/AddProjectModal';
import { SearchBar } from '../components/ui/SearchBar';
import { FilterBar, FilterSelect } from '../components/ui/FilterBar';
import { ProjectTable } from '../components/project/ProjectTable';
import { ProjectCard } from '../components/project/ProjectCard';
import { EmptyState } from '../components/ui/EmptyState';
import { FolderSearch } from 'lucide-react';
import { LoadingState } from '../components/ui/LoadingState';
import { useI18n } from '../i18n';

type ViewMode = 'table' | 'cards';

export default function Projects() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { t, riskLabel } = useI18n();
  const [searchParams] = useSearchParams();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [search, setSearch] = useState(searchParams.get('search') || '');
  const [sectorFilter, setSectorFilter] = useState('All');
  const [riskFilter, setRiskFilter] = useState('All');
  const [stateFilter, setStateFilter] = useState('All');
  const [ministryFilter, setMinistryFilter] = useState('All');
  const [viewMode, setViewMode] = useState<ViewMode>('table');
  const [addProjectOpen, setAddProjectOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const canCreate = user?.role === 'admin' || user?.role === 'officer';

  useEffect(() => {
    let isMounted = true;
    getProjects()
      .then((data) => {
        if (isMounted) {
          setProjects(data);
          setLoading(false);
        }
      })
      .catch(() => {
        if (isMounted) {
          setError(true);
          setLoading(false);
        }
      });
    return () => {
      isMounted = false;
    };
  }, [reloadKey]);

  const sectors = useMemo(() => {
    const unique = Array.from(new Set(projects.map((p) => p.sector)));
    return unique.sort();
  }, [projects]);

  const states = useMemo(() => {
    const unique = Array.from(new Set(projects.map((p) => p.state)));
    return unique.sort();
  }, [projects]);

  const ministries = useMemo(() => {
    const unique = Array.from(new Set(projects.map((p) => p.ministry)));
    return unique.sort();
  }, [projects]);

  const filteredProjects = useMemo(() => {
    return projects.filter((project: Project) => {
      if (search) {
        const q = search.toLowerCase();
        const matchesSearch =
          project.name.toLowerCase().includes(q) ||
          project.ministry.toLowerCase().includes(q) ||
          project.state.toLowerCase().includes(q) ||
          project.id.toLowerCase().includes(q);
        if (!matchesSearch) return false;
      }
      if (sectorFilter !== 'All' && project.sector !== sectorFilter) return false;
      if (riskFilter !== 'All' && project.riskLevel !== riskFilter) return false;
      if (stateFilter !== 'All' && project.state !== stateFilter) return false;
      if (ministryFilter !== 'All' && project.ministry !== ministryFilter) return false;
      return true;
    });
  }, [projects, search, sectorFilter, riskFilter, stateFilter, ministryFilter]);

  const sortedByRisk = useMemo(() => {
    return [...filteredProjects].sort((a, b) => b.riskScore - a.riskScore);
  }, [filteredProjects]);

  return (
    <div className="min-w-0">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-navy-900 lg:text-3xl">
            {t('projects.title')}
          </h1>
          <p className="mt-1 text-sm text-gray-500 lg:text-base">
            {t('projects.subtitle')}
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-lg border border-gray-200 bg-white p-1">
          <button
            onClick={() => setViewMode('table')}
            className={`inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              viewMode === 'table' ? 'bg-blue-600 text-white' : 'text-gray-600 hover:bg-gray-100'
            }`}
          >
            <TableIcon size={14} />
            {t('projects.table')}
          </button>
          <button
            onClick={() => setViewMode('cards')}
            className={`inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              viewMode === 'cards' ? 'bg-blue-600 text-white' : 'text-gray-600 hover:bg-gray-100'
            }`}
          >
            <LayoutGrid size={14} />
            {t('projects.cards')}
          </button>
        </div>
      </div>

      <div className="mb-6 rounded-xl border border-gray-200 bg-white p-4 lg:p-5">
        <FilterBar>
          <div className="w-full sm:w-72">
            <SearchBar value={search} onChange={setSearch} placeholder={t('projects.searchPlaceholder')} />
          </div>
          <FilterSelect
            label={t('projects.filterSector')}
            value={sectorFilter}
            onChange={setSectorFilter}
            options={[
              { value: 'All', label: t('projects.allSectors') },
              ...sectors.map((s) => ({ value: s, label: s })),
            ]}
          />
          <FilterSelect
            label={t('projects.filterRiskLevel')}
            value={riskFilter}
            onChange={setRiskFilter}
            options={[
              { value: 'All', label: t('common.all') },
              { value: 'LOW', label: riskLabel('LOW') },
              { value: 'MEDIUM', label: riskLabel('MEDIUM') },
              { value: 'HIGH', label: riskLabel('HIGH') },
              { value: 'CRITICAL', label: riskLabel('CRITICAL') },
            ]}
          />
          <FilterSelect
            label={t('projects.filterState')}
            value={stateFilter}
            onChange={setStateFilter}
            options={[
              { value: 'All', label: t('projects.allStates') },
              ...states.map((s) => ({ value: s, label: s })),
            ]}
          />
          <FilterSelect
            label={t('projects.filterMinistry')}
            value={ministryFilter}
            onChange={setMinistryFilter}
            options={[
              { value: 'All', label: t('projects.allMinistries') },
              ...ministries.map((m) => ({ value: m, label: m })),
            ]}
          />
          {canCreate && (
            <button
              onClick={() => setAddProjectOpen(true)}
              className="ml-auto inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-blue-500"
            >
              <Plus className="h-4 w-4" />
              {t('projects.addProject')}
            </button>
          )}
        </FilterBar>
      </div>

      {loading ? (
        <LoadingState text={t('projects.loading')} />
      ) : error ? (
        <EmptyState
          title="Unable to connect to GovRisk services"
          description="Please check that the GovRisk backend is running and try again."
          icon={<FolderSearch size={40} />}
        />
      ) : (
        <>
          <p className="mb-4 text-sm text-gray-500">
            {t('projects.showing', { count: filteredProjects.length, total: projects.length })}
          </p>

          {filteredProjects.length === 0 ? (
            <EmptyState
              title={t('projects.noProjects')}
              description={t('projects.noProjectsDesc')}
              icon={<FolderSearch size={40} />}
            />
          ) : viewMode === 'table' ? (
            <ProjectTable
              projects={filteredProjects}
              showPagination={true}
              pageSize={12}
              onRowClick={(project) => navigate(`/projects/${project.id}`)}
            />
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {sortedByRisk.map((project) => (
                <ProjectCard key={project.id} project={project} />
              ))}
            </div>
          )}
        </>
      )}

      <AddProjectModal
        open={addProjectOpen}
        onClose={() => setAddProjectOpen(false)}
        onCreated={() => setReloadKey((k) => k + 1)}
      />
    </div>
  );
}
