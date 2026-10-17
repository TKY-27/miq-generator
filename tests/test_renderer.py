import random
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageChops

import miq
from miq_fonts import FONT_DIR, coverage, find_font, find_italic_font, font_at
from miq_text import EmojiImages, MixedFont, fit
from miq_words import GRAPHEME, NO_END, NO_START, units

ROOT = Path(__file__).resolve().parents[1]
AVATAR = ROOT / "demo-avatar.png"


def maker(px):
    return MixedFont(
        font_at(find_font(None), px),
        str(FONT_DIR / "NotoColorEmoji.ttf"),
        find_italic_font(),
    )


@pytest.mark.parametrize(
    "value", [(0, 360), (640, -1), (199, 120), "bad", (640,), (640.5, 360)]
)
def test_invalid_dimensions(value):
    with pytest.raises(ValueError):
        miq.resolve_size(value)


def test_words_and_graphemes():
    assert units("じゃあ8時間ホモになるか") == ["じゃあ", "8時間", "ホモに", "なるか"]
    assert units("ものづくりに集中するか。") == ["ものづくりに", "集中するか。"]
    assert units("おはようございます。") == ["おはようございます。"]
    text = "👩🏽‍💻🇯🇵1️⃣e\u0301<a:wave:123>"
    assert GRAPHEME.findall(text) == ["👩🏽‍💻", "🇯🇵", "1️⃣", "e\u0301", "<a:wave:123>"]
    assert "café" in units("今日はcaféで話す。")[1]


def test_quote_word_wrap_and_kinsoku():
    result = fit("じゃあ8時間ホモになるか", maker, 257, 205, 25, classic=True)
    assert result.lines == ["じゃあ8時間ホモに", "なるか"]
    text = "「『大切な問い』を考えよう。」次の発見につながる。" * 8
    result = fit(text, maker, 257, 205, 25, classic=True)
    assert "".join(result.lines) == text
    assert all(
        row[0] not in NO_START and row[-1] not in NO_END for row in result.lines if row
    )
    assert all(
        result.font.width(row) * result.scale <= 257 + 0.01 for row in result.lines
    )


def test_no_minimum_size_or_truncation():
    text = "全文を残して小さく表示する。" * 12000
    result = fit(text, maker, 257, 205, 25, classic=True)
    assert 0 < result.size < 1
    assert "".join(result.lines) == text
    assert result.height <= 205 + 0.01
    assert result.scale == result.size / result.font.px


def test_long_word_stays_whole():
    text = "antidisestablishmentarianism" * 4000
    result = fit(text, maker, 257, 205, 25, classic=True)
    assert result.lines == [text]
    assert 0 < result.size < 1
    assert result.font.width(text) * result.scale <= 257 + 0.01


def test_tail_of_many_explicit_lines_changes_pixels(tmp_path):
    prefix = "\n".join(f"本文{i}" for i in range(119)) + "\n"
    outputs = []
    for tail in ["末尾まで表示する", "LAST LINE IS DIFFERENT"]:
        path = tmp_path / f"{len(outputs)}.png"
        miq.render(AVATAR, prefix + tail, path, layout="classic")
        outputs.append(Image.open(path).copy())
    assert ImageChops.difference(*outputs).getbbox() is not None


def test_custom_emoji_isolation_and_fallback(tmp_path):
    paths = []
    for color in ["red", "blue"]:
        p = tmp_path / f"{color}.png"
        Image.new("RGB", (40, 20), color).save(p)
        paths.append(p)
    first = EmojiImages(custom={"123": paths[0]}).get("<:same:123>")
    second = EmojiImages(custom={123: paths[1]}).get("<:same:123>")
    assert first.getpixel((5, 5)) != second.getpixel((5, 5))
    font = MixedFont(font_at(find_font(None), 24))
    assert font.getlength("<:missing:456>") == font.font.getlength(":missing:")
    assert EmojiImages(custom={}).get("<:missing:456>") is None
    with pytest.raises(OSError):
        EmojiImages(custom={"123": tmp_path / "invalid.png"}).get("<:same:123>")


def test_emoji_cache_is_bounded():
    images = EmojiImages()
    for i in range(160):
        images.get(f"<:missing:{i}>")
    assert len(images.cache) <= 128


@pytest.mark.parametrize("layout", [name for name, _ in miq.LAYOUT_WEIGHTS])
@pytest.mark.parametrize("shape", [(120, 400), (400, 120)])
def test_layout_attachment_and_repeatability(tmp_path, layout, shape):
    source = tmp_path / "photo.png"
    Image.new("RGBA", shape, (45, 100, 180, 180)).save(source)
    outputs = []
    for i in range(2):
        output = tmp_path / f"{i}.png"
        miq.render(
            source,
            "日本語と English 👩🏽‍💻",
            output,
            "著者 Name",
            "handle",
            layout=layout,
            attachment=True,
            size=(854, 480),
        )
        with Image.open(output) as image:
            assert image.size == (854, 480)
            outputs.append(image.copy())
    assert ImageChops.difference(*outputs).getbbox() is None


