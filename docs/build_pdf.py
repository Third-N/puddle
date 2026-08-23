"""発表スライドを PDF に書き出す。

    python docs/build_pdf.py

docs/slides.html を Chromium で開き、印刷用CSS（@media print）を適用して
1スライド1ページの PDF にする。ページサイズは 297mm × 167mm（16:9）。

必要なもの:
    uv pip install --python backend/.venv/bin/python playwright
    backend/.venv/bin/playwright install chromium
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DOCS = Path(__file__).resolve().parent
SOURCE = DOCS / "slides.html"
OUTPUT = DOCS / "水たまりゼロ東京_発表スライド.pdf"


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"{SOURCE.name} がありません。先に build_slides.py を実行してください")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(SOURCE.as_uri())
        # Webフォント（Google Fonts）の読み込みを待つ。
        # 待たずに書き出すと、明朝がフォールバックのまま焼き付いてしまう。
        page.wait_for_load_state("networkidle")
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(1500)

        page.pdf(
            path=str(OUTPUT),
            width="297mm",
            height="167mm",
            print_background=True,
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            prefer_css_page_size=True,
        )
        browser.close()

    size_mb = OUTPUT.stat().st_size / 1024 / 1024
    print(f"{OUTPUT.name} ({size_mb:.2f}MB)")


if __name__ == "__main__":
    main()
