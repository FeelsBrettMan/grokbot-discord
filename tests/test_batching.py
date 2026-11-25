from grokbot_discord.batching import ChannelBatcher
from grokbot_discord.bot import combine_texts
from grokbot_discord.history import cap_history, history_entry
from grokbot_discord.routing import route
from tests.helpers import make_msg


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_debounce_then_single_flight_then_batch():
    clk = Clock()
    b = ChannelBatcher(debounce_s=3, ttl_s=900, clock=clk)
    b.add(make_msg(message_id="1"))
    clk.t += 1
    b.add(make_msg(message_id="2"))
    clk.t += 2.5
    assert b.ready_channels() == []  # only 2.5s since last message
    clk.t += 1
    assert b.ready_channels() == ["c1"]
    batch = b.take("c1", "corr-a")
    assert [m.message_id for m in batch] == ["1", "2"]
    # messages during the run are held, not sent in parallel
    b.add(make_msg(message_id="3"))
    clk.t += 10
    assert b.ready_channels() == []
    assert b.take("c1", "corr-b") == []
    assert b.channel_for("corr-a") == "c1"
    assert b.release("corr-a") == "c1"
    assert b.ready_channels() == ["c1"]
    assert [m.message_id for m in b.take("c1", "corr-b")] == ["3"]


def test_expiry_releases_slot():
    clk = Clock()
    b = ChannelBatcher(debounce_s=3, ttl_s=900, clock=clk)
    b.add(make_msg(message_id="1"))
    clk.t += 4
    b.take("c1", "x")
    b.add(make_msg(message_id="2"))
    clk.t += 901
    assert b.expire() == ["c1"]
    assert b.channel_for("x") is None
    assert b.ready_channels() == ["c1"]


def test_release_unknown():
    b = ChannelBatcher()
    assert b.release("nope") is None
    assert b.channel_for("") is None


def test_cap_history_drops_oldest():
    items = [history_entry("Brett", False, "a" * 3000, f"t{i}") for i in range(4)]
    out = cap_history(items, char_cap=8000)
    assert [i["timestamp"] for i in out] == ["t2", "t3"]
    assert cap_history([], 10) == []


def test_combine_texts():
    assert combine_texts(["hi ", "", "  there"]) == "hi\nthere"


def test_route_without_mention_uses_default(bots):
    msg = make_msg(content="what's the weather", mention_user_ids=frozenset())
    assert route(msg, bots, self_user_id="bridge", default_bot="loops") is None
    hit = route(
        msg, bots, self_user_id="bridge", default_bot="loops", require_mention=False
    )
    assert hit is not None and hit.text == "what's the weather"
