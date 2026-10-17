"""Font discovery, glyph coverage and real font weights."""

import hashlib
import os
import shutil
import subprocess
from array import array
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import ImageFont

FONT_DIR = Path(__file__).resolve().parent / "fonts"


@lru_cache(maxsize=384)
def _font(path: str, px: int, weight):
    """Reuse FreeType handles: the binary search asks for the same sizes again."""

    font = ImageFont.truetype(path, px)
    if weight is not None:
        try:
            axes = font.get_variation_axes()
        except OSError:
            axes = []
        if axes:
            font.set_variation_by_axes(
                [
                    max(a["minimum"], min(a["maximum"], weight))
                    if a["name"] == b"Weight"
                    else a["default"]
                    for a in axes
                ]
            )
    return font


def font_at(path, px, weight=None):
    return _font(str(path), max(1, round(px)), weight)


@lru_cache(maxsize=32)
def coverage(path):
    """Codepoints the face can draw.

    Parsing a CJK cmap takes tens of milliseconds, so the result is also kept on
    disk (keyed by path, size and mtime) for short-lived CLI processes.
    """

    stat = os.stat(path)
    key = hashlib.blake2s(
        f"{os.path.abspath(path)}\0{stat.st_size}\0{stat.st_mtime_ns}".encode(),
        digest_size=10,
    ).hexdigest()
    cached = FONT_DIR / ".cache" / f"{key}.cmap"
    try:
        return frozenset(array("I", cached.read_bytes()))
    except (OSError, ValueError):
        pass
    result = _parse_coverage(path)
    try:
        cached.parent.mkdir(exist_ok=True)
        temporary = cached.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_bytes(array("I", sorted(result)).tobytes())
        temporary.replace(cached)
    except OSError:
        pass  # A read-only install still works, just without the disk cache.
    return result


def _parse_coverage(path):
    # Synthesised glyph names keep cmap parsing cheap.
    with TTFont(str(path), fontNumber=0, lazy=True) as font:
        try:
            count = font["maxp"].numGlyphs
        except (KeyError, AttributeError):
            return frozenset(font.getBestCmap() or {})
        font.setGlyphOrder(["glyph%.5d" % index for index in range(count)])
        return frozenset(font.getBestCmap() or {})


# Roles used by the layouts; files are fetched by scripts/setup_fonts.py.
FONT_FILES = {
    "mincho": "ShipporiMinchoB1-ExtraBold.ttf",
    "gothic": "ZenKakuGothicNew-Bold.ttf",
    "gothic-medium": "ZenKakuGothicNew-Medium.ttf",
    "display": "DelaGothicOne-Regular.ttf",
    "mono-jp": "MPLUS1Code.ttf",
    "mono": "JetBrainsMono.ttf",
    "sans": "Inter.ttf",
    "italic": "CormorantGaramond-Italic.ttf",
    "serif": "InstrumentSerif-Regular.ttf",
    "serif-italic": "InstrumentSerif-Italic.ttf",
    "condensed": "Anton-Regular.ttf",
    "brush": "YujiSyuku-Regular.ttf",
    "blackletter": "UnifrakturMaguntia-Book.ttf",
    "aa": "Saitamaar-Regular.ttf",
    "fallback": "NotoSansJP.ttf",
}


@lru_cache(maxsize=1)
def bundled_fonts():
    """Check every bundled face once per process and return role -> path."""

    paths = {role: FONT_DIR / name for role, name in FONT_FILES.items()}
    missing = sorted({p.name for p in paths.values() if not p.is_file()})
    if missing:
        raise ValueError(
            "標準フォントがありません: "
            + ", ".join(missing)
            + "。python scripts/setup_fonts.py を実行してください。"
        )
    return {role: str(path) for role, path in paths.items()}


EMOJI_FONT_CHOICES = [
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/noto/NotoColorEmoji.ttf",
    "/System/Library/Fonts/Apple Color Emoji.ttc",
    "C:/Windows/Fonts/seguiemj.ttf",
]

ITALIC_FONT_CHOICES = [
    "/usr/share/fonts/truetype/noto/NotoSans-Italic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/ariali.ttf",
]

BOLD_ITALIC_FONT_CHOICES = [
    "/usr/share/fonts/truetype/noto/NotoSans-BoldItalic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arialbi.ttf",
]

FONT_CHOICES = [
    # Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansJP-Regular.ttf",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/truetype/ipafont-gothic/ipag.ttf",
    # macOS
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc",
    # Windows
    "C:/Windows/Fonts/YuGothM.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
]


def find_font(custom: str | None, bold: bool = False) -> str:
    if custom:
        if not Path(custom).is_file():
            raise ValueError(f"指定されたフォントが見つかりません: {custom}")
        return custom

    from_env = os.getenv("MIQ_FONT")
    if from_env:
        return find_font(from_env, bold)

    return _system_font(bold)


@lru_cache(maxsize=8)
def _system_font(bold: bool = False) -> str:
    """Path probes and ``fc-match`` are process-wide; run them once per process."""

    candidates = []
    for name in FONT_CHOICES:
        if bold:
            name = (
                name.replace("Regular", "Bold")
                .replace("W3", "W6")
                .replace("YuGothM", "YuGothB")
            )
        candidates.append(name)
    candidates.extend(FONT_CHOICES)
    for name in candidates:
        if Path(name).is_file():
            return name

    if shutil.which("fc-match"):
        try:
            p = subprocess.run(
                ["fc-match", "-f", "%{file}", ":lang=ja"],
                capture_output=True,
                text=True,
                timeout=3,
                check=True,
            )
            path = p.stdout.strip()
            if (
                path
                and Path(path).is_file()
                and set(map(ord, "日本語")) <= coverage(path)
            ):
                return path
        except (OSError, subprocess.SubprocessError):
            pass
    raise ValueError(
        "日本語フォントが見つかりません。--font /path/to/font.ttf を指定してください。"
    )


def find_emoji_font(custom: str | None = None) -> str | None:
    """色つき絵文字フォントを探す（無ければ None）。"""

    if custom:
        if not Path(custom).is_file():
            raise ValueError(f"指定された絵文字フォントが見つかりません: {custom}")
        return custom

    from_env = os.getenv("MIQ_EMOJI_FONT")

    if from_env:
        return find_emoji_font(from_env)

    for name in EMOJI_FONT_CHOICES:
        if Path(name).is_file():
            return name

    return None


def find_italic_font(custom: str | None = None, *, bold: bool = False) -> str | None:
    """欧文の斜体フォントを探す（無ければ None）。"""

    if custom:
        if not Path(custom).is_file():
            raise ValueError(f"指定された欧文フォントが見つかりません: {custom}")
        return custom

    from_env = os.getenv("MIQ_ITALIC_FONT")

    if from_env:
        return find_italic_font(from_env, bold=bold)

    for name in BOLD_ITALIC_FONT_CHOICES if bold else ITALIC_FONT_CHOICES:
        if Path(name).is_file():
            return name

    return None
