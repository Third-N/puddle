"""歩行空間ネットワーク上の経路探索。

「距離だけを見る最短ルート」と「危険度をコストに織り込んだ回避ルート」を、
同じダイクストラ法にコスト関数だけ差し替えて求める。
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

import numpy as np

from . import geo
from .config import (
    AVOID_ALPHA,
    EDGE_SAMPLE_STEP_M,
    EXPOSURE_REFERENCE_M,
    MAX_SNAP_DISTANCE_M,
    PUDDLE_REFERENCE_RISK,
    WALK_METERS_PER_MIN,
)
from .hazards import RiskModel
from .network import WalkGraph


@dataclass
class Route:
    """探索結果の1本ぶん。"""

    path: list[tuple[float, float]]  # [(lon, lat), ...]
    distance_m: float
    risk_score: int  # 0..100

    @property
    def duration_min(self) -> int:
        return max(1, round(self.distance_m / WALK_METERS_PER_MIN))


def annotate_edge_risk(graph: WalkGraph, model: RiskModel) -> None:
    """各辺に、その区間の平均危険度と最大危険度を書き込む。

    危険地点との距離ではなくラスタを直接サンプリングするので、
    「危険地点の代表点からは外れているが、区間全体がじわっと低い」道も拾える。
    """
    for edge in graph.edges:
        lon1, lat1 = graph.nodes[edge["a"]]
        lon2, lat2 = graph.nodes[edge["b"]]
        samples = [
            model.sample_risk(lon, lat)
            for lon, lat in geo.interpolate_points(
                lon1, lat1, lon2, lat2, step_m=EDGE_SAMPLE_STEP_M
            )
        ]
        edge["risk"] = round(float(np.mean(samples)), 4)
        edge["riskMax"] = round(float(np.max(samples)), 4)


def _effective_risk(edge: dict, rain_multiplier: float) -> float:
    """雨の強さを掛けた、その辺の実効危険度(0..1)。"""
    return min(1.0, edge.get("risk", 0.0) * rain_multiplier)


def _dijkstra(
    graph: WalkGraph, start: int, goal: int, rain_multiplier: float, avoid: bool
) -> list[int]:
    """start から goal までの最小コスト経路のノード列を返す。"""
    best_cost: dict[int, float] = {start: 0.0}
    previous: dict[int, int] = {}
    queue: list[tuple[float, int]] = [(0.0, start)]
    settled: set[int] = set()

    while queue:
        cost, node = heapq.heappop(queue)
        if node in settled:
            continue
        settled.add(node)
        if node == goal:
            break

        for neighbour, edge in graph.neighbours(node):
            if neighbour in settled:
                continue
            length = edge["length"]
            if avoid:
                # 危険な区間は「実際より長い道」として扱い、迂回を選ばせる
                step = length * (1.0 + AVOID_ALPHA * _effective_risk(edge, rain_multiplier))
            else:
                step = length
            candidate = cost + step
            if candidate < best_cost.get(neighbour, float("inf")):
                best_cost[neighbour] = candidate
                previous[neighbour] = node
                heapq.heappush(queue, (candidate, neighbour))

    if goal not in best_cost:
        return []

    node_path = [goal]
    while node_path[-1] != start:
        node_path.append(previous[node_path[-1]])
    node_path.reverse()
    return node_path


def _edges_along(graph: WalkGraph, node_path: list[int]) -> list[dict]:
    """ノード列から、実際に通る辺を取り出す。"""
    edges = []
    for a, b in zip(node_path, node_path[1:]):
        candidates = [
            edge
            for _, edge in graph.neighbours(a)
            if (edge["a"] == a and edge["b"] == b) or (edge["a"] == b and edge["b"] == a)
        ]
        if candidates:
            edges.append(min(candidates, key=lambda e: e["length"]))
    return edges


def score_route(edges: list[dict], rain_multiplier: float) -> int:
    """ルート全体の危険度を 0..100 で表す。

    「そのルートを歩いて水たまりに出くわす推定確率」として計算する。
    区間ごとの遭遇率を距離で積み上げ、1回も出くわさない確率の余事象を取る。
    危険度の高い区間を長く歩くほど上がり、短く抜ければ下がる。
    """
    if not edges:
        return 0

    exposure = 0.0
    for edge in edges:
        risk = _effective_risk(edge, rain_multiplier)
        encounter_rate = min(1.0, risk / PUDDLE_REFERENCE_RISK)
        exposure += encounter_rate * edge["length"] / EXPOSURE_REFERENCE_M

    probability = 1.0 - math.exp(-exposure)
    return int(round(min(1.0, max(0.0, probability)) * 100))


def find_routes(
    graph: WalkGraph,
    origin: tuple[float, float],
    destination: tuple[float, float],
    rain_multiplier: float,
) -> dict[str, Route]:
    """最短ルートと水たまり回避ルートをまとめて求める。

    origin / destination は (lon, lat)。いちばん近い歩行ネットワーク上の
    ノードへスナップしてから探索し、線の端はクリック地点まで伸ばす。
    """
    start, start_distance = graph.nearest_node_with_distance(*origin)
    goal, goal_distance = graph.nearest_node_with_distance(*destination)

    # 道から離れすぎた地点を無理に寄せると、ピンとルートの始点が
    # 大きく離れて見える。そうなる前に、選び直してもらう。
    for name, distance in (("出発地", start_distance), ("目的地", goal_distance)):
        if distance > MAX_SNAP_DISTANCE_M:
            raise ValueError(
                f"{name}の近くに歩ける道が見つかりません"
                f"(いちばん近い道まで約{distance:.0f}m)。道路の上で選び直してください"
            )

    if start == goal:
        raise ValueError("出発地と目的地が近すぎます。もう少し離れた地点を選んでください")

    routes: dict[str, Route] = {}
    for key, avoid in (("shortest", False), ("avoid", True)):
        node_path = _dijkstra(graph, start, goal, rain_multiplier, avoid=avoid)
        if not node_path:
            raise ValueError("出発地と目的地をつなぐ歩行ルートが見つかりませんでした")

        coords = [graph.nodes[node_id] for node_id in node_path]
        coords = [origin] + coords + [destination]
        edges = _edges_along(graph, node_path)
        routes[key] = Route(
            path=coords,
            distance_m=geo.path_length_m(coords),
            risk_score=score_route(edges, rain_multiplier),
        )

    return routes
