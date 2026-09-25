import { describe, expect, it } from 'vitest';

const projectDetailsSource = Object.values(
  import.meta.glob('../../pages/ProjectDetails.tsx', {
    eager: true,
    query: '?raw',
    import: 'default',
  }),
)[0] as string;

const chartSource = Object.values(
  import.meta.glob('../../components/charts/RiskFactorChart.tsx', {
    eager: true,
    query: '?raw',
    import: 'default',
  }),
)[0] as string;

describe('canonical risk explanation presentation', () => {
  it('renders server-provided factor ranking, quality, and missing data', () => {
    expect(projectDetailsSource).toContain('topRiskFactors');
    expect(projectDetailsSource).toContain('dataQuality');
    expect(projectDetailsSource).toContain('riskLevelProvisional');
    expect(projectDetailsSource).toContain('triggeredConditions');
    expect(projectDetailsSource).toContain('minimumScore');
    expect(projectDetailsSource).not.toMatch(/sort\([^)]*contribution/);
    expect(projectDetailsSource).not.toContain('Math.round(f.contribution)');
  });

  it('uses the server factor score and severity for the factor chart', () => {
    expect(chartSource).toContain('dataKey="score"');
    expect(chartSource).toContain('entry.severity');
    expect(chartSource).not.toContain('value > 80');
  });
});
