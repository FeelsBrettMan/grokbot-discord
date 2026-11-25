import json
import logging
import os

import pytest

from discord_bridge.batching import ChannelBatcher
from discord_bridge.config import ConfigError, load_settings
from discord_bridge.filters import Dedupe, should_drop
from discord_bridge.history import ELLIPSIS, cap_history, clip, history_entry
from discord_bridge.logsetup import RedactingFormatter
from discord_bridge.models import WakePayload
from discord_bridge.state import StateStore
from discord_bridge.webhook import encode_body, webhook_headers
from tests.helpers import make_msg

ENV_KEYS = [
    "DISCORD_BOT_TOKEN", "GROK_BOT_GROK_WEBHOOK_URL", "GROK_BOT_GROK_WEBHOOK_KEY",
    "DISCORD_GUILD_ALLOWLIST", "DISCORD_CHANNEL_ALLOWLIST", "DISCORD_AUTHOR_ALLOWLIST",
    "REQUIRE_MENTION", "DRY_RUN", "BRIDGE_ENV_FILE", "DATA_DIR", "LOG_FILE",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def write_env(tmp_path, **over):
    vals = {
        "DISCORD_BOT_TOKEN": "dummy-token-value",
        "GROK_BOT_GROK_WEBHOOK_URL": "https://example.test/hook",
        "GROK_BOT_GROK_WEBHOOK_KEY": "dummy-key-value",
        "DISCORD_GUILD_ALLOWLIST": "1",
        "DISCORD_CHANNEL_ALLOWLIST": "2",
        "DISCORD_AUTHOR_ALLOWLIST": "3",
    }
    vals.update(over)
    p = tmp_path / ".env"
    p.write_text("".join(f"{k}={v}\n" for k, v in vals.items()))
    return p


def test_config_ok_defaults(tmp_path):
    s = load_settings(write_env(tmp_path))
    assert s.require_mention is False
    assert s.debounce_s == 3.0 and s.in_flight_timeout_s == 300.0
    assert s.history_limit == 12 and s.history_chars == 3000
    assert s.history_entry_chars == 600 and s.text_chars == 4000


@pytest.mark.parametrize(
    "over",
    [
        {"DISCORD_GUILD_ALLOWLIST": ""},
        {"DISCORD_CHANNEL_ALLOWLIST": ""},
        {"DISCORD_AUTHOR_ALLOWLIST": ""},
        {"DISCORD_AUTHOR_ALLOWLIST": "brett"},
        {"DISCORD_BOT_TOKEN": "changeme"},
        {"GROK_BOT_GROK_WEBHOOK_KEY": ""},
        {"GROK_BOT_GROK_WEBHOOK_URL": "http://example.test/hook"},
    ],
)
def test_config_fails_closed(tmp_path, over):
    for k in ENV_KEYS:
        os.environ.pop(k, None)
    with pytest.raises(ConfigError):
        load_settings(write_env(tmp_path, **over))


def test_example_env_has_no_secrets():
    from pathlib import Path

    text = (Path(__file__).parent.parent / ".env.example").read_text()
    lines = dict(
        line.split("=", 1) for line in text.splitlines() if "=" in line and not line.startswith("#")
    )
    assert lines["DISCORD_BOT_TOKEN"].strip() in {"", "changeme"}
    assert lines["GROK_BOT_GROK_WEBHOOK_KEY"].strip() in {"", "changeme"}


def test_filters():
    kw = dict(
        self_user_id="9", guilds={"1"}, channels={"2"}, authors={"3"},
        require_mention=False, dedupe=Dedupe(),
    )
    assert should_drop(make_msg(), **kw) is None
    assert should_drop(make_msg(), **kw) == "duplicate"
    assert should_drop(make_msg(message_id="a", author_id="9"), **kw) == "self"
    assert should_drop(make_msg(message_id="b", author_is_bot=True), **kw) == "bot"
    assert should_drop(make_msg(message_id="c", guild_id=""), **kw) == "guild"
    assert should_drop(make_msg(message_id="d", channel_id="7"), **kw) == "channel"
    assert should_drop(make_msg(message_id="e", author_id="8"), **kw) == "author"
    kw["require_mention"] = True
    assert should_drop(make_msg(message_id="f"), **kw) == "mention"
    assert should_drop(make_msg(message_id="g", mention_user_ids=frozenset({"9"})), **kw) is None


def test_batching_single_flight_without_callback():
    clk = Clock()
    b = ChannelBatcher(debounce_s=3, timeout_s=300, clock=clk)
    b.add(make_msg(message_id="1"))
    clk.t += 1
    b.add(make_msg(message_id="2"))
    b.add(make_msg(message_id="2"))  # duplicate ignored
    clk.t += 2.9
    assert b.ready_channels() == []
    clk.t += 0.2
    assert [m.message_id for m in b.take("2", "a")] == ["1", "2"]
    b.add(make_msg(message_id="3"))
    clk.t += 60
    assert b.ready_channels() == []  # run still in flight
    assert b.bot_posted("2") is True  # bot reply ends the run
    assert b.ready_channels() == []  # waits one debounce after the bot post
    clk.t += 3
    assert [m.message_id for m in b.take("2", "b")] == ["3"]
    assert b.bot_posted("2") is True
    assert b.bot_posted("2") is False  # second chunk of same reply
    assert b.active("2") is False


def test_batching_timeout_and_retry():
    clk = Clock()
    b = ChannelBatcher(debounce_s=3, timeout_s=300, clock=clk)
    b.add(make_msg(message_id="1"))
    clk.t += 3
    batch = b.take("2", "a")
    clk.t += 301
    assert b.expire() == ["2"]
    assert b.in_flight("2") is False
    b.add(make_msg(message_id="5"))
    clk.t += 3
    batch = b.take("2", "b")
    assert b.wake_failed("2", batch) is True
    assert b.ready_channels() == []  # backoff
    clk.t += 15
    assert [m.message_id for m in b.take("2", "c")] == ["5"]
    assert b.wake_failed("2", batch) is True
    clk.t += 30
    b.take("2", "d")
    assert b.wake_failed("2", batch) is False  # gave up after 3 attempts


def test_history_cap():
    items = [history_entry("Brett", False, "a" * 3000, f"t{i}") for i in range(6)]
    assert [i["timestamp"] for i in cap_history(items, 3000)] == ["t1", "t2", "t3", "t4", "t5"]


def test_state_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    s = StateStore(p)
    assert s.get("2") is None
    s.set("2", "500")
    s.set("2", "400")  # never moves backwards
    assert StateStore(p).get("2") == "500"
    assert json.loads(p.read_text()) == {"last_forwarded": {"2": "500"}}
    p.write_text("garbage")
    assert StateStore(p).get("2") is None


def test_payload_shape():
    p = WakePayload("grok", "hi", "3", "Brett", "2", "1", "100", "corr", ["100"], [])
    d = p.as_dict()
    assert list(d) == [
        "correlation_id", "reply_mode", "author_id", "guild_id", "channel_id", "message_id",
        "message_ids", "author_name", "bot", "text", "history",
    ]
    assert d["reply_mode"] == "discord_rest"
    assert "reply_url" not in d


def test_webhook_headers():
    assert webhook_headers("k") == {"Content-Type": "application/json", "Authorization": "Bearer k"}


def test_redaction():
    # fake token assembled at runtime so no token-shaped literal is in the repo
    head = "MTIz" + "NDU2Nzg5MDEyMzQ1Njc4"
    tok = ".".join([head, "GAbCdE", "abcdefghijklmnopqrstuvwxyz0123456789AB"])
    f = RedactingFormatter("%(message)s", [tok, "supersecretkey"])
    rec = logging.LogRecord("x", logging.INFO, "", 0, "t=%s k=%s h=%s", (
        tok, "supersecretkey", "Authorization: Bot abcdefghijklmnopqrstuvwx"), None)
    out = f.format(rec)
    assert tok not in out and "supersecretkey" not in out and "abcdefghijklmnopqrstuvwx" not in out
    other = ".".join([head, "GAbCdE", "z" * 38])
    rec2 = logging.LogRecord("x", logging.INFO, "", 0, other, (), None)
    assert "[REDACTED]" in f.format(rec2)


def test_clip_and_entry_cap():
    assert clip("short", 10) == "short"
    c = clip("x" * 700, 600)
    assert len(c) == 600 and c.endswith(ELLIPSIS)
    assert len(history_entry("Brett", False, "y" * 5000, "t")["text"]) == 600


def test_worst_case_body_small_fields_first():
    hist = cap_history([history_entry("Dave", True, "z" * 5000, f"t{i}") for i in range(12)])
    p = WakePayload(
        "grok", clip("w" * 9000, 4000), "300000000000000003", "Brett",
        "200000000000000002", "100000000000000001", "1" * 19,
        "c" * 32, ["1" * 19] * 5, hist,
    )
    body = encode_body(p.as_dict()).decode()
    head = body[:600]
    assert '"correlation_id":"' + "c" * 32 in head
    assert '"message_ids":[' in head and '"channel_id":"200000000000000002"' in head
    assert sum(len(h["text"]) for h in hist) <= 3000
    assert len(body) < 8000
    assert "\\u2026" not in body  # compact UTF-8, no escapes
