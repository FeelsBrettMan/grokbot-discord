from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IncomingMessage:
    message_id: str
    channel_id: str
    guild_id: str
    author_id: str
    author_name: str
    content: str
    mention_user_ids: frozenset[str] = frozenset()
    author_is_bot: bool = False


@dataclass(frozen=True)
class WakePayload:
    bot: str
    text: str
    author_id: str
    author_name: str
    channel_id: str
    guild_id: str
    message_id: str
    correlation_id: str
    message_ids: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    reply_mode: str = "discord_rest"

    def as_dict(self) -> dict[str, Any]:
        # Small fields first: routine wakes may only show the first part of the body,
        # so correlation_id and the IDs must survive truncation. history goes last.
        return {
            "correlation_id": self.correlation_id,
            "reply_mode": self.reply_mode,
            "author_id": self.author_id,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "message_id": self.message_id,
            "message_ids": list(self.message_ids),
            "author_name": self.author_name,
            "bot": self.bot,
            "text": self.text,
            "history": list(self.history),
        }
