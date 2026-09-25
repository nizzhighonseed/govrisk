import { CheckCircle, Clock, AlertTriangle, Target } from 'lucide-react';
import { useI18n } from '../../i18n';
import { formatDate, NO_DATA_LABEL } from '../../utils/helpers';

interface ProjectTimelineProps {
  expectedCompletion: string;
  predictedCompletion: string;
  delayMonths: number;
  delayProbability: number;
  progressGap: number | null;
}

export function ProjectTimeline({
  expectedCompletion,
  predictedCompletion,
  delayMonths,
  delayProbability,
  progressGap,
}: ProjectTimelineProps) {
  const { t } = useI18n();
  const onTime = delayMonths <= 0;

  return (
    <div className="grid grid-cols-1 gap-8 md:grid-cols-2">
      <div>
        <h3 className="mb-4 text-sm font-semibold text-gray-700">{t('apm.timeline')}</h3>
        <div className="space-y-4">
          <div className="flex items-start gap-4">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-blue-100">
              <CheckCircle size={18} className="text-blue-600" />
            </div>
            <div>
              <p className="text-sm font-medium text-gray-900">Original Completion</p>
              <p className="text-sm text-gray-500">{formatDate(expectedCompletion)}</p>
            </div>
          </div>
          <div className="ml-5 h-8 w-0.5 bg-gray-200" />
          <div className="flex items-start gap-4">
            <div
              className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${onTime ? 'bg-green-100' : 'bg-red-100'}`}
            >
              <Clock size={18} className={onTime ? 'text-green-600' : 'text-red-600'} />
            </div>
            <div>
              <p className="text-sm font-medium text-gray-900">Predicted Completion</p>
              <p className={`text-sm ${onTime ? 'text-green-600' : 'text-red-600'}`}>
                {formatDate(predictedCompletion)}
              </p>
            </div>
          </div>
        </div>
      </div>
      <div>
        <h3 className="mb-4 text-sm font-semibold text-gray-700">Key Metrics</h3>
        <div className="space-y-4">
          <div className="rounded-lg bg-gray-50 p-4">
            <div className="flex items-center gap-2">
              <Clock size={16} className="text-orange-500" />
              <span className="text-sm text-gray-500">Expected Delay</span>
            </div>
            <p className="mt-1 text-2xl font-bold text-navy-900">
              {onTime ? 'On schedule' : `${delayMonths} months`}
            </p>
          </div>
          <div className="rounded-lg bg-gray-50 p-4">
            <div className="flex items-center gap-2">
              <AlertTriangle size={16} className="text-red-500" />
              <span className="text-sm text-gray-500">Delay Probability</span>
            </div>
            <p className="mt-1 text-2xl font-bold text-red-600">{delayProbability}%</p>
          </div>
          <div className="rounded-lg bg-gray-50 p-4">
            <div className="flex items-center gap-2">
              <Target size={16} className="text-blue-500" />
              <span className="text-sm text-gray-500">{t('analytics.progressGap')}</span>
            </div>
            <p className="mt-1 text-2xl font-bold text-navy-900">
              {progressGap === null ? NO_DATA_LABEL : `${progressGap}% behind`}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
