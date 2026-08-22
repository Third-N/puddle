"""アプリ全体の設定値。

デモ対象地域・雨量プロファイル・危険度モデルの係数はすべてここに集約している。
チューニングするときはこのファイルだけを触れば済むようにしてある。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
GENERATED_DIR = DATA_DIR / "generated"

HAZARD_GEOJSON = GENERATED_DIR / "hazards.geojson"
RISK_RASTER = GENERATED_DIR / "risk_raster.npz"
WALK_GRAPH = GENERATED_DIR / "walk_graph.json"
PLACES_JSON = GENERATED_DIR / "places.json"


@dataclass(frozen=True)
class BBox:
    """緯度経度の矩形範囲。"""

    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float

    def contains(self, lat: float, lon: float) -> bool:
        return self.min_lat <= lat <= self.max_lat and self.min_lon <= lon <= self.max_lon

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.min_lat, self.min_lon, self.max_lat, self.max_lon)


# デモ対象地域: 東京駅〜有楽町駅〜日比谷〜京橋 周辺
DEMO_AREA = BBox(min_lat=35.6700, min_lon=139.7570, max_lat=35.6870, max_lon=139.7760)

# 国土地理院 標高タイル(DEM5A = 5mメッシュ航空レーザ測量による数値標高モデル)
GSI_DEM_TYPES = ("dem5a", "dem5b", "dem10b")
GSI_DEM_ZOOM = 15
GSI_DEM_URL = "https://cyberjapandata.gsi.go.jp/xyz/{dem}/{z}/{x}/{y}.txt"

# OpenStreetMap 歩行空間ネットワーク
OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

# 徒歩の平均速度(m/分)。フロントのモックと同じ値に揃えてある。
WALK_METERS_PER_MIN = 78.0

# 雨の強さごとの係数。キーはフロントの RainIntensity 型と一致させること。
#   multiplier : 地形由来の素の危険度(baseWeight)にかける倍率
#   label      : 表示名
#   mm_per_hour: 想定雨量。判定理由の文面に使う。
RAIN_PROFILES: dict[str, dict] = {
    "light": {"multiplier": 0.55, "label": "弱雨", "mm_per_hour": 3},
    "medium": {"multiplier": 1.00, "label": "中雨", "mm_per_hour": 10},
    "heavy": {"multiplier": 1.45, "label": "強雨", "mm_per_hour": 30},
}
DEFAULT_RAIN = "medium"

# 「水が集まる度合い」の重み付け。合計が 1.0 になるようにしている。
RISK_WEIGHTS = {
    "sink": 0.42,  # くぼ地の深さ(周囲より低い場所)
    "flow": 0.38,  # 雨水の集まりやすさ(流域面積)
    "relative": 0.20,  # 近傍平均標高との差
}

# 各要因を 0..1 に正規化するときの飽和値
SINK_DEPTH_SATURATION_M = 0.5  # 50cm くぼんでいれば最大
RELATIVE_DEPTH_SATURATION_M = 0.8
FLAT_SLOPE_SATURATION_DEG = 2.0  # 2度以下はほぼ平坦とみなす

# 流域面積は絶対値ではなく、対象地域の歩ける道の中での相対位置で正規化する。
# 都心部は全体が平坦なので、固定のしきい値だと全区間が同じ値に潰れてしまうため。
FLOW_CALIBRATION_PERCENTILES = (50.0, 97.0)

# 傾斜は加算項ではなく倍率として効かせる。
# 加算にすると「どこも平坦」な都心部で全区間に同じ下駄を履かせてしまう。
FLAT_MODIFIER_BASE = 0.65
FLAT_MODIFIER_RANGE = 0.35

# 回避ルートのコスト関数 cost = 距離 * (1 + AVOID_ALPHA * 危険度)
AVOID_ALPHA = 4.0
# 危険度を辺に割り当てるときのサンプリング間隔(m)
EDGE_SAMPLE_STEP_M = 8.0

# ルートの危険度(%)は「その道を歩いて水たまりに出くわす推定確率」として出す。
#   PUDDLE_REFERENCE_RISK : この危険度の区間は、その雨量ならほぼ確実に水たまりになる
#   EXPOSURE_REFERENCE_M  : 遭遇率を積み上げるときの基準距離
# 同じ危険度の道でも、長く歩けばそのぶん出くわしやすくなる、という考え方。
PUDDLE_REFERENCE_RISK = 0.35
EXPOSURE_REFERENCE_M = 500.0

# 危険地点の抽出条件
HAZARD_EXPORT_FLOOR = 0.30  # これ未満の素の危険度は危険地点として出さない
HAZARD_MIN_SPACING_M = 55.0  # 危険地点どうしの最低間隔(m)
HAZARD_NEAR_NETWORK_M = 12.0  # 歩ける道からこの距離以内の点だけを対象にする
HAZARD_CORRIDOR_M = 130.0  # 検索結果に含める、ルート周辺の帯の幅(m)
HAZARD_MAX_RESULTS = 40  # 1回の検索で返す危険地点の上限

# 危険度レベルの境界。フロントの表示(高/中/低)と合わせてある。
LEVEL_HIGH_THRESHOLD = 0.62
LEVEL_MEDIUM_THRESHOLD = 0.32

# クリックした地点を歩行ネットワークへ寄せるときの上限(m)。
# これより遠いと、地図上のピンとルートの始点が離れて見えてしまう。
MAX_SNAP_DISTANCE_M = 120.0

# 地点名を引くときの探索半径(m)。種別ごとに変えている。
# 駅は遠くても手がかりになるが、ビル名は目の前でないと意味がないため。
PLACE_SEARCH_RADIUS_M = {
    "station": 300.0,
    "landmark": 160.0,
    "building": 70.0,
    "street": 45.0,
}

# 地点名として採用する OSM のタグ。チェーン店などは目印にならないので入れない。
PLACE_LANDMARK_AMENITIES = {
    "theatre",
    "university",
    "college",
    "hospital",
    "townhall",
    "library",
    "arts_centre",
    "community_centre",
    "place_of_worship",
    "embassy",
    "courthouse",
    "marketplace",
    "conference_centre",
    "exhibition_centre",
    "cinema",
    "concert_hall",
}
PLACE_LANDMARK_TOURISM = {"museum", "gallery", "attraction"}
PLACE_LANDMARK_LEISURE = {"park", "garden"}
