import { describe, expect, it } from 'vitest';
import {
  adaptDisasterData,
  adaptDisasterSummary,
  adaptRiskAggregates,
  adaptRiskMapPoints,
  adaptTopRiskFactors,
  adaptWeatherData,
  adaptWeatherSummary,
  buildRegionRiskData,
  disasterIntensity,
  riskIntensity,
  weatherIntensity,
} from '../dataAdapters';

const VALID_POINTS = [
  {
    id: 'P-1',
    name: 'NH-44 Widening',
    state: 'Maharashtra',
    riskScore: 74,
    riskLevel: 'HIGH',
    costOverrunProbability: 0.4,
    delayProbability: 0.6,
    lat: 19.1,
    lng: 72.8,
  },
];

describe('adaptRiskMapPoints', () => {
  it('shapes a valid /api/risk-map payload', () => {
    const points = adaptRiskMapPoints(VALID_POINTS);
    expect(points).toHaveLength(1);
    expect(points[0]).toMatchObject({
      id: 'P-1',
      stateName: 'Maharashtra',
      riskScore: 74,
      riskLevel: 'HIGH',
    });
  });

  it('rejects a malformed payload (missing riskScore) instead of rendering garbage', () => {
    const bad = [{ ...VALID_POINTS[0], riskScore: undefined }];
    expect(() => adaptRiskMapPoints(bad)).toThrow();
  });

  it('rejects extra unknown keys to surface wire-format drift early', () => {
    const sneaky = [{ ...VALID_POINTS[0], injected: 'xss' }];
    expect(() => adaptRiskMapPoints(sneaky)).toThrow();
  });

  it('drops a project whose coordinates the source never reported', () => {
    // A null coordinate is a fact about the data, not a parse error: one
    // unlocated project must not blank the whole risk map.
    const payload = [{ ...VALID_POINTS[0], lat: null, lng: null }];
    expect(adaptRiskMapPoints(payload)).toEqual([]);
  });

  it('keeps plottable projects when a sibling has no coordinates', () => {
    const payload = [
      { ...VALID_POINTS[0], id: 'P-NOCOORD', lat: null, lng: null },
      { ...VALID_POINTS[0], id: 'P-2', lat: 12.97, lng: 79.58 },
    ];
    const points = adaptRiskMapPoints(payload);
    expect(points).toHaveLength(1);
    expect(points[0].id).toBe('P-2');
  });

  it('drops a half-specified coordinate pair', () => {
    const payload = [{ ...VALID_POINTS[0], lat: 19.1, lng: null }];
    expect(adaptRiskMapPoints(payload)).toEqual([]);
  });

  it('never plots (0, 0), which is a real point in the Gulf of Guinea', () => {
    const payload = [{ ...VALID_POINTS[0], lat: 0, lng: 0 }];
    expect(adaptRiskMapPoints(payload)).toEqual([]);
  });

  it('still plots a genuine zero on one axis', () => {
    const payload = [{ ...VALID_POINTS[0], lat: 0, lng: 78.9 }];
    expect(adaptRiskMapPoints(payload)).toHaveLength(1);
  });

  it('maps government-ingest provenance onto the point', () => {
    const points = adaptRiskMapPoints([
      {
        ...VALID_POINTS[0],
        status: 'DELAYED',
        sector: 'Transport',
        agency: 'NHAI',
        scale: 'LARGE',
        fundingSource: 'CENTRAL_GOVT',
        confidence: 'OFFICIAL',
        costEstimateCr: 24500,
      },
    ]);
    expect(points[0]).toMatchObject({
      status: 'DELAYED',
      sector: 'Transport',
      agency: 'NHAI',
      scale: 'LARGE',
      fundingSource: 'CENTRAL_GOVT',
      confidence: 'OFFICIAL',
      costEstimateCr: 24500,
    });
  });

  it('defaults an absent status to ONGOING but keeps other provenance undefined', () => {
    const points = adaptRiskMapPoints(VALID_POINTS);
    expect(points[0].status).toBe('ONGOING');
    expect(points[0].scale).toBeUndefined();
    expect(points[0].costEstimateCr).toBeUndefined();
  });
});

describe('adaptRiskAggregates', () => {
  it('derives compositeScore/riskLevel from avgRisk', () => {
    const aggregates = adaptRiskAggregates([
      { state: 'Assam', projectCount: 12, avgRisk: 88, critical: 3, high: 5 },
    ]);
    expect(aggregates[0]).toMatchObject({
      stateName: 'Assam',
      compositeScore: 88,
      riskLevel: 'CRITICAL',
    });
    expect(aggregates[0].high).toBe(5);
  });

  it('clamps compositeScore to 0..100', () => {
    const aggregates = adaptRiskAggregates([
      { state: 'Assam', projectCount: 1, avgRisk: 250, critical: 0, high: 0 },
    ]);
    expect(aggregates[0].compositeScore).toBe(100);
  });
});

describe('adaptTopRiskFactors', () => {
  it('maps and score-sorts factor drivers', () => {
    const drivers = adaptTopRiskFactors([
      { key: 'delay', name: 'Schedule Delay', avgScore: 12 },
      { key: 'cost', name: 'Cost Overrun', avgScore: 45 },
    ]);
    expect(drivers.map((d) => d.name)).toEqual(['Cost Overrun', 'Schedule Delay']);
    expect(drivers[0].avgScore).toBe(45);
  });
});

