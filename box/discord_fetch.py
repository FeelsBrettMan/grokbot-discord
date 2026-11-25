#!/usr/bin/env python3
"""Box-side context fetch for the Discord chat routine. Never prints the token.

Rebuild a truncated wake:
  python3 discord_fetch.py --channel-id ID --message-ids ID1,ID2 [--history 12]
Catch messages that arrived while you were working (call right before posting):
  python3 discord_fetch.py --channel-id ID --since MESSAGE_ID
Prints JSON. Only allowed authors (allowlist.json) and this bot appear; each entry
has author_id and trusted. Everyone else and other bots are left out.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import allowlist  # noqa: E402

TOKEN_FILE = Path.home() / ".config/discord-bridge/secrets/discord_bot_token"
API = "https://discord.com/api/v10"
UA = "DiscordBot (https://github.com/RudeDude/grokbot-discord, 0.3)"


def get(token: str, path: str):
    req = urllib.request.Request(
        API + path, headers={"Authorization": "Bot " + token, "User-Agent": UA}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def shape(m: dict, allow: dict, bot_id: str) -> dict | None:
    a = m.get("author") or {}
    aid = str(a.get("id", ""))
    is_self = aid == bot_id
    trust = allowlist.trust_of(aid, allow)
    if not is_self and (trust is None or a.get("bot")):
        return None
    return {
        "message_id": str(m.get("id")),
        "author_id": aid,
        "author_name": a.get("global_name") or a.get("username"),
        "trusted": trust == "trusted",
        "is_bot": is_self,
        "text": m.get("content") or "",
        "timestamp": m.get("timestamp"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel-id", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--message-ids", help="comma-separated batch message IDs")
    g.add_argument("--since", help="return allowed messages after this message ID")
    ap.add_argument("--history", type=int, default=12)
    a = ap.parse_args()
    allow = allowlist.load()
    if a.channel_id not in allow["channels"]:
        print(json.dumps({"error": "channel not allowlisted"}))
        return 2
    token = TOKEN_FILE.read_text().strip()
    try:
        bot_id = str(get(token, "/users/@me").get("id", ""))
        base = f"/channels/{a.channel_id}/messages"
        if a.since:
            if not a.since.isdigit():
                print(json.dumps({"error": "--since must be a message ID"}))
                return 2
            raw = get(token, f"{base}?after={a.since}&limit=100")  # newest first
            items = [x for x in (shape(m, allow, bot_id) for m in reversed(raw)) if x]
            print(json.dumps({"since": a.since, "messages": items}, ensure_ascii=False))
            return 0
        ids = [i for i in a.message_ids.split(",") if i.strip().isdigit()]
        if not ids:
            print(json.dumps({"error": "no valid message ids"}))
            return 2
        msgs = [x for x in (shape(get(token, f"{base}/{i}"), allow, bot_id) for i in ids) if x]
        first = min(ids, key=int)
        lim = max(1, min(a.history * 4, 100))
        hist_raw = get(token, f"{base}?before={first}&limit={lim}")
        hist = [x for x in (shape(m, allow, bot_id) for m in hist_raw) if x][: a.history]
        out = {"messages": msgs, "history": list(reversed(hist))}
    except Exception as exc:  # report only the type/status, never headers
        err = f"discord fetch failed: {type(exc).__name__} {getattr(exc, 'code', '')}".strip()
        print(json.dumps({"error": err}))
        return 1
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
