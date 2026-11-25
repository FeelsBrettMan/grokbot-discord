#!/usr/bin/env python3
"""Box-side context fetch for the Discord chat routine.

If the webhook body looks cut off, rebuild the full turn from Discord REST:
  python3 discord_fetch.py --channel-id ID --message-ids ID1,ID2 [--history 12]
Prints JSON {"text": ..., "history": [...]} (history oldest first). Never prints the token.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

TOKEN_FILE = Path.home() / ".config/discord-bridge/secrets/discord_bot_token"
API = "https://discord.com/api/v10"
UA = "DiscordBot (https://github.com/RudeDude/grokbot-discord, 0.2)"



def _allowed_channels() -> set[str]:
    """DISCORD_CHANNEL_ALLOWLIST from env, else from ~/.config/discord-bridge/bridge.env.

    Empty means nothing is allowed (fail closed).
    """
    raw = os.environ.get("DISCORD_CHANNEL_ALLOWLIST", "")
    cfg = Path.home() / ".config/discord-bridge/bridge.env"
    if not raw and cfg.is_file():
        for line in cfg.read_text().splitlines():
            if line.strip().startswith("DISCORD_CHANNEL_ALLOWLIST="):
                raw = line.split("=", 1)[1]
    return {c.strip() for c in raw.split(",") if c.strip().isdigit()}


ALLOWED_CHANNELS = _allowed_channels()

def get(token: str, path: str):
    req = urllib.request.Request(
        API + path, headers={"Authorization": "Bot " + token, "User-Agent": UA}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel-id", required=True)
    ap.add_argument("--message-ids", required=True)
    ap.add_argument("--history", type=int, default=12)
    a = ap.parse_args()
    if a.channel_id not in ALLOWED_CHANNELS:
        print(json.dumps({"error": "channel not allowlisted"}))
        return 2
    ids = [i for i in a.message_ids.split(",") if i.strip().isdigit()]
    if not ids:
        print(json.dumps({"error": "no valid message ids"}))
        return 2
    token = TOKEN_FILE.read_text().strip()
    try:
        msgs = [get(token, f"/channels/{a.channel_id}/messages/{i}") for i in ids]
        first = min(ids, key=int)
        hist = get(
            token,
            f"/channels/{a.channel_id}/messages?before={first}&limit={max(1, min(a.history, 50))}",
        )
    except Exception as exc:  # report only the type/status, never headers
        print(json.dumps({"error": f"discord fetch failed: {type(exc).__name__} "
                                   f"{getattr(exc, 'code', '')}".strip()}))
        return 1
    out = {
        "text": "\n".join((m.get("content") or "").strip() for m in msgs if m.get("content")),
        "history": [
            {
                "author": (m["author"].get("global_name") or m["author"].get("username")),
                "is_bot": bool(m["author"].get("bot")),
                "text": m.get("content") or "",
                "timestamp": m.get("timestamp"),
            }
            for m in reversed(hist)
        ],
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
