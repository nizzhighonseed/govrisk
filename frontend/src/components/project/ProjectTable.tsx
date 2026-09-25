import { useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight, ChevronsUpDown, ChevronUp, ChevronDown } from 'lucide-react';
import type { Project } from '../../types';
import { ProgressBar } from '../ui/ProgressBar';
import { RiskScore } from '../ui/RiskScore';
import { RiskBadge } from '../ui/RiskBadge';

interface ProjectTableProps {
  projects: Project[];
  onRowClick?: (project: Project) => void;
  showPagination?: boolean;
  pageSize?: number;
}

type SortKey =
  | 'name'
  | 'ministry'
  | 'sector'
  | 'state'
  | 'originalCost'
  | 'currentCost'
  | 'physicalProgress'
  | 'riskScore'
  | 'riskLevel';
type SortDir = 'asc' | 'desc';

const rankOfRisk = { LOW: 1, MEDIUM: 2, HIGH: 3, CRITICAL: 4 } as const;

function cellValue(project: Project, key: SortKey): string | number | null {
  switch (key) {
    case 'riskLevel':
      return rankOfRisk[project.riskLevel];
    default:
      return project[key];
  }
}

const inrFormatter = new Intl.NumberFormat('en-IN');

function formatCost(value: number) {
  return `₹${inrFormatter.format(value)} Cr`;
}

interface SortHeaderProps {
  label: string;
  col: SortKey;
  align?: 'left' | 'right' | 'center';
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (key: SortKey) => void;
}

function SortHeader({ label, col, align = 'left', sortKey, sortDir, onSort }: SortHeaderProps) {
  const active = sortKey === col;
  const icon = active ? (
    sortDir === 'asc' ? (
      <ChevronUp size={14} />
    ) : (
      <ChevronDown size={14} />
    )
  ) : (
    <ChevronsUpDown size={14} />
  );
  const alignClass =
    align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left';
  return (
    <th className={`px-4 py-3 font-medium ${alignClass}`}>
      <button
        onClick={() => onSort(col)}
        className={`inline-flex items-center gap-1 uppercase tracking-wider transition-colors hover:text-gray-900 ${
          active ? 'text-blue-700' : 'text-gray-500'
        }`}
      >
        {label}
        {icon}
      </button>
    </th>
  );
}

