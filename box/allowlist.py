"""Shared allowlist for the box-side Discord helpers (fail closed).

Reads ~/.config/discord-bridge/allowlist.json (override with DISCORD_ALLOWLIST_FILE):
  {"guilds": [...], "channels": [...], "trusted_authors": [...], "chat_authors": [...]}
Missing file, bad JSON or an empty channels/trusted list -> nothing is allowed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_PATH = Path.home() / ".config/discord-bridge/allowlist.json"


def _ids(raw) -> set[str]:
    if not isinstance(raw, list):
        return set()
    return {str(x).strip() for x in raw if str(x).strip().isdigit()}


def load(path: Path | None = None) -> dict[str, set[str]]:
    path = path or Path(os.environ.get("DISCORD_ALLOWLIST_FILE", DEFAULT_PATH))
    empty = {"guilds": set(), "channels": set(), "trusted_authors": set(), "chat_authors": set()}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(data, dict):
        return empty
    out = {k: _ids(data.get(k)) for k in empty}
    out["chat_authors"] -= out["trusted_authors"]
    if not out["channels"] or not out["trusted_authors"]:
        return empty
    return out


def trust_of(author_id: str, allow: dict[str, set[str]]) -> str | None:
    if author_id in allow["trusted_authors"]:
        return "trusted"
    if author_id in allow["chat_authors"]:
        return "chat"
    return None
