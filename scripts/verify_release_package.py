"""Verify the release wheel outside the source tree using installed dependencies.

Build first: python -m pip wheel . --no-deps --wheel-dir tmp/release-wheel
This checks packaging and hosted startup; it makes no inference request.
"""
import asyncio
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import zipfile

root = Path(__file__).resolve().parents[1]
wheel = root / "tmp/release-wheel/allps-0.1.0-py3-none-any.whl"


async def check():
    import httpx
    import allps.web.app as app_module
    from allps.web.deployment import create_hosted_app
    assert Path(app_module.__file__).is_relative_to(package_dir), app_module.__file__
    app = create_hosted_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
            assert (await client.get("/healthz")).status_code == 200
            assert (await client.get("/")).status_code == 200
            assert (await client.get("/static/app.js")).status_code == 200
            assert (await client.get("/api/learners")).status_code == 401
            response = await client.post("/api/auth/login", json={"teacher_id": "TCH-OCHIENG", "pin": password})
            assert response.status_code == 200, response.text
            assert len((await client.get("/api/learners")).json()) == 3
            assert (await client.get("/api/config")).json()["hosted"]
    print("Packaged hosted app: startup, synthetic seed, static assets, authentication and 3 learners passed.")


with tempfile.TemporaryDirectory(prefix="allps-wheel-") as directory:
    package_dir = Path(directory)
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(package_dir)
    os.chdir(package_dir)
    sys.path[:] = [str(package_dir)] + [p for p in sys.path if p and Path(p).resolve() not in {root, root / "src"}]
    password = secrets.token_urlsafe(24)
    os.environ.update({
        "ALLPS_SESSION_SECRET": secrets.token_urlsafe(48),
        "ALLPS_DB_PATH": str(package_dir / "demo.db"),
        "ALLPS_AI_BASE_URL": "https://api.tokenlab.amd.com/v1",
        "ALLPS_AI_MODEL": "Gemma-4-31B-IT",
        "ALLPS_AI_API_KEY": "not-used-in-package-smoke-check",
        "ALLPS_SYNTHETIC_DEMO": "true",
        "ALLPS_TEACHERS_JSON": json.dumps([
            {"teacher_id": f"TCH-{name}", "display_name": name, "password": password}
            for name in ("OCHIENG", "BANDA", "WANJIKU", "OTIENO", "KAMAU")
        ]),
    })
    try:
        asyncio.run(check())
    finally:
        os.chdir(root)