export function ProjectTable({
  projects,
  onRowClick,
  showPagination = false,
  pageSize = 10,
}: ProjectTableProps) {
  const [currentPage, setCurrentPage] = useState(1);
  const [sortKey, setSortKey] = useState<SortKey>('riskScore');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const sortedProjects = useMemo(() => {
    const sorted = [...projects].sort((a, b) => {
      const av = cellValue(a, sortKey);
      const bv = cellValue(b, sortKey);
      // A missing measurement is not 0. JavaScript would coerce null into 0 and
      // rank unreported projects as if they had no progress, so unreported rows
      // are always pushed to the end of the list.
      if (av === null || bv === null) {
        if (av === bv) return 0;
        return av === null ? 1 : -1;
      }
      let cmp = 0;
      if (typeof av === 'string' && typeof bv === 'string') {
        cmp = av.localeCompare(bv);
      } else {
        cmp = (av as number) - (bv as number);
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return sorted;
  }, [projects, sortKey, sortDir]);

  const totalPages = Math.max(Math.ceil(sortedProjects.length / pageSize), 1);
  const safePage = Math.min(currentPage, totalPages);

  const pagedProjects = useMemo(() => {
    if (!showPagination) return sortedProjects;
    const start = (safePage - 1) * pageSize;
    return sortedProjects.slice(start, start + pageSize);
  }, [sortedProjects, showPagination, safePage, pageSize]);

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
    setCurrentPage(1);
  };

  const start = sortedProjects.length === 0 ? 0 : (safePage - 1) * pageSize + 1;
  const end = Math.min(safePage * pageSize, sortedProjects.length);

  return (
    <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="bg-gray-50">
            <tr className="text-xs uppercase tracking-wider text-gray-500">
              <SortHeader
                label="Project"
                col="name"
                sortKey={sortKey}
                sortDir={sortDir}
                onSort={toggleSort}
              />
              <SortHeader
                label="Ministry"
                col="ministry"
                sortKey={sortKey}
                sortDir={sortDir}
                onSort={toggleSort}
              />
              <SortHeader
                label="Sector"
                col="sector"
                sortKey={sortKey}
                sortDir={sortDir}
                onSort={toggleSort}
              />
              <SortHeader
                label="State"
                col="state"
                sortKey={sortKey}
                sortDir={sortDir}
                onSort={toggleSort}
              />
              <SortHeader
                label="Original Cost"
                col="originalCost"
                align="right"
                sortKey={sortKey}
                sortDir={sortDir}
                onSort={toggleSort}
              />
              <SortHeader
                label="Current Cost"
                col="currentCost"
                align="right"
                sortKey={sortKey}
                sortDir={sortDir}
                onSort={toggleSort}
              />
              <SortHeader
                label="Progress"
                col="physicalProgress"
                sortKey={sortKey}
                sortDir={sortDir}
                onSort={toggleSort}
              />
              <SortHeader
                label="Risk Score"
                col="riskScore"
                align="center"
                sortKey={sortKey}
                sortDir={sortDir}
                onSort={toggleSort}
              />
              <SortHeader
                label="Risk Level"
                col="riskLevel"
                sortKey={sortKey}
                sortDir={sortDir}
                onSort={toggleSort}
              />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {pagedProjects.map((project) => (
              <tr
                key={project.id}
                onClick={() => onRowClick?.(project)}
                className={`transition-colors ${onRowClick ? 'cursor-pointer hover:bg-gray-50' : ''}`}
              >
                <td className="px-4 py-3">
                  <div className="font-medium text-gray-900">{project.name}</div>
                  <div className="text-xs text-gray-500">{project.id}</div>
                </td>
                <td className="px-4 py-3 text-gray-700">{project.ministry}</td>
                <td className="px-4 py-3 text-gray-700">{project.sector}</td>
                <td className="px-4 py-3 text-gray-700">{project.state}</td>
                <td className="px-4 py-3 text-right text-gray-700">
                  {formatCost(project.originalCost)}
                </td>
                <td className="px-4 py-3 text-right text-gray-700">
                  {formatCost(project.currentCost)}
                </td>
                <td className="px-4 py-3 w-40">
                  <ProgressBar value={project.physicalProgress} />
                </td>
                <td className="px-4 py-3">
                  <div className="flex justify-center">
                    <RiskScore score={project.riskScore} size="sm" />
                  </div>
                </td>
                <td className="px-4 py-3">
                  <RiskBadge level={project.riskLevel} size="sm" />
                </td>
              </tr>
            ))}
            {pagedProjects.length === 0 && (
              <tr>
                <td colSpan={9} className="px-4 py-12 text-center text-gray-500">
                  No projects found
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {showPagination && sortedProjects.length > 0 && (
        <div className="flex items-center justify-between border-t border-gray-200 px-4 py-3">
          <p className="text-sm text-gray-600">
            Showing {start}-{end} of {sortedProjects.length} projects
          </p>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setCurrentPage((p) => Math.max(p - 1, 1))}
              disabled={safePage === 1}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-gray-600 transition-colors hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronLeft size={16} />
            </button>
            {Array.from({ length: totalPages }, (_, i) => i + 1).map((page) => (
              <button
                key={page}
                onClick={() => setCurrentPage(page)}
                className={`h-8 w-8 rounded-lg text-sm font-medium transition-colors ${
                  page === safePage ? 'bg-blue-600 text-white' : 'text-gray-600 hover:bg-gray-100'
                }`}
              >
                {page}
              </button>
            ))}
            <button
              onClick={() => setCurrentPage((p) => Math.min(p + 1, totalPages))}
              disabled={safePage === totalPages}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-gray-600 transition-colors hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
