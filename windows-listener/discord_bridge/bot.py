from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from typing import Any

import aiohttp
import discord

from discord_bridge.batching import ChannelBatcher
from discord_bridge.config import DEPRECATED_NOTES, ConfigError, Settings, load_settings
from discord_bridge.filters import (
    Dedupe,
    addressed_by_name,
    classify,
    should_drop,
    strip_user_mention,
)
from discord_bridge.history import cap_history, cap_total, history_entry, message_entry
from discord_bridge.lock import acquire
from discord_bridge.logsetup import setup_logging
from discord_bridge.models import IncomingMessage, WakePayload
from discord_bridge.state import StateStore
from discord_bridge.webhook import encode_body, post_wake

log = logging.getLogger("discord_bridge")
TYPING_EVERY_S = 8.0  # Discord's typing indicator lasts ~10s
TICK_S = 0.5
EXIT_CONFIG = 2
EXIT_ALREADY_RUNNING = 3


def incoming(message: discord.Message) -> IncomingMessage:
    return IncomingMessage(
        message_id=str(message.id),
        channel_id=str(message.channel.id),
        guild_id=str(message.guild.id) if message.guild else "",
        author_id=str(message.author.id),
        author_name=str(getattr(message.author, "display_name", message.author.name)),
        content=message.content or "",
        mention_user_ids=frozenset(str(u.id) for u in message.mentions),
        author_is_bot=bool(message.author.bot),
        timestamp=message.created_at.isoformat() if getattr(message, "created_at", None) else "",
    )


