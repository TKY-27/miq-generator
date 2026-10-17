"""Word and grapheme boundaries shared by measurement and rendering."""

from functools import lru_cache
from itertools import pairwise

import emoji
import regex

CUSTOM = regex.compile(r"<a?:([A-Za-z0-9_]+):([0-9]+)>")
GRAPHEME = regex.compile(r"<a?:[A-Za-z0-9_]+:[0-9]+>|\X")
LATIN = regex.compile(r"[\p{Latin}\p{N}][\p{Latin}\p{M}\p{N}._/@:#’\x27+\-]*")
JAPANESE = regex.compile(r"[\p{Han}\p{Hiragana}\p{Katakana}ー]+")
KANA = regex.compile(r"[\p{Hiragana}\p{Katakana}]")
EDITORIAL_LATIN = regex.compile(r"[\p{Latin}\p{N}\p{M}\x20-\x7e]+")
NO_START = set(
    "、。，．：；？！゛゜ヽヾゝゞ々ー）］｝〕〉》」』】〙〗〟’”｠»・ぁぃぅぇぉっゃゅょァィゥェォッャュョ"
)
NO_END = set("（［｛〔〈《「『【〘〖〝‘“｟«")


@lru_cache(maxsize=1)
def tokenizer():
    from janome.tokenizer import Tokenizer

    return Tokenizer()


@lru_cache(maxsize=4096)
def is_emoji(text):
    # Text presentation selectors explicitly request an ordinary glyph.
    return not text.endswith("\ufe0e") and emoji.is_emoji(text)


def units(text):
    """Keep words, suffixes, punctuation and extended graphemes together."""
    if not text:
        return []
    boundaries = {0, len(text)}
    japanese = bool(KANA.search(text))
    # Only Japanese spans go through the Japanese dictionary.
    for span in JAPANESE.finditer(text):
        boundaries.update((span.start(), span.end()))
        if not japanese:
            boundaries.update(
                span.start() + m.start() for m in GRAPHEME.finditer(span.group())
            )
            continue
        offset = span.start()
        previous = None
        for token in tokenizer().tokenize(span.group()):
            pos = token.part_of_speech.split(",")
            attached = pos[0] in ("助詞", "助動詞") or pos[1] in ("接尾", "非自立")
            attached |= bool(
                previous and previous[1] == "サ変接続" and token.base_form == "する"
            )
            if not attached:
                boundaries.add(offset)
            offset += len(token.surface)
            previous = pos
    for match in regex.finditer(r"[^\S\n\u00a0\u202f]+", text):
        boundaries.add(match.end())
    legal = {len(text)}
    for match in GRAPHEME.finditer(text):
        legal.add(match.start())
        if is_emoji(match.group()) or CUSTOM.fullmatch(match.group()):
            boundaries.update((match.start(), match.end()))
    words = iter(LATIN.finditer(text))
    word = next(words, None)
    filtered = set()
    for boundary in sorted(boundaries):
        while word is not None and word.end() <= boundary:
            word = next(words, None)
        if word is None or not word.start() < boundary < word.end():
            filtered.add(boundary)
    boundaries = filtered
    accepted = [0]
    for i in sorted(boundaries & legal):
        if i == 0 or i == len(text):
            continue
        if text[i] in NO_START or text[i - 1] in NO_END:
            continue
        # Attach Japanese particles after a Latin word or a number.
        if regex.match(r"[\p{Latin}\p{N}]", text[i - 1]) and regex.match(
            r"\p{Hiragana}", text[i]
        ):
            continue
        if regex.match(r"\p{N}", text[i - 1]) and regex.match(r"\p{Han}", text[i]):
            continue
        if japanese and any(
            regex.fullmatch(s, text[i - 1] + text[i])
            for s in (r"[\p{Katakana}ー]{2}", r"\p{Han}{2}")
        ):
            continue
        accepted.append(i)
    accepted.append(len(text))
    return [text[a:b] for a, b in pairwise(accepted)]


def runs(text, editorial=False):
    """Keep classic Latin styling; never split a grapheme or custom emoji.

    Measurement asks for the same rows many times, so results are memoised.
    """
    if len(text) > 512:
        return tuple(_runs(text, editorial))
    return _cached_runs(text, editorial)


@lru_cache(maxsize=8192)
def _cached_runs(text, editorial):
    return tuple(_runs(text, editorial))


def _runs(text, editorial=False):
    plain = []

    def flush():
        chunk = "".join(plain)
        pattern = EDITORIAL_LATIN if editorial else LATIN
        start = 0
        for match in pattern.finditer(chunk):
            if match.start() > start:
                yield chunk[start : match.start()], "text"
            yield match.group(), "latin"
            start = match.end()
        if start < len(chunk):
            yield chunk[start:], "text"

    for match in GRAPHEME.finditer(text):
        cluster = match.group()
        if is_emoji(cluster) or CUSTOM.fullmatch(cluster):
            yield from flush()
            plain.clear()
            yield cluster, "emoji"
        else:
            plain.append(cluster)
    yield from flush()


def chunks(text, limit=64):
    """Bound temporary rasters; use word boundaries when possible."""
    batch = []
    for match in GRAPHEME.finditer(text):
        batch.append(match.group())
        if len(batch) >= limit or (
            len(batch) >= limit // 2 and match.group().isspace()
        ):
            yield "".join(batch)
            batch.clear()
    if batch:
        yield "".join(batch)
