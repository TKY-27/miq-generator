#!/usr/bin/env python3
"""Reference Discord bot for miq-generator (discord.py 2.x).

    pip install -r requirements.txt -r bot/requirements.txt
    DISCORD_TOKEN=... python bot/example_bot.py

Features
- Message context menu "Make it a Quote" and replying ``miq`` to a message.
- 🎲 button to redraw another layout, and a menu to narrow the style
  (cool / cute / classic).
- Avatar, custom emoji and image attachments are downloaded in memory;
  mentions are shown as names. Rendering runs in a process pool so the event
  loop and other requests are never blocked.

It is intentionally small: copy what you need into an existing bot.
"""

from __future__ import annotations

import asyncio
import io
import os
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path

import discord
from discord import app_commands

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import miq  # noqa: E402
from miq_fonts import FAMILIES  # noqa: E402
from miq_words import CUSTOM  # noqa: E402

SIZE = os.getenv("MIQ_SIZE", "640x360")
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
CATEGORIES = {
    "all": "すべて",
    "cool": "カッコいい",
    "cute": "かわいい",
    "classic": "定番",
}


@dataclass
class Request:
    image: bytes
    text: str
    name: str
    handle: str
    attachment: bool
    emojis: dict = field(default_factory=dict)
    mentions: dict = field(default_factory=dict)
    category: str | None = None
    seed: int = 0


async def collect(message: discord.Message) -> Request:
    """Everything the renderer needs, fetched once and kept in memory."""

    picture = next(
        (
            a
            for a in message.attachments
            if (a.content_type or "").split(";")[0] in IMAGE_TYPES
        ),
        None,
    )
    if picture is not None:
        image, attachment = await picture.read(), True
    else:
        avatar = message.author.display_avatar.replace(size=512, static_format="png")
        image, attachment = await avatar.read(), False
    emojis = {}
    for match in CUSTOM.finditer(message.content):
        partial_emoji = discord.PartialEmoji.with_state(
            message._state,  # gives PartialEmoji.read() the bot's HTTP session
            name=match[1],
            id=int(match[2]),
            animated=match[0].startswith("<a:"),
        )
        try:
            emojis[match[2]] = await partial_emoji.read()
        except discord.HTTPException:
            pass  # rendered as :name:
    mentions = {str(m.id): m.display_name for m in message.mentions}
    mentions.update({str(r.id): r.name for r in message.role_mentions})
    mentions.update({str(c.id): c.name for c in message.channel_mentions})
    text = message.content or ("（画像）" if picture else "")
    return Request(
        image,
        text,
        message.author.display_name,
        message.author.name,
        attachment,
        emojis,
        mentions,
        seed=random.getrandbits(32),
    )


class QuoteBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.pool = ProcessPoolExecutor(
            max_workers=max(1, (os.cpu_count() or 2) - 1), initializer=miq.warmup
        )

    async def setup_hook(self):
        self.tree.add_command(
            app_commands.ContextMenu(name="Make it a Quote", callback=quote_menu)
        )
        await self.tree.sync()

    async def render(self, request: Request):
        job = partial(
            miq.render_bytes,
            request.image,
            request.text,
            request.name,
            request.handle,
            size=SIZE,
            seed=request.seed,
            category=request.category,
            attachment=request.attachment,
            custom_emojis=request.emojis,
            mentions=request.mentions,
        )
        png, layout, face = await asyncio.get_running_loop().run_in_executor(
            self.pool, job
        )
        caption = f"-# {miq.REGISTRY[layout].label} · {FAMILIES[face].label}"
        return discord.File(io.BytesIO(png), "quote.png"), caption

    async def on_message(self, message: discord.Message):
        if message.author.bot or message.content.strip().lower() != "miq":
            return
        if message.reference is None or message.reference.message_id is None:
            return
        target = message.reference.resolved
        if not isinstance(target, discord.Message):
            target = await message.channel.fetch_message(message.reference.message_id)
        async with message.channel.typing():
            request = await collect(target)
            file, caption = await self.render(request)
        await message.reply(
            caption, file=file, view=Controls(self, request), mention_author=False
        )


class Controls(discord.ui.View):
    """🎲 redraw and a style menu; both edit the same message."""

    def __init__(self, bot: QuoteBot, request: Request):
        super().__init__(timeout=900)
        self.bot = bot
        self.request = request

    async def redraw(self, interaction: discord.Interaction, request: Request):
        self.request = request
        await interaction.response.defer()
        file, caption = await self.bot.render(request)
        await interaction.edit_original_response(
            content=caption, attachments=[file], view=self
        )

    @discord.ui.button(
        emoji="🎲", label="別の構図", style=discord.ButtonStyle.secondary
    )
    async def reroll(self, interaction: discord.Interaction, _button):
        await self.redraw(
            interaction, replace(self.request, seed=random.getrandbits(32))
        )

    @discord.ui.select(
        placeholder="系統をしぼる",
        options=[
            discord.SelectOption(label=label, value=key)
            for key, label in CATEGORIES.items()
        ],
    )
    async def category(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ):
        choice = select.values[0]
        await self.redraw(
            interaction,
            replace(
                self.request,
                category=None if choice == "all" else choice,
                seed=random.getrandbits(32),
            ),
        )


async def quote_menu(interaction: discord.Interaction, message: discord.Message):
    await interaction.response.defer(thinking=True)
    bot: QuoteBot = interaction.client
    request = await collect(message)
    file, caption = await bot.render(request)
    await interaction.followup.send(caption, file=file, view=Controls(bot, request))


if __name__ == "__main__":
    QuoteBot().run(os.environ["DISCORD_TOKEN"])
