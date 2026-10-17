"""Japanese vertical setting (tategaki): columns run top to bottom, right to left."""

import math
from dataclasses import dataclass

import regex
from PIL import Image, ImageDraw, ImageOps

from miq_fonts import coverage, font_at
from miq_images import put
from miq_text import cluster_metrics, draw_clusters
from miq_words import CUSTOM, GRAPHEME, NO_END, NO_START, is_emoji

CJK = regex.compile(r"[\p{Han}\p{Hiragana}\p{Katakana}ー々〆〇、。「」『』（）！？…・〜]")
SHORT = regex.compile(r"[A-Za-z0-9!?%]{1,3}")
LATIN_RUN = regex.compile(r"[A-Za-z0-9][A-Za-z0-9 .,'’:;!?%&@#/+\-]*[A-Za-z0-9.!?%]|[A-Za-z0-9]")
# Hanging punctuation may overflow the column end by one cell (burasage).
HANG = set("、。，．")
HALF_ADVANCE = 0.6
VERTICAL = ("vert", "vrt2")
# The ideographic em box spans 0.88em above to 0.12em below the baseline.
EM_CENTRE = 0.38


def suitable(text):
    """Vertical setting suits mostly-Japanese text without RTL or complex scripts."""

    graphemes = [g for g in GRAPHEME.findall(text) if not g.isspace()]
    if not graphemes or len(graphemes) > 260:
        return False
    if regex.search(r"[\p{Arabic}\p{Hebrew}\p{Devanagari}\p{Thai}]", text):
        return False
    japanese = sum(bool(CJK.match(g)) for g in graphemes)
    return japanese / len(graphemes) >= 0.6


@dataclass
class Cell:
    kind: str  # "char", "tcy" (upright Latin), "rotated", "emoji"
    text: str
    height: float  # in em


def cells(text):
    """Split one paragraph into vertical cells."""

    out = []
    pos = 0
    for match in LATIN_RUN.finditer(text):
        out.extend(_glyphs(text[pos : match.start()]))
        run = match.group()
        if SHORT.fullmatch(run):
            out.append(Cell("tcy", run, 1.0))
        else:
            out.append(Cell("rotated", run, len(run) * HALF_ADVANCE))
        pos = match.end()
    out.extend(_glyphs(text[pos:]))
    return out


def _glyphs(text):
    for g in GRAPHEME.findall(text):
        if is_emoji(g) or CUSTOM.fullmatch(g):
            yield Cell("emoji", g, 1.05)
        elif g.isspace():
            yield Cell("char", "　", 0.5)
        else:
            yield Cell("char", g, 1.0)


def columns(text, capacity, count=None):
    """Greedy column fill with kinsoku; ``capacity`` is the column length in em.

    With ``count`` (single paragraph), each column aims at an even share of what
    remains, so the last column is not left with a stray glyph.
    """

    result = []
    for paragraph in text.split("\n"):
        column, used = [], 0.0
        pending = cells(paragraph)
        remaining = sum(c.height for c in pending)
        for cell in pending:
            limit = capacity
            if count:
                left = max(1, count - len(result))
                limit = min(capacity, (remaining + used) / left + 0.5)
            fits = used + cell.height <= limit + 1e-6
            if not fits and column:
                if cell.text in HANG and cell.kind == "char":
                    column.append(cell)  # hangs below the column end
                    result.append(column)
                    column, used = [], 0.0
                    continue
                if cell.text[:1] in NO_START and len(column) > 1:
                    carry = column.pop()
                    result.append(column)
                    column, used = [carry], carry.height
                else:
                    carried = []
                    while len(column) > 1 and column[-1].text[-1:] in NO_END:
                        carried.insert(0, column.pop())
                    result.append(column)
                    column, used = carried, sum(c.height for c in carried)
                if cell.height > capacity:
                    return None
            elif not fits:
                return None
            column.append(cell)
            used += cell.height
            remaining -= cell.height
        result.append(column)
    return result


