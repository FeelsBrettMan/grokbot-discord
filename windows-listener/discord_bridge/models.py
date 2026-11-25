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
    timestamp: str = ""  # ISO 8601 UTC


@dataclass(frozen=True)
class WakePayload:
    correlation_id: str
    guild_id: str
    channel_id: str
    message_id: str  # last message in the batch
    trusted_author_ids: list[str]
    messages: list[dict[str, Any]]
    history: list[dict[str, Any]] = field(default_factory=list)
    omitted_count: int = 0  # oldest batch messages left out to keep the body small
    reply_mode: str = "discord_rest"

    def as_dict(self) -> dict[str, Any]:
        # Small fields first: routine wakes may only show the first part of the body,
        # so correlation_id and the IDs must survive truncation. history goes last.
        return {
            "correlation_id": self.correlation_id,
            "reply_mode": self.reply_mode,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "message_id": self.message_id,
            "batch_has_trusted": bool(self.trusted_author_ids),
            "trusted_author_ids": list(self.trusted_author_ids),
            "omitted_count": self.omitted_count,
            "messages": list(self.messages),
            "history": list(self.history),
        }
