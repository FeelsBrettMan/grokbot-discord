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


BRETT = _author(3, "Brett")  # trusted
ALEX = _author(4, "Alex")  # chat-only
STRANGER = _author(8, "Stranger")
OTHER_BOT = _author(4, "Alex", bot=True)  # even a listed ID is ignored if it's a bot
DAVE = _author(9, "Dave", bot=True)  # this bot


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
        discord_token="t", guilds={"1"}, channels={"2"}, trusted={"3"}, chat={"4"},
        require_mention=False,
        bot_name="grok", webhook_url="https://example.test", webhook_key="k", debounce_s=0.0,
        in_flight_timeout_s=300, history_limit=12, history_chars=3000, history_entry_chars=600,
        message_chars=1500, batch_chars=4000, catchup_limit=100,
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


async def test_group_batch_mixed_authors_and_reply_coverage(client):
    ch = FakeChannel([
        _msg(10, BRETT, "earlier"), _msg(11, STRANGER, "hidden"), _msg(12, DAVE, "earlier reply"),
        _msg(13, ALEX, "chat earlier"),
    ])
    client.get_channel = lambda i: ch
    await client.on_message(_msg(20, BRETT, "first"))
    await client.on_message(_msg(21, ALEX, "me too"))
    await client.on_message(_msg(22, STRANGER, "ignored"))
    await client.on_message(_msg(23, OTHER_BOT, "ignored bot"))
    assert ch.typed >= 1
    await client.tick()
    await _drain()
    p = client.dry_run_log[0]
    assert p["batch_has_trusted"] is True and p["trusted_author_ids"] == ["3"]
    assert [(m["message_id"], m["author_id"], m["trusted"], m["text"]) for m in p["messages"]] == [
        ("20", "3", True, "first"), ("21", "4", False, "me too"),
    ]
    assert p["message_id"] == "21"
    assert [(h["author"], h["trusted"], h["is_bot"]) for h in p["history"]] == [
        ("Brett", True, False), ("Dave", False, True), ("Alex", False, False),
    ]  # the stranger is included nowhere
    assert client.state.get("2") == "21"
    # more people talk while the run is in flight: held, not forwarded
    await client.on_message(_msg(24, ALEX, "also this"))
    await client.on_message(_msg(25, BRETT, "and this"))
    await client.tick()
    assert len(client.dry_run_log) == 1
    # the routine re-fetched 24/25 before posting, so its reply (26) covers them
    await client.on_message(_msg(27, ALEX, "after the reply"))
    await client.on_message(_msg(26, DAVE, "answer"))
    await client.tick()
    await _drain()
    assert len(client.dry_run_log) == 2
    p2 = client.dry_run_log[1]
    assert [m["message_id"] for m in p2["messages"]] == ["27"]
    assert p2["batch_has_trusted"] is False and p2["trusted_author_ids"] == []
    assert client.state.get("2") == "27"


async def test_chat_only_batch(client):
    ch = FakeChannel([])
    client.get_channel = lambda i: ch
    await client.on_message(_msg(40, ALEX, "hey bot"))
    await client.tick()
    await _drain()
    p = client.dry_run_log[0]
    assert p["batch_has_trusted"] is False and p["messages"][0]["trusted"] is False


async def test_catch_up_after_disconnect(client):
    client.state.set("2", "30")
    ch = FakeChannel([
        _msg(30, BRETT, "old"), _msg(31, BRETT, "answered"), _msg(32, DAVE, "reply"),
        _msg(33, BRETT, "missed 1"), _msg(34, STRANGER, "x"),
        _msg(35, ALEX, "missed 2"),
    ])
    client.get_channel = lambda i: ch
    await client.catch_up("ready")
    await client.tick()
    await _drain()
    assert len(client.dry_run_log) == 1
    msgs = client.dry_run_log[0]["messages"]
    assert [(m["text"], m["trusted"]) for m in msgs] == [("missed 1", True), ("missed 2", False)]
    assert client.state.get("2") == "35"
    # a live duplicate of a caught-up message is ignored
    await client.on_message(_msg(35, ALEX, "missed 2"))
    assert not client.batcher.channels["2"].buffer


async def test_catch_up_noop_on_first_run(client):
    ch = FakeChannel([_msg(30, BRETT, "old")])
    client.get_channel = lambda i: ch
    await client.catch_up("ready")
    assert not client.batcher.channels
