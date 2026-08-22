"""OpenStreetMap から歩行空間ネットワークを組み立てる。

Overpass API で対象地域の道路データを取り、歩ける道だけを残したグラフにする。
取得結果は data/cache に置くので、2回目以降はオフラインでも動く。
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import geo
from .config import (
    BBox,
    CACHE_DIR,
    OVERPASS_ENDPOINTS,
    PLACE_LANDMARK_AMENITIES,
    PLACE_LANDMARK_LEISURE,
    PLACE_LANDMARK_TOURISM,
)

_USER_AGENT = "mizutamari-zero-tokyo/0.1 (hackathon demo; contact: team-third-n)"

# 歩行者が通れない、あるいは経路として不適切な道路種別
_EXCLUDED_HIGHWAYS = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "construction",
    "proposed",
    "raceway",
    "bus_guideway",
    "busway",
}
# 明示的に歩行を禁じている値
_NO_FOOT = {"no", "private"}

# 最近傍ノード探索に使う格子のセル幅(度)。緯度35度あたりでおよそ200m四方。
_GRID_CELL_DEG = 0.002
# 見つからないときに広げる輪の上限。これを超えたら対象地域外とみなす。
_GRID_MAX_RINGS = 12


@dataclass
class WalkGraph:
    """歩行空間の無向グラフ。"""

    nodes: dict[int, tuple[float, float]]  # node_id -> (lon, lat)
    adjacency: dict[int, list[int]] = field(default_factory=dict)  # node_id -> edge索引
    edges: list[dict] = field(default_factory=list)
    _grid: dict[tuple[int, int], list[int]] | None = field(default=None, repr=False)

    def neighbours(self, node_id: int) -> list[tuple[int, dict]]:
        """隣接ノードと、そこへ至る辺を返す。"""
        result = []
        for edge_index in self.adjacency.get(node_id, ()):
            edge = self.edges[edge_index]
            other = edge["b"] if edge["a"] == node_id else edge["a"]
            result.append((other, edge))
        return result

    def _grid_key(self, lon: float, lat: float) -> tuple[int, int]:
        return (int(lon / _GRID_CELL_DEG), int(lat / _GRID_CELL_DEG))

    def _ensure_grid(self) -> None:
        """ノードをおよそ200m四方のセルに振り分けた索引を、初回だけ作る。"""
        if self._grid is not None:
            return
        grid: dict[tuple[int, int], list[int]] = {}
        for node_id, (node_lon, node_lat) in self.nodes.items():
            grid.setdefault(self._grid_key(node_lon, node_lat), []).append(node_id)
        self._grid = grid

    def nearest_node_with_distance(self, lon: float, lat: float) -> tuple[int, float]:
        """いちばん近いノードIDと、そこまでの距離(m)を返す。

        全ノードを線形に走査すると対象地域を広げたときに効かなくなるので、
        格子状の索引を使い、中心セルから外側へ輪を広げながら探す。
        """
        self._ensure_grid()
        assert self._grid is not None
        center_x, center_y = self._grid_key(lon, lat)

        best_id, best_distance = -1, math.inf
        for ring in range(0, _GRID_MAX_RINGS + 1):
            for dx in range(-ring, ring + 1):
                for dy in range(-ring, ring + 1):
                    # すでに見た内側のセルは飛ばす
                    if ring > 0 and max(abs(dx), abs(dy)) != ring:
                        continue
                    for node_id in self._grid.get((center_x + dx, center_y + dy), ()):
                        node_lon, node_lat = self.nodes[node_id]
                        distance = geo.haversine_m(lat, lon, node_lat, node_lon)
                        if distance < best_distance:
                            best_id, best_distance = node_id, distance
            # 1輪ぶん余分に見てから打ち切る。セル境界ぎわの取りこぼしを防ぐため。
            if best_id >= 0 and ring >= 1:
                break

        if best_id < 0:
            raise ValueError("対象地域内に歩行者ネットワークが見つかりませんでした")
        return best_id, best_distance

    def nearest_node(self, lon: float, lat: float) -> int:
        """指定座標にいちばん近いノードIDを返す。"""
        return self.nearest_node_with_distance(lon, lat)[0]

    def nearest_street_name(self, lon: float, lat: float, max_distance_m: float) -> tuple[str, float] | None:
        """指定座標の近くにある、名前つきの道の名称と距離を返す。"""
        self._ensure_grid()
        assert self._grid is not None
        center_x, center_y = self._grid_key(lon, lat)

        best: tuple[str, float] | None = None
        seen: set[int] = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for node_id in self._grid.get((center_x + dx, center_y + dy), ()):
                    for edge_index in self.adjacency.get(node_id, ()):
                        if edge_index in seen:
                            continue
                        seen.add(edge_index)
                        edge = self.edges[edge_index]
                        name = edge.get("name")
                        if not name:
                            continue
                        lon1, lat1 = self.nodes[edge["a"]]
                        lon2, lat2 = self.nodes[edge["b"]]
                        distance = geo.distance_to_path_m(
                            lon, lat, [(lon1, lat1), (lon2, lat2)]
                        )
                        if distance <= max_distance_m and (best is None or distance < best[1]):
                            best = (name, distance)
        return best

    def to_dict(self) -> dict:
        return {
            "nodes": {str(k): v for k, v in self.nodes.items()},
            "edges": self.edges,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "WalkGraph":
        nodes = {int(k): tuple(v) for k, v in payload["nodes"].items()}
        graph = cls(nodes=nodes, edges=payload["edges"])
        graph._rebuild_adjacency()
        return graph

    def _rebuild_adjacency(self) -> None:
        self.adjacency = {}
        for index, edge in enumerate(self.edges):
            self.adjacency.setdefault(edge["a"], []).append(index)
            self.adjacency.setdefault(edge["b"], []).append(index)


def _is_walkable(tags: dict) -> bool:
    highway = tags.get("highway")
    if not highway or highway in _EXCLUDED_HIGHWAYS:
        return False
    if tags.get("foot") in _NO_FOOT:
        return False
    if tags.get("access") in _NO_FOOT and tags.get("foot") not in {"yes", "designated"}:
        return False
    if highway == "cycleway" and tags.get("foot") not in {"yes", "designated"}:
        return False
    return True


def fetch_osm_ways(bbox: BBox, refresh: bool = False) -> dict:
    """対象地域の道路データを Overpass から取得する(キャッシュあり)。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / "osm_walk.json"
    if cached.exists() and not refresh:
        return json.loads(cached.read_text())

    min_lat, min_lon, max_lat, max_lon = bbox.as_tuple()
    query = (
        "[out:json][timeout:90];"
        f'(way["highway"]({min_lat},{min_lon},{max_lat},{max_lon}););'
        "out body geom;"
    )
    last_error: Exception | None = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            request = urllib.request.Request(
                endpoint,
                data=query.encode("utf-8"),
                headers={
                    "User-Agent": _USER_AGENT,
                    "Content-Type": "text/plain; charset=utf-8",
                },
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
            cached.write_text(json.dumps(payload))
            return payload
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as err:
            last_error = err
    raise RuntimeError(f"Overpass API から取得できませんでした: {last_error}")


def build_walk_graph(osm: dict, bbox: BBox) -> WalkGraph:
    """Overpass の応答から歩行グラフを組み立てる。"""
    nodes: dict[int, tuple[float, float]] = {}
    edges: list[dict] = []

    for element in osm.get("elements", []):
        if element.get("type") != "way":
            continue
        tags = element.get("tags", {})
        if not _is_walkable(tags):
            continue
        node_ids = element.get("nodes") or []
        geometry = element.get("geometry") or []
        if len(node_ids) != len(geometry) or len(node_ids) < 2:
            continue

        highway = tags["highway"]
        for node_id, point in zip(node_ids, geometry):
            nodes[node_id] = (point["lon"], point["lat"])

        for (a, pa), (b, pb) in zip(
            zip(node_ids, geometry), zip(node_ids[1:], geometry[1:])
        ):
            if a == b:
                continue
            if not (
                bbox.contains(pa["lat"], pa["lon"]) or bbox.contains(pb["lat"], pb["lon"])
            ):
                continue
            edges.append(
                {
                    "a": a,
                    "b": b,
                    "length": round(
                        geo.haversine_m(pa["lat"], pa["lon"], pb["lat"], pb["lon"]), 2
                    ),
                    "highway": highway,
                    "name": tags.get("name"),
                }
            )

    used = {edge["a"] for edge in edges} | {edge["b"] for edge in edges}
    graph = WalkGraph(nodes={k: v for k, v in nodes.items() if k in used}, edges=edges)
    graph._rebuild_adjacency()
    return largest_component(graph)


def largest_component(graph: WalkGraph) -> WalkGraph:
    """最大の連結成分だけを残す。孤立した小さな道は経路探索の邪魔になる。"""
    seen: set[int] = set()
    best: set[int] = set()

    for start in graph.nodes:
        if start in seen:
            continue
        component: set[int] = set()
        stack = [start]
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            for neighbour, _ in graph.neighbours(current):
                if neighbour not in component:
                    stack.append(neighbour)
        seen |= component
        if len(component) > len(best):
            best = component

    edges = [e for e in graph.edges if e["a"] in best and e["b"] in best]
    trimmed = WalkGraph(nodes={k: v for k, v in graph.nodes.items() if k in best}, edges=edges)
    trimmed._rebuild_adjacency()
    return trimmed


def load_walk_graph(path: Path) -> WalkGraph:
    return WalkGraph.from_dict(json.loads(path.read_text()))


def fetch_osm_places(bbox: BBox, refresh: bool = False) -> dict:
    """対象地域の駅・施設・ビルを Overpass から取得する(キャッシュあり)。

    地図をクリックした地点に「東京駅」「アーティゾン美術館 付近」といった
    名前を付けるために使う。座標だけの表示は、デモで何を選んだのか伝わらない。
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / "osm_places.json"
    if cached.exists() and not refresh:
        return json.loads(cached.read_text())

    min_lat, min_lon, max_lat, max_lon = bbox.as_tuple()
    area = f"({min_lat},{min_lon},{max_lat},{max_lon})"
    query = (
        "[out:json][timeout:90];("
        f'node["name"]["railway"="station"]{area};'
        f'node["name"]["public_transport"="station"]{area};'
        f'way["name"]["railway"="station"]{area};'
        f'node["name"]["amenity"]{area};'
        f'way["name"]["amenity"]{area};'
        f'way["name"]["building"]{area};'
        f'node["name"]["tourism"]{area};'
        f'way["name"]["tourism"]{area};'
        f'way["name"]["leisure"]{area};'
        ");out center tags;"
    )
    last_error: Exception | None = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            request = urllib.request.Request(
                endpoint,
                data=query.encode("utf-8"),
                headers={
                    "User-Agent": _USER_AGENT,
                    "Content-Type": "text/plain; charset=utf-8",
                },
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
            cached.write_text(json.dumps(payload))
            return payload
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as err:
            last_error = err
    raise RuntimeError(f"Overpass API から取得できませんでした: {last_error}")


def _classify_place(tags: dict) -> str | None:
    """OSMのタグから、地点名として使う種別を決める。使えないものは None。"""
    # public_transport=station だけだと、バス乗り場や桟橋まで駅扱いになってしまう
    if tags.get("railway") == "station":
        return "station"
    if (
        tags.get("tourism") in PLACE_LANDMARK_TOURISM
        or tags.get("amenity") in PLACE_LANDMARK_AMENITIES
        or tags.get("leisure") in PLACE_LANDMARK_LEISURE
    ):
        return "landmark"
    if tags.get("building"):
        return "building"
    return None


def build_places(osm: dict) -> list[dict]:
    """Overpass の応答から、地点名の一覧を組み立てる。

    チェーン店のような目印にならないものは `_classify_place` で落とす。
    同じ名前が近くに何件もある場合は、いちばん最初の1件だけ残す。
    """
    places: list[dict] = []
    seen: set[tuple[str, int, int]] = set()

    for element in osm.get("elements", []):
        tags = element.get("tags") or {}
        name = tags.get("name")
        if not name:
            continue
        kind = _classify_place(tags)
        if kind is None:
            continue

        if element.get("type") == "node":
            lon, lat = element.get("lon"), element.get("lat")
        else:
            center = element.get("center") or {}
            lon, lat = center.get("lon"), center.get("lat")
        if lon is None or lat is None:
            continue

        # 駅名は「東京」のように駅が付かない表記が多いので補う
        if kind == "station" and not name.endswith("駅"):
            name = f"{name}駅"

        # 同名の重複を間引く。駅は路線ごとにノードが分かれているので名前だけで、
        # それ以外はおよそ50m四方で見る。
        if kind == "station":
            key = (name, 0, 0)
        else:
            key = (name, int(lat / 0.00045), int(lon / 0.00055))
        if key in seen:
            continue
        seen.add(key)

        places.append(
            {"name": name, "lat": round(lat, 6), "lon": round(lon, 6), "kind": kind}
        )

    # 駅 → 施設 → ビル の順に並べておくと、後段で扱いやすい
    order = {"station": 0, "landmark": 1, "building": 2}
    places.sort(key=lambda p: order[p["kind"]])
    return places
