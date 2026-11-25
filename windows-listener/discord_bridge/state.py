"""Tiny JSON state: last forwarded message id per channel (atomic writes)."""

from __future__ import annotations

import json
import os
from pathlib import Path


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, str] = {}
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            last = raw.get("last_forwarded", {}) if isinstance(raw, dict) else {}
            self.data = {str(k): str(v) for k, v in last.items() if str(v).isdigit()}
        except (OSError, ValueError):
            self.data = {}

    def get(self, channel_id: str) -> str | None:
        return self.data.get(channel_id)

    def set(self, channel_id: str, message_id: str) -> None:
        cur = self.data.get(channel_id)
        if cur is not None and int(cur) >= int(message_id):
            return
        self.data[channel_id] = message_id
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps({"last_forwarded": self.data}, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