@dataclass
class VerticalLayout:
    px: int
    columns: list
    pitch: float

    @property
    def width(self):
        return self.px + (len(self.columns) - 1) * self.pitch

    @property
    def height(self):
        return max(
            (sum(c.height for c in col if c.text not in HANG or c is not col[-1]) for col in self.columns),
            default=0,
        ) * self.px


def fit_vertical(text, width, height, maximum, pitch=1.5, minimum=10):
    """Largest whole-pixel size whose columns fit the box (``None`` if too small).

    Short phrases are set in a few long columns rather than many stubby ones:
    the size is capped so that about sqrt(n / 3) columns hold ``n`` cells.
    """

    count = sum(len(cells(p)) for p in text.split("\n"))
    wanted = max(1, round((count / 3) ** 0.5), text.count("\n") + 1)
    maximum = min(maximum, height / math.ceil(count / wanted) * 0.98)
    low, high, best = minimum, max(minimum, int(maximum)), None
    while low <= high:
        px = (low + high) // 2
        cols = columns(text, height / px)
        if cols is not None and px + (len(cols) - 1) * px * pitch <= width:
            best = VerticalLayout(px, cols, px * pitch)
            low = px + 1
        else:
            high = px - 1
    if best is not None and "\n" not in text and len(best.columns) > 1:
        # Even out the columns so the last one is not left with a stray glyph.
        even = columns(text, height / best.px, len(best.columns))
        if even is not None and len(even) == len(best.columns):
            best = VerticalLayout(best.px, even, best.pitch)
    return best


def paint_vertical(canvas, layout, right, top, fill, face, latin, images, fallback=None):
    """Draw from the right edge; ``face`` holds vertical forms (GSUB ``vert``).

    Characters the face lacks are drawn from ``fallback`` (a font path).
    """

    draw = ImageDraw.Draw(canvas)
    px = layout.px
    cmap = coverage(str(face.path))
    for index, column in enumerate(layout.columns):
        cx = right - px / 2 - index * layout.pitch
        y = top
        for cell in column:
            box_h = cell.height * px
            if cell.kind == "char":
                use = face
                if fallback and any(ord(c) not in cmap for c in cell.text if not c.isspace()):
                    use = font_at(fallback, face.size)
                advance = cluster_metrics(use, cell.text, VERTICAL)[0]
                draw_clusters(
                    canvas,
                    use,
                    cell.text,
                    cx - advance / 2,
                    y + box_h / 2 + EM_CENTRE * use.size,
                    fill,
                    VERTICAL,
                )
            elif cell.kind == "tcy":
                size = px if len(cell.text) == 1 else px * (0.82 if len(cell.text) == 2 else 0.62)
                font = font_at(latin, size)
                draw.text((cx, y + box_h / 2), cell.text, font=font, fill=fill, anchor="mm")
            elif cell.kind == "rotated":
                font = font_at(latin, px * 0.92)
                l, t, r, b = font.getbbox(cell.text, anchor="lm")
                strip = Image.new("RGBA", (max(1, r - l + 4), px), fill[:3] + (0,))
                ImageDraw.Draw(strip).text(
                    (2 - l, px / 2), cell.text, font=font, fill=fill, anchor="lm"
                )
                strip = strip.rotate(-90, expand=True)
                put(canvas, 
                    strip, (round(cx - strip.width / 2), round(y + (box_h - strip.height) / 2))
                )
            else:
                sprite = images.get(cell.text)
                if sprite is not None:
                    side = max(1, round(px * 0.95))
                    sprite = ImageOps.contain(sprite, (side, side), Image.Resampling.LANCZOS)
                    put(canvas, 
                        sprite,
                        (round(cx - sprite.width / 2), round(y + (box_h - sprite.height) / 2)),
                    )
                else:
                    draw.text(
                        (cx, y + box_h / 2), images.label(cell.text), font=face, fill=fill, anchor="mm"
                    )
            y += box_h
