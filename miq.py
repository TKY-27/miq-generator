#!/usr/bin/env python3
"""Make-it-a-Quote-inspired PNG generator. Requires Pillow only.

アイコン画像と引用文から引用画像（PNG）を作る。画像生成AIも外部APIも使わない。

特徴:
- 出力サイズを指定できる（既定 640x360。``--size 854x480`` / ``MIQ_SIZE``）。
  レイアウトはすべて出力サイズに比例して縮む。
- **縦は伸ばさない**。長文でも同じ比率のまま、入る最大の文字サイズを二分探索で探し、
  最小サイズでも縦に入らないときは本文を縦に縮めて収める（文字が潰れるのは許容）。
  省略（「…」）はしないので、どれだけ長くても本文は全部入る。
- 本文の置き方を選べる（``--align`` / ``MIQ_TEXT_ALIGN``）。
  ``right``（既定）はアイコンの右側へ寄せる、``center`` は画面中央。
- 禁則処理（句読点を行頭に置かない・開き括弧を行末に残さない）。
- 絵文字は Noto Color Emoji で色つき（``--emoji-font`` / ``MIQ_EMOJI_FONT``）、
  欧文は斜体（``--italic-font`` / ``MIQ_ITALIC_FONT``）。
- サーバー絵文字（``<:name:id>`` / ``<a:name:id>``）は、``custom_emojis`` に
  ``{id: 画像パス}`` を渡すと画像として貼る（無いときは ``:name:`` と文字で出す）。
- 引用符（``“``）と青い縦棒の飾りは付けない。

コマンドラインから:

    python miq.py --avatar avatar.png --text "本文" --name "表示名" --output quote.png

"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

__all__ = [
    'SIZE',
    'BASE_SIZE',
    'render',
    'resolve_size',
    'resolve_align',
    'find_font',
    'wrap_line',
    'text_region',
    'fit_text',
]

# ---------------------------------------------------------------------------
# レイアウトの基準
# ---------------------------------------------------------------------------

#: 既定の出力サイズ。``MIQ_SIZE=854x480`` や ``1920x1080`` でも指定できる
SIZE = (640, 360)
#: レイアウトの基準になるサイズ（この比率で全部を拡大縮小する）
BASE_SIZE = (1920, 1080)
#: 本文の置き方。``right``（既定）はアイコンの右側へ寄せる、``center`` は画面中央
ALIGN_CHOICES = ('center', 'right')
#: 本文領域の左端（``BASE_SIZE`` 基準）。``right``（既定）はアイコンの右側の 1010、
#: ``center`` は上流寄りの 845（アイコンとの隙間を足した位置）
TEXT_LEFT = {'right': 1010, 'center': 845}
#: 本文領域の右端（``BASE_SIZE`` 基準）。狭くすると1行の文字数が減って、行が短くなる
TEXT_RIGHT = 1780
#: ``center`` のときに、画面中央からどれだけ右へ寄せるか（幅に対する割合）
CENTER_SHIFT = 0.05
#: 行の高さ（文字サイズに対する倍率）
LINE_HEIGHT = 1.43
#: 行頭に置かない文字（禁則）
NO_LINE_START = '、。，．：；？！゛゜ヽヾゝゞ々ー）］｝〕〉》」』】〙〗〟’”｠»・'
#: 行末に残さない文字（禁則）
NO_LINE_END = '（［｛〔〈《「『【〘〖〝‘“｟«'
#: 折り返しの単位。サーバー絵文字と英数字の塊はまとめて、それ以外は1文字ずつ
ATOM = re.compile(
    r"<a?:[A-Za-z0-9_]+:\d+>"
    r"|[A-Za-z0-9][A-Za-z0-9._'’\-/@:#]*"
    r"|[ \t]+"
    r"|[^A-Za-z0-9 \t]"
)

#: 絵文字フォント（色つき）。無ければ本文フォントのまま描く
EMOJI_FONT_CHOICES = [
    '/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf',
    '/usr/share/fonts/noto/NotoColorEmoji.ttf',
    '/System/Library/Fonts/Apple Color Emoji.ttc',
    'C:/Windows/Fonts/seguiemj.ttf',
]

#: 欧文（ローマ字）用の斜体フォント
ITALIC_FONT_CHOICES = [
    '/usr/share/fonts/truetype/noto/NotoSans-Italic.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf',
    '/System/Library/Fonts/Helvetica.ttc',
    'C:/Windows/Fonts/ariali.ttf',
]
BOLD_ITALIC_FONT_CHOICES = [
    '/usr/share/fonts/truetype/noto/NotoSans-BoldItalic.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf',
    '/System/Library/Fonts/Helvetica.ttc',
    'C:/Windows/Fonts/arialbi.ttf',
]

#: サーバー絵文字のトークン（``<:name:id>`` / アニメは ``<a:name:id>``）
CUSTOM_EMOJI_PATTERN = re.compile(r"<(a?):([A-Za-z0-9_]+):(\d+)>")

#: ローマ字（欧文の単語）の範囲。単語の途中で切れないようにまとめて扱う
LATIN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._'’\-/@:#]*")

#: 絵文字の範囲（記号・絵文字・旗・肌の色・異体字セレクタ・ZWJ）
EMOJI_PATTERN = re.compile(
    '['
    '\U0001F000-\U0001FAFF'
    '\U00002600-\U000027BF'
    '\U0001F1E6-\U0001F1FF'
    '\U0000FE0F\U0000200D\U000020E3'
    '\U00002190-\U000021FF\U00002B00-\U00002BFF\U00003030\U0000303D'
    ']+'
)
#: Noto Color Emoji は109px固定。1文字の送りはこの比率
EMOJI_NATIVE_PX = 109
EMOJI_ADVANCE_RATIO = 1.245

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


def resolve_size(value=None) -> tuple[int, int]:
    """出力サイズを決める（``value`` → ``MIQ_SIZE`` → 既定 ``SIZE``）。

    ``854x480`` のような文字列か ``(w, h)`` を受ける。指定が壊れているときは
    ``ValueError``（呼び出し側で気づけるように、黙って既定へは落とさない）。
    """

    if value is None or value == '':
        value = os.getenv('MIQ_SIZE', '')

    if not value:
        return SIZE

    if isinstance(value, (tuple, list)):
        return int(value[0]), int(value[1])

    matched = re.match(r'^\s*(\d+)\s*[xX×,]\s*(\d+)\s*$', str(value))

    if not matched:
        raise ValueError(f'MIQ_SIZE の形式が不正です: {value}（例 854x480）')

    width, height = int(matched.group(1)), int(matched.group(2))

    if width < 200 or height < 120:
        raise ValueError('MIQ_SIZE が小さすぎます（200x120 以上にしてください）。')

    return width, height


def resolve_align(value=None) -> str:
    """本文の寄せ方を決める（``value`` → ``MIQ_TEXT_ALIGN`` → ``right``）。"""

    raw = (value or os.getenv('MIQ_TEXT_ALIGN') or 'right').strip().lower()

    return raw if raw in ALIGN_CHOICES else 'right'


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
    return ImageFont.truetype(path, max(8, int(px)))


def find_emoji_font(custom: str | None = None) -> str | None:
    """色つき絵文字フォントを探す（無ければ None）。"""

    if custom:
        return custom if Path(custom).is_file() else None

    from_env = os.getenv('MIQ_EMOJI_FONT')

    if from_env:
        return from_env if Path(from_env).is_file() else None

    for name in EMOJI_FONT_CHOICES:
        if Path(name).is_file():
            return name

    return None


def find_italic_font(custom: str | None = None, *, bold: bool = False) -> str | None:
    """欧文の斜体フォントを探す（無ければ None）。"""

    if custom:
        return custom if Path(custom).is_file() else None

    from_env = os.getenv('MIQ_ITALIC_FONT')

    if from_env and Path(from_env).is_file():
        return from_env

    for name in (BOLD_ITALIC_FONT_CHOICES if bold else ITALIC_FONT_CHOICES):
        if Path(name).is_file():
            return name

    return None


def split_emoji(text: str) -> list[tuple[str, bool]]:
    """本文を「絵文字」と「それ以外」に分ける。"""

    runs: list[tuple[str, bool]] = []
    position = 0

    for match in EMOJI_PATTERN.finditer(text):
        if match.start() > position:
            runs.append((text[position:match.start()], False))

        runs.append((match.group(0), True))
        position = match.end()

    if position < len(text):
        runs.append((text[position:], False))

    return runs


def _split_plain(text: str) -> list[tuple[str, str]]:
    """サーバー絵文字を含まない部分を「絵文字」「ローマ字」「それ以外」に分ける。"""

    runs: list[tuple[str, str]] = []

    for chunk, is_emoji in split_emoji(text):
        if is_emoji:
            runs.append((chunk, 'emoji'))
            continue

        position = 0

        for match in LATIN_PATTERN.finditer(chunk):
            if match.start() > position:
                runs.append((chunk[position:match.start()], 'text'))

            runs.append((match.group(0), 'latin'))
            position = match.end()

        if position < len(chunk):
            runs.append((chunk[position:], 'text'))

    return runs


def split_runs(text: str) -> list[tuple[str, str]]:
    """本文を「絵文字（サーバー絵文字含む）」「ローマ字」「それ以外」に分ける。"""

    runs: list[tuple[str, str]] = []
    position = 0

    for match in CUSTOM_EMOJI_PATTERN.finditer(text):
        if match.start() > position:
            runs.extend(_split_plain(text[position:match.start()]))

        runs.append((match.group(0), 'emoji'))
        position = match.end()

    if position < len(text):
        runs.extend(_split_plain(text[position:]))

    return runs


def emoji_clusters(run: str) -> list[str]:
    """ZWJ・異体字セレクタ・肌の色をひとまとまりにする。"""

    clusters: list[str] = []

    for ch in run:
        if clusters and (ch in '\ufe0f\u200d\u20e3' or clusters[-1].endswith('\u200d')):
            clusters[-1] += ch
        else:
            clusters.append(ch)

    return clusters


def emoji_pieces(run: str) -> list[str]:
    """絵文字のかたまりを、サーバー絵文字トークンと Unicode の塊に分ける。

    ``<:name:id>`` を1文字ずつに割らないための入口。
    """

    pieces: list[str] = []
    position = 0

    for match in CUSTOM_EMOJI_PATTERN.finditer(run):
        if match.start() > position:
            pieces.extend(emoji_clusters(run[position:match.start()]))

        pieces.append(match.group(0))
        position = match.end()

    if position < len(run):
        pieces.extend(emoji_clusters(run[position:]))

    return pieces


class MixedFont:
    """本文フォントと絵文字フォントを混ぜた「幅の測り方」。

    ``font.getlength()`` と同じ使い方ができるので、折り返しや行送りの計算は
    そのまま使える。描画は :func:`draw_mixed` が行う。
    """

    def __init__(self, font: ImageFont.FreeTypeFont, emoji_font: str | None = None,
                 italic_font: str | None = None, custom_emojis: dict | None = None):
        self.font = font
        self.emoji_font = emoji_font
        self.custom_emojis = dict(custom_emojis or {})
        self.px = int(getattr(font, 'size', 0) or 0)
        self._emoji_advance = max(1.0, self.px * EMOJI_ADVANCE_RATIO)
        self.italic = font_at(italic_font, self.px) if italic_font else None

    @property
    def has_emoji(self) -> bool:
        return self.emoji_font is not None or bool(self.custom_emojis)

    def face_for(self, kind: str) -> ImageFont.FreeTypeFont:
        """その種類を描くフォント（ローマ字は斜体）。"""

        if kind == 'latin' and self.italic is not None:
            return self.italic

        return self.font

    def ascent(self) -> int:
        return self.font.getmetrics()[0]

    def getlength(self, text: str) -> float:
        if not text:
            return 0.0

        if not self.has_emoji and self.italic is None:
            return self.font.getlength(text)

        total = 0.0

        for chunk, kind in split_runs(text):
            if kind == 'emoji':
                total += self._emoji_advance * len(emoji_pieces(chunk))
            else:
                total += self.face_for(kind).getlength(chunk)

        return total

    def emoji_size(self) -> int:
        """絵文字を描く大きさ（本文と同じくらい）。"""

        return max(8, round(self.px * 1.05))


_EMOJI_CACHE: dict[tuple[str, int], Image.Image | None] = {}


def _square(image: Image.Image, px: int) -> Image.Image:
    """縦横比を保ったまま px の正方形に収める。"""

    image = image.convert('RGBA')
    scale = min(px / max(1, image.width), px / max(1, image.height))
    resized = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    square = Image.new('RGBA', (px, px), (0, 0, 0, 0))
    square.alpha_composite(resized, ((px - resized.width) // 2, (px - resized.height) // 2))

    return square


def emoji_image(cluster: str, px: int, custom: dict | None = None) -> Image.Image | None:
    """絵文字1つぶんの画像。

    サーバー絵文字（``<:name:id>``）は ``custom`` の画像を使い、
    それ以外は色つき絵文字フォント（109px）から作って縮小する。
    """

    key = (cluster, px)

    if key in _EMOJI_CACHE:
        return _EMOJI_CACHE[key]

    image = None
    matched = CUSTOM_EMOJI_PATTERN.fullmatch(cluster)

    if matched and custom:
        path = custom.get(matched.group(3))

        if path and Path(path).is_file():
            try:
                with Image.open(path) as source:
                    image = _square(source.copy(), px)
            except (OSError, ValueError):
                image = None

        _EMOJI_CACHE[key] = image

        return image

    path = find_emoji_font()

    if path:
        try:
            font = ImageFont.truetype(path, EMOJI_NATIVE_PX)
            canvas = Image.new('RGBA', (EMOJI_NATIVE_PX * 2, EMOJI_NATIVE_PX * 2), (0, 0, 0, 0))
            ImageDraw.Draw(canvas).text((0, 0), cluster, font=font,
                                        embedded_color=True, anchor='lt')
            box = canvas.getbbox()

            if box:
                image = _square(canvas.crop(box), px)
        except (OSError, ValueError):
            image = None

    if len(_EMOJI_CACHE) > 500:
        _EMOJI_CACHE.clear()

    _EMOJI_CACHE[key] = image

    return image


def draw_mixed(draw: ImageDraw.ImageDraw, canvas: Image.Image, xy: tuple[int, int],
               text: str, font: MixedFont, fill, *, anchor: str = 'lt'):
    """本文・ローマ字（斜体）・絵文字を混ぜて描く（``anchor`` は lt / mt）。

    縦位置はベースラインで合わせるので、フォントが混ざってもずれない。
    """

    x, y = xy
    width = font.getlength(text)

    if anchor == 'mt':
        x -= width / 2

    if not font.has_emoji and font.italic is None:
        draw.text((x, y), text, font=font.font, fill=fill, anchor='lt')
        return

    baseline = y + font.ascent()
    size = font.emoji_size()
    advance = font._emoji_advance

    for chunk, kind in split_runs(text):
        if kind != 'emoji':
            face = font.face_for(kind)
            draw.text((x, baseline), chunk, font=face, fill=fill, anchor='ls')
            x += face.getlength(chunk)
            continue

        for cluster in emoji_pieces(chunk):
            image = emoji_image(cluster, size, font.custom_emojis)

            if image is not None:
                canvas.alpha_composite(
                    image, (round(x), round(baseline - size + size * 0.12)),
                )
            else:
                # 画像が無いサーバー絵文字は、名前を文字で出す
                matched = CUSTOM_EMOJI_PATTERN.fullmatch(cluster)
                label = f':{matched.group(2)}:' if matched else cluster
                draw.text((x, baseline), label, font=font.font, fill=fill, anchor='ls')

            x += advance


def break_long_word(word: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """1行に収まらない塊を文字で折る（禁則つき）。

    幅は1文字ずつ足して持つ（毎回 getlength で行全体を測り直すと遅いため）。
    足し算は実際の幅より少し大きめに出るので、行が長くなりすぎることはない。
    """

    parts = []
    current = ''
    width = 0.0
    for ch in word:
        ch_width = font.getlength(ch)
        if current and width + ch_width > max_width:
            if ch in NO_LINE_START and len(current) > 1:
                # 句読点は行頭に置かない: 直前の1文字と抱き合わせて次へ送る
                parts.append(current[:-1])
                current = current[-1] + ch
                width = font.getlength(current)
                continue
            if current[-1] in NO_LINE_END and len(current) > 1:
                # 開き括弧は行末に残さない
                parts.append(current[:-1])
                current = current[-1] + ch
                width = font.getlength(current)
                continue
            parts.append(current)
            current = ch
            width = ch_width
        else:
            current += ch
            width += ch_width
    if current:
        parts.append(current)
    return parts


def wrap_line(para: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """1段落を折り返す。空白優先、日本語は禁則を見ながら1文字ずつ。"""

    if not para:
        return ['']

    rows: list[str] = []
    current = ''
    width = 0.0

    for atom in ATOM.findall(para):
        atom_width = font.getlength(atom)

        if atom.isspace():
            if current and width + atom_width <= max_width:
                current += atom
                width += atom_width
            continue

        if not current:
            current = atom
            width = atom_width
        elif width + atom_width <= max_width:
            current += atom
            width += atom_width
            continue
        elif atom in NO_LINE_START and len(current) > 1:
            # 句読点は行頭に置かない: 直前の1文字と抱き合わせて次へ送る
            rows.append(current[:-1].rstrip())
            current = current[-1] + atom
            width = font.getlength(current)
        elif current[-1] in NO_LINE_END and len(current) > 1:
            # 開き括弧は行末に残さない
            rows.append(current[:-1].rstrip())
            current = current[-1] + atom
            width = font.getlength(current)
        else:
            rows.append(current.rstrip())
            current = atom
            width = atom_width

        # それでも1行に入らない塊（長い英単語など）は文字で分割する
        while width > max_width and len(current) > 1:
            pieces = break_long_word(current, font, max_width)
            rows.extend(piece.rstrip() for piece in pieces[:-1])
            current = pieces[-1]
            width = font.getlength(current)

    if current.strip() or not rows:
        rows.append(current.rstrip())

    return rows


def _wrap_all(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []

    for para in text.split('\n'):
        lines.extend(wrap_line(para, font, max_width))

    return lines


def _fits(lines: list[str], font: ImageFont.FreeTypeFont, line_h: int,
          max_width: int, max_height: int) -> bool:
    if len(lines) * line_h > max_height:
        return False

    return all(font.getlength(line) <= max_width + 1 for line in lines)


def dark_background(size: tuple[int, int]) -> Image.Image:
    w, h = size
    kx, ky = w / BASE_SIZE[0], h / BASE_SIZE[1]
    bg = Image.new('RGB', size, (0, 1, 2))
    # Subtle cyan glow; no numpy needed.
    layer = Image.new('RGBA', size)
    gd = ImageDraw.Draw(layer)
    gd.ellipse((-320 * kx, -125 * ky, 1160 * kx, 1220 * ky), fill=(0, 70, 130, 26))
    layer = layer.filter(ImageFilter.GaussianBlur(max(1, int(255 * min(kx, ky)))))
    return Image.alpha_composite(bg.convert('RGBA'), layer)


def try_layout(text: str, font_path: str, max_width: int, max_height: int,
               *, min_px: int = 10, max_px: int = 76, make_font=font_at):
    """入る最大の文字サイズを二分探索で探す。入らなければ ``None``。"""

    best = None
    low, high = max(8, int(min_px)), max(int(min_px) + 1, int(max_px))

    while low <= high:
        px = (low + high) // 2
        font = make_font(font_path, px)
        lines = _wrap_all(text, font, max_width)
        line_h = int(px * LINE_HEIGHT)

        if _fits(lines, font, line_h, max_width, max_height):
            best = (font, lines, line_h)
            low = px + 1
        else:
            high = px - 1

    return best


def text_region(width: int, height: int, has_credit: bool,
                align: str = 'right'):
    """本文を置ける領域 ``(left, top, right, bottom)`` を返す。

    ``left`` は折り返しの左端。``center`` は上流と同じ広さを取り、``right`` は
    アイコンの右側だけに取る（長い行でもアイコンに掛からない）。
    """

    kx, ky = width / BASE_SIZE[0], height / BASE_SIZE[1]
    k = min(kx, ky)
    left = round(TEXT_LEFT.get(align, TEXT_LEFT['right']) * kx)
    right = round(TEXT_RIGHT * kx)
    top = round(150 * k)
    bottom = (round(846 * ky) - round(80 * k)) if has_credit else (height - round(80 * k))

    return left, top, right, bottom


def line_anchor(width: int, left: int, right: int, widest: float,
                align: str = 'right') -> float:
    """行の中心の x を決める。

    ``center`` は画面中央から少し右（``CENTER_SHIFT``）。ただしアイコン側（``left``）と
    右端（``right``）を越えない範囲で寄せるので、長い行でもアイコンに重ならない。
    """

    if align != 'center':
        return (left + right) / 2

    # 画面中央から少しだけ右へ寄せた位置を狙う
    target = width * (0.5 + CENTER_SHIFT)
    low, high = left + widest / 2, right - widest / 2

    if low > high:
        return (left + right) / 2

    return min(max(target, low), high)


def fit_text(text: str, font_path: str, width: int, height: int, has_credit: bool,
             make_font=font_at, align: str = 'right'):
    """決まった大きさの中で本文を組む（縦は伸ばさない）。

    1. 入る最大の文字サイズを二分探索で探す（上流と同じ方針）
    2. 最小サイズでも縦に入らないときは、本文を縦に縮めて収める（文字が潰れる）
       — そのときに使う倍率を ``squash`` として返す

    戻り値は ``(left, top, right, bottom, cx, layout, squash)``。
    ``cx`` は行の中心（``align`` に従う）。
    """

    left, top, right, bottom = text_region(width, height, has_credit, align)
    k = min(width / BASE_SIZE[0], height / BASE_SIZE[1])
    min_px = max(8, round(24 * k))
    max_px = max(min_px + 1, round(76 * k))
    layout = try_layout(
        text, font_path, right - left, bottom - top,
        min_px=min_px, max_px=max_px, make_font=make_font,
    )

    if layout is not None:
        font, lines, line_h = layout

        return left, top, right, bottom, _anchor(width, left, right, lines, font, align), \
            layout, 1.0

    # 最小サイズで組んで、はみ出す分だけ縦に縮める（同じ比率のまま収める）
    font = make_font(font_path, min_px)
    lines = _wrap_all(text, font, right - left)
    line_h = max(1, int(min_px * LINE_HEIGHT))
    needed = max(1, len(lines) * line_h)
    squash = min(1.0, (bottom - top) / needed)

    return left, top, right, bottom, _anchor(width, left, right, lines, font, align), \
        (font, lines, line_h), squash


def _anchor(width: int, left: int, right: int, lines: list[str], font,
            align: str) -> float:
    """行の中心。いちばん長い行が収まる範囲で画面中央へ寄せる。"""

    widest = max((font.getlength(line) for line in lines), default=0.0)

    return line_anchor(width, left, right, widest, align)


def render(avatar: Path, text: str, output: Path, name: str = '', handle: str = '',
           font_file: str | None = None, bold_font_file: str | None = None,
           size=None, emoji_font_file: str | None = None,
           italic_font_file: str | None = None, custom_emojis: dict | None = None,
           align: str | None = None) -> None:
    """MIQ 風の画像を作る。

    ``align`` は本文の寄せ方（``center`` / ``right``。省略時は ``MIQ_TEXT_ALIGN``）。
    """
    if not avatar.is_file():
        raise ValueError(f'画像ファイルが見つかりません: {avatar}')
    if not text.strip():
        raise ValueError('本文が空です。--text または --text-file を指定してください。')
    font_path = find_font(font_file)
    bold_path = find_font(bold_font_file, bold=True)
    emoji_path = find_emoji_font(emoji_font_file)
    italic_path = find_italic_font(italic_font_file)
    bold_italic_path = find_italic_font(italic_font_file, bold=True)
    make_font = lambda path, px: MixedFont(  # noqa: E731
        font_at(path, px), emoji_path,
        bold_italic_path if path == bold_path else italic_path,
        custom_emojis,
    )

    has_credit = bool(name.strip() or handle.strip())
    align = resolve_align(align)
    # 縦は伸ばさない（同じ比率のまま、文字サイズと行間で収める）
    w, h = resolve_size(size)
    left, top, right, bottom, cx, (font, lines, line_h), squash = fit_text(
        text, font_path, w, h, has_credit, make_font, align,
    )
    kx, ky = w / BASE_SIZE[0], h / BASE_SIZE[1]
    k = min(kx, ky)

    canvas = dark_background((w, h))
    with Image.open(avatar) as orig:
        im = ImageOps.exif_transpose(orig).convert('RGBA')
    # アイコンは正方形のまま（縦を伸ばしても歪ませない）
    side = max(1, round(970 * k))
    im = ImageOps.fit(im, (side, side), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))

    avatar_layer = Image.new('RGBA', (w, h))
    avatar_layer.alpha_composite(im, (round(-12 * kx), round(65 * k)))
    # Fade icon to the right, without losing its original colors.
    fade_mask = Image.new('L', (w, h), 0)
    fdraw = ImageDraw.Draw(fade_mask)
    for x in range(0, min(w, round(1020 * kx))):
        t = max(0., min(1., (x - 555 * kx) / (405 * kx)))
        smooth = t * t * (3 - 2 * t)
        alpha = int(255 * (1.0 - smooth))
        fdraw.line((x, 0, x, h), fill=alpha)
    vertical = Image.new('L', (w, h), 0)
    vdraw = ImageDraw.Draw(vertical)
    icon_top, icon_bottom = round(65 * k), round(1035 * k)
    for y in range(icon_top, min(icon_bottom, h)):
        factor = min(1., (y - icon_top) / (92 * k), (icon_bottom - y) / (115 * k))
        vdraw.line((0, y, w, y), fill=max(0, int(255 * factor)))
    fade_mask = ImageChops.multiply(fade_mask, vertical)
    avatar_layer.putalpha(ImageChops.multiply(avatar_layer.getchannel('A'), fade_mask))
    canvas = Image.alpha_composite(canvas, avatar_layer)
    draw = ImageDraw.Draw(canvas)
    # 本文の位置は align に従う（center でもアイコンへはみ出さない）
    block_h = len(lines) * line_h
    top = top + max(0, (bottom - top - round(block_h * squash)) // 2)

    if squash < 1.0:
        # 最小サイズでも縦に入らない → 本文だけ縦に縮めて収める（文字は潰れる）
        layer = Image.new('RGBA', (w, h))
        layer_draw = ImageDraw.Draw(layer)
        for i, line in enumerate(lines):
            draw_mixed(layer_draw, layer, (cx, i * line_h), line, font,
                       fill=(246, 248, 250), anchor='mt')
        box = layer.getbbox()

        if box is not None:
            scaled = layer.crop(box).resize(
                (box[2] - box[0], max(1, round((box[3] - box[1]) * squash))),
                Image.Resampling.LANCZOS,
            )
            # 横位置は元のまま（中央寄せを崩さない）
            canvas.alpha_composite(scaled, (box[0], top))
    else:
        for i, line in enumerate(lines):
            draw_mixed(draw, canvas, (cx, top + i * line_h), line, font,
                       fill=(246, 248, 250), anchor='mt')

    if has_credit:
        y = round(846 * ky)
        draw.line((cx - round(142 * kx), y, cx + round(142 * kx), y),
                  fill=(63, 125, 149), width=max(1, round(2 * k)))
        if name.strip():
            size_px = max(9, round(43 * k))
            face = MixedFont(font_at(bold_path, size_px), emoji_path, bold_italic_path,
                             custom_emojis)
            while face.getlength('— ' + name) > right - left and size_px > 9:
                size_px -= 1
                face = MixedFont(font_at(bold_path, size_px), emoji_path,
                                 bold_italic_path, custom_emojis)
            draw_mixed(draw, canvas, (cx, y + round(24 * ky)), '— ' + name, face,
                       fill=(248, 250, 252), anchor='mt')
        if handle.strip():
            hd = '@' + handle.strip().lstrip('@')
            face = MixedFont(font_at(font_path, max(8, round(30 * k))), emoji_path,
                             italic_path, custom_emojis)
            draw_mixed(draw, canvas, (cx, y + round((88 if name.strip() else 45) * ky)), hd,
                       face, fill=(132, 160, 173), anchor='mt')

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
    parser.add_argument('--size', help='出力サイズ（例 854x480 / 1920x1080。既定は 640x360）')
    parser.add_argument('--align', choices=list(ALIGN_CHOICES),
                        help='本文の寄せ方（right=アイコンの右側へ寄せる（既定） / center=画面中央）')
    parser.add_argument('--emoji-font', help='色つき絵文字フォント（省略時は自動検出）')
    parser.add_argument('--italic-font', help='欧文の斜体フォント（省略時は自動検出）')
    args = parser.parse_args()
    try:
        text = args.text_file.read_text(encoding='utf-8-sig') if args.text_file else args.text
        render(args.avatar, text, args.output, args.name, args.handle, args.font, args.bold_font,
               args.size, args.emoji_font, args.italic_font, None, args.align)
    except (ValueError, OSError) as exc:
        parser.exit(2, f'エラー: {exc}\n')


if __name__ == '__main__':
    main()
