"""Work done in the render processes: plain data in, PNG bytes out.

Everything here is picklable and imports no Discord code, so the process pool
can run it under any start method.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime

from PIL import Image

import miq
from miq_fonts import FAMILIES
from miq_images import collage, spoiler


@dataclass
class Part:
    """One person's contribution: their messages merged into one."""

    avatar: bytes
    text: str
    name: str
    handle: str
    # (image bytes, is_spoiler) for attachments, stickers and GIF previews.
    media: list = field(default_factory=list)
    date: datetime | None = None


@dataclass
class Request:
    parts: list
    mood: str | None = None
    layout: object = None
    orientation: str | None = None
    category: str | None = None
    seed: int = 0
    emojis: dict = field(default_factory=dict)
    mentions: dict = field(default_factory=dict)


def picture(part):
    """``(image, attachment)``: the media (as one collage) or else the avatar."""

    pictures = []
    for data, hidden in part.media:
        try:
            with Image.open(io.BytesIO(data)) as opened:
                if getattr(opened, "is_animated", False):
                    opened.seek(0)  # GIF / APNG / animated WebP: first frame
                image = opened.convert("RGBA")
        except (OSError, ValueError):
            continue
        pictures.append(spoiler(image) if hidden else image)
    if pictures:
        return collage(pictures), True
    return part.avatar, False


def text_of(part):
    """The quote text; a picture-only message still needs something to show."""

    if part.text.strip():
        return part.text
    return "（画像）" if part.media else "…"


def render(request: Request):
    """``(png, caption)`` for a quote or a two-person exchange."""

    if request.mood:
        from miq_dialogue import Speaker, render_dialogue_bytes

        speakers = []
        for part in request.parts:
            image, attachment = picture(part)
            speakers.append(
                Speaker(
                    image,
                    text_of(part),
                    part.name,
                    part.handle,
                    attachment,
                    date=part.date,
                )
            )
        png, mood, face = render_dialogue_bytes(
            *speakers,
            request.mood,
            orientation=request.orientation,
            seed=request.seed,
            custom_emojis=request.emojis,
            mentions=request.mentions,
        )
        from miq_dialogue import MOODS

        return png, f"{MOODS[mood][0]} · {FAMILIES[face].label}"
    (part,) = request.parts
    image, attachment = picture(part)
    png, layout, face = miq.render_bytes(
        image,
        text_of(part),
        part.name,
        part.handle,
        layout=request.layout or "auto",
        orientation=request.orientation,
        category=request.category,
        seed=request.seed,
        attachment=attachment,
        custom_emojis=request.emojis,
        mentions=request.mentions,
        date=part.date,
    )
    spec = miq.REGISTRY[layout]
    return png, f"#{spec.number} {spec.label} · {FAMILIES[face].label}"


def catalog():
    from miq_catalog import pages

    return pages()


def ready():
    """A no-op job: submitting a few starts (and warms) every worker."""

    return True
