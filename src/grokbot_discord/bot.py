from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from typing import Any

import aiohttp
import discord

from grokbot_discord.batching import ChannelBatcher
from grokbot_discord.callback import build_app, start_site
from grokbot_discord.config import ConfigError, Settings, load_settings
from grokbot_discord.filters import Dedupe, should_drop
from grokbot_discord.history import HISTORY_LIMIT, cap_history, history_entry
from grokbot_discord.models import BotSpec, IncomingMessage, WakePayload
from grokbot_discord.routing import addressed_by_name, mapped_role_ids, route
from grokbot_discord.split import split_message
from grokbot_discord.webhook import DryRunResult, ping

log = logging.getLogger("grokbot_discord")
PENDING_TTL_S = 15 * 60  # local hardening: expire unanswered wakes
DEBOUNCE_S = 3.0  # wait this long after the owner's last message before waking
TYPING_EVERY_S = 8.0  # Discord typing indicator lasts ~10s
TICK_S = 0.5


def _incoming(message: discord.Message) -> IncomingMessage:
    guild_id = str(message.guild.id) if message.guild else ""
    return IncomingMessage(
        message_id=str(message.id),
        channel_id=str(message.channel.id),
        guild_id=guild_id,
        author_id=str(message.author.id),
        author_name=str(getattr(message.author, "display_name", message.author.name)),
        content=message.content or "",
        mention_user_ids=frozenset(str(u.id) for u in message.mentions),
        mention_role_ids=frozenset(str(r.id) for r in message.role_mentions),
        author_is_bot=bool(message.author.bot),
    )


def combine_texts(texts: list[str]) -> str:
    return "\n".join(t for t in (x.strip() for x in texts) if t)


