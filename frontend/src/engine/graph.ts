import { haversineMeters, distanceToPath } from '../utils/geo';
import type { LatLng } from '../types';
import type { WalkGraph } from './data';

/**
 * 歩行グラフ上の近傍探索。
 *
 * 1万件のノードを毎回線形に走査すると、雨量を切り替えるたびに引っかかる。
 * およそ200m四方の格子に振り分けておき、中心から輪を広げて探す。
 */
const GRID_CELL_DEG = 0.002;
const GRID_MAX_RINGS = 12;

const indexes = new WeakMap<WalkGraph, Map<string, number[]>>();

function cellKey(lng: number, lat: number): string {
  return `${Math.floor(lng / GRID_CELL_DEG)}:${Math.floor(lat / GRID_CELL_DEG)}`;
}

function gridFor(graph: WalkGraph): Map<string, number[]> {
  const existing = indexes.get(graph);
  if (existing) return existing;

  const grid = new Map<string, number[]>();
  for (const [id, point] of graph.nodes) {
    const key = cellKey(point.lng, point.lat);
    const bucket = grid.get(key);
    if (bucket) bucket.push(id);
    else grid.set(key, [id]);
  }
  indexes.set(graph, grid);
  return grid;
}

export function nearestNode(graph: WalkGraph, point: LatLng): { id: number; distanceM: number } {
  const grid = gridFor(graph);
  const cx = Math.floor(point.lng / GRID_CELL_DEG);
  const cy = Math.floor(point.lat / GRID_CELL_DEG);

  let bestId = -1;
  let bestDistance = Infinity;

  for (let ring = 0; ring <= GRID_MAX_RINGS; ring++) {
    for (let dx = -ring; dx <= ring; dx++) {
      for (let dy = -ring; dy <= ring; dy++) {
        if (ring > 0 && Math.max(Math.abs(dx), Math.abs(dy)) !== ring) continue;
        const bucket = grid.get(`${cx + dx}:${cy + dy}`);
        if (!bucket) continue;
        for (const id of bucket) {
          const node = graph.nodes.get(id)!;
          const distance = haversineMeters(point, node);
          if (distance < bestDistance) {
            bestDistance = distance;
            bestId = id;
          }
        }
      }
    }
    // 1輪ぶん余分に見てから打ち切る。セル境界ぎわの取りこぼしを防ぐため。
    if (bestId >= 0 && ring >= 1) break;
  }

  if (bestId < 0) throw new Error('対象地域内に歩行者ネットワークが見つかりませんでした');
  return { id: bestId, distanceM: bestDistance };
}

/** 指定座標の近くにある、名前つきの道の名称と距離。 */
export function nearestStreetName(
  graph: WalkGraph,
  point: LatLng,
  maxDistanceM: number,
): { name: string; distanceM: number } | null {
  const grid = gridFor(graph);
  const cx = Math.floor(point.lng / GRID_CELL_DEG);
  const cy = Math.floor(point.lat / GRID_CELL_DEG);

  let best: { name: string; distanceM: number } | null = null;
  const seen = new Set<number>();

  for (let dx = -1; dx <= 1; dx++) {
    for (let dy = -1; dy <= 1; dy++) {
      const bucket = grid.get(`${cx + dx}:${cy + dy}`);
      if (!bucket) continue;
      for (const nodeId of bucket) {
        for (const edgeIndex of graph.adjacency.get(nodeId) ?? []) {
          if (seen.has(edgeIndex)) continue;
          seen.add(edgeIndex);
          const edge = graph.edges[edgeIndex];
          if (!edge.name) continue;
          const distance = distanceToPath(point, [
            graph.nodes.get(edge.a)!,
            graph.nodes.get(edge.b)!,
          ]);
          if (distance <= maxDistanceM && (best === null || distance < best.distanceM)) {
            best = { name: edge.name, distanceM: distance };
          }
        }
      }
    }
  }
  return best;
}
