#!/usr/bin/env python3
"""Warm-render timing for representative quotes: python scripts/benchmark.py [cycles]"""

from __future__ import annotations

import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import miq  # noqa: E402

AVATAR = ROOT / "demo-avatar.png"

CASES = [
    ("小さな発見が、明日を変える。", "classic", "640x360"),
    ("じゃあ8時間ホモになるか 👩🏽‍💻 Discord 8:30", "classic", "640x360"),
    ("「大切な問い」を考えよう。次の発見につながる。", "classic", "640x360"),
    ("مرحبا Discord 123 👩🏽‍💻", "classic", "640x360"),
    ("全文を残して小さく表示する。長い引用文でも省略せずに縮小する。" * 12, "classic", "640x360"),
    ("毎日が学びの機会。", "mirrored", "854x480"),
    ("毎日が学びの機会。", "magazine", "854x480"),
    ("問いを立て続けること。", "literary", "1920x1080"),
]


def main() -> int:
    cycles = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)
        for index, (text, layout, size) in enumerate(CASES):
            # Warm imports, font handles and mask caches before timing.
            miq.render(
                AVATAR,
                text,
                output / f"{index}.png",
                "投稿者",
                "poster",
                layout=layout,
                size=size,
            )
        samples = []
        for _ in range(cycles):
            for index, (text, layout, size) in enumerate(CASES):
                start = time.perf_counter()
                miq.render(
                    AVATAR,
                    text,
                    output / f"{index}.png",
                    "投稿者",
                    "poster",
                    layout=layout,
                    size=size,
                )
                samples.append(((time.perf_counter() - start) * 1000, layout))
    for layout in ("classic", "mirrored", "magazine", "literary"):
        group = [value for value, name in samples if name == layout]
        if group:
            median = statistics.median(group)
            print(f"{layout:9} n={len(group):3d} median={median:7.1f}ms")
    values = [value for value, _ in samples]
    print(
        f"{'all':9} n={len(values):3d} median={statistics.median(values):7.1f}ms"
        f" mean={statistics.mean(values):7.1f}ms"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
