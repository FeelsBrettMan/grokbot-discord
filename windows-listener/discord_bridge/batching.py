"""Per-channel debounce + single run in flight, without a reply callback.

Every allowed message (trusted or chat-only) is buffered per channel. A channel
flushes once `debounce_s` has passed since the last buffered message (or the
last bot post) and no run is in flight. A run counts as finished when the bot
itself posts in the channel, or after `timeout_s`. Buffered messages older than
that reply are dropped (the reply covered them); newer ones form the next batch.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from discord_bridge.models import IncomingMessage


@dataclass
class ChannelState:
    buffer: list[IncomingMessage] = field(default_factory=list)
    last_activity: float = 0.0
    in_flight: str | None = None
    in_flight_since: float = 0.0
    retry_at: float = 0.0
    attempts: int = 0


class ChannelBatcher:
    def __init__(
        self,
        debounce_s: float = 3.0,
        timeout_s: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.debounce_s = debounce_s
        self.timeout_s = timeout_s
        self.clock = clock
        self.channels: dict[str, ChannelState] = {}

    def _state(self, channel_id: str) -> ChannelState:
        return self.channels.setdefault(channel_id, ChannelState())

    def add(self, msg: IncomingMessage) -> None:
        st = self._state(msg.channel_id)
        if any(m.message_id == msg.message_id for m in st.buffer):
            return
        st.buffer.append(msg)
        st.last_activity = self.clock()

    def ready_channels(self) -> list[str]:
        now = self.clock()
        return [
            cid
            for cid, st in self.channels.items()
            if st.buffer
            and st.in_flight is None
            and now - st.last_activity >= self.debounce_s
            and now >= st.retry_at
        ]

    def take(self, channel_id: str, correlation_id: str) -> list[IncomingMessage]:
        st = self._state(channel_id)
        if st.in_flight is not None or not st.buffer:
            return []
        batch, st.buffer = st.buffer, []
        st.in_flight = correlation_id
        st.in_flight_since = self.clock()
        return batch

    def wake_failed(
        self, channel_id: str, batch: list[IncomingMessage], max_attempts: int = 3
    ) -> bool:
        """Put a failed batch back for retry with backoff. False if given up."""
        st = self._state(channel_id)
        st.in_flight = None
        st.attempts += 1
        if st.attempts >= max_attempts:
            st.attempts = 0
            return False
        st.buffer = batch + st.buffer
        st.retry_at = self.clock() + 15 * st.attempts
        return True

    def wake_ok(self, channel_id: str) -> None:
        self._state(channel_id).attempts = 0

    def bot_posted(self, channel_id: str, post_id: str) -> tuple[bool, list[IncomingMessage]]:
        """The bot posted in the channel.

        If a run was in flight, this post is its reply: end the run and drop the
        buffered messages older than the post (the replier re-fetched them before
        posting, so the reply already covered them). Later posts of the same reply
        (extra chunks) only count as activity, so newer messages wait one more
        debounce window before the next wake. Returns (ended_run, dropped).
        """
        st = self.channels.get(channel_id)
        if st is None:
            return False, []
        st.last_activity = self.clock()
        if st.in_flight is None:
            return False, []
        st.in_flight = None
        try:
            pid = int(post_id)
        except ValueError:
            return True, []
        dropped = [m for m in st.buffer if int(m.message_id) < pid]
        st.buffer = [m for m in st.buffer if int(m.message_id) >= pid]
        return True, dropped

    def expire(self) -> list[str]:
        now = self.clock()
        out = []
        for cid, st in self.channels.items():
            if st.in_flight is not None and now - st.in_flight_since > self.timeout_s:
                st.in_flight = None
                out.append(cid)
        return out

    def active(self, channel_id: str) -> bool:
        st = self.channels.get(channel_id)
        return bool(st and (st.buffer or st.in_flight is not None))

    def in_flight(self, channel_id: str) -> bool:
        st = self.channels.get(channel_id)
        return bool(st and st.in_flight is not None)
