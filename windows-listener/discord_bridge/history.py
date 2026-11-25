"""Conversation history / text shaping for the wake payload (listener). Data only."""

from __future__ import annotations

from typing import Any

HISTORY_LIMIT = 12
HISTORY_CHAR_CAP = 3000
ENTRY_CHAR_CAP = 600
TEXT_CHAR_CAP = 4000
ELLIPSIS = "\u2026"


def clip(text: str, cap: int) -> str:
    text = text or ""
    if len(text) <= cap:
        return text
    return text[: max(cap - 1, 0)].rstrip() + ELLIPSIS


def cap_history(
    items: list[dict[str, Any]], char_cap: int = HISTORY_CHAR_CAP
) -> list[dict[str, Any]]:
    """items oldest-first; drop oldest until total text length <= char_cap."""
    out = list(items)
    total = sum(len(str(i.get("text", ""))) for i in out)
    while out and total > char_cap:
        total -= len(str(out.pop(0).get("text", "")))
    return out


def history_entry(
    author: str, is_bot: bool, text: str, timestamp: str, entry_cap: int = ENTRY_CHAR_CAP
) -> dict[str, Any]:
    return {"author": author, "is_bot": is_bot, "text": clip(text, entry_cap),
            "timestamp": timestamp}
