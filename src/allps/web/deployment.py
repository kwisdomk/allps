"""Fail-closed hosted application factory for a single persistent server."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

from fastapi import Request
from fastapi.responses import JSONResponse

from allps.web.app import create_app


def create_hosted_app():
    if len(os.environ.get("ALLPS_SESSION_SECRET", "")) < 32:
        raise ValueError("Set ALLPS_SESSION_SECRET to at least 32 random characters")
    db_path = os.environ.get("ALLPS_DB_PATH", "")
    if not db_path or not Path(db_path).is_absolute():
        raise ValueError("ALLPS_DB_PATH must be an absolute path on persistent storage")
    accounts = json.loads(os.environ.get("ALLPS_TEACHERS_JSON", "[]"))
    if not isinstance(accounts, list) or not accounts:
        raise ValueError("ALLPS_TEACHERS_JSON must provision at least one educator account")
    teachers = []
    for account in accounts:
        teacher_id, name, password = (account.get(k, "") for k in ("teacher_id", "display_name", "password"))
        if not teacher_id or not name or not isinstance(password, str) or not 12 <= len(password) <= 64 or len(password.encode()) > 72:
            raise ValueError("Every educator needs an ID, name, and password of 12-72 UTF-8 bytes")
        teachers.append((teacher_id, name, password))
    demo = os.environ.get("ALLPS_SYNTHETIC_DEMO", "false").lower() == "true"
    if demo:
        required = {"TCH-OCHIENG", "TCH-BANDA", "TCH-WANJIKU", "TCH-OTIENO", "TCH-KAMAU"}
        if not required.issubset({t[0] for t in teachers}):
            raise ValueError("Synthetic demo requires all five assigned educator IDs with strong passwords")
    if not os.environ.get("ALLPS_AI_BASE_URL"):
        raise ValueError("Hosted deployments require ALLPS_AI_BASE_URL")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    app = create_app(db_path=db_path, mode="live", seed_demo_data=demo,
                     teacher_accounts=teachers, seed_school=demo,
                     allow_demo_reset=False, secure_cookies=True, hosted=True)
    attempts: dict[str, tuple[int, float]] = {}

    @app.middleware("http")
    async def hosted_security(request: Request, call_next):
        if request.url.path == "/api/auth/login" and request.method == "POST":
            now = time.monotonic()
            for host, (_, start) in list(attempts.items()):
                if now - start >= 60:
                    del attempts[host]
            host = request.client.host if request.client else "unknown"
            count, start = attempts.get(host, (0, now))
            if count >= 10:
                return JSONResponse({"detail": "Too many login attempts. Retry in one minute."},
                                    status_code=429, headers={"Retry-After": "60"})
            attempts[host] = (count + 1, start)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    return app
