export type RainIntensity = 'light' | 'medium' | 'heavy';

export interface LatLng {
  lat: number;
  lng: number;
}

export interface DangerPoint {
  id: string;
  lat: number;
  lng: number;
  /** Inherent risk magnitude for this spot, independent of current rain intensity (0-1). */
  baseWeight: number;
  /** baseWeight scaled by the currently selected rain intensity (0-1). */
  weight: number;
  /** weight expressed as 0-100 for display. */
  displayRisk: number;
  level: 'high' | 'medium' | 'low';
  reason: string;
}

export interface RouteResult {
  id: 'shortest' | 'avoid';
  label: string;
  color: string;
  distanceM: number;
  durationMin: number;
  /** 0-100 */
  riskScore: number;
  path: LatLng[];
}

export interface SearchResult {
  routes: RouteResult[];
  dangerPoints: DangerPoint[];
}

export type SearchStatus = 'idle' | 'loading' | 'success' | 'error';

/** 2ルートを比べた結果、利用者に伝えたい一言。 */
export type Banner =
  | { kind: 'improved'; extraMinutes: number; riskReduction: number }
  | { kind: 'no-gain' };
