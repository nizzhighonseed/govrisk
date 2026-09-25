import { z } from 'zod';

/**
 * Defensive validation for every raw payload that crosses the network
 * boundary (backend risk API + external weather/disaster sources).
 *
 * A malformed or malicious response is rejected up front — adapted data must
 * never drive rendering before passing these schemas.
 */

export const riskLevelSchema = z.enum(['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']);

/** `/api/risk-map` item (project point). */
export const rawRiskMapPointSchema = z
  .object({
    id: z.string().min(1),
    name: z.string(),
    state: z.string(),
    riskScore: z.number().finite(),
    riskLevel: riskLevelSchema,
    costOverrunProbability: z.number().finite(),
    delayProbability: z.number().finite(),
    // Coordinates are nullable: most government portals publish no location
    // for a project, and the backend stores "not reported" as NULL rather than
    // a fake 0,0. Unplottable points are dropped by the adapter, not rendered.
    lat: z.number().finite().nullable(),
    lng: z.number().finite().nullable(),
    // Government-ingest provenance (backend/ingest). Optional: manual projects
    // have no ingestion metadata.
    status: z.enum(['ONGOING', 'COMPLETED', 'DELAYED', 'STALLED', 'CANCELLED']).optional().nullable(),
    sector: z.string().optional().nullable(),
    agency: z.string().optional().nullable(),
    scale: z.enum(['MEDIUM', 'LARGE']).optional().nullable(),
    fundingSource: z.string().optional().nullable(),
    confidence: z.string().optional().nullable(),
    costEstimateCr: z.number().finite().optional().nullable(),
  })
  .strict();

export const rawRiskMapResponseSchema = z.array(rawRiskMapPointSchema);

/** `/api/analytics` riskByState item (region aggregate). */
export const rawRiskByStateSchema = z
  .object({
    state: z.string().min(1),
    projectCount: z.number().int().nonnegative(),
    avgRisk: z.number().finite(),
    critical: z.number().int().nonnegative(),
    high: z.number().int().nonnegative(),
  })
  .strict();

export const rawRiskByStateResponseSchema = z.array(rawRiskByStateSchema);

/** `/api/analytics` topRiskFactors item (portfolio factor averages). */
export const rawTopRiskFactorSchema = z
  .object({
    key: z.string().min(1),
    name: z.string(),
    avgScore: z.number().finite(),
  })
  .strict();

export const rawTopRiskFactorsSchema = z.array(rawTopRiskFactorSchema);

/** Wire shape for the disaster history source (documented contract). */
export const rawDisasterEventSchema = z.object({
  type: z.enum(['flood', 'cyclone', 'earthquake', 'drought', 'landslide', 'heatwave']),
  year: z.number().int().min(1900).max(2100),
  events: z.number().int().nonnegative(),
  severity: z.enum(['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']),
  deaths: z.number().int().nonnegative().nullable().default(null),
  displaced: z.number().int().nonnegative().nullable().default(null),
});

export const rawDisasterRegionSchema = z.object({
  stateName: z.string().min(1),
  history: z.array(rawDisasterEventSchema),
});

export const rawDisasterResponseSchema = z.object({
  generatedAt: z.string().datetime().optional(),
  regions: z.array(rawDisasterRegionSchema),
});

/** Wire shape for the weather source (documented contract). */
export const rawWeatherAlertSchema = z.object({
  id: z.string().min(1),
  type: z.enum(['HEAT_WAVE', 'RAIN', 'STORM', 'CYCLONE', 'FOG', 'COLD_WAVE', 'DUST']),
  severity: z.enum(['MODERATE', 'SEVERE', 'EXTREME']),
  headline: z.string(),
  issuedAt: z.string().datetime(),
  lat: z.number().finite().min(-90).max(90),
  lng: z.number().finite().min(-180).max(180),
});

export const rawWeatherRegionSchema = z.object({
  stateName: z.string().min(1),
  condition: z.enum(['CLEAR', 'MILD', 'MODERATE', 'SEVERE', 'EXTREME', 'UNKNOWN']),
  observedAt: z.string().datetime().nullable().optional(),
  temperatureC: z.number().finite().nullable(),
  humidity: z.number().finite().nullable(),
  windKmh: z.number().finite().nullable(),
  alerts: z.array(rawWeatherAlertSchema),
});

export const rawWeatherResponseSchema = z.object({
  observedAt: z.string().datetime().optional(),
  regions: z.array(rawWeatherRegionSchema),
});
