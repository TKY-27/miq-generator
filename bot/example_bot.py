#!/usr/bin/env python3
"""Discord bot for miq-generator (discord.py 2.x).

    pip install -r requirements.txt -r bot/requirements.txt
    DISCORD_TOKEN=... python bot/example_bot.py

Reply to a message with:
- ``miq`` — quote it; ``miqmiq`` / ``miqmiqmiq`` … also take that person's
  previous messages (others in between are skipped) as one quote.
- ``miq12`` — layout number 12 (``miq台帳`` posts the numbered list).
- ``miq 縦`` / ``miq 正方形`` / ``miq cute`` … — ratio and style.
- ``miq vs`` / ``miq love`` / ``miq talk`` — the target and the person it
  replies to, each with their run of consecutive messages.
- ``miq help`` — usage.

Pictures, stickers and GIF links in the messages are drawn (animated ones as
their first frame). Downloads run concurrently and are cached; rendering runs
in a warmed process pool so the event loop is never blocked.
"""

from __future__ import annotations

import asyncio
import io
import logging
import multiprocessing as mp
import os
import random
import re
import sys
import time
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import aiohttp
import discord
from discord import app_commands

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import miq  # noqa: E402
from bot import gather, jobs  # noqa: E402
from bot.commands import USAGE, Command, parse  # noqa: E402
from miq_layouts import by_number  # noqa: E402
from miq_words import CUSTOM  # noqa: E402

log = logging.getLogger("miq")
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
CATEGORIES = {
    "all": "すべて",
    "cool": "カッコいい",
    "cute": "かわいい",
    "classic": "定番",
}
NEXT_ORIENTATION = {
    "landscape": "portrait",
    "portrait": "square",
    "square": "landscape",
}
COOLDOWN = float(os.getenv("MIQ_COOLDOWN", "5"))
MAX_DOWNLOAD = 12 * 1024 * 1024
URL = re.compile(r"https?://\S+")


class Downloads:
    """Bytes by URL. Avatar and emoji URLs carry a content hash, so reuse is safe."""

    def __init__(self, limit=48 * 1024 * 1024):
        self.items: OrderedDict[str, bytes] = OrderedDict()
        self.limit = limit
        self.size = 0
        self.session: aiohttp.ClientSession | None = None

    async def get(self, url: str, read=None) -> bytes | None:
        if url in self.items:
            self.items.move_to_end(url)
            return self.items[url]
        try:
            data = await read() if read else await self._fetch(url)
        except (
            discord.HTTPException,
            aiohttp.ClientError,
            asyncio.TimeoutError,
            ValueError,
        ):
            log.warning("download failed: %s", url)
            return None
        if data and len(data) <= MAX_DOWNLOAD:
            self.items[url] = data
            self.size += len(data)
            while self.size > self.limit and self.items:
                _, old = self.items.popitem(last=False)
                self.size -= len(old)
        return data

    async def _fetch(self, url):
        if self.session is None:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
        async with self.session.get(url) as response:
            response.raise_for_status()
            if (response.content_length or 0) > MAX_DOWNLOAD:
                raise ValueError("too large")
            return await response.read()


def avatar_asset(user: discord.abc.User):
    return user.display_avatar.replace(size=512, static_format="png")


async def media_of(message: discord.Message, downloads: Downloads):
    """``[(bytes, spoiler)]`` for attachments, stickers and image/GIF embeds."""

    pending = []
    for a in message.attachments:
        if (a.content_type or "").split(";")[0] in IMAGE_TYPES:
            pending.append((downloads.get(a.url, a.read), a.is_spoiler()))
    for sticker in message.stickers:
        if sticker.format is not discord.StickerFormatType.lottie:
            pending.append((downloads.get(sticker.url, sticker.read), False))
    for embed in message.embeds:
        if embed.type in ("gifv", "image"):
            url = (embed.thumbnail and embed.thumbnail.url) or (
                embed.image and embed.image.url
            )
            if url:
                pending.append((downloads.get(url), False))
    results = await asyncio.gather(*(job for job, _ in pending))
    return [(data, hidden) for data, (_, hidden) in zip(results, pending) if data]


