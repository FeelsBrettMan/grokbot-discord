from __future__ import annotations

import re
from collections import OrderedDict

from discord_bridge.models import IncomingMessage


class ConfigError(ValueError):
    pass


class Dedupe:
    def __init__(self, cap: int = 2048) -> None:
        self._cap = cap
        self._seen: OrderedDict[str, None] = OrderedDict()

    def already_seen(self, message_id: str) -> bool:
        if message_id in self._seen:
            return True
        self._seen[message_id] = None
        if len(self._seen) > self._cap:
            self._seen.popitem(last=False)
        return False


def require_allowlists(guilds: set[str], channels: set[str], trusted: set[str]) -> None:
    if not guilds:
        raise ConfigError("DISCORD_GUILD_ALLOWLIST is empty")
    if not channels:
        raise ConfigError("DISCORD_CHANNEL_ALLOWLIST is empty")
    if not trusted:
        raise ConfigError("DISCORD_TRUSTED_AUTHORS is empty")


def classify(author_id: str, trusted: set[str], chat: set[str]) -> str | None:
    """'trusted', 'chat', or None (not allowed). Trusted wins if listed in both."""
    if author_id in trusted:
        return "trusted"
    if author_id in chat:
        return "chat"
    return None


def strip_user_mention(content: str, user_id: str) -> str:
    return re.sub(rf"<@!?{re.escape(user_id)}>", "", content or "").strip()


def addressed_by_name(content: str, bot_name: str) -> bool:
    first = (content or "").strip().partition(" ")[0].lstrip("@").casefold()
    return bool(bot_name) and first == bot_name.casefold()


def should_drop(
    msg: IncomingMessage,
    *,
    self_user_id: str,
    guilds: set[str],
    channels: set[str],
    trusted: set[str],
    chat: set[str],
    require_mention: bool,
    dedupe: Dedupe | None,
    named: bool = False,
) -> str | None:
    """Fail-closed filter. Returns a drop reason, or None to forward."""
    if msg.author_id == self_user_id:
        return "self"
    if msg.author_is_bot:
        return "bot"
    if not msg.guild_id or msg.guild_id not in guilds:
        return "guild"
    if msg.channel_id not in channels:
        return "channel"
    if classify(msg.author_id, trusted, chat) is None:
        return "author"
    if require_mention and self_user_id not in msg.mention_user_ids and not named:
        return "mention"
    if dedupe is not None and dedupe.already_seen(msg.message_id):
        return "duplicate"
    return None
