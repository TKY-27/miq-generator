#!/usr/bin/env python3
"""Offline quote PNG renderer: ten equally likely layouts and the original CLI."""

from __future__ import annotations

import argparse
import io
import os
import random
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from miq_fonts import (
    FONT_DIR,
    bundled_fonts,
    find_emoji_font,
    find_font,
    find_italic_font,
    font_at,
)
from miq_images import encode_png, read_image
from miq_layouts import ALIASES, LAYOUTS, Ctx
from miq_text import (
    EmojiImages,
    MixedFont,
    fit,
    wrap_words,
)
from miq_words import units

SIZE = (960, 540)
BASE_SIZE = (1920, 1080)
ALIGN_CHOICES = ("center", "right")
TEXT_LEFT = {"right": 1010, "center": 845}
TEXT_RIGHT = 1780
CENTER_SHIFT = 0.05
LINE_HEIGHT = 1.43
# Every layout is equally likely.
LAYOUT_WEIGHTS = tuple((name, 1) for name in LAYOUTS)
__all__ = [
    "BASE_SIZE",
    "LAYOUTS",
    "SIZE",
    "choose_layout",
    "find_font",
    "fit_text",
    "render",
    "resolve_align",
    "resolve_size",
    "text_region",
    "warmup",
    "wrap_line",
]


def resolve_size(value=None):
    value = (
        value if value is not None and value != "" else os.getenv("MIQ_SIZE") or SIZE
    )
    if isinstance(value, (tuple, list)) and len(value) == 2:
        if any(isinstance(n, bool) or int(n) != n for n in value):
            raise ValueError("出力サイズは整数で指定してください。")
        width, height = map(int, value)
    else:
        matched = re.fullmatch(r"\s*(\d+)\s*[xX×,]\s*(\d+)\s*", str(value))
        if not matched:
            raise ValueError(f"出力サイズが不正です: {value}（例 640x360）")
        width, height = map(int, matched.groups())
    if width < 200 or height < 120:
        raise ValueError("出力サイズは200x120以上にしてください。")
    return width, height


def choose_layout(rng=None):
    names = [name for name, _ in LAYOUT_WEIGHTS]
    index = int((rng or random).random() * len(names))
    return names[min(index, len(names) - 1)]


def wrap_line(para, font, max_width):
    measured = font if isinstance(font, MixedFont) else MixedFont(font)
    # An over-wide word remains intact; fit_text reduces its size.
    return wrap_words(units(para), measured, max_width) or [para]


def fit_text(
    text, font_path, width, height, has_credit, make_font=font_at, align="right"
):
    box = text_region(width, height, has_credit, align)

    def maker(px):
        font = make_font(font_path, px)
        return font if isinstance(font, MixedFont) else MixedFont(font)

    result = fit(
        text,
        maker,
        box[2] - box[0],
        box[3] - box[1],
        max(9, round(76 * min(width / 1920, height / 1080))),
        classic=True,
    )
    widest = max(
        (result.font.getlength(row) * result.scale for row in result.lines), default=0
    )
    cx = line_anchor(width, box[0], box[2], widest, align)
    return (*box, cx, (result.font, result.lines, result.leading), result.scale)


def resolve_align(value=None) -> str:
    """本文の寄せ方を決める（``value`` → ``MIQ_TEXT_ALIGN`` → ``right``）。"""

    raw = (value or os.getenv("MIQ_TEXT_ALIGN") or "right").strip().lower()

    return raw if raw in ALIGN_CHOICES else "right"


@lru_cache(maxsize=4)
def _background_layer(size: tuple[int, int]) -> Image.Image:
    w, h = size
    kx, ky = w / BASE_SIZE[0], h / BASE_SIZE[1]
    bg = Image.new("RGB", size, (0, 1, 2))
    # Subtle cyan glow; no numpy needed.
    layer = Image.new("RGBA", size)
    gd = ImageDraw.Draw(layer)
    gd.ellipse((-320 * kx, -125 * ky, 1160 * kx, 1220 * ky), fill=(0, 70, 130, 26))
    layer = layer.filter(ImageFilter.GaussianBlur(max(1, int(255 * min(kx, ky)))))
    return Image.alpha_composite(bg.convert("RGBA"), layer)


def dark_background(size: tuple[int, int]) -> Image.Image:
    """Kept for API compatibility with the original classic background."""

    # The glow only depends on the canvas size; callers paint over their own copy.
    return _background_layer(tuple(size)).copy()


def text_region(width: int, height: int, has_credit: bool, align: str = "right"):
    """本文を置ける領域 ``(left, top, right, bottom)`` を返す。

    ``left`` は折り返しの左端。``center`` は上流と同じ広さを取り、``right`` は
    アイコンの右側だけに取る（長い行でもアイコンに掛からない）。
    """

    kx, ky = width / BASE_SIZE[0], height / BASE_SIZE[1]
    k = min(kx, ky)
    left = round(TEXT_LEFT.get(align, TEXT_LEFT["right"]) * kx)
    right = round(TEXT_RIGHT * kx)
    top = round(150 * k)
    bottom = (
        (round(846 * ky) - round(80 * k)) if has_credit else (height - round(80 * k))
    )

    return left, top, right, bottom