def text_of(message: discord.Message) -> str:
    """The content, minus links that Discord already shows as a picture/GIF."""

    text = message.content
    shown = {e.url for e in message.embeds if e.type in ("gifv", "image") and e.url}
    if shown:
        text = URL.sub(lambda m: "" if m.group() in shown else m.group(), text)
    if not text.strip() and message.stickers:
        text = message.stickers[0].name
    return text.strip()


async def emojis_of(messages, downloads: Downloads):
    found = {}
    for message in messages:
        for match in CUSTOM.finditer(message.content):
            found[match[2]] = (match[1], match[0].startswith("<a:"), message)

    async def one(emoji_id, name, animated, message):
        emoji = discord.PartialEmoji.with_state(
            message._state, name=name, id=int(emoji_id), animated=animated
        )
        return emoji_id, await downloads.get(emoji.url, emoji.read)

    pairs = await asyncio.gather(*(one(i, *rest) for i, rest in found.items()))
    return {emoji_id: data for emoji_id, data in pairs if data}


def mentions_of(messages):
    names = {}
    for message in messages:
        names.update({str(m.id): m.display_name for m in message.mentions})
        names.update({str(r.id): r.name for r in message.role_mentions})
        names.update({str(c.id): c.name for c in message.channel_mentions})
    return names


async def part_of(messages, downloads: Downloads) -> jobs.Part:
    """Merge one person's messages (oldest first) into one quote part."""

    author = messages[-1].author
    asset = avatar_asset(author)
    avatar, *media = await asyncio.gather(
        downloads.get(asset.url, asset.read),
        *(media_of(m, downloads) for m in messages),
    )
    text = "\n".join(t for t in (text_of(m) for m in messages) if t)
    return jobs.Part(
        avatar or b"",
        text,
        author.display_name,
        author.name,
        [item for group in media for item in group],
        messages[-1].created_at.astimezone(),
    )


async def build(groups, command: Command, downloads: Downloads) -> jobs.Request:
    everything = [m for group in groups for m in group]
    parts, emojis = await asyncio.gather(
        asyncio.gather(*(part_of(group, downloads) for group in groups)),
        emojis_of(everything, downloads),
    )
    return jobs.Request(
        list(parts),
        mood=command.mood,
        layout=command.layout,
        orientation=command.orientation,
        category=command.category,
        seed=random.getrandbits(32),
        emojis=emojis,
        mentions=mentions_of(everything),
    )


async def replied_to(message: discord.Message):
    ref = message.reference
    if ref is None or ref.message_id is None or ref.channel_id != message.channel.id:
        return None
    if isinstance(ref.resolved, discord.Message):
        return ref.resolved
    try:
        return await message.channel.fetch_message(ref.message_id)
    except discord.HTTPException:
        return None


class QuoteBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.workers = max(1, (os.cpu_count() or 2) - 1)
        # Fresh interpreters (not fork) so workers never inherit the event loop.
        method = "forkserver" if "forkserver" in mp.get_all_start_methods() else "spawn"
        self.pool = ProcessPoolExecutor(
            max_workers=self.workers,
            initializer=miq.warmup,
            mp_context=mp.get_context(method),
        )
        self.downloads = Downloads()
        self.recent: dict[int, float] = {}
        self.catalog: asyncio.Future | None = None

    async def setup_hook(self):
        self.tree.add_command(
            app_commands.ContextMenu(name="Make it a Quote", callback=quote_menu)
        )
        await self.tree.sync()
        loop = asyncio.get_running_loop()
        # Start and warm every worker now, not on the first users' requests.
        start = time.perf_counter()
        await asyncio.gather(
            *(loop.run_in_executor(self.pool, jobs.ready) for _ in range(self.workers))
        )
        log.info(
            "render pool ready: %d workers in %.0fms",
            self.workers,
            (time.perf_counter() - start) * 1000,
        )
        self.catalog = loop.run_in_executor(self.pool, jobs.catalog)

    async def close(self):
        if self.downloads.session:
            await self.downloads.session.close()
        self.pool.shutdown(cancel_futures=True)
        await super().close()

    async def render(self, request: jobs.Request):
        start = time.perf_counter()
        png, caption = await asyncio.get_running_loop().run_in_executor(
            self.pool, jobs.render, request
        )
        log.info("render %.0fms (%s)", (time.perf_counter() - start) * 1000, caption)
        return discord.File(io.BytesIO(png), "quote.png"), f"-# {caption}"

    def cooling(self, user_id: int) -> bool:
        now = time.monotonic()
        if now - self.recent.get(user_id, -COOLDOWN) < COOLDOWN:
            return True
        self.recent[user_id] = now
        if len(self.recent) > 4096:
            self.recent = {k: v for k, v in self.recent.items() if now - v < COOLDOWN}
        return False

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        command = parse(message.content)
        if command is None:
            return
        if command.kind == "help":
            await message.reply(USAGE, mention_author=False)
            return
        if command.kind == "catalog":
            async with message.channel.typing():
                try:
                    pages = await asyncio.shield(self.catalog)
                except Exception:
                    log.exception("catalog failed")
                    self.catalog = asyncio.get_running_loop().run_in_executor(
                        self.pool, jobs.catalog
                    )
                    await message.reply(
                        "台帳を作れませんでした。少し待ってもう一度どうぞ。",
                        mention_author=False,
                    )
                    return
            files = [discord.File(io.BytesIO(png), name) for name, png in pages]
            await message.reply(files=files, mention_author=False)
            return
        target = await replied_to(message)
        if target is None:
            return
        if command.unknown:
            await message.reply(
                f"`{' '.join(command.unknown)}` はわかりませんでした。\n{USAGE}",
                mention_author=False,
            )
            return
        if command.layout is not None and by_number(command.layout) is None:
            last = max(spec.number for spec in miq.REGISTRY.values())
            await message.reply(
                f"構図 {command.layout} 番はありません（1〜{last}、`miq台帳` で一覧）。",
                mention_author=False,
            )
            return
        if self.cooling(message.author.id):
            await message.add_reaction("⏳")
            return
        async with message.channel.typing():
            start = time.perf_counter()

            def history(m):
                return message.channel.history(limit=gather.SCAN_LIMIT, before=m)

            if command.mood:
                groups = await gather.conversation(target, history, replied_to)
                if groups is None:
                    command = replace(command, mood=None)
            if not command.mood:
                groups = [await gather.same_author(target, command.count, history)]
            request = await build(groups, command, self.downloads)
            fetched = time.perf_counter()
            file, caption = await self.render(request)
        sent = time.perf_counter()
        await message.reply(
            caption, file=file, view=Controls(self, request), mention_author=False
        )
        log.info(
            "miq fetch=%.0fms render=%.0fms upload=%.0fms",
            (fetched - start) * 1000,
            (sent - fetched) * 1000,
            (time.perf_counter() - sent) * 1000,
        )


class Controls(discord.ui.View):
    """🎲 redraw, 📐 ratio and a style menu; all edit the same message."""

    def __init__(self, bot: QuoteBot, request: jobs.Request):
        super().__init__(timeout=900)
        self.bot = bot
        self.request = request
        if request.mood:
            self.remove_item(self.category)

    async def redraw(self, interaction: discord.Interaction, request: jobs.Request):
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
            interaction,
            replace(self.request, layout=None, seed=random.getrandbits(32)),
        )

    @discord.ui.button(emoji="📐", label="縦横", style=discord.ButtonStyle.secondary)
    async def ratio(self, interaction: discord.Interaction, _button):
        current = self.request.orientation or "landscape"
        following = NEXT_ORIENTATION[current]
        if self.request.mood and following == "square":
            following = "landscape"
        await self.redraw(
            interaction,
            replace(
                self.request,
                orientation=following,
                layout=None,
                seed=random.getrandbits(32),
            ),
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
                layout=None,
                seed=random.getrandbits(32),
            ),
        )


async def quote_menu(interaction: discord.Interaction, message: discord.Message):
    await interaction.response.defer(thinking=True)
    bot: QuoteBot = interaction.client
    request = await build([[message]], Command("quote"), bot.downloads)
    file, caption = await bot.render(request)
    await interaction.followup.send(caption, file=file, view=Controls(bot, request))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    QuoteBot().run(os.environ["DISCORD_TOKEN"], log_handler=None)
