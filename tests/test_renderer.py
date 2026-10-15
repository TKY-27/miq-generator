import random
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageChops

import miq
from miq_fonts import FONT_DIR, find_font, find_italic_font, font_at
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


def test_weighted_selection_boundaries_and_seed():
    class Fixed:
        def __init__(self, value):
            self.value = value

        def random(self):
            return self.value

    for value, expected in [
        (0, "classic"),
        (0.49999, "classic"),
        (0.5, "mirrored"),
        (0.79999, "mirrored"),
        (0.8, "magazine"),
        (0.94999, "magazine"),
        (0.95, "literary"),
        (0.9999, "literary"),
    ]:
        assert miq.choose_layout(Fixed(value)) == expected
    a, b = random.Random(42), random.Random(42)
    assert [miq.choose_layout(a) for _ in range(50)] == [
        miq.choose_layout(b) for _ in range(50)
    ]


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
        assert Image.open(output).size == (640, 360)


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