describe('adaptDisasterSummary', () => {
  it('aggregates events into totals + dominant type', () => {
    const summary = adaptDisasterSummary([
      { type: 'flood', year: 2024, events: 6, severity: 'HIGH', deaths: 40, displaced: 95 },
      { type: 'flood', year: 2023, events: 4, severity: 'CRITICAL', deaths: 27, displaced: 40 },
      { type: 'cyclone', year: 2024, events: 2, severity: 'HIGH', deaths: 6, displaced: 5 },
    ]);
    expect(summary.totalEvents).toBe(12);
    expect(summary.dominantType).toBe('Flood');
    expect(summary.dominantFrequency).toBe(10);
    expect(summary.lastEventYear).toBe(2024);
    expect(summary.regionAvailable).toBe(true);
  });

  it('returns an inert summary when history is empty', () => {
    const summary = adaptDisasterSummary([]);
    expect(summary.regionAvailable).toBe(false);
    expect(summary.totalEvents).toBe(0);
    expect(summary.dominantType).toBeNull();
  });
});

describe('adaptDisasterData', () => {
  it('joins regions by canonical state key and skips unknown names', () => {
    const map = adaptDisasterData({
      regions: [
        {
          stateName: 'Orissa',
          history: [
            { type: 'flood', year: 2023, events: 2, severity: 'MEDIUM', deaths: 0, displaced: 0 },
          ],
        },
      ],
    });
    expect(map.get('odisha')?.totalEvents).toBe(2);
  });
});

describe('adaptWeatherSummary', () => {
  it('marks region available when alerts exist', () => {
    const summary = adaptWeatherSummary({
      stateName: 'Maharashtra',
      condition: 'SEVERE',
      observedAt: '2025-01-01T00:00:00Z',
      temperatureC: 41,
      humidity: 34,
      windKmh: 26,
      alerts: [
        {
          id: 'WX-1',
          type: 'HEAT_WAVE',
          severity: 'SEVERE',
          headline: 'Heat wave',
          issuedAt: '2025-01-01T00:00:00Z',
          lat: 19.1,
          lng: 72.8,
        },
      ],
    });
    expect(summary.regionAvailable).toBe(true);
    expect(summary.observedAt).toBe('2025-01-01T00:00:00Z');
    expect(summary.activeAlerts).toHaveLength(1);
  });
});

describe('adaptWeatherData', () => {
  it('resolves Orissa -> odisha via KNOWN_REGIONS aliases', () => {
    const map = adaptWeatherData({
      regions: [
        {
          stateName: 'Orissa',
          condition: 'CLEAR',
          temperatureC: 30,
          humidity: 50,
          windKmh: 10,
          alerts: [],
        },
      ],
    });
    expect(map.get('odisha')?.regionAvailable).toBe(false);
  });
});

describe('buildRegionRiskData', () => {
  it('merges the three sources into one record per aggregate', () => {
    const aggregates = adaptRiskAggregates([
      { state: 'Assam', projectCount: 8, avgRisk: 70, critical: 1, high: 2 },
    ]);
    const disasters = adaptDisasterData({
      regions: [
        {
          stateName: 'Assam',
          history: [
            { type: 'flood', year: 2024, events: 5, severity: 'HIGH', deaths: 1, displaced: 2 },
          ],
        },
      ],
    });
    const weather = adaptWeatherData({
      regions: [
        {
          stateName: 'Assam',
          condition: 'MODERATE',
          temperatureC: 30,
          humidity: 50,
          windKmh: 10,
          alerts: [],
        },
      ],
    });

    const regions = buildRegionRiskData({ aggregates, disasters, weather });
    expect(regions).toHaveLength(1);
    expect(regions[0]).toMatchObject({
      stateKey: 'assam',
      compositeScore: 70,
      projectCount: 8,
      highRiskProjects: 2,
      criticalRiskProjects: 1,
    });
    expect(regions[0].disaster?.totalEvents).toBe(5);
    expect(regions[0].contributingFactors.length).toBeGreaterThan(0);
  });
});

describe('intensity helpers (choropleth scaling)', () => {
  it('riskIntensity normalizes composite score to 0..1', () => {
    const region = {
      stateKey: 'x',
      stateName: 'X',
      regionAvailable: true,
      compositeScore: 74,
      riskLevel: 'HIGH',
      projectCount: 1,
      avgRisk: 74,
      highRiskProjects: 0,
      criticalRiskProjects: 0,
      contributingFactors: [],
    } as never;
    expect(riskIntensity(region as never)).toBe(0.74);
  });

  it('disasterIntensity returns null without real history, else log-scaled', () => {
    expect(disasterIntensity(undefined)).toBeNull();
    expect(disasterIntensity({ regionAvailable: false, totalEvents: 0 } as never)).toBeNull();
    const withEvents = disasterIntensity({
      regionAvailable: true,
      totalEvents: 100,
    } as never);
    expect(withEvents).not.toBeNull();
    expect(withEvents!).toBeGreaterThan(0);
    expect(withEvents!).toBeLessThanOrEqual(1);
  });

  it('weatherIntensity scales with severity and alert load', () => {
    expect(weatherIntensity(undefined)).toBeNull();
    const calm = { regionAvailable: true, condition: 'CLEAR', activeAlerts: [] } as never;
    const dangerous = {
      regionAvailable: true,
      condition: 'SEVERE',
      activeAlerts: [{ severity: 'SEVERE' }, { severity: 'EXTREME' }],
    } as never;
    expect(weatherIntensity(calm)).toBe(0);
    expect(weatherIntensity(dangerous)!).toBeGreaterThan(0.65);
    expect(weatherIntensity(dangerous)!).toBeLessThanOrEqual(1);
  });
});
