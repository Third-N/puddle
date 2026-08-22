"""発表スライドの HTML を組み立てる。

    python docs/build_slides.py

docs/slides.template.html の {{...}} を docs/figures/ の画像で置き換え、
docs/slides.html を書き出す。画像は data URI で埋め込むので、
出来上がった HTML 1枚をどこに置いても、そのまま発表に使える。

図を作り直すときは backend/scripts/build_slide_figures.py を先に実行する。
"""

from __future__ import annotations

import base64
from pathlib import Path

DOCS = Path(__file__).resolve().parent
FIGURES = DOCS / "figures"

SOURCES = {
    "{{ELEVATION}}": ("elevation.jpg", "image/jpeg"),
    "{{RISK}}": ("risk.jpg", "image/jpeg"),
    "{{ROUTES}}": ("routes.png", "image/png"),
}


def data_uri(name: str, mime: str) -> str:
    encoded = base64.b64encode((FIGURES / name).read_bytes()).decode()
    return f"data:{mime};base64,{encoded}"


def main() -> None:
    html = (DOCS / "slides.template.html").read_text()
    for placeholder, (name, mime) in SOURCES.items():
        html = html.replace(placeholder, data_uri(name, mime))
    if "{{" in html:
        raise SystemExit("置き換えられていないプレースホルダが残っています")

    out = DOCS / "slides.html"
    out.write_text(html)
    print(f"{out} ({out.stat().st_size / 1024 / 1024:.2f}MB)")


if __name__ == "__main__":
    main()
