import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { RiskFactor } from '../../types';

interface RiskFactorChartProps {
  data: Array<Pick<RiskFactor, 'key' | 'name' | 'score' | 'severity' | 'dataAvailable'>>;
  title?: string;
  description?: string;
}

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: '#ef4444',
  HIGH: '#f97316',
  MODERATE: '#eab308',
  LOW: '#3b82f6',
  'VERY LOW': '#3b82f6',
};

function getBarColor(entry: RiskFactorChartProps['data'][number]) {
  if (!entry.dataAvailable) return '#cbd5e1';
  return SEVERITY_COLORS[entry.severity] ?? '#3b82f6';
}

export function RiskFactorChart({
  data,
  title = 'Top risk factors',
  description,
}: RiskFactorChartProps) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 lg:p-6">
      <h3 className="text-base font-semibold text-navy-900 lg:text-lg">{title}</h3>
      {description && <p className="mt-1 text-xs text-gray-500 lg:text-sm">{description}</p>}
      <div className="mt-4">
        <ResponsiveContainer width="100%" height={280}>
          <BarChart
            data={data}
            layout="vertical"
            margin={{ top: 0, right: 24, left: 0, bottom: 0 }}
            barCategoryGap={14}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" horizontal={false} />
            <XAxis
              type="number"
              domain={[0, 100]}
              tick={{ fontSize: 12, fill: '#6b7280' }}
              axisLine={{ stroke: '#e5e7eb' }}
              tickLine={false}
            />
            <YAxis
              type="category"
              dataKey="name"
              width={170}
              tick={{ fontSize: 12, fill: '#374151' }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              formatter={(value) => [`${value}/100`, 'Factor score']}
              contentStyle={{
                borderRadius: 8,
                border: '1px solid #e5e7eb',
                boxShadow: '0 4px 12px rgba(0,0,0,0.06)',
                fontSize: 12,
              }}
            />
            <Bar dataKey="score" radius={[0, 4, 4, 0]} barSize={22}>
              {data.map((entry) => (
                <Cell key={entry.key} fill={getBarColor(entry)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
