from aiohttp.test_utils import TestClient, TestServer

from grokbot_discord.callback import build_app


async def test_health_and_auth():
    seen = []

    async def on_reply(correlation_id, channel_id, message_id, text):
        seen.append((correlation_id, channel_id, message_id, text))
        return correlation_id == "x"

    app = build_app("s3cret", on_reply)
    async with TestClient(TestServer(app)) as client:
        health = await client.get("/health")
        assert health.status == 200
        denied = await client.post("/reply", json={"correlation_id": "x", "channel_id": "c"})
        assert denied.status == 401
        bad = await client.post(
            "/reply",
            json={"correlation_id": "x", "channel_id": "c", "message_id": "m", "text": "hi"},
            headers={"Authorization": "Bearer nope"},
        )
        assert bad.status == 401
        ok = await client.post(
            "/reply",
            json={"correlation_id": "x", "channel_id": "c", "message_id": "m", "text": "hi"},
            headers={"Authorization": "Bearer s3cret"},
        )
        assert ok.status == 200
        assert seen == [("x", "c", "m", "hi")]


async def test_unknown_correlation_rejected():
    async def on_reply(correlation_id, channel_id, message_id, text):
        return False

    app = build_app("s3cret", on_reply)
    async with TestClient(TestServer(app)) as client:
        resp = await client.post(
            "/reply",
            json={"correlation_id": "nope", "channel_id": "c", "message_id": "m", "text": "hi"},
            headers={"Authorization": "Bearer s3cret"},
        )
        assert resp.status == 404
