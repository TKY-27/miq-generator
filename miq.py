#!/usr/bin/env python3
"""Offline quote PNG renderer with the original composition and CLI."""

from __future__ import annotations

import argparse
import os
import random
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from miq_fonts import (
    FONT_DIR,
    editorial_fonts,
    find_emoji_font,
    find_font,
    find_italic_font,
    font_at,
)
from miq_images import classic_image, place_image, read_image
from miq_text import (
    EmojiImages,
    MixedFont,
    draw_mixed,
    fit,
    paint,
    wrap_words,
)
from miq_words import units

SIZE = (640, 360)
BASE_SIZE = (1920, 1080)
ALIGN_CHOICES = ("center", "right")
TEXT_LEFT = {"right": 1010, "center": 845}
TEXT_RIGHT = 1780
CENTER_SHIFT = 0.05
LINE_HEIGHT = 1.43
LAYOUT_WEIGHTS = (("classic", 50), ("mirrored", 30), ("magazine", 15), ("literary", 5))
__all__ = [
    "BASE_SIZE",
    "SIZE",
    "choose_layout",
    "find_font",
    "fit_text",
    "render",
    "resolve_align",
    "resolve_size",
    "text_region",
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
    value = (rng or random).random() * sum(weight for _, weight in LAYOUT_WEIGHTS)
    cumulative = 0
    for name, weight in LAYOUT_WEIGHTS:
        cumulative += weight
        if value < cumulative:
            return name
    return LAYOUT_WEIGHTS[-1][0]


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


def dark_background(size: tuple[int, int]) -> Image.Image:
    w, h = size
    kx, ky = w / BASE_SIZE[0], h / BASE_SIZE[1]
    bg = Image.new("RGB", size, (0, 1, 2))
    # Subtle cyan glow; no numpy needed.
    layer = Image.new("RGBA", size)
    gd = ImageDraw.Draw(layer)
    gd.ellipse((-320 * kx, -125 * ky, 1160 * kx, 1220 * ky), fill=(0, 70, 130, 26))
    layer = layer.filter(ImageFilter.GaussianBlur(max(1, int(255 * min(kx, ky)))))
    return Image.alpha_composite(bg.convert("RGBA"), layer)


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


def credit(
    canvas, text, maker, maximum, xy, width, fill, *, center=False, baseline=False
):
    if not text.strip():
        return
    font = maker(maximum)
    scale = min(1, width / max(1, font.width(text)))
    x = xy[0] - font.getlength(text) * scale / 2 if center else xy[0]
    if baseline:
        from miq_text import paint_line

        if font.complex_text(text):
            font.complex.draw(canvas, text, (x, xy[1]), fill, scale)
        else:
            paint_line(canvas, font, text, (x, xy[1]), fill, scale)
    elif scale == 1:
        draw_mixed(ImageDraw.Draw(canvas), canvas, (x, xy[1]), text, font, fill)
    else:
        from miq_text import paint_line

        if font.complex_text(text):
            font.complex.draw(
                canvas, text, (x, xy[1] + font.ascent() * scale), fill, scale
            )
        else:
            paint_line(
                canvas, font, text, (x, xy[1] + font.ascent() * scale), fill, scale
            )


def font_makers(images, font_file=None, bold_font_file=None, latin_override=None):
    jp, latin, serif = editorial_fonts()
    body = find_font(font_file or os.getenv("MIQ_FONT") or jp)
    author = find_font(bold_font_file or serif)
    ui = "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
    if not Path(ui).is_file():
        ui = find_font(None)

    def quote(px):
        english = (
            font_at(latin_override, px)
            if latin_override
            else font_at(latin, round(px * 1.12), 700)
        )
        return MixedFont(
            font_at(body, px, 800),
            images.path,
            images=images,
            editorial=not latin_override,
            latin=english,
        )

    def name(px):
        return MixedFont(font_at(author, px, 600), images.path, images=images)

    def handle(px):
        return MixedFont(font_at(ui, px), images.path, images=images)

    return quote, name, handle


def render(
    avatar: Path,
    text: str,
    output: Path,
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

    ``attachment=True`` keeps the source image's aspect ratio instead of cropping
    it to a square. Text has no character-count or minimum-size limit.
    """
    if not text.strip():
        raise ValueError("本文が空です。")
    target = resolve_size(size)
    align = resolve_align(align)
    if layout == "auto":
        editorial_fonts()
        layout = choose_layout(random.Random(seed) if seed is not None else None)
    if layout not in dict(LAYOUT_WEIGHTS):
        raise ValueError(f"不明なレイアウト: {layout}")
    image = read_image(avatar)
    emoji_path = find_emoji_font(emoji_font_file)
    if (
        not emoji_font_file
        and not os.getenv("MIQ_EMOJI_FONT")
        and (FONT_DIR / "NotoColorEmoji.ttf").is_file()
    ):
        emoji_path = str(FONT_DIR / "NotoColorEmoji.ttf")
    images = EmojiImages(emoji_path, custom_emojis)
    has_credit = bool(name.strip() or handle.strip())
    if layout == "classic":
        w, h = target
        kx, ky = w / 1920, h / 1080
        k = min(kx, ky)
        latin_override = italic_font_file or os.getenv("MIQ_ITALIC_FONT")
        if latin_override:
            latin_override = find_italic_font(latin_override)
        maker, name_maker, handle_maker = font_makers(
            images, font_file, bold_font_file, latin_override
        )

        box = text_region(w, h, has_credit, align)
        result = fit(
            text,
            maker,
            box[2] - box[0],
            box[3] - box[1],
            max(9, round(76 * k)),
            classic=True,
        )
        widest = max(result.font.getlength(row) * result.scale for row in result.lines)
        cx = line_anchor(w, box[0], box[2], widest, align)
        canvas = dark_background(target)
        classic_image(canvas, image, attachment)
        paint(canvas, result, box, (246, 248, 250), center=True, classic=True, cx=cx)
        if has_credit:
            y = round(846 * ky)
            ImageDraw.Draw(canvas).line(
                (cx - round(142 * kx), y, cx + round(142 * kx), y),
                fill=(63, 125, 149),
                width=max(1, round(2 * k)),
            )
            name_size = max(9, round(43 * k))
            while (
                name_size > 9
                and name_maker(name_size).width("— " + name) > box[2] - box[0]
            ):
                name_size -= 1
            if name.strip():
                credit(
                    canvas,
                    "— " + name,
                    name_maker,
                    name_size,
                    (cx, y + round(24 * ky)),
                    box[2] - box[0],
                    (248, 250, 252),
                    center=True,
                )
            if handle.strip():
                credit(
                    canvas,
                    "@" + handle.strip().lstrip("@"),
                    handle_maker,
                    max(8, round(30 * k)),
                    (cx, y + round((88 if name.strip() else 45) * ky)),
                    box[2] - box[0],
                    (132, 160, 173),
                    center=True,
                )
    else:
        # The approved small previews were downsampled from the editorial master.
        factor = max(1, 1920 / target[0])
        work = (round(target[0] * factor), round(target[1] * factor))
        canvas = editorial(
            image,
            text,
            name,
            handle,
            work,
            layout,
            images,
            attachment,
            font_file,
            bold_font_file,
        )
        if work != target:
            canvas = canvas.resize(target, Image.Resampling.LANCZOS)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output, format="PNG", optimize=True)


def editorial(
    image,
    text,
    name,
    handle,
    size,
    layout,
    images,
    attachment,
    font_file,
    bold_font_file,
):
    w, h = size
    kx, ky = w / 1920, h / 1080
    k = min(kx, ky)

    def box(values):
        return tuple(
            round(v * (kx if i % 2 == 0 else ky)) for i, v in enumerate(values)
        )

    maker, name_maker, handle_maker = font_makers(images, font_file, bold_font_file)

    if layout == "mirrored":
        background, ink, secondary = "#101010", "#f4f3ef", "#aaa9a7"
        slot = (946, 65, 1896, 1015)
        text_box = (112, 150, 886, 766)
        maximum = 82
        author = (112, 926)
    elif layout == "magazine":
        background, ink, secondary = "#f1f1ed", "#101010", "#626260"
        slot = (1306, 184, 1816, 694)
        text_box = (112, 143, 1202, 970)
        maximum = 88
        author = (1306, 822)
    else:
        background, ink, secondary = "#f1f1ed", "#101010", "#626260"
        slot = (545, 804, 865, 984) if attachment else (710, 833, 858, 981)
        text_box = (150, 154, 1770, 730)
        maximum = 98
        author = (930, 876) if attachment else (900, 889)
    canvas = Image.new("RGBA", size, background)
    place_image(canvas, image, box(slot), attachment)
    region = box(text_box)
    result = fit(text, maker, region[2] - region[0], region[3] - region[1], maximum * k)
    paint(canvas, result, region, ink, center=layout == "literary")
    x, y = box(author)
    available = w - round(104 * kx) - x
    credit(
        canvas, name, name_maker, round(48 * k), (x, y), available, ink, baseline=True
    )
    if handle.strip():
        credit(
            canvas,
            "@" + handle.strip().lstrip("@"),
            handle_maker,
            round(32 * k),
            (x, y + round(62 * ky)),
            available,
            secondary,
            baseline=True,
        )
    return canvas


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
        "--layout", choices=["auto"] + list(dict(LAYOUT_WEIGHTS)), default="auto"
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
