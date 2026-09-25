import { describe, expect, it } from 'vitest';

const source = Object.values(
  import.meta.glob('../../components/admin/AddProjectModal.tsx', {
    eager: true,
    query: '?raw',
    import: 'default',
  }),
)[0] as string;

describe('AddProjectModal risk authority', () => {
  it('delegates current risk calculation to the server', () => {
    expect(source).not.toContain('previewRisk');
    expect(source).not.toMatch(/gap\s*\*\s*2\.5/);
    expect(source).toContain('created.riskScore');
    expect(source).toContain('server-calculated');
  });
});