def test_uniform_selection_boundaries_and_seed():
    class Fixed:
        def __init__(self, value):
            self.value = value

        def random(self):
            return self.value

    names = [name for name, _ in miq.LAYOUT_WEIGHTS]
    assert len(names) == 10
    assert len({weight for _, weight in miq.LAYOUT_WEIGHTS}) == 1
    for index, name in enumerate(names):
        assert miq.choose_layout(Fixed(index / 10)) == name
        assert miq.choose_layout(Fixed((index + 1) / 10 - 1e-9)) == name
    assert miq.choose_layout(Fixed(0.9999999)) == names[-1]
    a, b = random.Random(42), random.Random(42)
    assert [miq.choose_layout(a) for _ in range(50)] == [
        miq.choose_layout(b) for _ in range(50)
    ]
    counts = {name: 0 for name in names}
    rng = random.Random(7)
    for _ in range(20000):
        counts[miq.choose_layout(rng)] += 1
    assert all(1700 < count < 2300 for count in counts.values())


@pytest.mark.parametrize(
    ("alias", "layout"),
    [("classic", "spotlight"), ("mirrored", "mirror"), ("magazine", "cover"), ("literary", "tategaki")],
)
def test_old_layout_names_still_work(tmp_path, alias, layout):
    paths = [tmp_path / f"{name}.png" for name in (alias, layout)]
    for name, path in zip((alias, layout), paths):
        miq.render(AVATAR, "引用文", path, "氏名", layout=name, size=(480, 270))
    assert Image.open(paths[0]).tobytes() == Image.open(paths[1]).tobytes()


@pytest.mark.parametrize("layout", list(miq.LAYOUTS))
@pytest.mark.parametrize(
    "text",
    [
        "全文を残して小さく表示する。" * 40,
        "مرحبا <:picture:123> Discord 123 👩🏽‍💻",
        "改行\nのある\n\n本文 ✨",
        "x",
    ],
)
def test_every_layout_handles_hard_text(layout, text):
    import io

    out = io.BytesIO()
    miq.render(AVATAR, text, out, "とても長い表示名" * 6, "handle" * 8,
               custom_emojis={"123": AVATAR}, layout=layout)
    image = Image.open(io.BytesIO(out.getvalue()))
    assert image.size == miq.SIZE


def test_file_object_output_and_lossless_png(tmp_path):
    import io

    from miq_images import encode_png

    out = io.BytesIO()
    miq.render(AVATAR, "本文", out, layout="cinema", size=(320, 180))
    assert out.getvalue().startswith(b"\x89PNG")
    source = Image.effect_noise((257, 199), 90).convert("RGB")
    for size in [(257, 199), (1, 1), (640, 3)]:
        image = source.resize(size)
        decoded = Image.open(io.BytesIO(encode_png(image)))
        assert decoded.convert("RGB").tobytes() == image.tobytes()
    for suffix in (".jpg", ".webp"):
        miq.render(AVATAR, "本文", tmp_path / f"q{suffix}", layout="noir", size=(320, 180))
        assert Image.open(tmp_path / f"q{suffix}").size == (320, 180)


def test_vertical_columns_follow_kinsoku():
    import miq_vertical as vertical

    assert vertical.suitable("小さな発見が、明日を変える。")
    assert not vertical.suitable("The best way to predict the future")
    assert not vertical.suitable("مرحبا بالعالم")
    text = "「大切な問い」を考えよう。次の発見につながる。" * 2
    columns = vertical.columns(text, 5)
    assert "".join(c.text for col in columns for c in col) == text
    for col in columns:
        assert col[0].text not in vertical.NO_START - vertical.HANG
        assert col[-1].text not in vertical.NO_END
    layout = vertical.fit_vertical("人は、自分が思っているよりも遠くまで行ける。", 600, 400, 120)
    lengths = [len(col) for col in layout.columns]
    assert max(lengths) - min(lengths) <= 2


def test_cluster_cache_matches_freetype():
    from miq_text import run_metrics

    face = font_at(FONT_DIR / "ZenKakuGothicNew-Bold.ttf", 40)
    for text in ["全文を残して小さく表示する。", "「大切な問い」、"]:
        advance, box = run_metrics(face, text)
        assert advance == face.getlength(text)
        expected = face.getbbox(text, anchor="ls")
        assert all(abs(a - b) <= 1 for a, b in zip(box, expected))


