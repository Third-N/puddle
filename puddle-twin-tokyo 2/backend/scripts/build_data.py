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

from app import hazards, network, routing, terrain  # noqa: E402
from app.config import (  # noqa: E402
    DEMO_AREA,
    GENERATED_DIR,
    HAZARD_GEOJSON,
    PLACES_JSON,
    RISK_RASTER,
    WALK_GRAPH,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="水たまりゼロ東京 データ生成")
    parser.add_argument(
        "--refresh", action="store_true", help="標高タイル・OSMを取り直す"
    )
    args = parser.parse_args()

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    started = time.time()

    print("1/6 標高データ(国土地理院 DEM5A)を読み込み中...")
    grid = terrain.load_elevation_grid(DEMO_AREA)
    print(
        f"    グリッド {grid.shape[0]}x{grid.shape[1]} / "
        f"1セル {grid.cell_size_m:.2f}m"
    )

    print("2/6 歩行空間ネットワーク(OpenStreetMap)を読み込み中...")
    osm = network.fetch_osm_ways(DEMO_AREA, refresh=args.refresh)
    graph = network.build_walk_graph(osm, DEMO_AREA)
    print(f"    ノード {len(graph.nodes):,} / 辺 {len(graph.edges):,}")

    print("3/6 地点名(駅・施設・ビル)を読み込み中...")
    places = network.build_places(network.fetch_osm_places(DEMO_AREA, refresh=args.refresh))
    PLACES_JSON.write_text(json.dumps(places, ensure_ascii=False))
    station_count = sum(1 for p in places if p["kind"] == "station")
    print(f"    地点 {len(places):,} 件(うち駅 {station_count} 件)")

    print("4/6 地形から危険度を計算中(窪地・流域・傾斜)...")
    model = hazards.build_risk_model(grid, graph)
    model.save(RISK_RASTER)
    print(f"    危険度 平均 {model.risk.mean():.3f} / 最大 {model.risk.max():.3f}")

    print("5/6 危険地点を抽出中...")
    points = hazards.extract_hazard_points(model, graph)
    HAZARD_GEOJSON.write_text(
        json.dumps(hazards.to_geojson(points), ensure_ascii=False, indent=1)
    )
    print(f"    危険地点 {len(points):,} 件")

    print("6/6 歩行グラフに危険度を付与中...")
    routing.annotate_edge_risk(graph, model)
    WALK_GRAPH.write_text(json.dumps(graph.to_dict()))
    risky = sum(1 for e in graph.edges if e["risk"] >= 0.5)
    print(f"    危険度0.5以上の辺 {risky:,} / {len(graph.edges):,}")

    print(f"完了 ({time.time() - started:.1f}秒) -> {GENERATED_DIR}")


if __name__ == "__main__":
    main()