class BridgeClient(discord.Client):
    def __init__(self, settings: Settings, **kwargs: Any) -> None:
        intents = kwargs.pop("intents", None) or discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.guild_messages = True
        super().__init__(intents=intents, **kwargs)
        self.settings = settings
        self.dedupe = Dedupe()
        self.batcher = ChannelBatcher(debounce_s=DEBOUNCE_S, ttl_s=PENDING_TTL_S)
        # channel_id -> (bot spec, list of routed texts aligned with buffer)
        self.routed: dict[str, list[tuple[BotSpec, str]]] = {}
        self.last_typing: dict[str, float] = {}
        self.http_session: aiohttp.ClientSession | None = None
        self._runner = None
        self._tick_task: asyncio.Task | None = None
        self.dry_run_log: list[dict[str, Any]] = []

    async def setup_hook(self) -> None:
        self.http_session = aiohttp.ClientSession()
        app = build_app(self.settings.callback_secret, self._on_callback)
        self._runner = await start_site(
            app, self.settings.callback_bind, self.settings.callback_port
        )
        self._tick_task = asyncio.create_task(self._tick_loop())

    async def close(self) -> None:
        if self._tick_task is not None:
            self._tick_task.cancel()
        if self.http_session is not None:
            await self.http_session.close()
        if self._runner is not None:
            await self._runner.cleanup()
        await super().close()

    async def on_ready(self) -> None:
        log.info(
            "online as %s (require_mention=%s debounce=%ss)",
            self.user, self.settings.require_mention, DEBOUNCE_S,
        )
        for gid in sorted(self.settings.guilds):
            g = self.get_guild(int(gid))
            name = g.name if g else "-"
            log.info("allowlisted guild %s visible=%s name=%s", gid, g is not None, name)
        for cid in sorted(self.settings.channels):
            c = self.get_channel(int(cid))
            name = getattr(c, "name", "-")
            log.info("allowlisted channel %s visible=%s name=%s", cid, c is not None, name)

    async def on_message(self, message: discord.Message) -> None:
        if self.user is None:
            return
        msg = _incoming(message)
        self_id = str(self.user.id)
        named = addressed_by_name(msg.content, self.settings.bots, self_user_id=self_id)
        reason = should_drop(
            msg,
            self_user_id=self_id,
            guilds=self.settings.guilds,
            channels=self.settings.channels,
            authors=self.settings.authors,
            require_mention=self.settings.require_mention,
            mapped_role_ids=mapped_role_ids(self.settings.bots),
            dedupe=self.dedupe,
            named=named,
        )
        if reason:
            return
        hit = route(
            msg,
            self.settings.bots,
            self_user_id=self_id,
            default_bot=self.settings.default_bot,
            require_mention=self.settings.require_mention,
        )
        if hit is None:
            log.info("no route for message_id=%s; dropped", msg.message_id)
            return
        self.routed.setdefault(msg.channel_id, []).append((hit.bot, hit.text))
        self.batcher.add(msg)
        await self._typing(msg.channel_id, force=True)

    # ---- scheduling -------------------------------------------------------

    async def _tick_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(TICK_S)
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("tick failed")

    async def _tick(self) -> None:
        for cid in self.batcher.expire():
            log.warning("wake in channel %s expired without a reply; slot released", cid)
        for cid in self.batcher.ready_channels():
            await self._flush(cid)
        for cid in list(self.batcher.channels):
            if self.batcher.active(cid):
                await self._typing(cid)

    async def _typing(self, channel_id: str, *, force: bool = False) -> None:
        now = self.batcher.clock()
        if not force and now - self.last_typing.get(channel_id, 0.0) < TYPING_EVERY_S:
            return
        self.last_typing[channel_id] = now
        try:
            channel = self.get_channel(int(channel_id))
            if channel is not None:
                await channel.typing()
        except Exception:
            log.warning("typing indicator failed in channel %s", channel_id)

    async def _history(self, channel_id: str, before_message_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        try:
            channel = self.get_channel(int(channel_id))
            if channel is None or not hasattr(channel, "history"):
                return []
            before = discord.Object(id=int(before_message_id))
            async for m in channel.history(limit=HISTORY_LIMIT, before=before, oldest_first=False):
                author = str(getattr(m.author, "display_name", m.author.name))
                ts = m.created_at.isoformat()
                items.append(history_entry(author, bool(m.author.bot), m.content or "", ts))
        except Exception:
            log.warning("history fetch failed in channel %s", channel_id)
            return []
        items.reverse()  # oldest first
        return cap_history(items)

    async def _flush(self, channel_id: str) -> None:
        correlation_id = uuid.uuid4().hex
        batch = self.batcher.take(channel_id, correlation_id)
        routed = self.routed.pop(channel_id, [])
        if not batch:
            return
        bot = routed[-1][0] if routed else self.settings.bots[self.settings.default_bot]
        text = combine_texts([t for _b, t in routed]) or combine_texts([m.content for m in batch])
        first, last = batch[0], batch[-1]
        history = await self._history(channel_id, first.message_id)
        payload = WakePayload(
            bot=bot.name,
            text=text,
            author_id=last.author_id,
            author_name=last.author_name,
            channel_id=channel_id,
            guild_id=last.guild_id,
            message_id=last.message_id,
            reply_url=f"{self.settings.callback_public_url}/reply",
            correlation_id=correlation_id,
            history=history,
            message_ids=[m.message_id for m in batch],
        )
        log.info(
            "waking bot=%s channel=%s batched=%d history=%d",
            bot.name, channel_id, len(batch), len(history),
        )
        await self._typing(channel_id, force=True)
        asyncio.create_task(self._wake(bot.webhook_url, bot.webhook_key, payload))

    async def _wake(self, url: str, key: str, payload: WakePayload) -> None:
        ok = False
        try:
            if self.http_session is None:
                return
            result = await ping(self.http_session, url, key, payload, dry_run=self.settings.dry_run)
            if isinstance(result, DryRunResult):
                self.dry_run_log.append(result.payload)
                log.info("DRY_RUN would POST webhook for bot=%s", payload.bot)
                return
            if result != 200:
                log.warning("webhook wake returned %s for bot=%s", result, payload.bot)
                return
            ok = True
        except TimeoutError:
            log.warning("webhook wake timed out for bot=%s", payload.bot)
        except aiohttp.ClientError:
            log.exception("webhook wake failed for bot=%s", payload.bot)
        finally:
            if not ok:
                self.batcher.release(payload.correlation_id)

    async def _on_callback(
        self, correlation_id: str, channel_id: str, message_id: str, text: str
    ) -> bool:
        # local hardening: replies only go to the channel of the in-flight,
        # allowlisted wake; body channel_id/message_id are ignored.
        ref_channel = self.batcher.channel_for(correlation_id)
        if ref_channel is None:
            return False
        if ref_channel not in self.settings.channels:
            self.batcher.release(correlation_id)
            return False
        chunks = split_message(text)
        try:
            if chunks:
                channel = self.get_channel(int(ref_channel))
                if channel is None:
                    channel = await self.fetch_channel(int(ref_channel))
                for chunk in chunks:
                    await channel.send(chunk)
        finally:
            self.batcher.release(correlation_id)
            # typing stops on its own once the channel is idle; reset so the
            # next batch (if any) shows typing immediately
            self.last_typing.pop(ref_channel, None)
        return True


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        settings = load_settings()
    except ConfigError as exc:
        log.error("%s", exc)
        sys.exit(2)
    client = BridgeClient(settings)
    client.run(settings.discord_token, log_handler=None)
