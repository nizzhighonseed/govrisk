import { z } from 'zod';
import { levelForScore, resolveStateKey } from '../constants/regions';
import type {
  DisasterEvent,
  DisasterSummary,
  FactorDriver,
  ProjectRiskPoint,
  RegionRiskAggregate,
  RegionRiskData,
  StateKey,
  WeatherAlert,
  WeatherSummary,
} from '../types/map';
import {
  rawDisasterResponseSchema,
  rawRiskByStateResponseSchema,
  rawRiskMapPointSchema,
  rawRiskMapResponseSchema,
  rawTopRiskFactorsSchema,
  rawWeatherResponseSchema,
} from './validation';

/** Validated wire types. Export for use by fetchers + fixtures. */
export type RawRiskMapPoint = z.infer<typeof rawRiskMapPointSchema>;
export type RawDisasterResponse = z.infer<typeof rawDisasterResponseSchema>;
export type RawWeatherResponse = z.infer<typeof rawWeatherResponseSchema>;

const HANDLED_DISASTER_TYPES: readonly DisasterEvent['type'][] = [
  'flood',
  'cyclone',
  'earthquake',
  'drought',
  'landslide',
  'heatwave',
];

const EVENT_TYPE_LABEL: Record<DisasterEvent['type'], string> = {
  flood: 'Flood',
  cyclone: 'Cyclone',
  earthquake: 'Earthquake',
  drought: 'Drought',
  landslide: 'Landslide',
  heatwave: 'Heat wave',
};

// ---------------------------------------------------------------------------
// Risk data (backend)
// ---------------------------------------------------------------------------

/**
 * A project can only be pinned on the map when the source gave both
 * coordinates. `null` means "not reported", and (0, 0) is a genuine location in
 * the Gulf of Guinea that the backend rejects — so neither may become a marker.
 */
function isPlottable<T extends { lat: number | null; lng: number | null }>(
  p: T,
): p is T & { lat: number; lng: number } {
  if (p.lat === null || p.lng === null) return false;
  if (p.lat === 0 && p.lng === 0) return false;
  return true;
}

/**
 * Validate + shape `/api/risk-map` payload into typed project points.
 * Throws a typed `PayloadError` when the wire format drifts.
 */
export function adaptRiskMapPoints(raw: unknown): ProjectRiskPoint[] {
  const validated = rawRiskMapResponseSchema.parse(raw);
  return validated.filter(isPlottable).map((p) => ({
    id: p.id,
    name: p.name,
    stateName: p.state,
    riskScore: p.riskScore,
    riskLevel: p.riskLevel,
    costOverrunProbability: p.costOverrunProbability,
    delayProbability: p.delayProbability,
    lat: p.lat,
    lng: p.lng,
    status: p.status ?? 'ONGOING',
    sector: p.sector ?? undefined,
    agency: p.agency ?? undefined,
    scale: p.scale ?? undefined,
    fundingSource: p.fundingSource ?? undefined,
    confidence: p.confidence ?? undefined,
    costEstimateCr: p.costEstimateCr ?? undefined,
  }));
}

/**
 * Validate + shape `/api/analytics` [[riskByState]] items into region
 * aggregates with a derived composite level for choropleth banding.
 */
export function adaptRiskAggregates(raw: unknown): RegionRiskAggregate[] {
  const validated = rawRiskByStateResponseSchema.parse(raw);
  return validated.map((r) => {
    const compositeScore = Math.min(100, Math.max(0, r.avgRisk || 0));
    return {
      stateName: r.state,
      projectCount: r.projectCount,
      avgRisk: r.avgRisk ?? 0,
      critical: r.critical,
      high: r.high,
      compositeScore,
      riskLevel: levelForScore(compositeScore),
    };
  });
}

/** Validate + shape [[topRiskFactors]] into factor driver summaries. */
export function adaptTopRiskFactors(raw: unknown): FactorDriver[] {
  const validated = rawTopRiskFactorsSchema.parse(raw);
  return validated
    .map((f) => ({
      key: f.key,
      name: f.name,
      avgScore: Math.min(100, Math.max(0, f.avgScore)),
    }))
    .sort((a, b) => b.avgScore - a.avgScore);
}

// ---------------------------------------------------------------------------
// Disaster history
// ---------------------------------------------------------------------------

function eventKey(regionKey: StateKey, index: number): string {
  return `DIS-${regionKey}-${index}`;
}

/** Aggregate a region's event history into a compact, render-ready summary. */
export function adaptDisasterSummary(
  rawEvents: z.infer<typeof rawDisasterResponseSchema>['regions'][number]['history'],
): DisasterSummary {
  if (!rawEvents || rawEvents.length === 0) {
    return {
      regionAvailable: false,
      totalEvents: 0,
      lastEventYear: null,
      dominantType: null,
      dominantFrequency: 0,
      events: [],
    };
  }

  let total = 0;
  let lastEventYear: number | null = null;
  const frequencyByType = new Map<DisasterEvent['type'], number>();
  const events: DisasterEvent[] = rawEvents.map((e, i) => {
    total += e.events;
    const type = e.type;
    frequencyByType.set(type, (frequencyByType.get(type) ?? 0) + e.events);
    if (lastEventYear === null || e.year > lastEventYear) lastEventYear = e.year;
    return {
      id: eventKey(type, i),
      type,
      year: e.year,
      severity: e.severity,
      magnitude: null,
      deaths: e.deaths,
      displaced: e.displaced,
    };
  });

  let dominantType: DisasterEvent['type'] | null = null;
  let dominantFrequency = 0;
  for (const type of HANDLED_DISASTER_TYPES) {
    const freq = frequencyByType.get(type) ?? 0;
    if (freq > dominantFrequency) {
      dominantFrequency = freq;
      dominantType = type;
    }
  }

  return {
    regionAvailable: true,
    totalEvents: total,
    lastEventYear,
    dominantType: dominantType ? EVENT_TYPE_LABEL[dominantType] : null,
    dominantFrequency,
    events,
  };
}

