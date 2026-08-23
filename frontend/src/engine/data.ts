import type { LatLng } from '../types';

/**
 * 静的サイト版で使う、生成済みデータの読み込み。
 *
 * バックエンドの scripts/build_data.py が書き出したものをそのまま読む。
 * 係数の類は engine.json から取るので、ブラウザ側に数値を書き写していない。
 * 片方だけ直したときに結果が食い違うのを避けるため。
 */

export interface EngineSettings {
  demoArea: { minLat: number; minLng: number; maxLat: number; maxLng: number };
  rainProfiles: Record<string, { label: string; multiplier: number; mmPerHour: number }>;
  walkMetersPerMin: number;
  avoidAlpha: number;
  puddleReferenceRisk: number;
  exposureReferenceM: number;
  maxSnapDistanceM: number;
  hazardCorridorM: number;
  hazardMaxResults: number;
  levelHighThreshold: number;
  levelMediumThreshold: number;
  placeSearchRadiusM: Record<'station' | 'landmark' | 'building' | 'street', number>;
  routeStyles: Record<'shortest' | 'avoid', { label: string; color: string }>;
}

export interface Edge {
  a: number;
  b: number;
  length: number;
  highway: string;
  name: string | null;
  risk: number;
  riskMax: number;
  flood: number;
  floodMax: number;
}

export interface WalkGraph {
  nodes: Map<number, LatLng>;
  edges: Edge[];
  adjacency: Map<number, number[]>;
}

export interface Hazard {
  id: string;
  lat: number;
  lng: number;
  baseWeight: number;
  reasons: Record<string, string>;
}

export interface Place {
  name: string;
  lat: number;
  lon: number;
  kind: 'station' | 'landmark' | 'building';
}

export interface EngineData {
  settings: EngineSettings;
  graph: WalkGraph;
  hazards: Hazard[];
  places: Place[];
}

const DATA_BASE = `${import.meta.env.BASE_URL}data`;

async function loadJson<T>(name: string): Promise<T> {
  const response = await fetch(`${DATA_BASE}/${name}`);
  if (!response.ok) {
    throw new Error(`データを読み込めませんでした (${name}: HTTP ${response.status})`);
  }
  return (await response.json()) as T;
}

function buildGraph(payload: {
  nodes: Record<string, [number, number]>;
  edges: Edge[];
}): WalkGraph {
  const nodes = new Map<number, LatLng>();
  for (const [id, [lng, lat]] of Object.entries(payload.nodes)) {
    nodes.set(Number(id), { lat, lng });
  }

  const adjacency = new Map<number, number[]>();
  payload.edges.forEach((edge, index) => {
    for (const id of [edge.a, edge.b]) {
      const list = adjacency.get(id);
      if (list) list.push(index);
      else adjacency.set(id, [index]);
    }
  });

  return { nodes, edges: payload.edges, adjacency };
}

let cached: Promise<EngineData> | null = null;

/** 生成済みデータを読み込む。2回目以降は同じものを返す。 */
export function loadEngineData(): Promise<EngineData> {
  if (cached) return cached;

  cached = (async () => {
    const [settings, graphPayload, hazardCollection, places] = await Promise.all([
      loadJson<EngineSettings>('engine.json'),
      loadJson<{ nodes: Record<string, [number, number]>; edges: Edge[] }>('walk_graph.json'),
      loadJson<{ features: { properties: Record<string, unknown>; geometry: { coordinates: [number, number] } }[] }>(
        'hazards.geojson',
      ),
      loadJson<Place[]>('places.json'),
    ]);

    const hazards: Hazard[] = hazardCollection.features.map((feature) => ({
      id: feature.properties.id as string,
      lng: feature.geometry.coordinates[0],
      lat: feature.geometry.coordinates[1],
      baseWeight: feature.properties.baseWeight as number,
      reasons: (feature.properties.reasons ?? {}) as Record<string, string>,
    }));

    return { settings, graph: buildGraph(graphPayload), hazards, places };
  })();

  return cached;
}
