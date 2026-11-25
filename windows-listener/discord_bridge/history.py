"""Shaping of batch messages and history for the wake payload (listener). Data only."""

from __future__ import annotations

from typing import Any

HISTORY_LIMIT = 12
HISTORY_CHAR_CAP = 3000
ENTRY_CHAR_CAP = 600
MESSAGE_CHAR_CAP = 1500
BATCH_CHAR_CAP = 4000
ELLIPSIS = "\u2026"


def clip(text: str, cap: int) -> str:
    text = text or ""
    if len(text) <= cap:
        return text
    return text[: max(cap - 1, 0)].rstrip() + ELLIPSIS


def cap_total(
    items: list[dict[str, Any]], char_cap: int
) -> tuple[list[dict[str, Any]], int]:
    """items oldest-first; drop oldest until total text <= char_cap. Returns (kept, dropped)."""
    out = list(items)
    total = sum(len(str(i.get("text", ""))) for i in out)
    dropped = 0
    while len(out) > 1 and total > char_cap:
        total -= len(str(out.pop(0).get("text", "")))
        dropped += 1
    if out and total > char_cap:  # a single item still too big
        out[0] = {**out[0], "text": clip(str(out[0].get("text", "")), char_cap)}
    return out, dropped


def cap_history(
    items: list[dict[str, Any]], char_cap: int = HISTORY_CHAR_CAP
) -> list[dict[str, Any]]:
    out = list(items)
    total = sum(len(str(i.get("text", ""))) for i in out)
    while out and total > char_cap:
        total -= len(str(out.pop(0).get("text", "")))
    return out


def message_entry(
    message_id: str, author_id: str, author_name: str, trusted: bool, text: str,
    timestamp: str, cap: int = MESSAGE_CHAR_CAP,
) -> dict[str, Any]:
    return {"message_id": message_id, "author_id": author_id, "author_name": author_name,
            "trusted": trusted, "text": clip(text, cap), "timestamp": timestamp}


def history_entry(
    author: str, author_id: str, trusted: bool, is_bot: bool, text: str, timestamp: str,
    entry_cap: int = ENTRY_CHAR_CAP,
) -> dict[str, Any]:
    return {"author": author, "author_id": author_id, "trusted": trusted, "is_bot": is_bot,
            "text": clip(text, entry_cap), "timestamp": timestamp}