def line_anchor(
    width: int, left: int, right: int, widest: float, align: str = "right"
) -> float:
    """行の中心の x を決める。

    ``center`` は画面中央から少し右（``CENTER_SHIFT``）。ただしアイコン側（``left``）と
    右端（``right``）を越えない範囲で寄せるので、長い行でもアイコンに重ならない。
    """

    if align != "center":
        return (left + right) / 2

    # 画面中央から少しだけ右へ寄せた位置を狙う
    target = width * (0.5 + CENTER_SHIFT)
    low, high = left + widest / 2, right - widest / 2

    if low > high:
        return (left + right) / 2

    return min(max(target, low), high)


def render(
    avatar: Path,
    text: str,
    output,
    name: str = "",
    handle: str = "",
    font_file=None,
    bold_font_file=None,
    size=None,
    emoji_font_file=None,
    italic_font_file=None,
    custom_emojis=None,
    align=None,
    *,
    layout="auto",
    seed=None,
    attachment=False,
):
    """Render offline. Fix layout (or seed) for reproducible output.

    ``output`` is a path (``.png``/``.jpg``/``.webp`` by suffix) or a binary file
    object, which receives PNG bytes. ``attachment=True`` keeps the source image's
    aspect ratio. Text has no character-count or minimum-size limit.
    """
    if not text.strip():
        raise ValueError("本文が空です。")
    target = resolve_size(size)
    align = resolve_align(align)
    bundled_fonts()
    if layout == "auto":
        layout = choose_layout(random.Random(seed) if seed is not None else None)
    layout = ALIASES.get(layout, layout)
    if layout not in LAYOUTS:
        raise ValueError(f"不明なレイアウト: {layout}")
    image = read_image(avatar, target)
    emoji_path = find_emoji_font(emoji_font_file)
    if (
        not emoji_font_file
        and not os.getenv("MIQ_EMOJI_FONT")
        and (FONT_DIR / "NotoColorEmoji.ttf").is_file()
    ):
        emoji_path = str(FONT_DIR / "NotoColorEmoji.ttf")
    latin = italic_font_file or os.getenv("MIQ_ITALIC_FONT")
    body = font_file or os.getenv("MIQ_FONT")
    ctx = Ctx(
        image,
        text,
        name,
        handle,
        target,
        EmojiImages(emoji_path, custom_emojis),
        attachment,
        align,
        find_font(body) if body else None,
        find_font(bold_font_file) if bold_font_file else None,
        find_italic_font(latin) if latin else None,
    )
    save(LAYOUTS[layout](ctx), output)


def save(canvas, output):
    if not isinstance(output, (str, os.PathLike)):
        output.write(encode_png(canvas))
        return
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    suffix = output.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        canvas.convert("RGB").save(output, "JPEG", quality=93, subsampling=0)
    elif suffix == ".webp":
        canvas.convert("RGB").save(output, "WEBP", quality=92, method=2)
    else:
        output.write_bytes(encode_png(canvas))


def warmup(size=None):
    """Load fonts, the Japanese dictionary and per-size caches before the first
    request (call once at bot start-up). Returns the warmed layout names."""

    from miq_words import tokenizer

    tokenizer()
    avatar = io.BytesIO()
    Image.new("RGBA", (64, 64), (90, 120, 160, 255)).save(avatar, "PNG")
    for name in LAYOUTS:
        avatar.seek(0)
        render(avatar, "準備 Warm up 👍", io.BytesIO(), "名前", "name", size=size, layout=name)
    return list(LAYOUTS)


def main():
    parser = argparse.ArgumentParser(description="画像と本文から引用PNGを作成します。")
    parser.add_argument("--avatar", "--image", dest="avatar", required=True, type=Path)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", "--quote", dest="text")
    source.add_argument("--text-file", type=Path)
    parser.add_argument("--name", default="")
    parser.add_argument("--handle", default="")
    parser.add_argument("--output", "-o", type=Path, default=Path("quote.png"))
    parser.add_argument("--font")
    parser.add_argument("--bold-font")
    parser.add_argument("--size")
    parser.add_argument("--align", choices=ALIGN_CHOICES)
    parser.add_argument("--emoji-font")
    parser.add_argument("--italic-font")
    parser.add_argument(
        "--layout", choices=["auto", *LAYOUTS, *ALIASES], default="auto"
    )
    parser.add_argument("--seed", type=int)
    parser.add_argument(
        "--attachment", action="store_true", help="画像を正方形に切らず縦横比を維持する"
    )
    args = parser.parse_args()
    try:
        text = (
            args.text_file.read_text(encoding="utf-8-sig")
            if args.text_file
            else args.text
        )
        render(
            args.avatar,
            text,
            args.output,
            args.name,
            args.handle,
            args.font,
            args.bold_font,
            args.size,
            args.emoji_font,
            args.italic_font,
            None,
            args.align,
            layout=args.layout,
            seed=args.seed,
            attachment=args.attachment,
        )
    except (ValueError, OSError) as exc:
        parser.exit(2, f"エラー: {exc}\n")
    print(f"Created: {args.output}")


if __name__ == "__main__":
    main()
