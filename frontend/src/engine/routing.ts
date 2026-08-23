import { haversineMeters, pathLengthMeters, distanceToPath } from '../utils/geo';
import { nearestNode } from './graph';
import type { DangerPoint, LatLng, RainIntensity, RouteResult, SearchResult } from '../types';
import type { Edge, EngineData } from './data';

/**
 * ブラウザ側の経路探索。
 *
 * バックエンド(app/routing.py)と同じ手順を踏む。辺ごとの危険度と
 * 浸水フラグは walk_graph.json に焼き込み済みなので、地形の再計算は要らない。
 * 係数はすべて engine.json から取っている。
 */

/** 最小ヒープ。経路探索の待ち行列に使う。 */
class MinHeap {
  private items: { cost: number; node: number }[] = [];

  push(cost: number, node: number): void {
    this.items.push({ cost, node });
    let i = this.items.length - 1;
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (this.items[parent].cost <= this.items[i].cost) break;
      [this.items[parent], this.items[i]] = [this.items[i], this.items[parent]];
      i = parent;
    }
  }

  pop(): { cost: number; node: number } | undefined {
    const top = this.items[0];
    const last = this.items.pop();
    if (this.items.length > 0 && last) {
      this.items[0] = last;
      let i = 0;
      for (;;) {
        const left = i * 2 + 1;
        const right = left + 1;
        let smallest = i;
        if (left < this.items.length && this.items[left].cost < this.items[smallest].cost) smallest = left;
        if (right < this.items.length && this.items[right].cost < this.items[smallest].cost) smallest = right;
        if (smallest === i) break;
        [this.items[smallest], this.items[i]] = [this.items[i], this.items[smallest]];
        i = smallest;
      }
    }
    return top;
  }

  get size(): number {
    return this.items.length;
  }
}

function effectiveRisk(edge: Edge, rainMultiplier: number): number {
  return Math.min(1, edge.risk * rainMultiplier);
}

function dijkstra(
  data: EngineData,
  start: number,
  goal: number,
  rainMultiplier: number,
  avoid: boolean,
): number[] {
  const { graph, settings } = data;
  const best = new Map<number, number>([[start, 0]]);
  const previous = new Map<number, number>();
  const settled = new Set<number>();
  const queue = new MinHeap();
  queue.push(0, start);

  while (queue.size > 0) {
    const current = queue.pop()!;
    if (settled.has(current.node)) continue;
    settled.add(current.node);
    if (current.node === goal) break;

    for (const edgeIndex of graph.adjacency.get(current.node) ?? []) {
      const edge = graph.edges[edgeIndex];
      const next = edge.a === current.node ? edge.b : edge.a;
      if (settled.has(next)) continue;

      // 危険な区間は「実際より長い道」として扱い、迂回を選ばせる
      const step = avoid
        ? edge.length * (1 + settings.avoidAlpha * effectiveRisk(edge, rainMultiplier))
        : edge.length;
      const candidate = current.cost + step;
      if (candidate < (best.get(next) ?? Infinity)) {
        best.set(next, candidate);
        previous.set(next, current.node);
        queue.push(candidate, next);
      }
    }
  }

  if (!best.has(goal)) return [];
  const nodePath = [goal];
  while (nodePath[nodePath.length - 1] !== start) {
    const prior = previous.get(nodePath[nodePath.length - 1]);
    if (prior === undefined) return [];
    nodePath.push(prior);
  }
  return nodePath.reverse();
}

function edgesAlong(data: EngineData, nodePath: number[]): Edge[] {
  const { graph } = data;
  const edges: Edge[] = [];
  for (let i = 0; i + 1 < nodePath.length; i++) {
    const a = nodePath[i];
    const b = nodePath[i + 1];
    let chosen: Edge | null = null;
    for (const edgeIndex of graph.adjacency.get(a) ?? []) {
      const edge = graph.edges[edgeIndex];
      const connects = (edge.a === a && edge.b === b) || (edge.a === b && edge.b === a);
      if (connects && (chosen === null || edge.length < chosen.length)) chosen = edge;
    }
    if (chosen) edges.push(chosen);
  }
  return edges;
}

/**
 * ルート全体の危険度を 0..100 で表す。
 * そのルートを歩いて水たまりに出くわす推定確率として計算する。
 */
