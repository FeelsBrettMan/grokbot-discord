import datetime
import types

import pytest

from discord_bridge.bot import BridgeClient
from discord_bridge.config import Settings


def _author(uid, name, bot=False):
    return types.SimpleNamespace(id=int(uid), display_name=name, name=name, bot=bot)


def _msg(mid, author, content="hi", channel_id=2):
    return types.SimpleNamespace(
        id=int(mid), channel=types.SimpleNamespace(id=channel_id),
        guild=types.SimpleNamespace(id=1), author=author, content=content, mentions=[],
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )


BRETT = _author(3, "Brett")
DAVE = _author(9, "Dave", bot=True)


class FakeChannel:
    def __init__(self, msgs):
        self.msgs = msgs  # oldest first
        self.typed = 0

    async def typing(self):
        self.typed += 1

    async def history(self, limit, before=None, after=None, oldest_first=False):
        sel = [m for m in self.msgs
               if (before is None or m.id < before.id) and (after is None or m.id > after.id)]
        sel = sel if oldest_first else list(reversed(sel))
        for m in sel[:limit]:
            yield m


@pytest.fixture
def client(tmp_path):
    s = Settings(
        discord_token="t", guilds={"1"}, channels={"2"}, authors={"3"}, require_mention=False,
        bot_name="grok", webhook_url="https://example.test", webhook_key="k", debounce_s=0.0,
        in_flight_timeout_s=300, history_limit=12, history_chars=3000, history_entry_chars=600,
        text_chars=4000, catchup_limit=100,
        data_dir=tmp_path, log_file=tmp_path / "b.log", dry_run=True,
    )
    c = BridgeClient(s)
    c._connection.user = types.SimpleNamespace(id=9)  # fake login
    type(c).user = property(lambda self: self._connection.user)
    return c


async def _drain():
    import asyncio

    for _ in range(5):
        await asyncio.sleep(0)


async def test_forward_batch_and_reply_ends_run(client):
    ch = FakeChannel([_msg(10, BRETT, "earlier"), _msg(11, DAVE, "earlier reply")])
    client.get_channel = lambda i: ch
    await client.on_message(_msg(20, BRETT, "first"))
    await client.on_message(_msg(21, BRETT, "second"))
    await client.on_message(_msg(22, _author(8, "Stranger"), "ignored"))
    assert ch.typed >= 1
    await client.tick()
    await _drain()
    p = client.dry_run_log[0]
    assert p["text"] == "first\nsecond"
    assert p["message_ids"] == ["20", "21"] and p["message_id"] == "21"
    assert [h["author"] for h in p["history"]] == ["Brett", "Dave"]
    assert p["history"][1]["is_bot"] is True
    assert p["reply_mode"] == "discord_rest"
    assert client.state.get("2") == "21"
    # Brett sends more while the run is in flight: held, not forwarded
    await client.on_message(_msg(23, BRETT, "third"))
    await client.tick()
    assert len(client.dry_run_log) == 1
    # the routine's reply (our own bot user) ends the run; next batch goes out
    await client.on_message(_msg(24, DAVE, "answer"))
    await client.tick()
    await _drain()
    assert client.dry_run_log[1]["text"] == "third"


async def test_catch_up_after_disconnect(client):
    client.state.set("2", "30")
    ch = FakeChannel([
        _msg(30, BRETT, "old"), _msg(31, BRETT, "answered"), _msg(32, DAVE, "reply"),
        _msg(33, BRETT, "missed 1"), _msg(34, _author(8, "Other"), "x"),
        _msg(35, BRETT, "missed 2"),
    ])
    client.get_channel = lambda i: ch
    await client.catch_up("ready")
    await client.tick()
    await _drain()
    assert len(client.dry_run_log) == 1
    assert client.dry_run_log[0]["text"] == "missed 1\nmissed 2"
    assert client.state.get("2") == "35"
    # a live duplicate of a caught-up message is ignored
    await client.on_message(_msg(35, BRETT, "missed 2"))
    assert not client.batcher.active("2") or client.batcher.in_flight("2")


async def test_catch_up_noop_on_first_run(client):
    ch = FakeChannel([_msg(30, BRETT, "old")])
    client.get_channel = lambda i: ch
    await client.catch_up("ready")
    assert not client.batcher.channels
