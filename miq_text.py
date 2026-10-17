"""Measured text, bounded emoji resources and proportion-preserving fitting."""

import hashlib
import math
import unicodedata
from collections import OrderedDict
from contextlib import nullcontext
from dataclasses import dataclass
from functools import lru_cache

import regex
from PIL import Image, ImageColor, ImageDraw, ImageOps

from miq_fonts import coverage, font_at
from miq_images import put
from miq_words import CUSTOM, GRAPHEME, chunks, runs, units


# Japanese faces carry no kerning between CJK glyphs, so a run is the sum of its
# grapheme clusters. Caching each cluster's metrics and coverage mask replaces
# FreeType's per-call outline loading, hinting and rasterisation.
ASCII_WORD = regex.compile(r"[A-Za-z0-9]")


def clusterable(text):
    return not ASCII_WORD.search(text)


@lru_cache(maxsize=16384)
def cluster_metrics(face, cluster, features=None):
    return face.getlength(cluster, features=features), face.getbbox(
        cluster, anchor="ls", features=features
    )


@lru_cache(maxsize=4096)
def cluster_mask(face, cluster, features=None):
    left, top, right, bottom = cluster_metrics(face, cluster, features)[1]
    mask = Image.new("L", (max(1, right - left), max(1, bottom - top)))
    ImageDraw.Draw(mask).text(
        (-left, -top), cluster, font=face, fill=255, anchor="ls", features=features
    )
    return mask, left, top


def run_metrics(face, text):
    x = 0.0
    left = top = math.inf
    right = bottom = -math.inf
    for cluster in GRAPHEME.findall(text):
        advance, (l, t, r, b) = cluster_metrics(face, cluster)
        if r > l and b > t:
            left, top = min(left, x + l), min(top, t)
            right, bottom = max(right, x + r), max(bottom, b)
        x += advance
    if left == math.inf:
        return x, (0, 0, 0, 0)
    return x, (math.floor(left), top, math.ceil(right), bottom)


def ink(canvas, fill):
    if isinstance(fill, int):
        return fill
    if isinstance(fill, str):
        return ImageColor.getcolor(fill, canvas.mode)
    fill = tuple(fill)
    if canvas.mode == "RGBA" and len(fill) == 3:
        return fill + (255,)
    if canvas.mode == "RGB" and len(fill) == 4:
        return fill[:3]
    return fill


def draw_clusters(canvas, face, text, x, baseline, fill, features=None):
    color = ink(canvas, fill)
    for cluster in GRAPHEME.findall(text):
        advance = cluster_metrics(face, cluster, features)[0]
        if not cluster.isspace():
            mask, left, top = cluster_mask(face, cluster, features)
            canvas.paste(color, (round(x + left), round(baseline + top)), mask)
        x += advance
    return x


@lru_cache(maxsize=512)
def unicode_emoji(font_path, token):
    """Colour emoji come from a fixed font, so sprites are shared across requests."""

    font = None
    for size in (109, 128, 64):
        try:
            font = font_at(font_path, size)
            break
        except OSError:
            continue
    if font is None:
        raise ValueError(f"絵文字フォントを読み込めません: {font_path}")
    image = Image.new("RGBA", (320, 280))
    ImageDraw.Draw(image).text(
        (4, 4), token, font=font, anchor="lt", embedded_color=True
    )
    bbox = image.getbbox()
    if not bbox:
        return None
    return ImageOps.contain(image.crop(bbox), (128, 128), Image.Resampling.LANCZOS)


class EmojiImages:
    """A render-local cache: another request cannot reuse stale custom images."""

    def __init__(self, font_path=None, custom=None):
        self.path = font_path
        self.custom = {str(k): v for k, v in (custom or {}).items()}
        self.cache = OrderedDict()

    def get(self, token):
        if token in self.cache:
            self.cache.move_to_end(token)
            return self.cache[token]
        matched = CUSTOM.fullmatch(token)
        image = None
        if matched:
            path = self.custom.get(matched[2])
            if path:
                with Image.open(path) as source:
                    image = ImageOps.exif_transpose(source).convert("RGBA")
                image = ImageOps.contain(image, (128, 128), Image.Resampling.LANCZOS)
        elif self.path:
            image = unicode_emoji(self.path, token)
        self.cache[token] = image
        if len(self.cache) > 128:
            self.cache.popitem(last=False)
        return image

    @staticmethod
    def label(token):
        matched = CUSTOM.fullmatch(token)
        return f":{matched[1]}:" if matched else token