def test_diagonal_fade_mask():
    from miq_images import fade_mask

    mask = fade_mask((200, 100), 0.4, 0.6, -0.2)
    assert mask.getpixel((5, 5)) == 255 and mask.getpixel((195, 95)) == 0
    # The edge moves left towards the bottom.
    top = next(x for x in range(200) if mask.getpixel((x, 0)) < 128)
    bottom = next(x for x in range(200) if mask.getpixel((x, 99)) < 128)
    assert bottom < top - 30


@pytest.mark.parametrize(
    "text",
    [
        "لا تتوقف عن التعلم. Discord 8:30 👩🏽‍💻",
        "Не переставай задавать вопросы.",
        "כל יום הוא הזדמנות ללמוד. Discord 8:30",
        "सीखना कभी बंद मत करो।",
        "อย่าหยุดเรียนรู้และตั้งคำถาม",
        "日本語と العربية、English を一緒に。",
    ],
)
def test_multilingual_layout_retains_text(text):
    result = fit(text, maker, 257, 205, 25, classic=True)
    assert "".join("".join(result.lines).split()) == "".join(text.split())
    assert result.height <= 205 + 0.01
    assert all(
        result.font.width(row) * result.scale <= 257 + 0.01 for row in result.lines
    )


def test_rtl_custom_emoji_and_missing_label(tmp_path):
    for custom in [{}, {"123": AVATAR}]:
        output = tmp_path / f"rtl-{len(custom)}.png"
        miq.render(
            AVATAR,
            "مرحبا <:picture:123> Discord 123",
            output,
            "ليلى",
            custom_emojis=custom,
            layout="classic",
        )
        assert Image.open(output).size == miq.SIZE


def test_cli_and_original_positional_api(tmp_path):
    output = tmp_path / "cli.png"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "miq.py"),
            "--image",
            str(AVATAR),
            "--quote",
            "引用文",
            "--layout",
            "classic",
            "--size",
            "640x360",
            "-o",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert Image.open(output).size == (640, 360)
    miq.render(
        AVATAR,
        "引用文",
        output,
        "氏名",
        "name",
        None,
        None,
        "640x360",
        None,
        None,
        None,
        "right",
        seed=1,
    )
    with pytest.raises((ValueError, OSError)):
        miq.render(tmp_path / "missing.jpg", "引用文", output, layout="classic")
    with pytest.raises(ValueError):
        miq.render(AVATAR, "", output, layout="classic")


def test_animation_first_frame_and_exif_orientation(tmp_path):
    from miq_images import read_image

    gif = tmp_path / "animation.gif"
    Image.new("RGB", (30, 20), "red").save(
        gif,
        save_all=True,
        append_images=[Image.new("RGB", (30, 20), "blue")],
        duration=100,
    )
    image = EmojiImages(custom={"123": gif}).get("<a:animated:123>")
    assert image.getpixel((5, 5))[:3] == (255, 0, 0)
    exif = Image.Exif()
    exif[274] = 6
    jpeg = tmp_path / "rotated.jpg"
    Image.new("RGB", (80, 40), "green").save(jpeg, exif=exif)
    assert read_image(jpeg).size == (40, 80)


def test_optional_fonts_and_invalid_explicit_font(tmp_path, monkeypatch):
    monkeypatch.setattr(miq, "find_emoji_font", lambda _: None)
    monkeypatch.setattr(miq, "find_italic_font", lambda *a, **k: None)
    monkeypatch.setattr(miq, "FONT_DIR", tmp_path)
    miq.render(AVATAR, "日本語の本文", tmp_path / "plain.png", layout="classic")
    from miq_fonts import find_emoji_font, find_italic_font

    for finder in (find_emoji_font, find_italic_font):
        with pytest.raises(ValueError):
            finder(str(tmp_path / "missing.ttf"))


def test_real_font_weights_and_cjk_without_kana():
    regular = font_at(FONT_DIR / "NotoSansJP.ttf", 32, 400)
    heavy = font_at(FONT_DIR / "NotoSansJP.ttf", 32, 800)
    assert bytes(regular.getmask("日本語")) != bytes(heavy.getmask("日本語"))
    text = "不要急着寻找答案，先把问题想清楚。" * 8
    result = fit(text, maker, 257, 205, 25, classic=True)
    assert len(result.lines) > 1
    assert "".join(result.lines) == text


def test_bidi_order_and_plain_digits():
    import pangocffi as pango

    font = maker(24)
    text = "مرحبا Discord 123"
    layout, _ = font.complex.layout(text)
    positions = {}
    offset = 0
    for char in text:
        rect = pango.Rectangle()
        pango.pango.pango_layout_index_to_pos(layout.pointer, offset, rect.pointer)
        positions[char] = min(rect.x, rect.x + rect.width)
        offset += len(char.encode())
    for word, reverse in [("مرحبا", True), ("Discord", False), ("123", False)]:
        points = [positions[c] for c in word]
        assert points == sorted(points, reverse=reverse)
    width, _ = font.complex.measure("8:30")
    assert abs(width - font.italic.getlength("8:30")) < 3