/** Disaster raw response -> map of region key -> summary. */
export function adaptDisasterData(raw: unknown): ReadonlyMap<StateKey, DisasterSummary> {
  const validated = rawDisasterResponseSchema.parse(raw);
  const map = new Map<StateKey, DisasterSummary>();
  for (const region of validated.regions) {
    const key = resolveStateKey(region.stateName);
    if (!key) continue;
    map.set(key, adaptDisasterSummary(region.history));
  }
  return map;
}

// ---------------------------------------------------------------------------
// Weather alerts
// ---------------------------------------------------------------------------

/** Join active alerts to a region and lift the snapshot into render shape. */
export function adaptWeatherSummary(
  rawRegion: z.infer<typeof rawWeatherResponseSchema>['regions'][number],
): WeatherSummary {
  const alerts: WeatherAlert[] = rawRegion.alerts.map((a) => ({
    id: a.id,
    type: a.type,
    severity: a.severity,
    headline: a.headline,
    issuedAt: a.issuedAt,
    lat: a.lat,
    lng: a.lng,
  }));
  return {
    regionAvailable: rawRegion.alerts.length > 0,
    condition: rawRegion.condition,
    activeAlerts: alerts,
    temperatureC: rawRegion.temperatureC,
    humidity: rawRegion.humidity,
    windKmh: rawRegion.windKmh,
    observedAt: rawRegion.observedAt ?? null,
  };
}

/** Weather raw response -> map of region key -> summary. */
export function adaptWeatherData(raw: unknown): ReadonlyMap<StateKey, WeatherSummary> {
  const validated = rawWeatherResponseSchema.parse(raw);
  const map = new Map<StateKey, WeatherSummary>();
  for (const region of validated.regions) {
    const key = resolveStateKey(region.stateName);
    if (!key) continue;
    map.set(key, adaptWeatherSummary(region));
  }
  return map;
}

// ---------------------------------------------------------------------------
// Normalized merge
// ---------------------------------------------------------------------------

const MIN_CONTRIBUTORS = 3;

/** 0..1 choropleth intensity for a disaster summary (log-scaled event count). */
export function disasterIntensity(summary: DisasterSummary | undefined): number | null {
  if (!summary?.regionAvailable || summary.totalEvents <= 0) return null;
  const raw = Math.log10(1 + summary.totalEvents) / Math.log10(101);
  return Math.min(1, Math.max(0, raw));
}

/** 0..1 choropleth intensity = composite risk score / 100. */
export function riskIntensity(region: RegionRiskData): number {
  return Math.min(1, Math.max(0, region.compositeScore / 100));
}

/** 0..1 weather overlay intensity from condition + active alerts. */
export function weatherIntensity(weather: WeatherSummary | undefined): number | null {
  if (!weather) return null;
  const CONDITION_RANK: Record<WeatherSummary['condition'], number> = {
    CLEAR: 0,
    MILD: 0.15,
    UNKNOWN: 0.2,
    MODERATE: 0.4,
    SEVERE: 0.65,
    EXTREME: 0.9,
  };
  const base = CONDITION_RANK[weather.condition] ?? 0.2;
  const alertRank: Record<WeatherAlert['severity'], number> = {
    MODERATE: 0.1,
    SEVERE: 0.2,
    EXTREME: 0.3,
  };
  const alertBoost = weather.activeAlerts.reduce((sum, a) => sum + (alertRank[a.severity] ?? 0), 0);
  const total = base + Math.min(0.55, alertBoost);
  return weather.regionAvailable ? Math.min(1, Math.max(0, total)) : base;
}

/**
 * Combine every source into the normalized per-region schema consumed by the
 * map layers. Regions with no data from any source are omitted; layers decide
 * how to render a missing region (neutral fill + "No data" tooltip).
 */
export function buildRegionRiskData(input: {
  aggregates: RegionRiskAggregate[];
  disasters: ReadonlyMap<StateKey, DisasterSummary>;
  weather: ReadonlyMap<StateKey, WeatherSummary>;
}): RegionRiskData[] {
  const result: RegionRiskData[] = [];

  for (const aggregate of input.aggregates) {
    const stateKey = resolveStateKey(aggregate.stateName);
    if (!stateKey) continue;

    const disaster = input.disasters.get(stateKey);
    const weather = input.weather.get(stateKey);

    const factors: string[] = [];
    if (aggregate.high > 0) factors.push(`${aggregate.high} high-risk projects`);
    if (aggregate.critical > 0) factors.push(`${aggregate.critical} critical-risk projects`);
    if (disaster && disaster.dominantType) {
      factors.push(`${disaster.dominantType} (dominant hazard)`);
    }
    if (weather && weather.activeAlerts.length > 0) {
      const severe = weather.activeAlerts.filter((a) => a.severity !== 'MODERATE').length;
      factors.push(`${severe} severe weather alerts`);
    }
    if (factors.length === 0) factors.push('Portfolio risk within average range');

    result.push({
      stateKey,
      stateName: aggregate.stateName,
      regionAvailable: true,
      compositeScore: aggregate.compositeScore,
      riskLevel: aggregate.riskLevel,
      projectCount: aggregate.projectCount,
      avgRisk: aggregate.avgRisk,
      highRiskProjects: aggregate.high,
      criticalRiskProjects: aggregate.critical,
      contributingFactors: factors.slice(0, MIN_CONTRIBUTORS),
      disaster,
      weather,
    });
  }

  return result;
}
