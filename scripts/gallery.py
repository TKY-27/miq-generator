#!/usr/bin/env python3
"""Render every layout and a contact sheet.

python scripts/gallery.py [output_dir] [--size 960x540] [--text "..."]
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import miq  # noqa: E402
from miq_fonts import FAMILIES  # noqa: E402

TEXT = "答えを急がず、問いを深めよう。Stay curious. 👩🏽‍💻✨ 小さな発見が、明日の景色を変えていく。"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output", nargs="?", type=Path, default=ROOT / "output" / "gallery"
    )
    parser.add_argument("--size", default="960x540")
    parser.add_argument("--text", default=TEXT)
    parser.add_argument("--name", default="高橋 直人")
    parser.add_argument("--handle", default="naoto_notes")
    parser.add_argument("--avatar", type=Path, default=ROOT / "demo-avatar.png")
    parser.add_argument("--columns", type=int, default=4)
    parser.add_argument("--sheet", type=Path, help="コンタクトシートの出力先")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    date = datetime(2026, 4, 1, 9, 41)
    tiles = []
    for name, spec in miq.REGISTRY.items():
        font_family = spec.fonts[0]
        start = time.perf_counter()
        canvas, _, _ = miq.compose(
            args.avatar,
            args.text,
            args.name,
            args.handle,
            # --size is for landscape; portrait/square use their default sizes.
            size=args.size if spec.orientation == "landscape" else None,
            layout=name,
            font_family=font_family,
            date=date,
        )
        elapsed = (time.perf_counter() - start) * 1000
        path = args.output / f"{name}.png"
        canvas.convert("RGB").save(path)
        tiles.append((name, spec.label, FAMILIES[font_family].label, canvas))
        print(f"{name:11} {elapsed:7.1f}ms  {path}")
    width, height = tiles[0][3].size
    scale = 480 / width
    tw, th = round(width * scale), round(height * scale)
    label = 34
    rows = (len(tiles) + args.columns - 1) // args.columns
    sheet = Image.new("RGB", (tw * args.columns, (th + label) * rows), (232, 230, 225))
    font = ImageFont.truetype(str(FAMILIES["gothic"].path), 18)
    draw = ImageDraw.Draw(sheet)
    for i, (name, title, face, canvas) in enumerate(tiles):
        x, y = (i % args.columns) * tw, (i // args.columns) * (th + label)
        draw.text(
            (x + 12, y + 8), f"{name} / {title} · {face}", font=font, fill=(40, 40, 40)
        )
        thumb = ImageOps.contain(
            canvas.convert("RGB"), (tw, th), Image.Resampling.LANCZOS
        )
        sheet.paste(thumb, (x + (tw - thumb.width) // 2, y + label))
    sheet_path = args.sheet or args.output / "sheet.png"
    sheet.save(sheet_path)
    print(f"sheet: {sheet_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
