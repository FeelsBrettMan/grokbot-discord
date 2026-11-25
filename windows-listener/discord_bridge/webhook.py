from __future__ import annotations

import json
from typing import Any

import aiohttp

WEBHOOK_TIMEOUT_S = 15.0


def encode_body(payload: dict[str, Any]) -> bytes:
    """Compact JSON, UTF-8 (no \\uXXXX escapes), key order preserved."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def webhook_headers(key: str) -> dict[str, str]:
    return {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}


async def post_wake(
    session: aiohttp.ClientSession, url: str, key: str, payload: dict[str, Any]
) -> int:
    timeout = aiohttp.ClientTimeout(total=WEBHOOK_TIMEOUT_S)
    async with session.post(
        url,
        data=encode_body(payload),
        headers=webhook_headers(key),
        timeout=timeout,
        allow_redirects=False,
    ) as resp:
        return resp.status
