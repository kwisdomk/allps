"""Public relay must authenticate before forwarding and expose only bounded inference."""
import asyncio

import httpx
import pytest

from allps.web.inference_relay import create_relay_app


@pytest.mark.asyncio
async def test_relay_restricts_access_payloads_models_and_routes(monkeypatch):
    key = "relay-secret-" * 4
    monkeypatch.setenv("ALLPS_LOCAL_RELAY_KEY", key)
    monkeypatch.setenv("ALLPS_LOCAL_MODEL", "qwen3.5-4b")
    monkeypatch.setenv("ALLPS_LOCAL_UPSTREAM_KEY", "private-lm-studio-token")
    calls = []

    async def upstream(request):
        calls.append(request)
        assert request.url.host == "127.0.0.1"
        assert request.headers["authorization"] == "Bearer private-lm-studio-token"
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "qwen3.5-4b"}, {"id": "other-private-model"}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})

    app = create_relay_app(upstream_transport=httpx.MockTransport(upstream))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay") as client:
            assert (await client.get("/healthz")).status_code == 200
            assert (await client.get("/v1/models")).status_code == 401
            assert (await client.get("/v1/models", headers={"Authorization": "Bearer wrong"})).status_code == 401
            assert (await client.post("/v1/chat/completions", json={})).status_code == 401
            assert calls == []
            client.headers["Authorization"] = f"Bearer {key}"
            models = await client.get("/v1/models")
            assert [model["id"] for model in models.json()["data"]] == ["qwen3.5-4b"]
            assert "private-lm-studio-token" not in models.text
            assert models.headers["cache-control"] == "no-store"
            for path in ("/api/v1/models/load", "/docs", "/openapi.json", "/v1/embeddings"):
                assert (await client.get(path)).status_code == 404
            request = {"model": "other-private-model", "messages": [{"role": "user", "content": "hello"}]}
            assert (await client.post("/v1/chat/completions", json=request)).status_code == 400
            request["model"] = "qwen3.5-4b"
            request["stream"] = True
            assert (await client.post("/v1/chat/completions", json=request)).status_code == 400
            response = await client.post("/v1/chat/completions", content=b"x" * (256 * 1024 + 1))
            assert response.status_code == 413
            assert len(calls) == 1
            request.pop("stream")
            response = await client.post("/v1/chat/completions", json=request)
            assert response.status_code == 200
            assert response.json()["choices"][0]["message"]["content"] == "pong"
            assert len(calls) == 2


@pytest.mark.asyncio
async def test_relay_limits_concurrency_and_hides_upstream_errors(monkeypatch):
    monkeypatch.setenv("ALLPS_LOCAL_RELAY_KEY", "relay-secret-" * 4)
    monkeypatch.setenv("ALLPS_LOCAL_MODEL", "qwen3.5-4b")
    entered, release = asyncio.Event(), asyncio.Event()

    async def upstream(request):
        entered.set()
        await release.wait()
        return httpx.Response(500, text="private model path and credentials")

    app = create_relay_app(upstream_transport=httpx.MockTransport(upstream))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay",
                                     headers={"Authorization": "Bearer " + "relay-secret-" * 4}) as client:
            payload = {"model": "qwen3.5-4b", "messages": [{"role": "user", "content": "hello"}]}
            first = asyncio.create_task(client.post("/v1/chat/completions", json=payload))
            await asyncio.wait_for(entered.wait(), 2)
            assert (await client.post("/v1/chat/completions", json=payload)).status_code == 429
            release.set()
            response = await first
            assert response.status_code == 502
            assert "private" not in response.text


def test_relay_refuses_missing_credentials(monkeypatch):
    monkeypatch.delenv("ALLPS_LOCAL_RELAY_KEY", raising=False)
    monkeypatch.setenv("ALLPS_LOCAL_MODEL", "qwen3.5-4b")
    with pytest.raises(ValueError, match="ALLPS_LOCAL_RELAY_KEY"):
        create_relay_app()
