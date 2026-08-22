"""地形指標から「水たまりができそうな危険地点」を作る。

terrain.py が出した窪地の深さ・流域面積・傾斜・近傍との高低差を、
0..1 の危険度ラスタにまとめ、そこから代表点を危険地点として抜き出す。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import geo, terrain
from .config import (
    FLAT_MODIFIER_BASE,
    FLAT_MODIFIER_RANGE,
    FLAT_SLOPE_SATURATION_DEG,
    FLOW_CALIBRATION_PERCENTILES,
    HAZARD_EXPORT_FLOOR,
    HAZARD_MIN_SPACING_M,
    HAZARD_NEAR_NETWORK_M,
    LEVEL_HIGH_THRESHOLD,
    LEVEL_MEDIUM_THRESHOLD,
    RELATIVE_DEPTH_SATURATION_M,
    RISK_WEIGHTS,
    SINK_DEPTH_SATURATION_M,
)
from .terrain import ElevationGrid


@dataclass
class RiskModel:
    """危険度ラスタと、その根拠になった地形指標の束。"""

    grid: ElevationGrid
    risk: np.ndarray  # 0..1 の素の危険度(雨量を掛ける前)
    sink: np.ndarray  # くぼ地の深さ[m]
    flow: np.ndarray  # 流域面積[m^2]
    slope: np.ndarray  # 傾斜[度]
    relative: np.ndarray  # 近傍平均との高低差[m]

    def sample_risk(self, lon: float, lat: float) -> float:
        return self.grid.sample(self.risk, lon, lat)

    def metrics_at(self, lon: float, lat: float) -> dict[str, float]:
        return {
            "sink_m": self.grid.sample(self.sink, lon, lat),
            "flow_m2": self.grid.sample(self.flow, lon, lat),
            "slope_deg": self.grid.sample(self.slope, lon, lat),
            "relative_m": self.grid.sample(self.relative, lon, lat),
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            risk=self.risk.astype(np.float32),
            sink=self.sink.astype(np.float32),
            flow=self.flow.astype(np.float32),
            slope=self.slope.astype(np.float32),
            relative=self.relative.astype(np.float32),
            elevation=self.grid.elevation.astype(np.float32),
            meta=np.array(
                [
                    self.grid.origin_px,
                    self.grid.origin_py,
                    float(self.grid.zoom),
                    self.grid.cell_size_m,
                ]
            ),
        )

    @classmethod
    def load(cls, path: Path) -> "RiskModel":
        payload = np.load(path)
        origin_px, origin_py, zoom, cell_size = payload["meta"]
        grid = ElevationGrid(
            elevation=payload["elevation"],
            origin_px=float(origin_px),
            origin_py=float(origin_py),
            zoom=int(zoom),
            cell_size_m=float(cell_size),
        )
        return cls(
            grid=grid,
            risk=payload["risk"],
            sink=payload["sink"],
            flow=payload["flow"],
            slope=payload["slope"],
            relative=payload["relative"],
        )


def _smooth(raster: np.ndarray, radius: int = 1) -> np.ndarray:
    """単純な移動平均。DEM由来のノイズをならす。"""
    kernel = 2 * radius + 1
    padded = np.pad(raster, radius, mode="edge")
    stacked = np.zeros_like(raster, dtype=np.float64)
    for dr in range(kernel):
        for dc in range(kernel):
            stacked += padded[dr : dr + raster.shape[0], dc : dc + raster.shape[1]]
    return stacked / (kernel * kernel)


def _dilate(mask: np.ndarray, radius_cells: int) -> np.ndarray:
    """円形の構造要素で膨張させる。"""
    result = mask.copy()
    for dr in range(-radius_cells, radius_cells + 1):
        for dc in range(-radius_cells, radius_cells + 1):
            if dr * dr + dc * dc > radius_cells * radius_cells:
                continue
            result |= np.roll(np.roll(mask, dr, axis=0), dc, axis=1)
    return result


def network_mask(grid: ElevationGrid, walk_graph) -> np.ndarray:
    """歩ける道の近くのセルだけ True にしたマスクを作る。

    建物の中や線路上のくぼ地は歩行者に関係ないので、ここで落とす。
    """
    rows, cols = grid.shape
    mask = np.zeros((rows, cols), dtype=bool)

    for edge in walk_graph.edges:
        lon1, lat1 = walk_graph.nodes[edge["a"]]
        lon2, lat2 = walk_graph.nodes[edge["b"]]
        for lon, lat in geo.interpolate_points(lon1, lat1, lon2, lat2, step_m=4.0):
            row, col = grid.lonlat_to_rc(lon, lat)
            r, c = int(round(row)), int(round(col))
            if 0 <= r < rows and 0 <= c < cols:
                mask[r, c] = True

    radius_cells = max(1, int(round(HAZARD_NEAR_NETWORK_M / grid.cell_size_m)))
    return _dilate(mask, radius_cells)


def build_risk_model(grid: ElevationGrid, walk_graph) -> RiskModel:
    """標高グリッドから危険度ラスタを組み立てる。

    危険度 = (水が集まる度合い) × (水がはけない度合い) という形にしている。
    傾斜を加算項にすると、全体が平坦な都心部では全区間に同じ下駄が乗ってしまい、
    「この道だけ危ない」という差が消えてしまうため、倍率として掛けている。
    """
    elevation = grid.elevation
    source = np.nan_to_num(elevation, nan=float(np.nanmax(elevation)))

    # 窪地の深さ: 埋める前と後の差 = そこに溜まりうる水深
    filled_flat = terrain.fill_depressions(elevation)
    sink = np.clip(filled_flat - source, 0.0, None)

    # 流域面積: 平坦面でも流れが進むよう、微小な傾きを付けて埋めてから D8
    filled_sloped = terrain.fill_depressions(elevation, epsilon=1e-4)
    flow = terrain.flow_accumulation(filled_sloped, grid.cell_size_m)

    slope = terrain.slope_degrees(elevation, grid.cell_size_m)
    relative = terrain.relative_depth(elevation, radius_cells=8)

    # 流域面積は、歩ける道の上での分布を基準に正規化する。
    # 「対象地域の歩道の中で、どれくらい水が集まりやすいほうか」という相対評価。
    walkable = network_mask(grid, walk_graph)
    log_flow = np.log1p(flow)
    low_pct, high_pct = FLOW_CALIBRATION_PERCENTILES
    flow_low = float(np.percentile(log_flow[walkable], low_pct))
    flow_high = float(np.percentile(log_flow[walkable], high_pct))
    flow_score = np.clip((log_flow - flow_low) / max(flow_high - flow_low, 1e-6), 0.0, 1.0)

    sink_score = np.clip(sink / SINK_DEPTH_SATURATION_M, 0.0, 1.0)
    relative_score = np.clip(relative / RELATIVE_DEPTH_SATURATION_M, 0.0, 1.0)
    flat_score = np.clip(1.0 - slope / FLAT_SLOPE_SATURATION_DEG, 0.0, 1.0)

    convergence = (
        RISK_WEIGHTS["sink"] * sink_score
        + RISK_WEIGHTS["flow"] * flow_score
        + RISK_WEIGHTS["relative"] * relative_score
    )
    drainage_penalty = FLAT_MODIFIER_BASE + FLAT_MODIFIER_RANGE * flat_score

    risk = np.clip(_smooth(convergence * drainage_penalty, radius=1), 0.0, 1.0)

    return RiskModel(
        grid=grid, risk=risk, sink=sink, flow=flow, slope=slope, relative=relative
    )


def describe(metrics: dict[str, float], rain_label: str) -> str:
    """危険と判定した理由を、そのまま画面に出せる日本語にする。

    危険度の内訳そのものではなく、「何を根拠にそう言っているか」を返す。
    地形の落ち込みと、雨水の集まりやすさを1文ずつに分けている。
    """
    sink_m = metrics["sink_m"]
    relative_cm = metrics["relative_m"] * 100
    flow_m2 = metrics["flow_m2"]
    slope_deg = metrics["slope_deg"]

    sentences: list[str] = []

    if sink_m >= 0.08:
        depth = f"{sink_m:.1f}m" if sink_m >= 1.0 else f"{sink_m * 100:.0f}cm"
        sentences.append(f"周囲より約{depth}低いくぼ地です")
    elif relative_cm >= 30:
        sentences.append(f"半径約30mの平均より{relative_cm:.0f}cm低い地形です")

    if flow_m2 >= 2000:
        sentences.append(f"上流側の約{flow_m2:,.0f}m²から雨水が流れ込みます")
    elif slope_deg <= 0.6:
        sentences.append(f"傾斜が約{slope_deg:.1f}度とほぼ平坦で、雨水がはけにくい区間です")

    if not sentences:
        sentences.append("雨水が集まりやすい地形です")

    return f"{rain_label}の想定：" + "。".join(sentences)


def level_for(weight: float) -> str:
    """フロントの表示(高/中/低)に対応するレベル。"""
    if weight >= LEVEL_HIGH_THRESHOLD:
        return "high"
    if weight >= LEVEL_MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def extract_hazard_points(model: RiskModel, walk_graph) -> list[dict]:
    """危険度ラスタから、代表的な危険地点を抜き出す。

    危険度が高い順に見て、すでに採用した点から一定距離離れていれば採用する
    (貪欲な非最大値抑制)。近すぎる点が団子にならないようにするため。
    """
    grid = model.grid
    near_network = network_mask(grid, walk_graph)
    candidate = (model.risk >= HAZARD_EXPORT_FLOOR) & near_network

    rows, cols = np.nonzero(candidate)
    if rows.size == 0:
        return []

    values = model.risk[rows, cols]
    order = np.argsort(values)[::-1]

    spacing_cells = HAZARD_MIN_SPACING_M / grid.cell_size_m
    accepted: list[tuple[float, float]] = []
    points: list[dict] = []

    for index in order:
        r, c = int(rows[index]), int(cols[index])
        if any(
            (r - ar) ** 2 + (c - ac) ** 2 < spacing_cells**2 for ar, ac in accepted
        ):
            continue
        accepted.append((r, c))

        lon, lat = grid.rc_to_lonlat(r, c)
        metrics = model.metrics_at(lon, lat)
        points.append(
            {
                "id": f"hz-{len(points):03d}",
                "lon": round(lon, 6),
                "lat": round(lat, 6),
                "baseWeight": round(float(model.risk[r, c]), 4),
                "metrics": {k: round(v, 3) for k, v in metrics.items()},
            }
        )

    return points


def to_geojson(points: list[dict]) -> dict:
    """危険地点を GeoJSON FeatureCollection にする。"""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": point["id"],
                "geometry": {"type": "Point", "coordinates": [point["lon"], point["lat"]]},
                "properties": {
                    "id": point["id"],
                    "baseWeight": point["baseWeight"],
                    **point["metrics"],
                },
            }
            for point in points
        ],
    }


def from_geojson(collection: dict) -> list[dict]:
    """GeoJSON を内部表現へ戻す。"""
    points = []
    for feature in collection.get("features", []):
        lon, lat = feature["geometry"]["coordinates"]
        properties = feature["properties"]
        points.append(
            {
                "id": properties["id"],
                "lon": lon,
                "lat": lat,
                "baseWeight": properties["baseWeight"],
                "metrics": {
                    "sink_m": properties.get("sink_m", 0.0),
                    "flow_m2": properties.get("flow_m2", 0.0),
                    "slope_deg": properties.get("slope_deg", 0.0),
                    "relative_m": properties.get("relative_m", 0.0),
                },
            }
        )
    return points
