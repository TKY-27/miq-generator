#!/usr/bin/env python3
"""Make-it-a-Quote-inspired PNG generator. Requires Pillow only."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

SIZE = (1920, 1080)
FONT_CHOICES = [
    # Linux
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/noto/NotoSansJP-Regular.ttf',
    '/usr/share/fonts/truetype/fonts-japanese-gothic.ttf',
    '/usr/share/fonts/truetype/ipafont-gothic/ipag.ttf',
    # macOS
    '/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc',
    '/System/Library/Fonts/Hiragino Sans GB.ttc',
    '/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc',
    # Windows
    'C:/Windows/Fonts/YuGothM.ttc',
    'C:/Windows/Fonts/meiryo.ttc',
    'C:/Windows/Fonts/msgothic.ttc',
]


def find_font(custom: str | None, bold: bool = False) -> str:
    if custom:
        if not Path(custom).is_file():
            raise ValueError(f'指定されたフォントが見つかりません: {custom}')
        return custom

    from_env = os.getenv('MIQ_FONT')
    if from_env and Path(from_env).is_file():
        return from_env

    candidates = []
    for name in FONT_CHOICES:
        if bold:
            name = name.replace('Regular', 'Bold').replace('W3', 'W6').replace('YuGothM', 'YuGothB')
        candidates.append(name)
    candidates.extend(FONT_CHOICES)
    for name in candidates:
        if Path(name).is_file():
            return name

    if shutil.which('fc-match'):
        try:
            p = subprocess.run(['fc-match', '-f', '%{file}', ':lang=ja'],
                               capture_output=True, text=True, timeout=3, check=True)
            path = p.stdout.strip()
            if path and Path(path).is_file():
                return path
        except (OSError, subprocess.SubprocessError):
            pass
    raise ValueError('日本語フォントが見つかりません。--font /path/to/font.ttf を指定してください。')


def font_at(path: str, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, px)


def break_long_word(word: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    parts = []
    current = ''
    for ch in word:
        if current and font.getlength(current + ch) > max_width:
            parts.append(current)
            current = ch
        else:
            current += ch
    if current:
        parts.append(current)
    return parts


def wrap_line(para: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Wrap by spaces where possible; split long (e.g. Japanese) tokens by character."""
    if not para:
        return ['']
    tokens = re.findall(r'\S+|\s+', para)
    rows = []
    cur = ''
    for token in tokens:
        if token.isspace():
            if cur and font.getlength(cur + token) <= max_width:
                cur += token
            continue
        candidate = cur + token
        if font.getlength(candidate) <= max_width:
            cur = candidate
            continue
        if cur.strip():
            rows.append(cur.rstrip())
            cur = ''
        if font.getlength(token) <= max_width:
            cur = token
        else:
            pieces = break_long_word(token, font, max_width)
            rows.extend(pieces[:-1])
            cur = pieces[-1]
    rows.append(cur.rstrip())
    return rows


def layout_quote(text: str, font_path: str, max_width: int, max_height: int):
    # No truncation. For impossible input sizes, signal the problem rather than silently cut text.
    for px in range(76, 23, -1):
        font = font_at(font_path, px)
        lines = []
        for para in text.split('\n'):
            lines.extend(wrap_line(para, font, max_width))
        height = int(px * 1.43)
        if len(lines) * height <= max_height and all(font.getlength(l) <= max_width + 1 for l in lines):
            return font, lines, height
    raise ValueError('本文が長すぎて1920×1080の画像内に収まりません。本文を短くしてください。')


def dark_background(size: tuple[int, int]) -> Image.Image:
    w, h = size
    bg = Image.new('RGB', size, (0, 1, 2))
    # Subtle cyan glow; no numpy needed.
    layer = Image.new('RGBA', size)
    gd = ImageDraw.Draw(layer)
    gd.ellipse((-320, -125, 1160, 1220), fill=(0, 70, 130, 26))
    layer = layer.filter(ImageFilter.GaussianBlur(255))
    return Image.alpha_composite(bg.convert('RGBA'), layer)


