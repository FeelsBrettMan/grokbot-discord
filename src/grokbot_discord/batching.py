"""Per-channel debounce + single-flight batching (local addition).

Messages from the owner are buffered per channel. A channel is flushed once the
debounce window has passed since its last buffered message AND no wake is in
flight for it. Only one wake per channel is ever in flight; messages arriving
while a wake is in flight are batched into the next wake after the reply
arrives (or the in-flight slot expires).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from grokbot_discord.models import IncomingMessage


@dataclass
class ChannelState:
    buffer: list[IncomingMessage] = field(default_factory=list)
    last_added: float = 0.0
    in_flight: str | None = None  # correlation_id
    in_flight_since: float = 0.0
    in_flight_message_id: str = ""


class ChannelBatcher:
    def __init__(
        self,
        debounce_s: float = 3.0,
        ttl_s: float = 15 * 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.debounce_s = debounce_s
        self.ttl_s = ttl_s
        self.clock = clock
        self.channels: dict[str, ChannelState] = {}

    def _state(self, channel_id: str) -> ChannelState:
        return self.channels.setdefault(channel_id, ChannelState())

    def add(self, msg: IncomingMessage) -> None:
        st = self._state(msg.channel_id)
        st.buffer.append(msg)
        st.last_added = self.clock()

    def ready_channels(self) -> list[str]:
        now = self.clock()
        return [
            cid
            for cid, st in self.channels.items()
            if st.buffer and st.in_flight is None and now - st.last_added >= self.debounce_s
        ]

    def take(self, channel_id: str, correlation_id: str) -> list[IncomingMessage]:
        st = self._state(channel_id)
        if st.in_flight is not None or not st.buffer:
            return []
        batch, st.buffer = st.buffer, []
        st.in_flight = correlation_id
        st.in_flight_since = self.clock()
        st.in_flight_message_id = batch[-1].message_id
        return batch

    def channel_for(self, correlation_id: str) -> str | None:
        for cid, st in self.channels.items():
            if correlation_id and st.in_flight == correlation_id:
                return cid
        return None

    def message_for(self, channel_id: str) -> str:
        st = self.channels.get(channel_id)
        return st.in_flight_message_id if st else ""

    def release(self, correlation_id: str) -> str | None:
        cid = self.channel_for(correlation_id)
        if cid is None:
            return None
        st = self.channels[cid]
        st.in_flight = None
        st.in_flight_message_id = ""
        # Let messages that queued during the run go out on the next tick
        # without waiting another full debounce window from an old timestamp.
        return cid

    def expire(self) -> list[str]:
        now = self.clock()
        out = []
        for cid, st in self.channels.items():
            if st.in_flight is not None and now - st.in_flight_since > self.ttl_s:
                st.in_flight = None
                st.in_flight_message_id = ""
                out.append(cid)
        return out

    def active(self, channel_id: str) -> bool:
        st = self.channels.get(channel_id)
        return bool(st and (st.buffer or st.in_flight is not None))
