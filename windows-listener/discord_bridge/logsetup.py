"""Logging to a rotating file + console, with secret redaction on every line."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_PATTERNS = [
    re.compile(r"[MNO][A-Za-z0-9_-]{20,30}\.[A-Za-z0-9_-]{5,7}\.[A-Za-z0-9_-]{25,45}"),  # bot token
    re.compile(r"(?i)(authorization:?\s*(?:bot|bearer)\s+)\S+"),
    re.compile(r"(?i)\b(bot|bearer)\s+[A-Za-z0-9._-]{20,}"),
]


class RedactingFormatter(logging.Formatter):
    def __init__(self, fmt: str, secrets: list[str]) -> None:
        super().__init__(fmt)
        self.secrets = [s for s in secrets if s and len(s) >= 6]

    def redact(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, "[REDACTED]")
        text = _PATTERNS[0].sub("[REDACTED]", text)
        text = _PATTERNS[1].sub(r"\1[REDACTED]", text)
        text = _PATTERNS[2].sub(r"\1 [REDACTED]", text)
        return text

    def format(self, record: logging.LogRecord) -> str:
        return self.redact(super().format(record))


def setup_logging(log_file: Path, secrets: list[str]) -> None:
    fmt = RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s", secrets)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(fh)
    root.addHandler(sh)