def render(avatar: Path, text: str, output: Path, name: str = '', handle: str = '',
           font_file: str | None = None, bold_font_file: str | None = None) -> None:
    if not avatar.is_file():
        raise ValueError(f'画像ファイルが見つかりません: {avatar}')
    if not text.strip():
        raise ValueError('本文が空です。--text または --text-file を指定してください。')
    font_path = find_font(font_file)
    bold_path = find_font(bold_font_file, bold=True)

    w, h = SIZE
    canvas = dark_background(SIZE)
    with Image.open(avatar) as orig:
        im = ImageOps.exif_transpose(orig).convert('RGBA')
    im = ImageOps.fit(im, (970, 970), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))

    avatar_layer = Image.new('RGBA', SIZE)
    avatar_layer.alpha_composite(im, (-12, 65))
    # Fade icon to the right, without losing its original colors.
    fade_mask = Image.new('L', SIZE, 0)
    fdraw = ImageDraw.Draw(fade_mask)
    for x in range(0, 1020):
        t = max(0., min(1., (x - 555) / 405))
        smooth = t * t * (3 - 2 * t)
        alpha = int(255 * (1.0 - smooth))
        fdraw.line((x, 0, x, h), fill=alpha)
    vertical = Image.new('L', SIZE, 0)
    vdraw = ImageDraw.Draw(vertical)
    for y in range(65, min(1035, h)):
        factor = min(1., (y - 65) / 92, (1035 - y) / 115)
        vdraw.line((0, y, w, y), fill=max(0, int(255 * factor)))
    fade_mask = ImageChops.multiply(fade_mask, vertical)
    avatar_layer.putalpha(ImageChops.multiply(avatar_layer.getchannel('A'), fade_mask))
    canvas = Image.alpha_composite(canvas, avatar_layer)
    draw = ImageDraw.Draw(canvas)
    left, right = 785, 1900
    cx = (left + right) // 2
    has_credit = bool(name.strip() or handle.strip())
    text_height = 515 if has_credit else 685
    font, lines, line_h = layout_quote(text, font_path, right - left, text_height)
    top = 230 + max(0, (text_height - len(lines) * line_h) // 2)
    accent_y = max(115, top - 113)
    draw.rounded_rectangle((818, accent_y + 40, 824, accent_y + 86), radius=3, fill=(42, 183, 242))
    qfont = font_at(font_path, 105)
    draw.text((844, accent_y), '“', font=qfont, fill=(50, 161, 213), anchor='lt')
    for i, line in enumerate(lines):
        draw.text((cx, top + i * line_h), line, font=font,
                  fill=(246, 248, 250), anchor='mt')

    if has_credit:
        y = 846
        draw.line((cx - 142, y, cx + 142, y), fill=(63, 125, 149), width=2)
        if name.strip():
            size = 43
            face = font_at(bold_path, size)
            while face.getlength(name) > 1000 and size > 25:
                size -= 1
                face = font_at(bold_path, size)
            draw.text((cx, y + 24), '— ' + name, font=face,
                      fill=(248, 250, 252), anchor='mt')
        if handle.strip():
            hd = '@' + handle.strip().lstrip('@')
            face = font_at(font_path, 30)
            draw.text((cx, y + (88 if name.strip() else 45)), hd,
                      font=face, fill=(132, 160, 173), anchor='mt')

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert('RGB').save(output, format='PNG', optimize=True)
    print(f'Created: {output} ({w}x{h})')


def main() -> None:
    parser = argparse.ArgumentParser(description='画像と本文から MIQ 風の画像を作成します。')
    parser.add_argument('--avatar', '--image', dest='avatar', required=True, type=Path,
                        help='投稿者のアイコン (PNG/JPEG/WebPなど)')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--text', '--quote', dest='text', help='表示する引用文')
    source.add_argument('--text-file', type=Path, help='UTF-8テキストファイル')
    parser.add_argument('--name', default='', help='表示名 (省略可)')
    parser.add_argument('--handle', default='', help='@ユーザー名 (省略可)')
    parser.add_argument('--output', '-o', type=Path, default=Path('quote.png'))
    parser.add_argument('--font', help='日本語フォントパス（自動検出できない場合）')
    parser.add_argument('--bold-font', help='名前表示用の太字フォントパス (省略可)')
    args = parser.parse_args()
    try:
        text = args.text_file.read_text(encoding='utf-8-sig') if args.text_file else args.text
        render(args.avatar, text, args.output, args.name, args.handle, args.font, args.bold_font)
    except (ValueError, OSError) as exc:
        parser.exit(2, f'エラー: {exc}\n')


if __name__ == '__main__':
    main()