class MixedFont:
    def __init__(
        self,
        font,
        emoji_font=None,
        italic_font=None,
        custom_emojis=None,
        *,
        images=None,
        editorial=False,
        latin=None,
        weight=None,
    ):
        self.font = font
        self.px = font.size
        self.emoji_font = emoji_font
        self.images = images or EmojiImages(emoji_font, custom_emojis)
        self.italic = latin or (font_at(italic_font, self.px) if italic_font else None)
        self.editorial = editorial
        self.weight = weight or (800 if editorial else None)
        self._emoji_advance = self.px * (1.1 if editorial else 1.245)
        self._metrics = OrderedDict()
        self._complex = None
        self._complex_rows = {}

    @property
    def has_emoji(self):
        return bool(self.emoji_font or self.images.custom)

    def face_for(self, kind):
        return self.italic if kind == "latin" and self.italic else self.font

    def ascent(self):
        return self.font.getmetrics()[0]

    def emoji_size(self):
        return self.px if self.editorial else max(1, round(self.px * 1.05))

    def complex_text(self, text):
        known = self._complex_rows.get(text)
        if known is None:
            known = self._complex_scan(text)
            if len(self._complex_rows) < 2048:
                self._complex_rows[text] = known
        return known

    def _complex_scan(self, text):
        for token, kind in runs(text, self.editorial):
            if kind == "emoji":
                continue
            face = self.face_for(kind)
            cmap = coverage(str(face.path))
            for ch in token:
                if unicodedata.bidirectional(ch) in ("R", "AL", "AN"):
                    return True
                if (
                    ord(ch) not in cmap
                    and not ch.isspace()
                    and unicodedata.category(ch) not in ("Cf", "Cc")
                ):
                    return True
        return False

    @property
    def complex(self):
        if self._complex is None:
            from miq_complex import ComplexText

            self._complex = ComplexText(self)
        return self._complex

    def pieces(self, text, tiled=False):
        for token, kind in runs(text, self.editorial):
            image = self.images.get(token) if kind == "emoji" else None
            if image is not None:
                yield token, None, image, self._emoji_advance
            else:
                face = self.face_for("text" if kind == "emoji" else kind)
                token = self.images.label(token) if kind == "emoji" else token
                parts = (
                    chunks(token, 24 if tiled else 64)
                    if tiled or len(token) > 1024
                    else [token]
                )
                for part in parts:
                    yield part, face, None, self.glyph_metrics(face, part)[0]

    def glyph_metrics(self, face, text):
        """Metrics belong to the face, so the cache travels with the face handle."""

        cache = getattr(face, "_miq_glyph_metrics", None)
        if cache is None:
            cache = face._miq_glyph_metrics = OrderedDict()
        if text in cache:
            cache.move_to_end(text)
            return cache[text]
        if face is self.font and clusterable(text) and len(text) <= 1024:
            result = run_metrics(face, text)
        else:
            result = face.getlength(text), face.getbbox(text, anchor="ls")
        if len(text) <= 1024:
            cache[text] = result
            if len(cache) > 128:
                cache.popitem(last=False)
        return result

    def measure(self, text):
        key = text if len(text) <= 512 else hashlib.sha256(text.encode()).digest()
        if key in self._metrics:
            self._metrics.move_to_end(key)
            return self._metrics[key]
        if self.complex_text(text):
            result = self.complex.measure(text)
        else:
            x = 0.0
            boxes = []
            for part, face, image, advance in self.pieces(text):
                if image is not None:
                    size = self.emoji_size()
                    top = (
                        -114 * self.px / 128 if self.editorial else -size + size * 0.12
                    )
                    boxes.append((x, top, x + size, top + size))
                else:
                    l, t, r, b = self.glyph_metrics(face, part)[1]
                    boxes.append((x + l, t, x + r, b))
                x += advance
            bounds = (
                (
                    min(b[0] for b in boxes),
                    min(b[1] for b in boxes),
                    max(b[2] for b in boxes),
                    max(b[3] for b in boxes),
                )
                if boxes
                else (0, 0, 0, 0)
            )
            result = x, bounds
        self._metrics[key] = result
        if len(self._metrics) > 512:
            self._metrics.popitem(last=False)
        return result

    def getlength(self, text):
        return self.measure(text)[0]

    def width(self, text):
        advance, (left, _, right, _) = self.measure(text)
        return max(advance, right) - min(0, left)


