"""緯度経度・Webメルカトルタイル・距離まわりの小さなヘルパー。"""

from __future__ import annotations

import math

EARTH_RADIUS_M = 6378137.0
TILE_SIZE = 256


def deg2pixel(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    """緯度経度を、そのズームレベルのグローバルピクセル座標へ変換する。"""
    n = TILE_SIZE * (2**zoom)
    x = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(max(min(lat, 85.05112878), -85.05112878))
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def pixel2deg(px: float, py: float, zoom: int) -> tuple[float, float]:
    """グローバルピクセル座標を緯度経度へ戻す。"""
    n = TILE_SIZE * (2**zoom)
    lon = px / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1.0 - 2.0 * py / n)))
    return math.degrees(lat_rad), lon


def meters_per_pixel(lat: float, zoom: int) -> float:
    """そのズームでの 1px あたりの地上距離(m)。"""
    return 156543.03392 * math.cos(math.radians(lat)) / (2**zoom)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """2点間の大円距離(m)。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def path_length_m(coords: list[tuple[float, float]]) -> float:
    """[(lon, lat), ...] の折れ線の長さ(m)。"""
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
        total += haversine_m(lat1, lon1, lat2, lon2)
    return total


def interpolate_points(
    lon1: float, lat1: float, lon2: float, lat2: float, step_m: float
) -> list[tuple[float, float]]:
    """線分を step_m 間隔でサンプリングした (lon, lat) の列を返す。"""
    dist = haversine_m(lat1, lon1, lat2, lon2)
    n = max(1, int(dist // step_m))
    return [
        (lon1 + (lon2 - lon1) * i / n, lat1 + (lat2 - lat1) * i / n) for i in range(n + 1)
    ]


def distance_to_path_m(
    lon: float, lat: float, path: list[tuple[float, float]]
) -> float:
    """点から折れ線までの最短距離(m)。数km程度なら平面近似で十分。"""
    if not path:
        return math.inf

    origin_lon, origin_lat = path[0]
    meters_per_deg_lat = 111320.0
    meters_per_deg_lon = 111320.0 * math.cos(math.radians(origin_lat))

    def to_xy(p_lon: float, p_lat: float) -> tuple[float, float]:
        return (
            (p_lon - origin_lon) * meters_per_deg_lon,
            (p_lat - origin_lat) * meters_per_deg_lat,
        )

    px, py = to_xy(lon, lat)
    best = math.inf
    for (lon1, lat1), (lon2, lat2) in zip(path, path[1:]):
        ax, ay = to_xy(lon1, lat1)
        bx, by = to_xy(lon2, lat2)
        abx, aby = bx - ax, by - ay
        length_sq = abx * abx + aby * aby
        t = 0.0 if length_sq == 0 else ((px - ax) * abx + (py - ay) * aby) / length_sq
        t = max(0.0, min(1.0, t))
        dx, dy = px - (ax + abx * t), py - (ay + aby * t)
        best = min(best, math.hypot(dx, dy))
    return best
