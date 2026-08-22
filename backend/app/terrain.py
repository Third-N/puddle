"""国土地理院の標高タイルから、水たまりの手がかりになる地形指標を作る。

やっていること:
  1. DEM5A(5mメッシュ)タイルを対象地域ぶん取得してモザイク化する
  2. 窪地埋め(priority-flood)で「周囲より低い場所」の深さを出す
  3. D8 の流向から流域面積を積み上げて「雨水が集まりやすい場所」を出す
  4. 標高の勾配から傾斜を出す
"""

from __future__ import annotations

import heapq
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import geo
from .config import BBox, CACHE_DIR, GSI_DEM_TYPES, GSI_DEM_URL, GSI_DEM_ZOOM

_USER_AGENT = "mizutamari-zero-tokyo/0.1 (hackathon demo; contact: team-third-n)"


@dataclass
class ElevationGrid:
    """対象地域を覆う等間隔(Webメルカトル画素)の標高グリッド。"""

    elevation: np.ndarray  # (rows, cols) 標高[m]、欠測は NaN
    origin_px: float  # 左上のグローバルピクセルX
    origin_py: float  # 左上のグローバルピクセルY
    zoom: int
    cell_size_m: float

    @property
    def shape(self) -> tuple[int, int]:
        return self.elevation.shape

    def lonlat_to_rc(self, lon: float, lat: float) -> tuple[float, float]:
        """経度緯度 → グリッド上の (row, col) 実数座標。"""
        px, py = geo.deg2pixel(lat, lon, self.zoom)
        return py - self.origin_py, px - self.origin_px

    def rc_to_lonlat(self, row: float, col: float) -> tuple[float, float]:
        """グリッド上の (row, col) → (lon, lat)。セル中心で返す。"""
        lat, lon = geo.pixel2deg(
            self.origin_px + col + 0.5, self.origin_py + row + 0.5, self.zoom
        )
        return lon, lat

    def sample(self, raster: np.ndarray, lon: float, lat: float) -> float:
        """任意の座標でラスタ値を最近傍サンプリングする。範囲外は 0。"""
        row, col = self.lonlat_to_rc(lon, lat)
        r, c = int(round(row)), int(round(col))
        rows, cols = raster.shape
        if 0 <= r < rows and 0 <= c < cols:
            value = raster[r, c]
            return 0.0 if math.isnan(value) else float(value)
        return 0.0


def _fetch_dem_tile(x: int, y: int, zoom: int) -> np.ndarray | None:
    """DEMタイル1枚を取得する。ローカルキャッシュを優先する。"""
    tile_dir = CACHE_DIR / "dem"
    tile_dir.mkdir(parents=True, exist_ok=True)
    cached = tile_dir / f"{zoom}_{x}_{y}.txt"

    if cached.exists():
        text = cached.read_text()
        return _parse_dem_text(text)

    for dem_type in GSI_DEM_TYPES:
        url = GSI_DEM_URL.format(dem=dem_type, z=zoom, x=x, y=y)
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                text = response.read().decode("utf-8")
        except urllib.error.HTTPError as err:
            if err.code == 404:
                continue  # その種別には無いので次の精度へ落とす
            raise
        cached.write_text(text)
        time.sleep(0.1)  # 配信元に負荷をかけない
        return _parse_dem_text(text)

    return None  # 海域など、どの種別にもデータが無いタイル


def _parse_dem_text(text: str) -> np.ndarray:
    """GSIのテキスト形式(256行×256列、欠測は 'e')を配列に変換する。"""
    rows = [line for line in text.strip().splitlines() if line]
    grid = np.full((geo.TILE_SIZE, geo.TILE_SIZE), np.nan, dtype=np.float32)
    for r, line in enumerate(rows[: geo.TILE_SIZE]):
        for c, token in enumerate(line.split(",")[: geo.TILE_SIZE]):
            if token and token != "e":
                grid[r, c] = float(token)
    return grid


