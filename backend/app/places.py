"""クリックした地点に、人が読んで分かる名前を付ける。

緯度経度をそのまま出しても、デモを見ている人には何も伝わらない。
OSMから拾った駅・施設・ビルと、歩行グラフが持つ道路名を突き合わせて、
「東京駅」「アーティゾン美術館 付近」「丸の内仲通り 付近」のように言い換える。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import geo
from .config import PLACE_SEARCH_RADIUS_M

# 駅は、この距離より近ければ「付近」を付けずに駅名だけで呼ぶ
_EXACT_HIT_M = 60.0

# 駅がこの距離内にあるときは、より近い施設があっても駅名を優先する。
# 駅のそばなら人は駅名で場所を言うため。「角川シネマ有楽町 付近」より
# 「有楽町駅」のほうが、聞いた側にすぐ伝わる。
_STATION_PRIORITY_M = 150.0


@dataclass
class PlaceIndex:
    """地点名の一覧。件数が千件程度なので、素直に総当たりで引く。"""

    places: list[dict]

    @classmethod
    def load(cls, path: Path) -> "PlaceIndex":
        return cls(places=json.loads(path.read_text()))

    def _nearest_by_kind(self, lat: float, lon: float) -> list[tuple[float, dict]]:
        """種別ごとの探索半径に収まる候補を、正規化した距離とともに返す。

        正規化しているのは、種別によって「近い」の意味が違うため。
        300m先の駅と20m先のビルなら、後者のほうが地点の説明として役に立つ。
        """
        candidates: list[tuple[float, dict]] = []
        for place in self.places:
            radius = PLACE_SEARCH_RADIUS_M[place["kind"]]
            # 総当たりの前に、粗い矩形で明らかに遠いものを落とす
            if abs(place["lat"] - lat) > 0.004 or abs(place["lon"] - lon) > 0.005:
                continue
            distance = geo.haversine_m(lat, lon, place["lat"], place["lon"])
            if distance <= radius:
                candidates.append((distance / radius, {**place, "distance": distance}))
        return candidates

    def label_for(self, lat: float, lon: float, walk_graph=None) -> dict:
        """地点の呼び名を決める。見つからなければ座標のまま返す。"""
        candidates = self._nearest_by_kind(lat, lon)

        if walk_graph is not None:
            street = walk_graph.nearest_street_name(
                lon, lat, PLACE_SEARCH_RADIUS_M["street"]
            )
            if street is not None:
                name, distance = street
                candidates.append(
                    (
                        distance / PLACE_SEARCH_RADIUS_M["street"],
                        {"name": name, "kind": "street", "distance": distance},
                    )
                )

        if not candidates:
            return {
                "label": f"地点 ({lat:.4f}, {lon:.4f})",
                "kind": "coordinate",
                "distanceM": 0,
            }

        nearby_stations = [
            item
            for item in candidates
            if item[1]["kind"] == "station"
            and item[1]["distance"] <= _STATION_PRIORITY_M
        ]
        pool = nearby_stations or candidates
        _, best = min(pool, key=lambda item: item[0])
        name, kind, distance = best["name"], best["kind"], best["distance"]

        if kind == "station" and distance <= _EXACT_HIT_M:
            label = name
        else:
            label = f"{name} 付近"

        return {"label": label, "kind": kind, "distanceM": round(distance)}
