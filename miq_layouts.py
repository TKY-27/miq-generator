"""Ten quote layouts, each drawn natively at the output size.

Positions are designed on a 1920x1080 grid and scaled: ``ctx.x``/``ctx.y`` map
horizontal/vertical positions and ``ctx.s`` maps sizes (type, strokes, radii).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import cached_property, lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

import miq_aa
import miq_vertical as vertical
from miq_fonts import bundled_fonts, coverage, font_at
from miq_images import (
    backdrop,
    contain,
    cover,
    dominant_color,
    duotone,
    fade_mask,
    fit_media,
    grain,
    grayscale,
    keep_level,
    light_map,
    halftone,
    luminance,
    opaque,
    paper,
    pixelate,
    put,
    rounded_mask,
    shade,
    soft_blur,
    tint,
    vertical_mask,
    vignette,
    with_mask,
)
from miq_text import MixedFont, cluster_metrics, draw_clusters, draw_mixed, fit, paint
from miq_words import CUSTOM, GRAPHEME, is_emoji


@dataclass(frozen=True)
class Type:
    """A pairing: Japanese face (+ weight) and an optional Latin face."""

    jp: str
    weight: int | None = None
    latin: str | None = None
    latin_weight: int | None = None
    latin_scale: float = 1.0


GOTHIC = Type("gothic", None, "sans", 700)
GOTHIC_MEDIUM = Type("gothic-medium", None, "sans", 500)
MINCHO = Type("mincho", None, "serif", None, 1.16)
MINCHO_ITALIC = Type("mincho", None, "italic", 600, 1.18)
DISPLAY = Type("display")
MONO = Type("mono-jp", 500, "mono", 500)
SANS = Type("gothic-medium", None, "sans", 500)
SANS_BOLD = Type("gothic", None, "sans", 800)
SERIF = Type("mincho", None, "serif", None, 1.16)
SERIF_ITALIC = Type("gothic", None, "serif-italic", None, 1.2)
CONDENSED = Type("display", None, "condensed")
BRUSH = Type("brush", None, "serif", None, 1.1)


class Ctx:
    def __init__(
        self,
        image,
        text,
        name,
        handle,
        size,
        images,
        attachment=False,
        align="right",
        font_file=None,
        bold_font_file=None,
        latin_font_file=None,
    ):
        self.image = image
        self.text = text
        self.name = name.strip()
        self.handle = handle.strip().lstrip("@")
        self.size = self.w, self.h = size
        self.kx, self.ky = self.w / 1920, self.h / 1080
        self.k = min(self.kx, self.ky)
        self.images = images
        self.attachment = attachment
        self.align = align
        self.font_file = font_file
        self.bold_font_file = bold_font_file
        self.latin_font_file = latin_font_file
        self.fonts = bundled_fonts()
        self._makers = {}

    def x(self, value):
        return round(value * self.kx)

    def y(self, value):
        return round(value * self.ky)

    def s(self, value):
        return value * self.k

    @cached_property
    def accent(self):
        return dominant_color(self.image)

    @cached_property
    def aa(self):
        """``(mode, lines)`` when the text is ASCII art, else ``None``."""

        return miq_aa.detect(self.text, self.fonts)

    @cached_property
    def glyphs(self):
        return [g for g in GRAPHEME.findall(self.text.strip()) if not g.isspace()]

    @cached_property
    def hero(self):
        """One or two Japanese characters (or emoji) get a poster treatment."""

        if self.aa or "\n" in self.text.strip() or not 1 <= len(self.glyphs) <= 2:
            return None
        if all(vertical.CJK.match(g) or is_emoji(g) or CUSTOM.fullmatch(g) for g in self.glyphs):
            return self.glyphs
        return None

    @cached_property
    def short(self):
        return "\n" not in self.text.strip() and len(self.glyphs) <= 24

    @cached_property
    def issue(self):
        digest = hashlib.blake2s(f"{self.text}\0{self.name}".encode(), digest_size=4)
        return int.from_bytes(digest.digest(), "big") % 999 + 1

    def maker(self, spec, role="label"):
        """Font factory for ``spec``; ``--font``/``--bold-font`` override JP faces."""

        key = (spec, role)
        if key in self._makers:
            return self._makers[key]
        jp = self.fonts[spec.jp]
        if role == "body" and self.font_file:
            jp = self.font_file
        elif role == "name" and self.bold_font_file:
            jp = self.bold_font_file
        latin = self.fonts[spec.latin] if spec.latin else None
        if role == "body" and self.latin_font_file:
            latin = self.latin_font_file
        cache = {}

        def make(px):
            px = max(1, int(px))
            font = cache.get(px)
            if font is None:
                font = cache[px] = MixedFont(
                    font_at(jp, px, spec.weight),
                    self.images.path,
                    images=self.images,
                    editorial=True,
                    latin=font_at(latin, px * spec.latin_scale, spec.latin_weight)
                    if latin
                    else None,
                    weight=spec.weight or 700,
                )
            return font

        self._makers[key] = make
        return make


# ---------------------------------------------------------------- drawing kit


def measure(ctx, spec, box, maximum, leading=1.42):
    """``(height, layout)`` of the quote inside ``box``, to size a frame first.

    Pass the layout back to ``quote(prepared=...)`` to paint without refitting.
    """

    left, top, right, bottom = box
    if ctx.aa:
        mode, lines = ctx.aa
        px, _, _, _, line = miq_aa.layout(
            lines, mode, ctx.fonts, right - left, bottom - top, maximum * 0.6
        )
        return len(lines) * px * line, None
    result = fit(
        ctx.text,
        ctx.maker(spec, "body"),
        right - left,
        bottom - top,
        maximum,
        native=True,
        balanced=True,
        leading=leading,
    )
    return result.height, result


def quote(
    canvas,
    ctx,
    spec,
    box,
    fill,
    maximum,
    *,
    align="left",
    valign="middle",
    leading=1.42,
    prepared=None,
):
    """Fit the whole quote into ``box`` and paint it; returns the ink rectangle.

    ASCII art keeps its lines and spacing exactly and is scaled as one block.
    """

    left, top, right, bottom = box
    if ctx.aa:
        mode, lines = ctx.aa
        return miq_aa.draw(
            canvas, lines, mode, ctx.fonts, box, fill, maximum * 0.6, align, valign
        ), None
    result = prepared or fit(
        ctx.text,
        ctx.maker(spec, "body"),
        right - left,
        bottom - top,
        maximum,
        native=True,
        balanced=True,
        leading=leading,
    )
    paint(canvas, result, box, fill, align=align, valign=valign)
    spare = bottom - top - result.height
    y0 = top + {"top": 0, "bottom": spare}.get(valign, spare / 2)
    widest = max(result.font.getlength(row) for row in result.lines) * result.scale
    x0 = {"center": (left + right - widest) / 2, "right": right - widest}.get(align, left)
    return (x0, y0, x0 + widest, y0 + result.height), result


def hero_column(canvas, ctx, role, box, fill, *, size=None, valign="middle"):
    """One or two characters stacked vertically as large as ``box`` allows."""

    left, top, right, bottom = box
    count = len(ctx.hero)
    gap = 1.04
    px = int(size or min((bottom - top) / (count * gap), right - left))
    face = font_at(ctx.font_file if ctx.font_file and role != "brush" else ctx.fonts[role], px)
    cmap = coverage(str(face.path))
    total = px * gap * count
    y = top + {"top": 0, "bottom": bottom - top - total}.get(valign, (bottom - top - total) / 2)
    cx = (left + right) / 2
    y0 = y
    for glyph in ctx.hero:
        centre = y + px * gap / 2
        sprite = ctx.images.get(glyph) if (is_emoji(glyph) or CUSTOM.fullmatch(glyph)) else None
        if sprite is not None:
            side = round(px * 0.92)
            sprite = contain(sprite, (side, side))
            put(canvas, sprite, (cx - sprite.width / 2, centre - sprite.height / 2))
        else:
            use = face
            if any(ord(c) not in cmap for c in glyph):
                use = font_at(ctx.fonts["fallback"], px)
            advance = cluster_metrics(use, glyph, vertical.VERTICAL)[0]
            draw_clusters(
                canvas, use, glyph, cx - advance / 2, centre + vertical.EM_CENTRE * px,
                fill, vertical.VERTICAL,
            )
        y += px * gap
    return (cx - px / 2, y0, cx + px / 2, y0 + total)


def label(
    canvas,
    ctx,
    spec,
    text,
    px,
    xy,
    fill,
    *,
    anchor="left",
    max_width=None,
    tracking=0.0,
    role="label",
):
    """One line on a baseline at ``xy``; shrinks to ``max_width``. Returns width.

    Plain lines (no emoji or complex script) are rasterised once into a cached
    coverage mask, so fixed labels such as mastheads cost one paste per render.
    """

    if not text:
        return 0
    make = ctx.maker(spec, role)
    px = max(1, int(px))
    font = make(px)

    def measure(f):
        extra = tracking * f.px * max(0, len(text) - 1) if tracking else 0
        return f.width(text) + extra

    width = measure(font)
    if max_width and width > max_width:
        px = max(1, int(px * max_width / width))
        font = make(px)
        while px > 1 and measure(font) > max_width:
            px -= 1
            font = make(px)
        width = measure(font)
    x = xy[0] - {"center": width / 2, "right": width}.get(anchor, 0)
    y = xy[1]
    if font.complex_text(text):
        font.complex.draw(canvas, text, (x, y), fill)
    elif any(image is not None for _, _, image, _ in font.pieces(text)):
        draw_mixed(ImageDraw.Draw(canvas), canvas, (x, y - font.ascent()), text, font, fill)
    else:
        mask, left, top = _label_mask(font, text, tracking)
        color = tuple(fill[:3]) if canvas.mode == "RGB" else tuple(fill[:3]) + (255,)
        canvas.paste(color, (round(x + left), round(y + top)), mask)
    return width


def _label_mask(font, text, tracking):
    key = (
        str(font.font.path), font.px, font.weight,
        str(font.italic.path) if font.italic else None,
        font.italic.size if font.italic else None,
        text, tracking,
    )
    cached = _LABELS.get(key)
    if cached is not None:
        return cached
    ascent = font.ascent()
    advance, (l, t, r, b) = font.measure(text)
    extra = tracking * font.px * max(0, len(text) - 1)
    pad = font.px
    mask = Image.new("L", (max(1, round(max(advance, r) + extra - min(0, l) + 2 * pad)),
                           max(1, round(b - t + 2 * pad))))
    origin = (pad - min(0, l), pad - t - ascent)
    if tracking:
        draw = ImageDraw.Draw(mask)
        x = origin[0]
        for char in text:
            draw_mixed(draw, mask, (x, origin[1]), char, font, 255)
            x += font.getlength(char) + tracking * font.px
    else:
        draw_mixed(ImageDraw.Draw(mask), mask, origin, text, font, 255)
    box = mask.getbbox() or (0, 0, 1, 1)
    value = (mask.crop(box), box[0] - origin[0], box[1] - origin[1] - ascent)
    if len(_LABELS) > 512:
        _LABELS.clear()
    _LABELS[key] = value
    return value


_LABELS = {}


def shadowed(canvas, fill, radius, opacity, draw, offset=(0, 0)):
    """Run ``draw(layer)`` on a clear layer, then lay it over a soft shadow."""

    layer = Image.new("RGBA", canvas.size, tuple(fill[:3]) + (0,))
    result = draw(layer)
    bbox = layer.getbbox()
    if not bbox:
        return result
    pad = max(1, round(radius * 3))
    box = (
        max(0, bbox[0] - pad),
        max(0, bbox[1] - pad),
        min(canvas.width, bbox[2] + pad),
        min(canvas.height, bbox[3] + pad),
    )
    alpha = layer.crop(box).getchannel("A")
    # Blurring at half size looks the same for a soft shadow and costs a quarter.
    small = alpha.reduce(2) if min(alpha.size) > 8 else alpha
    small = small.filter(ImageFilter.GaussianBlur(radius * small.width / alpha.width))
    alpha = small.resize(alpha.size, Image.Resampling.BILINEAR)
    shadow = Image.new("RGBA", alpha.size, (0, 0, 0, 0))
    shadow.putalpha(alpha.point(lambda v: round(v * opacity)))
    put(canvas, shadow, (box[0] + offset[0], box[1] + offset[1]))
    put(canvas, layer.crop(bbox), bbox[:2])
    return result


def overlay(canvas, color, mask):
    """Composite a flat ``color`` through ``mask`` (an L image of canvas size)."""

    canvas.paste(tuple(color[:3]), (0, 0) + canvas.size, mask)


def scaled(mask, factor):
    return mask.point(lambda v: round(v * factor))


def handle_text(ctx):
    return "@" + ctx.handle if ctx.handle else ""


# ---------------------------------------------------------------- layouts


def credits_centre(canvas, ctx, name_spec, cx, y, width, name_fill, handle_fill, *, prefix=""):
    """Name over handle, centred on ``cx`` from baseline ``y``."""

    if ctx.name:
        label(canvas, ctx, name_spec, prefix + ctx.name, ctx.s(58), (cx, y), name_fill,
              anchor="center", max_width=width, role="name")
        y += ctx.s(68)
    label(canvas, ctx, SANS, handle_text(ctx), ctx.s(34), (cx, y), handle_fill,
          anchor="center", max_width=width)


def noir(ctx):
    """Monochrome icon cut by a diagonal fade into black (Make it a Quote style)."""

    w, h = ctx.size
    canvas = Image.new("RGB", ctx.size, (0, 0, 0))
    slot = (min(h, round(w * 0.62)), h)
    photo = grayscale(fit_media(ctx.image, slot, ctx.attachment), 1.08)
    mask = fade_mask(ctx.size, 0.40, 0.62, -0.22).crop((0, 0, photo.width, photo.height))
    put(canvas, with_mask(photo, mask), (0, (h - photo.height) // 2))
    credit = bool(ctx.name or ctx.handle)
    white = (246, 246, 244)
    if ctx.hero:
        box = (ctx.x(1060), ctx.y(90), ctx.x(1740), ctx.y(800 if credit else 990))
        ink = hero_column(canvas, ctx, "brush", box, white)
    else:
        box = (ctx.x(1000), ctx.y(150), ctx.x(1800), ctx.y(720 if credit else 930))
        ink, _ = quote(canvas, ctx, MINCHO, box, white, ctx.s(210), align="center")
    cx = (ctx.x(1000) + ctx.x(1800)) / 2
    y = min(ink[3] + ctx.s(100), h - ctx.s(140))
    credits_centre(canvas, ctx, MINCHO_ITALIC, cx, y, ctx.x(800), (236, 236, 234), (128, 128, 128),
                   prefix="- ")
    return canvas


def spotlight(ctx):
    """The classic composition, rebuilt: full-height colour icon and a lit stage."""

    w, h = ctx.size
    accent = ctx.accent
    canvas = Image.new("RGB", ctx.size, (7, 8, 10))
    overlay(canvas, shade(accent, 0.32, 0.6), _glow(ctx.size))
    slot = (min(h, round(w * 0.58)), h)
    photo = fit_media(ctx.image, slot, ctx.attachment)
    mask = _spotlight_mask(ctx.size, photo.size)
    put(canvas, with_mask(photo, mask), (0, (h - photo.height) // 2))
    credit = bool(ctx.name or ctx.handle)
    left = ctx.x(1010 if ctx.align == "right" else 860)
    white = (247, 248, 250)
    if ctx.hero:
        box = (left, ctx.y(100), ctx.x(1800), ctx.y(770 if credit else 980))
        ink = hero_column(canvas, ctx, "gothic", box, white)
    else:
        box = (left, ctx.y(150), ctx.x(1800), ctx.y(740 if credit else 930))
        ink, _ = quote(canvas, ctx, GOTHIC, box, white, ctx.s(190), align="center")
    cx = (box[0] + box[2]) / 2
    if credit:
        y = min(ink[3] + ctx.s(66), h - ctx.s(196))
        bright = shade(accent, 0.62, 0.8)
        ImageDraw.Draw(canvas).rectangle(
            (cx - ctx.s(70), y, cx + ctx.s(70), y + max(1, ctx.s(5))), fill=bright
        )
        credits_centre(canvas, ctx, GOTHIC_MEDIUM, cx, y + ctx.s(78), box[2] - box[0],
                       (240, 242, 245), (138, 148, 158))
    return canvas


def mirror(ctx):
    """Icon on the right behind a reversed diagonal; bold flush-left type."""

    w, h = ctx.size
    accent = ctx.accent
    canvas = Image.new("RGB", ctx.size, shade(accent, 0.06, 0.4))
    slot = (min(h, round(w * 0.6)), h)
    photo = fit_media(ctx.image, slot, ctx.attachment)
    x0 = w - photo.width
    mask = fade_mask(ctx.size, 0.48, 0.70, 0.16, invert=True).crop((x0, 0, w, photo.height))
    put(canvas, with_mask(photo, mask), (x0, (h - photo.height) // 2))
    credit = bool(ctx.name or ctx.handle)
    bright = shade(accent, 0.6, 0.85)
    white = (250, 250, 250)
    if ctx.hero:
        box = (ctx.x(150), ctx.y(100), ctx.x(760), ctx.y(820 if credit else 980))
        ink = hero_column(canvas, ctx, "brush", box, white)
    else:
        box = (ctx.x(150), ctx.y(130), ctx.x(1020), ctx.y(780 if credit else 950))
        ink, _ = quote(canvas, ctx, SANS_BOLD, box, white, ctx.s(200))
    # A single unbreakable run (a long URL) shrinks the quote to a sliver, which
    # can make ink[3] fall above ink[1] + ctx.s(10): keep the rule at least two
    # pixels tall instead of letting the two ends cross.
    top = ink[1] + ctx.s(10)
    bottom = max(top + max(2, ctx.s(10)), ink[3] - ctx.s(4))
    ImageDraw.Draw(canvas).rectangle(
        (ctx.x(96), top, ctx.x(96) + max(2, ctx.s(10)), bottom),
        fill=bright,
    )
    y = min(ink[3] + ctx.s(96), h - ctx.s(120))
    width = ctx.x(870)
    if ctx.name:
        label(canvas, ctx, SANS_BOLD, ctx.name, ctx.s(56), (box[0], y), bright,
              max_width=width, role="name")
        y += ctx.s(64)
    label(canvas, ctx, SANS, handle_text(ctx), ctx.s(36), (box[0], y), (160, 166, 172),
          max_width=width)
    return canvas


def tategaki(ctx):
    """Calligraphy on washi: vertical brush (or Mincho) and a vermilion seal ring.

    One or two characters are written large and horizontally, like a shikishi;
    long, Latin or right-to-left text falls back to horizontal Mincho.
    """

    ink_color = (30, 26, 22)
    vermilion = (196, 58, 40)
    canvas = paper(ctx.size, (243, 238, 226)).copy()
    region = (ctx.x(470), ctx.y(110), ctx.x(1800), ctx.y(970))
    if ctx.hero:
        quote(canvas, ctx, BRUSH, region, ink_color, ctx.s(520), align="center", leading=1.1)
    else:
        layout = None
        brush = ctx.short and not ctx.font_file
        if not ctx.aa and vertical.suitable(ctx.text):
            layout = vertical.fit_vertical(
                ctx.text,
                region[2] - region[0],
                region[3] - region[1],
                ctx.s(250 if brush else 190),
                minimum=max(8, round(ctx.s(30))),
            )
        if layout is not None:
            right = (region[0] + region[2]) / 2 + layout.width / 2
            top = region[1] + max(0, (region[3] - region[1] - layout.height) / 2)
            face = ctx.font_file or ctx.fonts["brush" if brush else "mincho"]
            vertical.paint_vertical(
                canvas, layout, right, top, ink_color, font_at(face, layout.px),
                ctx.fonts["serif"], ctx.images, ctx.fonts["fallback"],
            )
        else:
            quote(canvas, ctx, MINCHO, region, ink_color, ctx.s(150), align="center")
    # Author column: seal ring with the icon, then the name set vertically.
    side = round(ctx.s(230))
    cx, cy = ctx.x(240), ctx.y(700)
    icon = fit_media(ctx.image, (side, side), ctx.attachment)
    disc = rounded_mask(icon.size, side // 2 if not ctx.attachment else ctx.s(12))
    ring = round(ctx.s(10))
    if not ctx.attachment:
        ImageDraw.Draw(canvas).ellipse(
            (cx - side / 2 - ring, cy - side / 2 - ring, cx + side / 2 + ring, cy + side / 2 + ring),
            fill=vermilion,
        )
    put(canvas, with_mask(icon, disc), (round(cx - icon.width / 2), round(cy - icon.height / 2)))
    upright = ctx.name and vertical.CJK.search(ctx.name)
    if upright:
        name_px = round(ctx.s(64))
        space = cy - side / 2 - ring - ctx.s(60) - ctx.y(110)
        cols = vertical.columns(ctx.name, max(1, space / name_px))
        while (cols is None or len(cols) > 1) and name_px > 8:
            name_px -= 2
            cols = vertical.columns(ctx.name, max(1, space / name_px))
        if cols:
            vertical.paint_vertical(
                canvas,
                vertical.VerticalLayout(name_px, cols, name_px * 1.4),
                cx + name_px / 2,
                ctx.y(110),
                ink_color,
                font_at(ctx.bold_font_file or ctx.fonts["brush"], name_px),
                ctx.fonts["serif"],
                ctx.images,
                ctx.fonts["fallback"],
            )
    y = cy + side / 2 + ring + ctx.s(78)
    if ctx.name and not upright:
        label(canvas, ctx, MINCHO, ctx.name, ctx.s(48), (cx, y), ink_color,
              anchor="center", max_width=ctx.s(400), role="name")
        y += ctx.s(48)
    if ctx.handle:
        label(canvas, ctx, SANS, handle_text(ctx), ctx.s(32), (cx, y),
              (120, 112, 100), anchor="center", max_width=ctx.s(400))
    return canvas


def cinema(ctx):
    """A film still: letterbox bars, a subtitle and a credit line.

    One or two characters become a vertical subtitle on the right, as in
    Japanese cinema.
    """

    w, h = ctx.size
    canvas = backdrop(ctx.image, ctx.size, ctx.attachment, (0.5, 0.36), fast=True)
    canvas = ImageChops.multiply(canvas, _cinema_light(ctx.size))
    put(canvas, grain(ctx.size))
    bar = max(0, round((h - w / 2.39) / 2))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, w, bar), fill=(0, 0, 0))
    draw.rectangle((0, h - bar, w, h), fill=(0, 0, 0))
    white = (252, 250, 240)
    if ctx.hero:
        box = (ctx.x(1500), bar + ctx.y(60), ctx.x(1800), h - bar - ctx.y(60))
        shadowed(canvas, white, ctx.s(6), 0.95,
                 lambda layer: hero_column(layer, ctx, "gothic", box, white, size=ctx.s(150)))
    else:
        box = (ctx.x(170), bar + ctx.y(70), ctx.x(1750), h - bar - ctx.y(64))
        shadowed(canvas, white, ctx.s(5), 0.95,
                 lambda layer: quote(layer, ctx, GOTHIC, box, white, ctx.s(84 if ctx.short else 72),
                                     align="center", valign="bottom", leading=1.36))
    parts = [p for p in (ctx.name.upper(), handle_text(ctx)) if p]
    if parts:
        line = "—  " + "   ·   ".join(parts)
        label(canvas, ctx, SANS, line, ctx.s(30), (w / 2, h - bar / 2 + ctx.s(11)), (190, 190, 186),
              anchor="center", tracking=0.12, max_width=w - ctx.x(240), role="name")
    return canvas


def glass(ctx):
    """A frosted card over the blurred icon, like a social post."""

    w, h = ctx.size
    source = cover(ctx.image, (max(1, w // 4), max(1, h // 4)), fast=True)
    background = soft_blur(opaque(source), max(2, ctx.s(10))).resize(ctx.size, Image.Resampling.BILINEAR)
    background = ImageEnhance.Color(background).enhance(1.5)
    canvas = tint(background, 0.62)
    card = (ctx.x(150), ctx.y(110), ctx.x(1770), ctx.y(970))
    put(canvas, _glass_panel((card[2] - card[0], card[3] - card[1]), round(ctx.s(44)), ctx.s(2)), card[:2])
    pad = round(ctx.s(70))
    side = round(ctx.s(140))
    icon = fit_media(ctx.image, (side, side), ctx.attachment)
    shape = rounded_mask(icon.size, side // 2 if not ctx.attachment else round(ctx.s(18)))
    ix, iy = card[0] + pad, card[1] + pad
    put(canvas, with_mask(icon, shape), (ix + (side - icon.width) // 2, iy + (side - icon.height) // 2))
    tx = ix + side + round(ctx.s(30))
    text_width = card[2] - pad - tx
    if ctx.name and ctx.handle:
        label(canvas, ctx, GOTHIC, ctx.name, ctx.s(54), (tx, iy + side * 0.47), (255, 255, 255),
              max_width=text_width, role="name")
        label(canvas, ctx, SANS, handle_text(ctx), ctx.s(36), (tx, iy + side * 0.88), (222, 226, 232),
              max_width=text_width)
    elif ctx.name or ctx.handle:
        label(canvas, ctx, GOTHIC, ctx.name or handle_text(ctx), ctx.s(54), (tx, iy + side * 0.66),
              (255, 255, 255), max_width=text_width, role="name")
    box = (card[0] + pad, iy + side + round(ctx.s(40)), card[2] - pad, card[3] - pad)
    if ctx.hero:
        hero_column(canvas, ctx, "gothic", box, (255, 255, 255))
    else:
        quote(canvas, ctx, GOTHIC, box, (255, 255, 255), ctx.s(170), leading=1.42,
              align="center" if ctx.short else "left")
    return canvas


def poster(ctx):
    """Swiss poster in the icon's colour: huge type, duotone image, hard rules."""

    w, h = ctx.size
    background = shade(ctx.accent, 0.52, 0.62)
    ink = (18, 18, 18) if luminance(background) > 0.3 else (250, 248, 240)
    canvas = Image.new("RGB", ctx.size, background)
    slot_side = round(ctx.s(420))
    image = duotone(ctx.image, shade(background, 0.12, 0.5), shade(background, 0.86, 0.4))
    image = fit_media(image, (slot_side, slot_side), ctx.attachment)
    ix = ctx.x(1810) - image.width
    put(canvas, image, (ix, ctx.y(140)))
    label(canvas, ctx, SANS_BOLD, f"No.{ctx.issue:03d}", ctx.s(30), (ctx.x(1810), ctx.y(104)), ink,
          anchor="right", tracking=0.08)
    if ctx.hero:
        hero_column(canvas, ctx, "display", (ctx.x(110), ctx.y(60), ctx.x(820), ctx.y(840)), ink)
    else:
        mark = tuple(round(a * 0.8 + b * 0.2) for a, b in zip(background, ink))
        label(canvas, ctx, CONDENSED, "“", ctx.s(380), (ctx.x(96), ctx.y(330)), mark)
        box = (ctx.x(130), ctx.y(200), ix - ctx.x(90), ctx.y(830))
        quote(canvas, ctx, DISPLAY, box, ink, ctx.s(240), leading=1.28)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((ctx.x(130), ctx.y(872), ctx.x(1810), ctx.y(872) + max(2, ctx.s(6))), fill=ink)
    y = ctx.y(962)
    if ctx.name:
        label(canvas, ctx, SANS_BOLD, ctx.name.upper(), ctx.s(56), (ctx.x(130), y), ink,
              max_width=ctx.x(1000), role="name", tracking=0.04)
    label(canvas, ctx, SANS, handle_text(ctx), ctx.s(38), (ctx.x(1810), y), ink,
          anchor="right", max_width=ctx.x(600))
    return canvas


