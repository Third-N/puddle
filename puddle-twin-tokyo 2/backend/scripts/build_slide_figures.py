"""発表スライド用の図を、実際のデータから描き出す。

    python scripts/build_slide_figures.py

出力先は docs/figures/ :
    elevation.jpg ... 対象地域の陰影起伏(国土地理院 DEM5A)
    risk.jpg      ... 危険度ラスタ
    routes.png    ... 歩行ネットワーク＋最短/回避ルート＋危険地点

Pillow が要る: uv pip install --python .venv/bin/python pillow
"""
import json, math, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import RISK_RASTER, WALK_GRAPH, HAZARD_GEOJSON, RAIN_PROFILES
from app import hazards, network, routing

OUT = Path(__file__).resolve().parent.parent.parent / "docs" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

model = hazards.RiskModel.load(RISK_RASTER)
grid = model.grid
graph = network.load_walk_graph(WALK_GRAPH)
SCALE = 2  # 表示用に2倍に拡大する

def ramp(values, stops):
    """0..1 の配列を、色の停留点で着色する。"""
    positions = np.array([s[0] for s in stops])
    colors = np.array([s[1] for s in stops], dtype=float)
    out = np.zeros(values.shape + (3,), dtype=float)
    for channel in range(3):
        out[..., channel] = np.interp(values, positions, colors[:, channel])
    return out.astype(np.uint8)

# --- 1. 標高（陰影起伏＋標高の色づけ）
elev = np.nan_to_num(grid.elevation, nan=float(np.nanmedian(grid.elevation)))
lo, hi = np.percentile(elev, 1), np.percentile(elev, 99)
norm = np.clip((elev - lo) / (hi - lo), 0, 1)

# 陰影起伏: 北西45度から光を当てたときの明るさ
dy, dx = np.gradient(elev, grid.cell_size_m)
slope = np.arctan(np.hypot(dx, dy) * 6.0)  # 都心は平坦なので誇張する
aspect = np.arctan2(-dx, dy)
azimuth, altitude = math.radians(315.0), math.radians(45.0)
shade = (
    math.sin(altitude) * np.cos(slope)
    + math.cos(altitude) * np.sin(slope) * np.cos(azimuth - aspect)
)
shade = np.clip((shade - shade.min()) / (shade.max() - shade.min()), 0, 1)

tint = ramp(norm, [
    (0.00, (16, 44, 60)),
    (0.30, (26, 84, 108)),
    (0.60, (58, 140, 168)),
    (0.85, (146, 196, 202)),
    (1.00, (236, 242, 243)),
]).astype(float)
img = np.clip(tint * (0.42 + 0.95 * shade[..., None]), 0, 255).astype(np.uint8)
Image.fromarray(img).resize((img.shape[1]*SCALE, img.shape[0]*SCALE), Image.LANCZOS).save(
    OUT/"elevation.jpg", quality=86, optimize=True)

# --- 2. 危険度ラスタ
risk = np.clip(model.risk, 0, 1)
img = ramp(risk, [
    (0.00, (13, 26, 34)),
    (0.18, (20, 52, 68)),
    (0.40, (58, 140, 190)),
    (0.62, (232, 190, 90)),
    (1.00, (224, 90, 69)),
])
Image.fromarray(img).resize((img.shape[1]*SCALE, img.shape[0]*SCALE), Image.LANCZOS).save(
    OUT/"risk.jpg", quality=86, optimize=True)

# --- 3. ルート比較図（歩行ネットワーク＋2ルート＋危険地点）
W, H = grid.shape[1]*SCALE, grid.shape[0]*SCALE
canvas = Image.new("RGB", (W, H), (13, 26, 34))
draw = ImageDraw.Draw(canvas, "RGBA")

def to_xy(lon, lat):
    row, col = grid.lonlat_to_rc(lon, lat)
    return (col*SCALE, row*SCALE)

for edge in graph.edges:
    a, b = graph.nodes[edge["a"]], graph.nodes[edge["b"]]
    draw.line([to_xy(*a), to_xy(*b)], fill=(120, 160, 180, 60), width=1)

points = hazards.from_geojson(json.loads(HAZARD_GEOJSON.read_text()))
for p in points:
    x, y = to_xy(p["lon"], p["lat"])
    r = 3 + 7 * p["baseWeight"]
    draw.ellipse([x-r, y-r, x+r, y+r], fill=(224, 90, 69, 90))

found = routing.find_routes(graph, (139.7595, 35.6740), (139.7706, 35.6777), RAIN_PROFILES["medium"]["multiplier"])
for key, color, width in (("shortest", (176, 190, 197, 255), 5), ("avoid", (53, 160, 106, 255), 5)):
    draw.line([to_xy(*c) for c in found[key].path], fill=color, width=width, joint="curve")

for lon, lat, color in ((139.7595, 35.6740, (58, 169, 217)), (139.7706, 35.6777, (224, 90, 69))):
    x, y = to_xy(lon, lat)
    draw.ellipse([x-9, y-9, x+9, y+9], fill=color + (255,), outline=(238, 243, 244, 255), width=3)

canvas.save(OUT/"routes.png")

for f in sorted(OUT.iterdir()):
    print(f.name, f"{f.stat().st_size/1024:.0f}KB")
print("shortest", round(found["shortest"].distance_m), found["shortest"].risk_score,
      "| avoid", round(found["avoid"].distance_m), found["avoid"].risk_score)
