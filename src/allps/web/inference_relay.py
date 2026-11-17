"""Authenticated, bounded OpenAI-compatible relay to a loopback LM Studio server.

Publish this relay through an HTTPS tunnel, never LM Studio's unrestricted API.
Configuration belongs in an ignored .env file, not browser code or CLI arguments.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hmac
import logging
import os
import time
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger("uvicorn.error")
_UPSTREAM = "http://127.0.0.1:1234/v1"
_BODY_LIMIT = 256 * 1024


class _Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=200_000)


class _Completion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    messages: list[_Message] = Field(min_length=1, max_length=16)
    temperature: float = Field(default=0.0, ge=0, le=2)
    max_tokens: int = Field(default=2048, ge=1, le=4096)
    response_format: dict | None = None
    stream: Literal[False] = False


def create_relay_app(*, upstream_transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    key = os.environ.get("ALLPS_LOCAL_RELAY_KEY", "")
    model = os.environ.get("ALLPS_LOCAL_MODEL", "").strip()
    if len(key) < 32 or not model:
        raise ValueError("Set ALLPS_LOCAL_RELAY_KEY (32+ characters) and ALLPS_LOCAL_MODEL")
    upstream_key = os.environ.get("ALLPS_LOCAL_UPSTREAM_KEY", "not-needed")
    busy = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            transport=upstream_transport,
            timeout=httpx.Timeout(180, connect=5),
            headers={"Authorization": f"Bearer {upstream_key}"},
            follow_redirects=False,
            trust_env=False,
        ) as client:
            app.state.upstream = client
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def authorize(request: Request):
        scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.encode(), key.encode()):
            raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})

    async def forward(method: str, path: str, payload: dict | None = None):
        try:
            response = await app.state.upstream.request(method, f"{_UPSTREAM}{path}", json=payload)
        except httpx.TimeoutException:
            raise HTTPException(504, "Local model timed out") from None
        except httpx.HTTPError:
            raise HTTPException(502, "Local model is unavailable") from None
        if response.status_code in (401, 403):
            raise HTTPException(503, "Local model authentication needs attention")
        if response.status_code != 200:
            raise HTTPException(502, f"Local model returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise HTTPException(502, "Local model returned an invalid response") from None
        if not isinstance(data, dict):
            raise HTTPException(502, "Local model returned an invalid response")
        return data

    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    @app.get("/v1/models")
    async def models(request: Request):
        authorize(request)
        data = await forward("GET", "/models")
        selected = [entry for entry in data.get("data", []) if isinstance(entry, dict) and entry.get("id") == model]
        if not selected:
            raise HTTPException(503, "Configured local model is not loaded")
        return {"object": "list", "data": [{"id": model, "object": "model", "owned_by": "local"}]}

    @app.post("/v1/chat/completions")
    async def complete(request: Request):
        authorize(request)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > _BODY_LIMIT:
                raise HTTPException(413, "Request too large")
        try:
            payload = _Completion.model_validate_json(bytes(raw))
        except ValidationError:
            # Validation errors can contain the submitted learner payload.
            raise HTTPException(400, "Invalid completion request") from None
        if payload.model != model:
            raise HTTPException(400, "Requested model is not permitted")
        if busy.locked():
            raise HTTPException(429, "Local model is busy", headers={"Retry-After": "5"})
        started = time.monotonic()
        async with busy:
            data = await forward("POST", "/chat/completions", payload.model_dump(exclude_none=True))
        if not data.get("choices"):
            raise HTTPException(502, "Local model returned no completion")
        logger.info("Local inference completed: model=%s duration=%.2fs", model, time.monotonic() - started)
        return JSONResponse(data)

    return app
