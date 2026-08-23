"""回避ルートが実際にどれだけ役に立つのかを、対象地域全体で測る。

    python scripts/measure_impact.py [--trips 500]

1件のデモではなく、対象地域内の多数の経路で試して分布を出す。
「何割の移動で、どれだけの遠回りと引き換えに、どれだけ危険度が下がるのか」
が言えないと、社会的な効果を主張する根拠にならない。

出発地と目的地は歩行ネットワークのノードから無作為に選び、
歩いて移動する現実的な距離(300m〜2km)のものだけを対象にする。
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import geo, network, routing  # noqa: E402
from app.config import RAIN_PROFILES, WALK_GRAPH  # noqa: E402

MIN_TRIP_M = 300.0
MAX_TRIP_M = 2000.0
# これ未満の差は誤差の範囲とみなす。フロントの案内表示と同じ基準。
MEANINGFUL_REDUCTION = 3
CLEAR_REDUCTION = 10


def main() -> None:
    parser = argparse.ArgumentParser(description="回避ルートの効果を測る")
    parser.add_argument("--trips", type=int, default=500, help="試行する経路の数")
    parser.add_argument("--rain", default="medium", choices=list(RAIN_PROFILES))
    parser.add_argument("--seed", type=int, default=20260823)
    args = parser.parse_args()

    graph = network.load_walk_graph(WALK_GRAPH)
    multiplier = RAIN_PROFILES[args.rain]["multiplier"]
    node_ids = list(graph.nodes)
    rng = random.Random(args.seed)

    reductions: list[int] = []
    extra_minutes: list[int] = []
    extra_meters: list[float] = []
    flood_before: list[int] = []
    flood_after: list[int] = []
    attempts = 0

    while len(reductions) < args.trips and attempts < args.trips * 12:
        attempts += 1
        a, b = rng.choice(node_ids), rng.choice(node_ids)
        lon1, lat1 = graph.nodes[a]
        lon2, lat2 = graph.nodes[b]
        straight = geo.haversine_m(lat1, lon1, lat2, lon2)
        if not (MIN_TRIP_M <= straight <= MAX_TRIP_M):
            continue
        try:
            found = routing.find_routes(graph, (lon1, lat1), (lon2, lat2), multiplier)
        except ValueError:
            continue

        shortest, avoid = found["shortest"], found["avoid"]
        reductions.append(shortest.risk_score - avoid.risk_score)
        extra_minutes.append(avoid.duration_min - shortest.duration_min)
        extra_meters.append(avoid.distance_m - shortest.distance_m)
        flood_before.append(shortest.flood_overlap_pct)
        flood_after.append(avoid.flood_overlap_pct)

    total = len(reductions)
    if total == 0:
        raise SystemExit("条件に合う経路が見つかりませんでした")

    helped = [r for r in reductions if r >= MEANINGFUL_REDUCTION]
    clearly = [r for r in reductions if r >= CLEAR_REDUCTION]
    helped_minutes = [
        m for m, r in zip(extra_minutes, reductions) if r >= MEANINGFUL_REDUCTION
    ]

    label = RAIN_PROFILES[args.rain]["label"]
    print(f"対象 {total} 経路（{label}・直線距離 300m〜2km）\n")

    print("回避ルートの効果")
    print(
        f"  危険度が{MEANINGFUL_REDUCTION}ポイント以上下がる: "
        f"{len(helped) / total * 100:.1f}%（{len(helped)}/{total}）"
    )
    print(
        f"  {CLEAR_REDUCTION}ポイント以上下がる:          "
        f"{len(clearly) / total * 100:.1f}%（{len(clearly)}/{total}）"
    )
    print(f"  下がり幅の中央値（効果があった経路）: {statistics.median(helped) if helped else 0:.0f}ポイント")
    print(f"  最大の下がり幅: {max(reductions)}ポイント\n")

    print("そのために増える手間")
    print(f"  遠回りの中央値: {statistics.median(extra_meters):.0f}m")
    print(
        f"  所要時間の増加中央値: "
        f"{statistics.median(helped_minutes) if helped_minutes else 0:.0f}分"
    )
    print(f"  遠回り0分で済む割合: {sum(1 for m in extra_minutes if m <= 0) / total * 100:.1f}%\n")

    print("東京都の浸水予想との重なり")
    covered = [i for i, f in enumerate(flood_before) if f > 0]
    if covered:
        before = statistics.mean(flood_before[i] for i in covered)
        after = statistics.mean(flood_after[i] for i in covered)
        print(f"  浸水想定区間を通る経路: {len(covered) / total * 100:.1f}%")
        print(f"  その経路での重なり: 最短 {before:.1f}% → 回避 {after:.1f}%")


if __name__ == "__main__":
    main()
