"""Deployment boundaries: credentials, HTTPS sessions and actual provider selection."""
import json

import httpx
import pytest

from allps.runtime import ExecutionMode
from allps.runtime.discovery import ProviderDiscoveryService
from allps.runtime.registry import RuntimeRegistry
from allps.web.deployment import create_hosted_app


def configure(monkeypatch, tmp_path):
    monkeypatch.setenv("ALLPS_SESSION_SECRET", "test-session-secret-" * 3)
    monkeypatch.setenv("ALLPS_DB_PATH", str(tmp_path / "hosted.db"))
    monkeypatch.setenv("ALLPS_AI_BASE_URL", "https://api.tokenlab.amd.com/v1")
    monkeypatch.setenv("ALLPS_AI_API_KEY", "test-secret-never-client-side")
    monkeypatch.setenv("ALLPS_AI_MODEL", "Gemma-4-31B-IT")
    monkeypatch.setenv("ALLPS_SYNTHETIC_DEMO", "true")
    ids = ["OCHIENG", "BANDA", "WANJIKU", "OTIENO", "KAMAU"]
    monkeypatch.setenv("ALLPS_TEACHERS_JSON", json.dumps([
        {"teacher_id": f"TCH-{i}", "display_name": i, "password": "a-strong-demo-password"}
        for i in ids
    ]))


def test_hosted_refuses_missing_secret(monkeypatch):
    monkeypatch.delenv("ALLPS_SESSION_SECRET", raising=False)
    with pytest.raises(ValueError, match="SESSION_SECRET"):
        create_hosted_app()


@pytest.mark.asyncio
async def test_amd_discovery_and_probe_use_server_credentials(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    def handler(request):
        assert request.headers["Authorization"] == "Bearer test-secret-never-client-side"
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "Gemma-4-31B-IT"}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        registry = RuntimeRegistry(discovery_service=ProviderDiscoveryService(client=client))
        selection, adapter = await registry.select_runtime(ExecutionMode.LIVE)
        assert selection.model_id == "Gemma-4-31B-IT"
        assert selection.provider_name == "AMD Token Lab"
        assert adapter.api_key == "test-secret-never-client-side"
        assert "test-secret" not in str(selection)


@pytest.mark.asyncio
async def test_hosted_auth_and_storage_boundaries(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    app = create_hosted_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
            assert (await client.get("/healthz")).json() == {"status": "ok"}
            assert (await client.get("/api/learners")).status_code == 401
            bad = await client.post("/api/auth/login", json={"teacher_id": "TCH-OCHIENG", "pin": "5678"})
            assert bad.status_code == 401
            login = await client.post("/api/auth/login", json={"teacher_id": "TCH-OCHIENG", "pin": "a-strong-demo-password"})
            assert login.status_code == 200
            assert "Secure" in login.headers["set-cookie"]
            assert len((await client.get("/api/learners")).json()) == 3
            config = await client.get("/api/config")
            assert not config.json()["show_demo_credentials"]
            assert config.json()["hosted"]
            assert not config.json()["allow_demo_reset"]
            assert config.headers["cache-control"] == "no-store"
            assert "test-secret" not in config.text
            assert not app.state.allow_demo_reset
            for _ in range(8):
                await client.post("/api/auth/login", json={"teacher_id": "none", "pin": "0000"})
            assert (await client.post("/api/auth/login", json={"teacher_id": "none", "pin": "0000"})).status_code == 429


@pytest.mark.asyncio
async def test_hosted_generation_cannot_select_offline_runtime(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    app = create_hosted_app()
    seen_modes = []

    async def refuse_runtime(*, mode, mock_responses):
        seen_modes.append(mode)
        raise RuntimeError("Provider unavailable for this test")

    async with app.router.lifespan_context(app):
        monkeypatch.setattr(app.state.runtime_registry, "select_runtime", refuse_runtime)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
            await client.post("/api/auth/login", json={"teacher_id": "TCH-OCHIENG", "pin": "a-strong-demo-password"})
            for requested in ("mock", "deterministic", "auto"):
                response = await client.post("/api/learners/LRN-001/generate", json={"mode": requested})
                assert response.json()["status"] == "inference_failed"
                assert response.json()["runtime_method"] == "unavailable"
    assert seen_modes == ["live", "live", "live"]
