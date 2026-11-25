from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from discord_bridge.filters import ConfigError, require_allowlists

APP_ROOT = Path(__file__).resolve().parent.parent


def parse_id_list(raw: str) -> set[str]:
    ids = {p.strip() for p in (raw or "").split(",") if p.strip()}
    bad = [i for i in ids if not i.isdigit()]
    if bad:
        raise ConfigError(f"allowlist entries must be numeric Discord IDs ({len(bad)} invalid)")
    return ids


def load_dotenv(path: Path) -> None:
    """KEY=VALUE lines; real environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, _, value = s.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def _truthy(raw: str | None, default: bool) -> bool:
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


def _num(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc
    if v <= 0:
        raise ConfigError(f"{name} must be > 0")
    return v


_PLACEHOLDERS = {"", "changeme", "paste-here", "<token>", "<key>"}


@dataclass
class Settings:
    discord_token: str
    guilds: set[str]
    channels: set[str]
    authors: set[str]
    require_mention: bool
    bot_name: str
    webhook_url: str
    webhook_key: str
    debounce_s: float
    in_flight_timeout_s: float
    history_limit: int
    history_chars: int
    history_entry_chars: int
    text_chars: int
    catchup_limit: int
    data_dir: Path
    log_file: Path
    dry_run: bool


def load_settings(env_file: Path | None = None) -> Settings:
    env_file = env_file or Path(os.environ.get("BRIDGE_ENV_FILE", APP_ROOT / ".env"))
    load_dotenv(env_file)
    dry_run = _truthy(os.environ.get("DRY_RUN"), False)

    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    url = os.environ.get("GROK_BOT_GROK_WEBHOOK_URL", "").strip()
    key = os.environ.get("GROK_BOT_GROK_WEBHOOK_KEY", "").strip()
    if token.casefold() in _PLACEHOLDERS:
        raise ConfigError("DISCORD_BOT_TOKEN is empty")
    if not dry_run:
        if key.casefold() in _PLACEHOLDERS:
            raise ConfigError("GROK_BOT_GROK_WEBHOOK_KEY is empty")
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ConfigError("GROK_BOT_GROK_WEBHOOK_URL must be an https:// URL")

    guilds = parse_id_list(os.environ.get("DISCORD_GUILD_ALLOWLIST", ""))
    channels = parse_id_list(os.environ.get("DISCORD_CHANNEL_ALLOWLIST", ""))
    authors = parse_id_list(os.environ.get("DISCORD_AUTHOR_ALLOWLIST", ""))
    require_allowlists(guilds, channels, authors)

    data_dir = Path(os.environ.get("DATA_DIR", APP_ROOT / "data"))
    log_file = Path(os.environ.get("LOG_FILE", APP_ROOT / "logs" / "bridge.log"))
    return Settings(
        discord_token=token,
        guilds=guilds,
        channels=channels,
        authors=authors,
        require_mention=_truthy(os.environ.get("REQUIRE_MENTION"), False),
        bot_name=os.environ.get("BOT_NAME", "grok").strip() or "grok",
        webhook_url=url,
        webhook_key=key,
        debounce_s=_num("DEBOUNCE_SECONDS", 3.0),
        in_flight_timeout_s=_num("IN_FLIGHT_TIMEOUT_SECONDS", 300.0),
        history_limit=int(_num("HISTORY_LIMIT", 12)),
        history_chars=int(_num("HISTORY_CHAR_CAP", 3000)),
        history_entry_chars=int(_num("HISTORY_ENTRY_CHAR_CAP", 600)),
        text_chars=int(_num("TEXT_CHAR_CAP", 4000)),
        catchup_limit=int(_num("CATCHUP_LIMIT", 100)),
        data_dir=data_dir,
        log_file=log_file,
        dry_run=dry_run,
    )