def draw_mixed(draw, canvas, xy, text, font, fill, *, anchor="lt"):
    x, y = xy
    if anchor == "mt":
        x -= font.getlength(text) / 2
    if font.complex_text(text):
        font.complex.draw(canvas, text, (x, y + font.ascent()), fill)
        return
    baseline = y + font.ascent()
    for part, face, image, advance in font.pieces(text):
        if image is None and face is font.font and clusterable(part):
            draw_clusters(canvas, face, part, x, baseline, fill)
        elif image is None:
            draw.text((x, baseline), part, font=face, fill=fill, anchor="ls")
        else:
            size = font.emoji_size()
            image = ImageOps.contain(image, (size, size), Image.Resampling.LANCZOS)
            put(canvas, 
                image,
                (
                    round(x + (size - image.width) / 2),
                    round(baseline - size + size * 0.12 + (size - image.height) / 2),
                ),
            )
        x += advance


def wrap_words(words, font, width, balanced=False):
    if not words:
        return [""]
    if balanced and len(words) <= 160:
        n = len(words)
        costs = [math.inf] * n + [0]
        after = [None] * n
        for i in range(n - 1, -1, -1):
            candidate = ""
            for j in range(i + 1, n + 1):
                candidate += words[j - 1]
                value = candidate.strip()
                measured = font.width(value)
                if measured > width:
                    break
                if not value:
                    continue
                penalty = 0.28 + (1 - measured / width) ** 2
                penalty += 0.18 if j < n and value[-1] not in "、。.!?" else 0
                penalty += 0.6 if j == n and measured < width * 0.25 else 0
                if penalty + costs[j] < costs[i]:
                    costs[i], after[i] = penalty + costs[j], j
        if after[0] is None:
            return None
        rows = []
        i = 0
        while i < n:
            j = after[i]
            rows.append("".join(words[i:j]).strip())
            i = j
        return rows
    rows = []
    pending = []
    estimate = 0
    for word in words:
        w = font.width(word)
        if font.width(word.strip()) > width:
            return None
        if pending and estimate + w > width:
            # The final measurement includes kerning and actual ink overhang.
            candidate = "".join(pending)
            while len(pending) > 1 and font.width(candidate.rstrip()) > width:
                tail = pending.pop()
                rows.append("".join(pending).rstrip())
                pending = [tail]
                candidate = tail
            rows.append(candidate.rstrip())
            pending = []
            estimate = 0
        pending.append(word)
        estimate += w
    if pending:
        candidate = "".join(pending).rstrip()
        if font.width(candidate) > width:
            return None
        rows.append(candidate)
    return rows or [""]


@dataclass
class TextLayout:
    font: MixedFont
    lines: list[str]
    size: float
    leading: float
    top: float
    bottom: float

    @property
    def scale(self):
        return self.size / self.font.px

    @property
    def height(self):
        return (
            (len(self.lines) - 1) * self.leading + self.bottom - self.top
        ) * self.scale


def fit(
    text,
    make_font,
    width,
    height,
    maximum,
    *,
    classic=False,
    native=None,
    balanced=None,
    leading=1.43,
):
    """Largest size whose wrapped rows fit; never truncates.

    ``native`` searches whole pixel sizes with real fonts (fast and crisp), and only
    falls back to scaled sub-pixel sizes when even 8px is too large.
    """
    native = classic if native is None else native
    balanced = not classic if balanced is None else balanced
    paragraphs = [units(p) for p in text.split("\n")]
    # Fixed metrics below the ordinary pixel range allow subpixel type sizes.
    reference = make_font(128)
    complex_text = reference.complex_text(text)

    def attempt(size):
        whole = native and size >= 8
        font = make_font(int(size)) if whole else reference
        scale = size / font.px
        available = width / scale
        if complex_text:
            rows = font.complex.wrap(text, available)
        else:
            rows = []
            for words in paragraphs:
                wrapped = wrap_words(words, font, available, balanced=balanced)
                if wrapped is None:
                    return None
                rows.extend(wrapped)
        if any(font.width(row) > available + 0.01 for row in rows):
            return None
        bounds = [font.measure(row)[1] for row in rows]
        line = int(font.px * leading) if whole else font.px * leading
        top = min(b[1] for b in bounds)
        bottom = max(b[3] for b in bounds)
        if classic:
            # Preserve the original line-box placement for ordinary quotes.
            top = min(top, -font.ascent())
            bottom = max(bottom, line - font.ascent())
        line = max(line, bottom - top)
        layout = TextLayout(font, rows, size, line, top, bottom)
        return layout if layout.height <= height + 0.01 else None

    if native:
        low, high = 8, max(8, int(maximum))
        best = None
        # Probe near the area estimate first: it usually halves the search.
        glyphs = max(1, sum(len(w) for words in paragraphs for w in words))
        guess = int(0.92 * (width * height / (glyphs * leading)) ** 0.5)
        while low <= high:
            mid = min(high, max(low, guess)) if guess else (low + high) // 2
            guess = 0
            result = attempt(mid)
            if result is None:
                high = mid - 1
            else:
                best = result
                low = mid + 1
        if best is not None:
            return best
        maximum = 8
    best = attempt(maximum)
    if best is not None:
        return best
    high = maximum
    low = high / 2
    while (best := attempt(low)) is None:
        high = low
        low /= 2
    for _ in range(13):
        mid = (low + high) / 2
        trial = attempt(mid)
        if trial is None:
            high = mid
        else:
            low, best = mid, trial
    return best


