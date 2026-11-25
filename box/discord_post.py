#!/usr/bin/env python3
"""Box-side reply helper for the Discord chat routine (runs on the Grok Bot box).

Posts a reply to the allowlisted Discord channel over REST, split at 1900 chars,
exactly once per correlation_id. Reads the token from a file and never prints it.

  python3 discord_post.py --channel-id ID --correlation-id CORR --reply-to MSGID < reply.txt
  (add --dry-run to only print chunk sizes)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import allowlist  # noqa: E402

TOKEN_FILE = Path.home() / ".config/discord-bridge/secrets/discord_bot_token"
SENT_LOG = Path.home() / ".local/state/discord-bridge/replied.txt"
API = "https://discord.com/api/v10"
UA = "DiscordBot (https://github.com/RudeDude/grokbot-discord, 0.2)"
LIMIT = 1900


def split_message(text: str, limit: int = LIMIT) -> list[str]:
    text = (text or "").strip()
    parts: list[str] = []
    while len(text) > limit:
        window = text[:limit]
        cut = window.rfind("\n\n")
        if cut <= limit // 4:
            cut = max(window.rfind("\n"), window.rfind(" "))
        if cut <= 0:
            cut = limit
        head = text[:cut].rstrip()
        if head:
            parts.append(head)
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts


def already_sent(corr: str) -> bool:
    try:
        return corr in SENT_LOG.read_text().split()
    except OSError:
        return False


def mark_sent(corr: str) -> None:
    SENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with SENT_LOG.open("a") as fh:
        fh.write(corr + "\n")


def post(token: str, channel_id: str, content: str, reply_to: str | None) -> int:
    body: dict = {"content": content, "allowed_mentions": {"parse": []}}
    if reply_to:
        body["message_reference"] = {"message_id": reply_to, "fail_if_not_exists": False}
    req = urllib.request.Request(
        f"{API}/channels/{channel_id}/messages",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Authorization": "Bot " + token, "Content-Type": "application/json",
                 "User-Agent": UA},
    )
    for _ in range(5):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.status
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                try:
                    wait = float(json.loads(exc.read() or b"{}").get("retry_after", 1))
                except ValueError:
                    wait = 1.0
                time.sleep(min(wait, 30) + 0.2)
                continue
            return exc.code
    return 429


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel-id", required=True)
    ap.add_argument("--correlation-id", required=True)
    ap.add_argument("--reply-to", default=None, help="message_id to reply to (first chunk only)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.channel_id not in allowlist.load()["channels"]:
        print("refused: channel not allowlisted")
        return 2
    chunks = split_message(sys.stdin.read())
    if not chunks:
        print("refused: empty reply")
        return 2
    if a.dry_run:
        print("dry-run chunks:", [len(c) for c in chunks])
        return 0
    if already_sent(a.correlation_id):
        print("skipped: already replied for this correlation_id")
        return 0
    token = TOKEN_FILE.read_text().strip()
    mark_sent(a.correlation_id)  # mark first: at most once, even if a chunk fails
    for i, chunk in enumerate(chunks):
        status = post(token, a.channel_id, chunk, a.reply_to if i == 0 else None)
        if not 200 <= status < 300:
            print(f"error: Discord returned {status} on chunk {i + 1}/{len(chunks)}")
            return 1
    print(f"ok: posted {len(chunks)} message(s)")
    return 0


if __name__ == "__main__":
    os.umask(0o077)
    sys.exit(main())