def load_elevation_grid(bbox: BBox, zoom: int = GSI_DEM_ZOOM) -> ElevationGrid:
    """対象地域を覆う標高グリッドを組み立てる。"""
    left_px, top_py = geo.deg2pixel(bbox.max_lat, bbox.min_lon, zoom)
    right_px, bottom_py = geo.deg2pixel(bbox.min_lat, bbox.max_lon, zoom)

    x0, x1 = int(left_px // geo.TILE_SIZE), int(right_px // geo.TILE_SIZE)
    y0, y1 = int(top_py // geo.TILE_SIZE), int(bottom_py // geo.TILE_SIZE)

    mosaic = np.full(
        ((y1 - y0 + 1) * geo.TILE_SIZE, (x1 - x0 + 1) * geo.TILE_SIZE),
        np.nan,
        dtype=np.float32,
    )
    for ty in range(y0, y1 + 1):
        for tx in range(x0, x1 + 1):
            tile = _fetch_dem_tile(tx, ty, zoom)
            if tile is None:
                continue
            r = (ty - y0) * geo.TILE_SIZE
            c = (tx - x0) * geo.TILE_SIZE
            mosaic[r : r + geo.TILE_SIZE, c : c + geo.TILE_SIZE] = tile

    # モザイクから対象地域ぶんだけ切り出す
    off_r = int(round(top_py)) - y0 * geo.TILE_SIZE
    off_c = int(round(left_px)) - x0 * geo.TILE_SIZE
    height = int(round(bottom_py - top_py))
    width = int(round(right_px - left_px))
    cropped = mosaic[off_r : off_r + height, off_c : off_c + width].copy()

    center_lat = (bbox.min_lat + bbox.max_lat) / 2
    return ElevationGrid(
        elevation=cropped,
        origin_px=float(int(round(left_px))),
        origin_py=float(int(round(top_py))),
        zoom=zoom,
        cell_size_m=geo.meters_per_pixel(center_lat, zoom),
    )


def fill_depressions(elevation: np.ndarray, epsilon: float = 0.0) -> np.ndarray:
    """priority-flood 法で窪地を埋めた標高を返す。

    埋めた後との差が、そのセルが「どれだけ周囲より低いか」＝溜まりうる水深になる。
    epsilon に微小値を与えると、埋めて平坦になった面にごくわずかな傾きが付く。
    D8 の流向計算では平坦面で流れが止まってしまうため、そちらでは epsilon を使う。
    """
    rows, cols = elevation.shape
    filled = np.full_like(elevation, np.inf, dtype=np.float64)
    source = np.nan_to_num(elevation, nan=np.nanmax(elevation)).astype(np.float64)

    heap: list[tuple[float, int, int]] = []
    visited = np.zeros((rows, cols), dtype=bool)

    for r in range(rows):
        for c in (0, cols - 1):
            heapq.heappush(heap, (source[r, c], r, c))
            visited[r, c] = True
            filled[r, c] = source[r, c]
    for c in range(cols):
        for r in (0, rows - 1):
            if not visited[r, c]:
                heapq.heappush(heap, (source[r, c], r, c))
                visited[r, c] = True
                filled[r, c] = source[r, c]

    neighbours = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1))
    while heap:
        level, r, c = heapq.heappop(heap)
        for dr, dc in neighbours:
            nr, nc = r + dr, c + dc
            if not (0 <= nr < rows and 0 <= nc < cols) or visited[nr, nc]:
                continue
            visited[nr, nc] = True
            filled[nr, nc] = max(source[nr, nc], level + epsilon)
            heapq.heappush(heap, (filled[nr, nc], nr, nc))

    return filled


def flow_accumulation(filled: np.ndarray, cell_size_m: float) -> np.ndarray:
    """D8 の最急降下方向をたどって流域面積(m^2)を積み上げる。"""
    rows, cols = filled.shape
    accumulation = np.full((rows, cols), cell_size_m**2, dtype=np.float64)

    # 標高の高い順に処理すれば、下流側は必ず後から更新される
    order = np.argsort(filled, axis=None)[::-1]
    neighbours = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1))

    for index in order:
        r, c = divmod(int(index), cols)
        here = filled[r, c]
        best_drop = 0.0
        best: tuple[int, int] | None = None
        for dr, dc in neighbours:
            nr, nc = r + dr, c + dc
            if not (0 <= nr < rows and 0 <= nc < cols):
                continue
            distance = math.hypot(dr, dc)
            drop = (here - filled[nr, nc]) / distance
            if drop > best_drop:
                best_drop = drop
                best = (nr, nc)
        if best is not None:
            accumulation[best] += accumulation[r, c]

    return accumulation


def slope_degrees(elevation: np.ndarray, cell_size_m: float) -> np.ndarray:
    """標高の勾配から傾斜角(度)を出す。"""
    filled = np.nan_to_num(elevation, nan=float(np.nanmean(elevation)))
    dy, dx = np.gradient(filled, cell_size_m)
    return np.degrees(np.arctan(np.hypot(dx, dy)))


def relative_depth(elevation: np.ndarray, radius_cells: int = 8) -> np.ndarray:
    """近傍平均標高との差。正なら周囲より低い。"""
    filled = np.nan_to_num(elevation, nan=float(np.nanmean(elevation)))
    kernel = 2 * radius_cells + 1
    padded = np.pad(filled, radius_cells, mode="edge")

    # 積分画像で移動平均を高速に求める
    integral = padded.cumsum(axis=0).cumsum(axis=1)
    integral = np.pad(integral, ((1, 0), (1, 0)), mode="constant")
    rows, cols = filled.shape
    window = (
        integral[kernel:, kernel:]
        - integral[:-kernel, kernel:]
        - integral[kernel:, :-kernel]
        + integral[:-kernel, :-kernel]
    )
    mean = window[:rows, :cols] / (kernel * kernel)
    return mean - filled