def test_concurrent_render_requests(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    def run(index):
        out = tmp_path / f"concurrent-{index}.png"
        miq.render(
            AVATAR,
            "مرحبا Discord <:same:123>",
            out,
            custom_emojis={"123": AVATAR},
            layout="classic",
        )
        return out.read_bytes()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, range(4)))
    assert len(set(results)) == 1


def test_caches_are_reused_but_never_shared_by_callers():
    from miq_images import edge_mask

    path = FONT_DIR / "NotoSansJP.ttf"
    assert font_at(path, 24) is font_at(path, 24)
    assert font_at(path, 24) is not font_at(path, 25)
    assert font_at(path, 24) is not font_at(path, 24, 800)

    mask = edge_mask((40, 30), 4)
    centre = (mask.width // 2, mask.height // 2)
    assert mask.getpixel(centre) > 0
    mask.putpixel(centre, 0)
    assert edge_mask((40, 30), 4).getpixel(centre) > 0

    background = miq.dark_background((320, 180))
    background.putpixel((10, 10), (255, 0, 0, 255))
    assert miq.dark_background((320, 180)).getpixel((10, 10)) != (255, 0, 0, 255)


def test_coverage_matches_the_font_cmap():
    from fontTools.ttLib import TTFont

    path = str(FONT_DIR / "NotoSansJP.ttf")
    with TTFont(path, fontNumber=0, lazy=True) as font:
        expected = frozenset(font.getBestCmap() or {})
    assert expected
    assert coverage(path) == expected


AA_DIR = ROOT / "tests" / "aa"


def test_ascii_art_detection_and_fences():
    import miq_aa

    mona = (AA_DIR / "mona.txt").read_text()
    mode, lines = miq_aa.detect(mona)
    assert mode == "sjis" and len(lines) == 6
    # Shared indentation goes, relative spacing stays.
    assert lines[0].startswith("  ") and any(not line.startswith(" ") for line in lines)
    assert "\\" not in "".join(lines) and "∖" in "".join(lines)
    tux = (AA_DIR / "tux.txt").read_text()
    assert miq_aa.detect(tux)[0] == "mono"
    fenced = miq_aa.detect("```txt\n a  b\nc\n```")
    assert fenced == ("mono", [" a  b", "c"])
    for prose in ["小さな発見が、明日を変える。", "一行目\n二行目の普通の文章です", "LGTM 🚀"]:
        assert miq_aa.detect(prose) is None


def test_sjis_art_keeps_ms_pgothic_widths():
    """Saitamaar advances at 16px are whole pixels and add up per line, so every
    column of the art lands exactly where MS PGothic put it."""

    import miq_aa

    path = str(FONT_DIR / "Saitamaar-Regular.ttf")
    _, lines = miq_aa.detect((AA_DIR / "mona.txt").read_text())
    for px in (16, 32, 48):
        face = font_at(path, px)
        for line in lines:
            whole = face.getlength(line)
            assert whole == int(whole)
            assert whole == sum(face.getlength(c) for c in line)


@pytest.mark.parametrize("name", ["mona.txt", "tux.txt", "dragon.txt"])
@pytest.mark.parametrize("layout", list(miq.LAYOUTS))
def test_ascii_art_renders_unwrapped_in_every_layout(tmp_path, name, layout):
    import miq_aa

    text = (AA_DIR / name).read_text()
    out = tmp_path / "aa.png"
    miq.render(AVATAR, text, out, "名前", "handle", layout=layout)
    assert Image.open(out).size == miq.SIZE
    mode, lines = miq_aa.detect(text)
    canvas = Image.new("RGB", (900, 600))
    from miq_fonts import bundled_fonts

    box = miq_aa.draw(canvas, lines, mode, bundled_fonts(), (0, 0, 900, 600), (255, 255, 255), 64)
    ink = canvas.getbbox()
    # One block, never reflowed: its height follows the line count.
    assert ink and ink[3] - ink[1] <= box[3] - box[1] + 1


@pytest.mark.parametrize("text", ["草", "無理", "👍", "神!"])
def test_one_or_two_characters_get_the_hero_treatment(text):
    from miq_layouts import Ctx
    from miq_text import EmojiImages

    ctx = Ctx(Image.new("RGB", (64, 64)), text, "", "", miq.SIZE, EmojiImages(None))
    assert (ctx.hero is not None) == (text != "神!")
    for layout in miq.LAYOUTS:
        miq.render(AVATAR, text, __import__("io").BytesIO(), "名前", layout=layout)


def test_short_phrases_use_few_long_columns():
    import miq_vertical as vertical

    layout = vertical.fit_vertical("今日も一日がんばるぞい", 1300, 860, 250)
    assert len(layout.columns) == 2
