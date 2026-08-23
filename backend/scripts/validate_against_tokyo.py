"""危険度の推定を、東京都の浸水予想と突き合わせて検証する。

    python scripts/validate_against_tokyo.py

東京都下水道局が公開している「浸水予想区域図(改定) 浸水深・地盤高」は、
河川と下水道の水理シミュレーションから出した想定浸水深のメッシュデータ。
私たちが地形だけから出した危険度が、それと同じ場所を指すかを確かめる。

照合するのは model.risk_terrain (地形のみ)。実際にルート探索で使う
model.risk には都の予想を重ねてあるので、そちらで照合すると
答えを見てから答え合わせをすることになる。

対象地域ぶんだけ切り出したCSVを data/generated/ に残すので、
2回目以降は26MBの元データを取り直さずに再検証できる。

なお、都のデータが表すのは「街区が冠水する規模」で、私たちが狙うのは
「歩道にできる水たまり」。規模は違うが、水が集まる低い土地という
原因を共有しているため、場所の一致は推定の妥当性の裏づけになる。
"""

from __future__ import annotations

import csv
import sys
import urllib.request
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import hazards  # noqa: E402
from app.config import (  # noqa: E402
    CACHE_DIR,
    DEMO_AREA,
    RISK_RASTER,
    TOKYO_FLOOD_CSV,
    TOKYO_FLOOD_URL,
)

_USER_AGENT = "mizutamari-zero-tokyo/0.1 (hackathon demo; contact: team-third-n)"

DEPTH_BINS = [
    (0.0, 0.01, "浸水なし"),
    (0.01, 0.10, "0〜10cm"),
    (0.10, 0.30, "10〜30cm"),
    (0.30, 0.50, "30〜50cm"),
    (0.50, 1.00, "50cm〜1m"),
    (1.00, 99.0, "1m以上"),
]


def clip_to_demo_area() -> list[tuple[float, float, float, float]]:
    """都のメッシュから、対象地域ぶんだけを取り出す。"""
    if TOKYO_FLOOD_CSV.exists():
        rows = []
        with TOKYO_FLOOD_CSV.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                rows.append((float(row[0]), float(row[1]), float(row[2]), float(row[3])))
        return rows

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / "tokyo_flood_kandagawa_south.csv"
    if not cached.exists():
        print("東京都のオープンデータを取得中(26MB)...")
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
    print(f"対象地域ぶんを書き出しました -> {TOKYO_FLOOD_CSV.name}")
    return rows


def main() -> None:
    rows = clip_to_demo_area()
    model = hazards.RiskModel.load(RISK_RASTER)
    grid = model.grid

    depth = np.array([r[0] for r in rows])
    ground = np.array([r[1] for r in rows])
    # 検証には地形だけのモデルを使う。都の予想を重ねた risk で照合すると、
    # 答えを見てから答え合わせをすることになる。
    risk = np.array([grid.sample(model.risk_terrain, r[3], r[2]) for r in rows])
    dem = np.array([grid.sample(grid.elevation, r[3], r[2]) for r in rows])

    print(f"\n照合点数 {len(rows):,}（東京都下水道局 浸水予想区域図・神田川流域）\n")

    print("① 入力の妥当性 — 都の地盤高 と 国土地理院DEM5A")
    valid = dem != 0
    print(f"   相関 r = {np.corrcoef(ground[valid], dem[valid])[0, 1]:.3f}")
    print(f"   中央絶対差 {np.median(np.abs(dem[valid] - ground[valid])):.2f}m\n")

    print("② 推定の妥当性 — 地形のみの危険度 と 都の想定浸水深")
    print(f"   相関 r = {np.corrcoef(depth, risk)[0, 1]:.3f}\n")
    for low, high, label in DEPTH_BINS:
        mask = (depth >= low) & (depth < high)
        if not mask.any():
            continue
        print(
            f"   {label:>8}  n={mask.sum():>7,}   危険度 平均 {risk[mask].mean():.3f}"
            f"   中央値 {np.median(risk[mask]):.3f}"
        )

    top = risk >= np.percentile(risk, 90)
    flooded = depth >= 0.10
    print("\n③ 危険度が上位10%の地点は、都の予想でどうなっているか")
    print(
        f"   平均想定浸水深   上位10% {depth[top].mean():.2f}m  /  それ以外 "
        f"{depth[~top].mean():.2f}m  （{depth[top].mean() / max(depth[~top].mean(), 1e-9):.1f}倍）"
    )
    print(
        f"   10cm以上浸かる割合 上位10% {flooded[top].mean() * 100:.1f}%  /  それ以外 "
        f"{flooded[~top].mean() * 100:.1f}%  （{flooded[top].mean() / max(flooded[~top].mean(), 1e-9):.1f}倍）"
    )


if __name__ == "__main__":
    main()
