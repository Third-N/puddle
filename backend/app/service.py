"""APIが使う計算のまとめ役。

起動時に生成済みデータを読み込み、リクエストごとに
「最短ルート・回避ルート・周辺の危険地点」を組み立てる。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from . import geo, hazards, routing
from .config import (
    DEMO_AREA,
    HAZARD_CORRIDOR_M,
    HAZARD_GEOJSON,
    HAZARD_MAX_RESULTS,
    PLACES_JSON,
    RAIN_PROFILES,
    RISK_RASTER,
    WALK_GRAPH,
)
from .models import DangerPoint, LatLng, PlaceLabel, RouteResult, SearchResult
from .network import WalkGraph, load_walk_graph
from .places import PlaceIndex

ROUTE_STYLES = {
    "shortest": {"label": "最短ルート", "color": "#6b7280"},
    "avoid": {"label": "水たまり回避ルート", "color": "#16a34a"},
}


class DataNotBuiltError(RuntimeError):
    """生成物が無いときに出す。何をすればいいかまで伝える。"""


class OutOfAreaError(ValueError):
    """デモ対象地域の外を指定されたときに出す。"""


@dataclass
class PuddleService:
    graph: WalkGraph
    model: hazards.RiskModel
    hazard_points: list[dict]
    places: PlaceIndex

    @classmethod
    def load(cls) -> "PuddleService":
        missing = [
            path.name
            for path in (WALK_GRAPH, RISK_RASTER, HAZARD_GEOJSON, PLACES_JSON)
            if not path.exists()
        ]
        if missing:
            raise DataNotBuiltError(
                f"生成済みデータが見つかりません({', '.join(missing)})。"
                "backend で `python scripts/build_data.py` を実行してください。"
            )
        return cls(
            graph=load_walk_graph(WALK_GRAPH),
            model=hazards.RiskModel.load(RISK_RASTER),
            hazard_points=hazards.from_geojson(json.loads(HAZARD_GEOJSON.read_text())),
            places=PlaceIndex.load(PLACES_JSON),
        )

    def describe_point(self, point: LatLng) -> PlaceLabel:
        """地図上の1点に、人が読んで分かる名前を付けて返す。"""
        self._check_area(point, "指定した地点")
        return PlaceLabel(**self.places.label_for(point.lat, point.lng, self.graph))

    def _check_area(self, point: LatLng, name: str) -> None:
        if not DEMO_AREA.contains(point.lat, point.lng):
            raise OutOfAreaError(
                f"{name}がデモ対象地域の外です。"
                "東京駅・有楽町駅・日比谷・京橋の周辺で指定してください"
            )

    def danger_points_for(
        self, intensity: str, paths: list[list[tuple[float, float]]]
    ) -> list[DangerPoint]:
        """ルート周辺の危険地点を、雨量を反映した形で返す。"""
        profile = RAIN_PROFILES[intensity]
        multiplier = profile["multiplier"]

        selected: list[tuple[float, dict]] = []
        for point in self.hazard_points:
            distance = min(
                geo.distance_to_path_m(point["lon"], point["lat"], path)
                for path in paths
            )
            if distance <= HAZARD_CORRIDOR_M:
                selected.append((distance, point))

        selected.sort(key=lambda item: -item[1]["baseWeight"])

        results: list[DangerPoint] = []
        for _, point in selected[:HAZARD_MAX_RESULTS]:
            weight = min(1.0, point["baseWeight"] * multiplier)
            results.append(
                DangerPoint(
                    id=point["id"],
                    lat=point["lat"],
                    lng=point["lon"],
                    baseWeight=round(point["baseWeight"], 4),
                    weight=round(weight, 4),
                    displayRisk=round(weight * 100),
                    level=hazards.level_for(weight),
                    reason=hazards.describe(point["metrics"], profile["label"]),
                )
            )
        return results

    def search(
        self, origin: LatLng, destination: LatLng, intensity: str
    ) -> SearchResult:
        """フロントがそのまま描画できる形で検索結果を返す。"""
        self._check_area(origin, "出発地")
        self._check_area(destination, "目的地")

        multiplier = RAIN_PROFILES[intensity]["multiplier"]
        found = routing.find_routes(
            self.graph,
            (origin.lng, origin.lat),
            (destination.lng, destination.lat),
            multiplier,
        )

        routes = [
            RouteResult(
                id=route_id,
                label=ROUTE_STYLES[route_id]["label"],
                color=ROUTE_STYLES[route_id]["color"],
                distanceM=round(route.distance_m),
                durationMin=route.duration_min,
                riskScore=route.risk_score,
                path=[LatLng(lat=lat, lng=lon) for lon, lat in route.path],
            )
            for route_id, route in found.items()
        ]

        danger_points = self.danger_points_for(
            intensity, [route.path for route in found.values()]
        )
        return SearchResult(routes=routes, dangerPoints=danger_points)