def paint(
    canvas,
    layout,
    box,
    fill,
    *,
    center=False,
    classic=False,
    cx=None,
    align=None,
    valign="middle",
):
    """Paint in bounded strips, including sizes below a physical pixel.

    ``align`` is ``left``/``center``/``right``; ``valign`` is ``top``/``middle``/
    ``bottom``. Whole-pixel layouts draw straight onto the canvas.
    """
    font = layout.font
    scale = layout.scale
    align = align or ("center" if center else "left")
    spare = box[3] - box[1] - layout.height
    spare = {"top": 0, "bottom": spare}.get(valign, spare / 2)
    baseline = box[1] + spare - layout.top * scale
    direct = scale == 1
    if classic and direct:
        baseline = box[1] + max(0, int(spare // 1)) + font.ascent()
    if scale < 1 / 32:
        from miq_complex import BitmapTiles

        context = BitmapTiles(canvas)
    else:
        context = nullcontext(None)
    with context as tiles:
        for row in layout.lines:
            advance, bounds = font.measure(row)
            if align == "center":
                x = (cx if cx is not None else (box[0] + box[2]) / 2) - advance * scale / 2
            elif align == "right":
                x = box[2] - max(advance, bounds[2]) * scale
            else:
                x = box[0] - min(0, bounds[0]) * scale
            if direct:
                x = round(x)
                draw_mixed(
                    ImageDraw.Draw(canvas),
                    canvas,
                    (x, baseline - font.ascent()),
                    row,
                    font,
                    fill,
                )
            elif font.complex_text(row):
                font.complex.draw(canvas, row, (x, baseline), fill, scale)
            else:
                paint_line(canvas, font, row, (x, baseline), fill, scale, tiles=tiles)
            baseline += layout.leading * scale


def paint_line(canvas, font, text, xy, fill, scale, *, tiles=None):
    advance, bounds = font.measure(text)
    # Ordinary lines use the same rasterization as the approved prototype.
    if advance <= 4096 and scale >= 1 / 32:
        left, top, right, bottom = bounds
        origin = -min(0, left) + 2
        image = Image.new(
            "RGBA",
            (
                max(1, math.ceil(max(advance, right) + origin + 2)),
                max(1, math.ceil(bottom - top + 4)),
            ),
        )
        baseline = -top + 2
        x = origin
        for part, face, sprite, step in font.pieces(text):
            if sprite is not None:
                size = font.emoji_size()
                sprite = ImageOps.contain(
                    sprite, (round(size), round(size)), Image.Resampling.LANCZOS
                )
                y = -114 * font.px / 128 if font.editorial else -size + size * 0.12
                image.alpha_composite(
                    sprite,
                    (
                        round(x + (size - sprite.width) / 2),
                        round(baseline + y + (size - sprite.height) / 2),
                    ),
                )
            else:
                ImageDraw.Draw(image).text(
                    (x, baseline), part, font=face, fill=fill, anchor="ls"
                )
            x += step
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
        put(canvas, 
            image, (round(xy[0] - origin * scale), round(xy[1] + (top - 2) * scale))
        )
        return
    # Cairo maps each bounded source tile uniformly to fractional pixel space.
    from miq_complex import BitmapTiles

    with nullcontext(tiles) if tiles is not None else BitmapTiles(canvas) as compositor:
        x = xy[0]
        for part, face, sprite, step in font.pieces(text, tiled=True):
            if sprite is not None:
                size = font.emoji_size()
                sprite = ImageOps.pad(sprite, (round(size), round(size)))
                top = -114 * font.px / 128 if font.editorial else -size + size * 0.12
                compositor.paint(sprite, x, xy[1] + top * scale, scale)
            else:
                compositor.text(face, part, fill, x, xy[1], scale)
            x += step * scale
