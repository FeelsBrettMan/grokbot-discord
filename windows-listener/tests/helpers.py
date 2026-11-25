from discord_bridge.models import IncomingMessage


def make_msg(**overrides) -> IncomingMessage:
    base = dict(
        message_id="100",
        channel_id="2",
        guild_id="1",
        author_id="3",
        author_name="Brett",
        content="hello",
        mention_user_ids=frozenset(),
    )
    base.update(overrides)
    return IncomingMessage(**base)
