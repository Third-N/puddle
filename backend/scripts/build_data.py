"""地形データと歩行ネットワークから、APIが読む生成物を作る。

    python scripts/build_data.py            # キャッシュがあればそれを使う
    python scripts/build_data.py --refresh  # 元データを取り直す

出力先は backend/data/generated/ :
    risk_raster.npz  ... 危険度ラスタと地形指標
    walk_graph.json  ... 危険度を付与した歩行グラフ
    hazards.geojson  ... 危険地点(代表点)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import hazards, network, routing, terrain, tokyo_flood  # noqa: E402
from app.config import (  # noqa: E402
    DEMO_AREA,
    ENGINE_JSON,
    GENERATED_DIR,
    HAZARD_GEOJSON,
    PLACES_JSON,
    RISK_RASTER,
    WALK_GRAPH,
)


def engine_settings() -> dict:
    """サーバーとブラウザが共通で参照する設定。

    静的サイト版はブラウザ側で経路探索を行う。係数をそちらに書き写すと
    片方だけ直したときに結果が食い違うので、1か所から配る。
    """
    from app import config

    return {
        "demoArea": {
            "minLat": config.DEMO_AREA.min_lat,
            "minLng": config.DEMO_AREA.min_lon,
            "maxLat": config.DEMO_AREA.max_lat,
            "maxLng": config.DEMO_AREA.max_lon,
        },
        "rainProfiles": {
            key: {"label": p["label"], "multiplier": p["multiplier"], "mmPerHour": p["mm_per_hour"]}
            for key, p in config.RAIN_PROFILES.items()
        },
        "walkMetersPerMin": config.WALK_METERS_PER_MIN,
        "avoidAlpha": config.AVOID_ALPHA,
        "puddleReferenceRisk": config.PUDDLE_REFERENCE_RISK,
        "exposureReferenceM": config.EXPOSURE_REFERENCE_M,
        "maxSnapDistanceM": config.MAX_SNAP_DISTANCE_M,
        "hazardCorridorM": config.HAZARD_CORRIDOR_M,
        "hazardMaxResults": config.HAZARD_MAX_RESULTS,
        "levelHighThreshold": config.LEVEL_HIGH_THRESHOLD,
        "levelMediumThreshold": config.LEVEL_MEDIUM_THRESHOLD,
        "placeSearchRadiusM": config.PLACE_SEARCH_RADIUS_M,
        "routeStyles": {
            "shortest": {"label": "最短ルート", "color": "#6b7280"},
            "avoid": {"label": "水たまり回避ルート", "color": "#16a34a"},
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="水たまりゼロ東京 データ生成")
    parser.add_argument(
        "--refresh", action="store_true", help="標高タイル・OSMを取り直す"
    )
    args = parser.parse_args()

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    started = time.time()

    print("1/7 標高データ(国土地理院 DEM5A)を読み込み中...")
    grid = terrain.load_elevation_grid(DEMO_AREA)
    print(
        f"    グリッド {grid.shape[0]}x{grid.shape[1]} / "
        f"1セル {grid.cell_size_m:.2f}m"
    )

    print("2/7 歩行空間ネットワーク(OpenStreetMap)を読み込み中...")
    osm = network.fetch_osm_ways(DEMO_AREA, refresh=args.refresh)
    graph = network.build_walk_graph(osm, DEMO_AREA)
    print(f"    ノード {len(graph.nodes):,} / 辺 {len(graph.edges):,}")

    print("3/7 地点名(駅・施設・ビル)を読み込み中...")
    places = network.build_places(network.fetch_osm_places(DEMO_AREA, refresh=args.refresh))
    PLACES_JSON.write_text(json.dumps(places, ensure_ascii=False))
    station_count = sum(1 for p in places if p["kind"] == "station")
    print(f"    地点 {len(places):,} 件(うち駅 {station_count} 件)")

    print("4/7 東京都の浸水予想を読み込み中...")
    flood_points = tokyo_flood.load_points(refresh=args.refresh)
    tokyo_depth = tokyo_flood.rasterize(grid, flood_points)
    import numpy as _np

    covered = (~_np.isnan(tokyo_depth)).sum() / tokyo_depth.size
    print(f"    メッシュ {len(flood_points):,} 点 / 対象地域の {covered * 100:.0f}% を被覆")

    print("5/7 地形から危険度を計算し、都の予想を重ねています...")
    model = hazards.build_risk_model(grid, graph, tokyo_depth=tokyo_depth)
    model.save(RISK_RASTER)
    print(
        f"    地形のみ 平均 {model.risk_terrain.mean():.3f} → "
        f"都の予想を重ねて 平均 {model.risk.mean():.3f}"
    )

    print("6/7 危険地点を抽出中...")
    points = hazards.extract_hazard_points(model, graph)
    HAZARD_GEOJSON.write_text(
        json.dumps(hazards.to_geojson(points), ensure_ascii=False, indent=1)
    )
    print(f"    危険地点 {len(points):,} 件")

    print("7/7 歩行グラフに危険度を付与中...")
    routing.annotate_edge_risk(graph, model)
    WALK_GRAPH.write_text(json.dumps(graph.to_dict()))
    risky = sum(1 for e in graph.edges if e["risk"] >= 0.5)
    print(f"    危険度0.5以上の辺 {risky:,} / {len(graph.edges):,}")

    print("   設定を書き出し中...")
    ENGINE_JSON.write_text(json.dumps(engine_settings(), ensure_ascii=False, indent=1))

    print(f"完了 ({time.time() - started:.1f}秒) -> {GENERATED_DIR}")


if __name__ == "__main__":
    main()
