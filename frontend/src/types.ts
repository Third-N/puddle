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
  /** 東京都の浸水予想で浸水が想定される区間が、経路に占める割合（0-100） */
  floodOverlapPct: number;
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

/** 地点検索の候補。 */
export interface PlaceSuggestion {
  label: string;
  kind: 'station' | 'landmark' | 'building';
  lat: number;
  lng: number;
}

/** 座標に付ける呼び名。 */
export interface PlaceLabel {
  label: string;
  kind: 'station' | 'landmark' | 'building' | 'street' | 'coordinate';
  distanceM: number;
}

/** デモ対象地域の情報。 */
export interface AreaInfo {
  bounds: { minLat: number; minLng: number; maxLat: number; maxLng: number };
  center: LatLng;
  intensities: { value: RainIntensity; label: string; mmPerHour: number }[];
  hazardCount: number;
}