class BridgeClient(discord.Client):
    def __init__(self, settings: Settings, **kwargs: Any) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        super().__init__(intents=intents, **kwargs)
        self.settings = settings
        self.dedupe = Dedupe()
        self.batcher = ChannelBatcher(settings.debounce_s, settings.in_flight_timeout_s)
        self.state = StateStore(settings.data_dir / "state.json")
        self.last_typing: dict[str, float] = {}
        self.http_session: aiohttp.ClientSession | None = None
        self._tick_task: asyncio.Task | None = None
        self._catchup_lock = asyncio.Lock()
        self.dry_run_log: list[dict[str, Any]] = []

    # ---- lifecycle --------------------------------------------------------

    async def setup_hook(self) -> None:
        self.http_session = aiohttp.ClientSession()
        self._tick_task = asyncio.create_task(self._tick_loop())

    async def close(self) -> None:
        if self._tick_task is not None:
            self._tick_task.cancel()
        if self.http_session is not None:
            await self.http_session.close()
        await super().close()

    async def on_ready(self) -> None:
        log.info(
            "online as %s (require_mention=%s debounce=%ss timeout=%ss)",
            self.user, self.settings.require_mention,
            self.settings.debounce_s, self.settings.in_flight_timeout_s,
        )
        for gid in sorted(self.settings.guilds):
            g = self.get_guild(int(gid))
            name = g.name if g else "-"
            log.info("allowlisted guild %s visible=%s name=%s", gid, g is not None, name)
        for cid in sorted(self.settings.channels):
            c = self.get_channel(int(cid))
            name = getattr(c, "name", "-")
            log.info("allowlisted channel %s visible=%s name=%s", cid, c is not None, name)
        await self.catch_up("ready")

    async def on_resumed(self) -> None:
        log.info("gateway session resumed")
        await self.catch_up("resumed")

    # ---- inbound ----------------------------------------------------------

    def trust_of(self, author_id: str) -> str | None:
        return classify(author_id, self.settings.trusted, self.settings.chat)

    def _accept(self, msg: IncomingMessage, *, dedupe: bool = True) -> bool:
        assert self.user is not None
        self_id = str(self.user.id)
        reason = should_drop(
            msg,
            self_user_id=self_id,
            guilds=self.settings.guilds,
            channels=self.settings.channels,
            trusted=self.settings.trusted,
            chat=self.settings.chat,
            require_mention=self.settings.require_mention,
            dedupe=self.dedupe if dedupe else None,
            named=addressed_by_name(
                strip_user_mention(msg.content, self_id), self.settings.bot_name
            ),
        )
        return reason is None

    async def on_message(self, message: discord.Message) -> None:
        if self.user is None:
            return
        msg = incoming(message)
        if msg.author_id == str(self.user.id):
            # Our own post (the routine replying over REST) ends the run in flight
            # and covers everything said before it.
            if msg.channel_id in self.settings.channels:
                ended, dropped = self.batcher.bot_posted(msg.channel_id, msg.message_id)
                if ended:
                    log.info(
                        "reply seen in channel %s; run finished; %d covered message(s) dropped",
                        msg.channel_id, len(dropped),
                    )
                if dropped:
                    self.state.set(msg.channel_id, max((m.message_id for m in dropped), key=int))
            return
        if not self._accept(msg):
            return
        self.batcher.add(msg)
        await self._typing(msg.channel_id, force=True)

    async def catch_up(self, why: str) -> None:
        """Forward allowed authors' messages sent while we were disconnected."""
        if self.user is None:
            return
        async with self._catchup_lock:
            for cid in sorted(self.settings.channels):
                last = self.state.get(cid)
                if last is None:
                    continue  # first run: nothing to catch up on
                channel = self.get_channel(int(cid))
                if channel is None or not hasattr(channel, "history"):
                    continue
                missed: list[IncomingMessage] = []
                try:
                    async for m in channel.history(
                        limit=self.settings.catchup_limit,
                        after=discord.Object(id=int(last)),
                        oldest_first=True,
                    ):
                        msg = incoming(m)
                        if msg.author_id == str(self.user.id):
                            missed = []  # the bot already answered everything before this
                            continue
                        missed.append(msg)
                except Exception:
                    log.warning("catch-up history fetch failed for channel %s", cid)
                    continue
                found = 0
                for msg in missed:
                    if self._accept(msg):
                        self.batcher.add(msg)
                        found += 1
                if found:
                    log.info("catch-up (%s): %d missed message(s) in %s", why, found, cid)
                    await self._typing(cid, force=True)

    # ---- scheduling -------------------------------------------------------

    async def _tick_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(TICK_S)
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("tick failed")

    async def tick(self) -> None:
        for cid in self.batcher.expire():
            log.warning("no reply in channel %s within timeout; run released", cid)
        for cid in self.batcher.ready_channels():
            await self.flush(cid)
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

    async def history_before(self, channel_id: str, before_id: str) -> list[dict[str, Any]]:
        """Recent context before the batch: allowed authors and the bot only, oldest first."""
        assert self.user is not None
        self_id = str(self.user.id)
        items: list[dict[str, Any]] = []
        try:
            channel = self.get_channel(int(channel_id))
            if channel is None or not hasattr(channel, "history"):
                return []
            async for m in channel.history(
                limit=min(self.settings.history_limit * 4, 100),
                before=discord.Object(id=int(before_id)),
                oldest_first=False,
            ):
                aid = str(m.author.id)
                trust = self.trust_of(aid)
                is_self = aid == self_id
                if not is_self and (trust is None or m.author.bot):
                    continue  # strangers and other bots are included nowhere
                author = str(getattr(m.author, "display_name", m.author.name))
                items.append(
                    history_entry(
                        author, aid, trust == "trusted", is_self, m.content or "",
                        m.created_at.isoformat(), self.settings.history_entry_chars,
                    )
                )
                if len(items) >= self.settings.history_limit:
                    break
        except Exception:
            log.warning("history fetch failed in channel %s", channel_id)
            return []
        items.reverse()  # oldest first
        return cap_history(items, self.settings.history_chars)

    def build_messages(self, batch: list[IncomingMessage]) -> tuple[list[dict[str, Any]], int]:
        assert self.user is not None
        self_id = str(self.user.id)
        entries = [
            message_entry(
                m.message_id, m.author_id, m.author_name, self.trust_of(m.author_id) == "trusted",
                strip_user_mention(m.content, self_id), m.timestamp, self.settings.message_chars,
            )
            for m in batch
        ]
        return cap_total(entries, self.settings.batch_chars)

    async def flush(self, channel_id: str) -> None:
        correlation_id = uuid.uuid4().hex
        batch = self.batcher.take(channel_id, correlation_id)
        if not batch:
            return
        first, last = batch[0], batch[-1]
        messages, omitted = self.build_messages(batch)
        trusted_ids = sorted({m["author_id"] for m in messages if m["trusted"]}, key=int)
        payload = WakePayload(
            correlation_id=correlation_id,
            guild_id=last.guild_id,
            channel_id=channel_id,
            message_id=last.message_id,
            trusted_author_ids=trusted_ids,
            messages=messages,
            history=await self.history_before(channel_id, first.message_id),
            omitted_count=omitted,
        )
        size = len(encode_body(payload.as_dict()).decode("utf-8"))
        log.info(
            "waking channel=%s batched=%d trusted=%s history=%d body_chars=%d corr=%s",
            channel_id, len(batch), bool(trusted_ids), len(payload.history), size,
            correlation_id[:8],
        )
        await self._typing(channel_id, force=True)
        asyncio.create_task(self._wake(payload, batch))

    async def _wake(self, payload: WakePayload, batch: list[IncomingMessage]) -> None:
        body = payload.as_dict()
        status: int | str
        try:
            if self.settings.dry_run:
                self.dry_run_log.append(body)
                log.info("DRY_RUN: would POST wake corr=%s", payload.correlation_id[:8])
                status = 200
            else:
                assert self.http_session is not None
                status = await post_wake(
                    self.http_session, self.settings.webhook_url, self.settings.webhook_key, body
                )
        except (TimeoutError, aiohttp.ClientError) as exc:
            status = type(exc).__name__
        if status == 200 or (isinstance(status, int) and 200 <= status < 300):
            self.batcher.wake_ok(payload.channel_id)
            self.state.set(payload.channel_id, payload.message_id)
            return
        if self.batcher.wake_failed(payload.channel_id, batch):
            log.warning("wake failed (%s); will retry", status)
        else:
            log.error("wake failed (%s) after retries; dropped %d message(s)", status, len(batch))
            self.state.set(payload.channel_id, payload.message_id)


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    setup_logging(settings.log_file, [settings.discord_token, settings.webhook_key])
    for note in DEPRECATED_NOTES:
        log.warning(note)
    if "--check" in sys.argv:
        log.info(
            "config ok: guilds=%d channels=%d trusted=%d chat=%d require_mention=%s dry_run=%s",
            len(settings.guilds), len(settings.channels), len(settings.trusted),
            len(settings.chat),
            settings.require_mention, settings.dry_run,
        )
        return
    lock = acquire(settings.data_dir / "bridge.lock")
    if lock is None:
        log.error("another bridge instance is already running; exiting")
        sys.exit(EXIT_ALREADY_RUNNING)
    client = BridgeClient(settings)
    try:
        client.run(settings.discord_token, log_handler=None)
    except discord.LoginFailure:
        log.error("Discord rejected the bot token (reset it and update .env)")
        sys.exit(EXIT_CONFIG)
    except discord.PrivilegedIntentsRequired:
        log.error("Enable MESSAGE CONTENT INTENT for the bot in the Discord developer portal")
        sys.exit(EXIT_CONFIG)
    except Exception:
        log.exception("bridge crashed")
        sys.exit(1)
