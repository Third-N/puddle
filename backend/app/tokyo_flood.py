"""東京都の浸水予想区域図を読み込み、危険度の根拠として使えるようにする。

東京都下水道局が公開している「浸水予想区域図(改定) 浸水深・地盤高」は、
河川と下水道の水理シミュレーションから出した想定浸水深のメッシュデータ。
私たちが地形だけから出した推定に対して、行政による裏づけを重ねる役割を持つ。

対象地域を覆っているのは流域の一部だけなので、データが無い場所では
地形由来の推定だけで動く。あくまで上乗せの根拠として扱う。
"""

from __future__ import annotations

import csv
import urllib.request
from pathlib import Path

import numpy as np

from .config import (
    CACHE_DIR,
    DEMO_AREA,
    TOKYO_DEPTH_FILL_RADIUS_M,
    TOKYO_FLOOD_CSV,
    TOKYO_FLOOD_URL,
)

_USER_AGENT = "mizutamari-zero-tokyo/0.1 (hackathon demo; contact: team-third-n)"


def load_points(refresh: bool = False) -> list[tuple[float, float, float, float]]:
    """(浸水深, 地盤高, 緯度, 経度) の一覧を、対象地域ぶんだけ返す。

    切り出し済みCSVがあればそれを使う。26MBの元データを毎回読まないため。
    """
    if TOKYO_FLOOD_CSV.exists() and not refresh:
        rows = []
        with TOKYO_FLOOD_CSV.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                rows.append(
                    (float(row[0]), float(row[1]), float(row[2]), float(row[3]))
                )
        return rows

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / "tokyo_flood_kandagawa_south.csv"
    if not cached.exists() or refresh:
        request = urllib.request.Request(
            TOKYO_FLOOD_URL, headers={"User-Agent": _USER_AGENT}
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            cached.write_bytes(response.read())

    rows = []
    # 都のCSVは Shift_JIS。列は 浸水深, 地盤高, 緯度, 経度。
    with cached.open(newline="", encoding="cp932", errors="replace") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) < 4:
                continue
            try:
                depth, ground = float(row[0]), float(row[1])
                lat, lon = float(row[2]), float(row[3])
            except ValueError:
                continue
            if DEMO_AREA.contains(lat, lon):
                rows.append((round(depth, 3), round(ground, 2), lat, lon))

    TOKYO_FLOOD_CSV.parent.mkdir(parents=True, exist_ok=True)
    with TOKYO_FLOOD_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["depth_m", "ground_m", "lat", "lon"])
        writer.writerows(rows)
    return rows


def rasterize(grid, points: list[tuple[float, float, float, float]]) -> np.ndarray:
    """想定浸水深を、標高グリッドと同じ形のラスタに落とす。

    都のメッシュは約12.5m間隔で、こちらの1セルは約3.9m。そのままでは
    点が飛び飛びに乗るだけなので、1点の値をその周囲まで広げて面にする。
    データが無いところは NaN のままにし、地形由来の推定だけで動かす。
    """
    rows, cols = grid.shape
    depth = np.full((rows, cols), np.nan, dtype=np.float32)

    for value, _, lat, lon in points:
        row, col = grid.lonlat_to_rc(lon, lat)
        r, c = int(round(row)), int(round(col))
        if 0 <= r < rows and 0 <= c < cols:
            current = depth[r, c]
            depth[r, c] = value if np.isnan(current) else max(current, value)

    radius = max(1, int(round(TOKYO_DEPTH_FILL_RADIUS_M / grid.cell_size_m)))
    filled = depth.copy()
    for dr in range(-radius, radius + 1):
        for dc in range(-radius, radius + 1):
            if dr * dr + dc * dc > radius * radius:
                continue
            shifted = np.roll(np.roll(depth, dr, axis=0), dc, axis=1)
            gap = np.isnan(filled) & ~np.isnan(shifted)
            filled[gap] = shifted[gap]
    return filled
