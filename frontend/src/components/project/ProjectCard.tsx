import { useNavigate } from 'react-router-dom';
import { ArrowRight, MapPin } from 'lucide-react';
import { useI18n } from '../../i18n';
import type { Project } from '../../types';
import { RiskScore } from '../ui/RiskScore';
import { RiskBadge } from '../ui/RiskBadge';
import { ProgressBar } from '../ui/ProgressBar';
import { formatCurrency, formatPercentNullable } from '../../utils/helpers';

interface ProjectCardProps {
  project: Project;
  onSelect?: (project: Project) => void;
}

export function ProjectCard({ project, onSelect }: ProjectCardProps) {
  const navigate = useNavigate();
  const { t } = useI18n();

  const handleClick = () => {
    if (onSelect) {
      onSelect(project);
    } else {
      navigate(`/projects/${project.id}`);
    }
  };

  const costOverrun = ((project.currentCost - project.originalCost) / project.originalCost) * 100;

  return (
    <div
      onClick={handleClick}
      className="cursor-pointer rounded-xl border border-gray-200 bg-white p-4 transition-colors hover:border-blue-200 hover:bg-blue-50/40"
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 className="truncate text-sm font-semibold text-navy-900">{project.name}</h4>
          <p className="mt-0.5 flex items-center gap-1 text-xs text-gray-500">
            <MapPin size={12} />
            {project.state} · {project.sector}
          </p>
        </div>
        <RiskScore score={project.riskScore} size="sm" />
      </div>

      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs text-gray-500">{t('projectCard.physicalProgress')}</span>
        <span className="text-xs font-medium text-gray-700">
          {formatPercentNullable(project.physicalProgress)}
        </span>
      </div>
      <ProgressBar value={project.physicalProgress} />

      <div className="mt-3 flex items-center justify-between text-xs text-gray-500">
        <span>{t('projectCard.original', { cost: formatCurrency(project.originalCost) })}</span>
        <span className={costOverrun > 15 ? 'font-medium text-red-600' : 'text-gray-500'}>
          {t('projectCard.overrun', { pct: costOverrun.toFixed(1) })}
        </span>
      </div>

      <div className="mt-3 flex items-center justify-between border-t border-gray-100 pt-3">
        <RiskBadge level={project.riskLevel} size="sm" />
        <span className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-700">
          {t('projectCard.viewDetails')}
          <ArrowRight size={13} />
        </span>
      </div>
    </div>
  );
}