def newspaper(ctx):
    """A front page: blackletter masthead, halftone portrait, Mincho headline.

    One or two characters run as a vertical headline under a red 号外 tag.
    """

    w, h = ctx.size
    ink = (26, 24, 22)
    canvas = paper(ctx.size, (236, 231, 218)).copy()
    draw = ImageDraw.Draw(canvas)
    label(canvas, ctx, Type("blackletter"), "The Daily Quote", ctx.s(112), (w / 2, ctx.y(132)), ink,
          anchor="center")
    rule = max(1, round(ctx.s(2)))
    draw.rectangle((ctx.x(90), ctx.y(160), ctx.x(1830), ctx.y(160) + rule * 2), fill=ink)
    draw.rectangle((ctx.x(90), ctx.y(170), ctx.x(1830), ctx.y(170) + rule), fill=ink)
    meta_y = ctx.y(210)
    label(canvas, ctx, SANS, f"No. {ctx.issue:03d}", ctx.s(24), (ctx.x(90), meta_y), ink, tracking=0.1)
    label(canvas, ctx, SANS, "特報 · 発言録", ctx.s(24), (w / 2, meta_y), ink, anchor="center", tracking=0.1)
    label(canvas, ctx, SANS, "PRICE ¥0", ctx.s(24), (ctx.x(1830), meta_y), ink, anchor="right", tracking=0.1)
    draw.rectangle((ctx.x(90), ctx.y(232), ctx.x(1830), ctx.y(232) + rule), fill=ink)
    side = round(ctx.s(560))
    photo = fit_media(ctx.image, (side, side), ctx.attachment, (0.5, 0.4))
    photo = halftone(photo, max(3, round(ctx.s(9))), ink, (236, 231, 218))
    px, py = ctx.x(90), ctx.y(276)
    put(canvas, photo, (px + (side - photo.width) // 2, py))
    caption_y = py + photo.height + ctx.s(52)
    caption = " ".join(p for p in ("— " + ctx.name if ctx.name else "", handle_text(ctx)) if p)
    label(canvas, ctx, SERIF_ITALIC, caption, ctx.s(40), (px, caption_y), ink, max_width=side, role="name")
    column = px + side + ctx.x(60)
    draw.rectangle((column, ctx.y(276), column + rule, ctx.y(990)), fill=ink)
    box = (column + ctx.x(60), ctx.y(270), ctx.x(1830), ctx.y(990))
    if ctx.hero:
        tag = (box[0], box[1] + ctx.s(10), box[0] + ctx.s(150), box[1] + ctx.s(250))
        draw.rectangle(tag, fill=(186, 30, 30))
        vertical.paint_vertical(
            canvas, vertical.VerticalLayout(round(ctx.s(64)), vertical.columns("号外", 9), 0),
            tag[2] - (tag[2] - tag[0] - ctx.s(64)) / 2, tag[1] + ctx.s(52), (250, 246, 236),
            font_at(ctx.fonts["mincho"], round(ctx.s(64))), ctx.fonts["serif"], ctx.images,
        )
        hero_column(canvas, ctx, "mincho", (tag[2], box[1], box[2], box[3]), ink)
    else:
        quote(canvas, ctx, MINCHO, box, ink, ctx.s(200), leading=1.36)
    return canvas


def terminal(ctx):
    """A terminal window on the icon's blurred wallpaper; the quote is the output.

    The window hugs its content, so short quotes do not float in empty space.
    One or two characters are printed as a block-letter banner.
    """

    w, h = ctx.size
    small = cover(ctx.image, (max(1, w // 6), max(1, h // 6)), fast=True)
    canvas = tint(soft_blur(opaque(small), max(2, ctx.s(6))).resize(ctx.size, Image.Resampling.BILINEAR), 0.4)
    left, right = ctx.x(150), ctx.x(1770)
    pad = ctx.s(60)
    bar_h = ctx.s(64)
    side = round(ctx.s(200))
    text_left = left + pad
    text_right = right - pad - side - ctx.s(48)
    banner = miq_aa.banner("".join(ctx.hero), ctx.fonts["gothic"]) if ctx.hero else None
    budget = h - ctx.y(120) - (bar_h + pad * 2 + ctx.s(56) + ctx.s(40) + ctx.s(92))
    box = (text_left, 0, text_right, budget)
    if banner:
        px, _, _, _, line = miq_aa.layout(banner, "mono", ctx.fonts, text_right - text_left, budget, ctx.s(40))
        needed, prepared = len(banner) * px * line, None
    else:
        needed, prepared = measure(ctx, MONO, box, ctx.s(110), 1.48)
    content = max(needed, side - ctx.s(56))
    win_h = bar_h + pad + ctx.s(56) + ctx.s(40) + content + ctx.s(92) + pad
    top = (h - win_h) / 2
    win = (left, top, right, top + win_h)
    radius = round(ctx.s(22))
    shadow = Image.new("L", (round(right - left), round(win_h)))
    ImageDraw.Draw(shadow).rounded_rectangle((0, 0, shadow.width - 1, shadow.height - 1), radius, fill=150)
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, ctx.s(18))))
    canvas.paste((0, 0, 0), (round(left), round(top + ctx.s(16))), shadow)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(win, radius, fill=(22, 27, 34), outline=(58, 64, 72), width=max(1, round(ctx.s(2))))
    bar = top + bar_h
    draw.line((left, bar, right, bar), fill=(48, 54, 61), width=max(1, round(ctx.s(2))))
    dot = ctx.s(11)
    for i, color in enumerate(((255, 95, 87), (254, 188, 46), (40, 200, 64))):
        x = left + ctx.s(40) + i * ctx.s(36)
        draw.ellipse((x - dot, top + bar_h / 2 - dot, x + dot, top + bar_h / 2 + dot), fill=color)
    label(canvas, ctx, MONO, "miq — zsh", ctx.s(26), ((left + right) / 2, top + bar_h / 2 + ctx.s(9)),
          (139, 148, 158), anchor="center")
    icon = pixelate(ctx.image, (side, side), 24) if not ctx.attachment else contain(ctx.image, (side, side))
    ix = round(right - pad - icon.width)
    put(canvas, icon, (ix, round(bar + pad)))
    prompt_y = bar + pad + ctx.s(36)
    arrow = "❯" if ord("❯") in coverage(ctx.fonts["mono"]) else ">"
    who = ctx.handle or ctx.name or "anon"
    x = text_left
    x += label(canvas, ctx, MONO, arrow + " ", ctx.s(38), (x, prompt_y), (126, 231, 135))
    x += label(canvas, ctx, MONO, "~ ", ctx.s(38), (x, prompt_y), (121, 192, 255))
    label(canvas, ctx, MONO, f"quote --by {who}", ctx.s(38), (x, prompt_y), (230, 237, 243),
          max_width=text_right - x)
    body = (text_left, prompt_y + ctx.s(40), text_right, prompt_y + ctx.s(40) + max(needed, 1))
    if banner:
        ink = miq_aa.draw(canvas, banner, "mono", ctx.fonts, body, (230, 237, 243), ctx.s(40), "left", "top")
    else:
        ink, _ = quote(canvas, ctx, MONO, body, (230, 237, 243), ctx.s(110), valign="top",
                       leading=1.48, prepared=prepared)
    y = ink[3] + ctx.s(70)
    tail = "— " + ctx.name if ctx.name else ""
    width = label(canvas, ctx, MONO, tail, ctx.s(40), (text_left, y), (126, 231, 135),
                  max_width=right - pad - text_left - ctx.s(40), role="name")
    cursor_x = text_left + width + (ctx.s(14) if width else 0)
    draw.rectangle((cursor_x, y - ctx.s(30), cursor_x + ctx.s(18), y + ctx.s(6)), fill=(230, 237, 243))
    return canvas


def magazine_cover(ctx):
    """A magazine cover: full-bleed icon, masthead and an overlaid pull quote.

    One or two characters are brushed vertically down the right-hand side.
    """

    w, h = ctx.size
    canvas = backdrop(ctx.image, ctx.size, ctx.attachment, (0.5, 0.3), fast=True)
    canvas = ImageChops.multiply(canvas, _cover_light(ctx.size))
    white = (255, 255, 255)
    label(canvas, ctx, CONDENSED, "MIQ", ctx.s(190), (ctx.x(90), ctx.y(214)), white, tracking=0.02)
    label(canvas, ctx, SANS_BOLD, f"ISSUE {ctx.issue:03d}", ctx.s(28), (ctx.x(1830), ctx.y(96)), white,
          anchor="right", tracking=0.2)
    label(canvas, ctx, SANS, "THE QUOTE ISSUE", ctx.s(28), (ctx.x(1830), ctx.y(140)), (220, 220, 220),
          anchor="right", tracking=0.2)
    accent = shade(ctx.accent, 0.62, 0.9)
    credit = bool(ctx.name or ctx.handle)
    if ctx.hero:
        box = (ctx.x(1380), ctx.y(190), ctx.x(1830), ctx.y(1000))
        shadowed(canvas, white, ctx.s(8), 0.85,
                 lambda layer: hero_column(layer, ctx, "brush", box, white))
    else:
        box = (ctx.x(90), ctx.y(300), ctx.x(1500), ctx.y(890 if credit else 990))
        shadowed(canvas, white, ctx.s(6), 0.7,
                 lambda layer: quote(layer, ctx, SERIF_ITALIC, box, white, ctx.s(190),
                                     valign="bottom", leading=1.3))
    if credit:
        y = ctx.y(980)
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((ctx.x(90), y - ctx.s(28), ctx.x(90) + ctx.s(60), y - ctx.s(18)), fill=accent)
        x = ctx.x(90) + ctx.s(84)
        x += label(canvas, ctx, SANS_BOLD, ctx.name.upper(), ctx.s(44), (x, y), white,
                   tracking=0.08, max_width=ctx.x(1100), role="name")
        if ctx.handle:
            label(canvas, ctx, SANS, ("   " if ctx.name else "") + handle_text(ctx), ctx.s(36), (x, y),
                  (210, 210, 210), max_width=ctx.x(1700) - x)
    return canvas


@lru_cache(maxsize=8)
def _glow(size):
    glow = Image.new("L", (96, 54))
    ImageDraw.Draw(glow).ellipse((-30, -14, 60, 70), fill=90)
    return glow.filter(ImageFilter.GaussianBlur(10)).resize(size, Image.Resampling.BILINEAR)


@lru_cache(maxsize=8)
def _spotlight_mask(size, photo):
    mask = fade_mask(size, 0.32, 0.56).crop((0, 0) + photo)
    mask = ImageChops.multiply(mask, vertical_mask(photo, -0.2, 0.08))
    return ImageChops.multiply(mask, vertical_mask(photo, 0.92, 1.2, invert=True))


@lru_cache(maxsize=8)
def _glass_panel(size, radius, stroke):
    panel = Image.new("RGBA", size, (255, 255, 255, 0))
    panel.putalpha(scaled(rounded_mask(size, radius), 0.14))
    ImageDraw.Draw(panel).rounded_rectangle(
        (0, 0, size[0] - 1, size[1] - 1), radius, outline=(255, 255, 255, 64),
        width=max(1, round(stroke)),
    )
    return panel


@lru_cache(maxsize=8)
def _cinema_light(size):
    return light_map(
        vignette(size, 0.7),
        keep_level(vertical_mask(size, 0.42, 1.0), 0.75),
        Image.new("L", size, round(255 * 0.58)),
    )


@lru_cache(maxsize=8)
def _cover_light(size):
    return light_map(
        keep_level(vertical_mask(size, 0.22, 0.95), 0.86),
        keep_level(vertical_mask(size, 0.0, 0.24, invert=True), 0.45),
        keep_level(fade_mask(size, 0.0, 0.8), 0.35),
    )


LAYOUTS = {
    "noir": noir,
    "spotlight": spotlight,
    "mirror": mirror,
    "tategaki": tategaki,
    "cinema": cinema,
    "glass": glass,
    "poster": poster,
    "newspaper": newspaper,
    "terminal": terminal,
    "cover": magazine_cover,
}

ALIASES = {
    "classic": "spotlight",
    "mirrored": "mirror",
    "magazine": "cover",
    "literary": "tategaki",
}