function scoreRoute(data: EngineData, edges: Edge[], rainMultiplier: number): number {
  const { settings } = data;
  if (edges.length === 0) return 0;

  let exposure = 0;
  for (const edge of edges) {
    const rate = Math.min(1, effectiveRisk(edge, rainMultiplier) / settings.puddleReferenceRisk);
    exposure += (rate * edge.length) / settings.exposureReferenceM;
  }
  return Math.round(Math.min(1, Math.max(0, 1 - Math.exp(-exposure))) * 100);
}

/** 東京都の浸水予想で浸水する区間が、経路に占める割合(%)。 */
function floodOverlap(edges: Edge[]): number {
  if (edges.length === 0) return 0;
  let total = 0;
  let flooded = 0;
  for (const edge of edges) {
    total += edge.length;
    flooded += edge.flood * edge.length;
  }
  return total <= 0 ? 0 : Math.round((flooded / total) * 100);
}

function levelFor(data: EngineData, weight: number): DangerPoint['level'] {
  if (weight >= data.settings.levelHighThreshold) return 'high';
  if (weight >= data.settings.levelMediumThreshold) return 'medium';
  return 'low';
}

function dangerPointsFor(
  data: EngineData,
  intensity: RainIntensity,
  paths: LatLng[][],
): DangerPoint[] {
  const { settings, hazards } = data;
  const multiplier = settings.rainProfiles[intensity].multiplier;

  const nearby = hazards.filter((hazard) => {
    const point = { lat: hazard.lat, lng: hazard.lng };
    return paths.some((path) => distanceToPath(point, path) <= settings.hazardCorridorM);
  });

  nearby.sort((a, b) => b.baseWeight - a.baseWeight);

  return nearby.slice(0, settings.hazardMaxResults).map((hazard) => {
    const weight = Math.min(1, hazard.baseWeight * multiplier);
    return {
      id: hazard.id,
      lat: hazard.lat,
      lng: hazard.lng,
      baseWeight: hazard.baseWeight,
      weight,
      displayRisk: Math.round(weight * 100),
      level: levelFor(data, weight),
      reason: hazard.reasons[intensity] ?? '',
    };
  });
}

export function computeRoutes(
  data: EngineData,
  origin: LatLng,
  destination: LatLng,
  intensity: RainIntensity,
): SearchResult {
  const { graph, settings } = data;
  const area = settings.demoArea;

  for (const [point, name] of [
    [origin, '出発地'],
    [destination, '目的地'],
  ] as const) {
    const inside =
      point.lat >= area.minLat &&
      point.lat <= area.maxLat &&
      point.lng >= area.minLng &&
      point.lng <= area.maxLng;
    if (!inside) {
      throw new Error(
        `${name}がデモ対象地域の外です。東京駅・有楽町駅・日比谷・京橋の周辺で指定してください`,
      );
    }
  }

  const start = nearestNode(graph, origin);
  const goal = nearestNode(graph, destination);

  for (const [snap, name] of [
    [start, '出発地'],
    [goal, '目的地'],
  ] as const) {
    if (snap.distanceM > settings.maxSnapDistanceM) {
      throw new Error(
        `${name}の近くに歩ける道が見つかりません（いちばん近い道まで約${snap.distanceM.toFixed(0)}m）。道路の上で選び直してください`,
      );
    }
  }

  if (start.id === goal.id) {
    throw new Error('出発地と目的地が近すぎます。もう少し離れた地点を選んでください');
  }

  const multiplier = settings.rainProfiles[intensity].multiplier;
  const routes: RouteResult[] = [];
  const paths: LatLng[][] = [];

  for (const id of ['shortest', 'avoid'] as const) {
    const nodePath = dijkstra(data, start.id, goal.id, multiplier, id === 'avoid');
    if (nodePath.length === 0) {
      throw new Error('出発地と目的地をつなぐ歩行ルートが見つかりませんでした');
    }

    const path = [origin, ...nodePath.map((n) => graph.nodes.get(n)!), destination];
    const edges = edgesAlong(data, nodePath);
    const distanceM = pathLengthMeters(path);

    paths.push(path);
    routes.push({
      id,
      label: settings.routeStyles[id].label,
      color: settings.routeStyles[id].color,
      distanceM: Math.round(distanceM),
      durationMin: Math.max(1, Math.round(distanceM / settings.walkMetersPerMin)),
      riskScore: scoreRoute(data, edges, multiplier),
      floodOverlapPct: floodOverlap(edges),
      path,
    });
  }

  return { routes, dangerPoints: dangerPointsFor(data, intensity, paths) };
}

export { haversineMeters };
