#!/usr/bin/env python3
"""Render timing per layout: python scripts/benchmark.py [cycles] [WxH]

Warm numbers match a bot that keeps the renderer loaded (call ``miq.warmup()``
once at start-up); the cold number is one CLI process per image.
"""

from __future__ import annotations

import io
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import miq  # noqa: E402

AVATAR = ROOT / "demo-avatar.png"

TEXTS = [
    "小さな発見が、明日を変える。",
    "じゃあ8時間ホモになるか 👩🏽‍💻 Discord 8:30",
    "「大切な問い」を考えよう。次の発見につながる。",
    "مرحبا Discord 123 👩🏽‍💻",
    "全文を残して小さく表示する。長い引用文でも省略せずに縮小する。" * 12,
]


def main() -> int:
    cycles = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    size = sys.argv[2] if len(sys.argv) > 2 else None
    miq.warmup(size)
    medians = []
    for layout in miq.LAYOUTS:
        per_text = []
        for text in TEXTS:
            samples = []
            for _ in range(cycles):
                start = time.perf_counter()
                miq.render(
                    AVATAR,
                    text,
                    io.BytesIO(),
                    "投稿者",
                    "poster",
                    layout=layout,
                    size=size,
                )
                samples.append((time.perf_counter() - start) * 1000)
            per_text.append(statistics.median(samples))
        medians.extend(per_text)
        print(
            f"{layout:10} median={statistics.median(per_text):6.1f}ms "
            f"long={per_text[-1]:6.1f}ms"
        )
    print(f"{'all':10} median={statistics.median(medians):6.1f}ms")
    with tempfile.TemporaryDirectory() as directory:
        start = time.perf_counter()
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "miq.py"),
                "--avatar",
                str(AVATAR),
                "--text",
                TEXTS[0],
                "--layout",
                "noir",
                "-o",
                str(Path(directory) / "cold.png"),
            ],
            check=True,
            capture_output=True,
        )
        print(f"{'cold CLI':10} {(time.perf_counter() - start) * 1000:6.1f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
