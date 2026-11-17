"""Exercise web reads through store methods without exposing a raw connection."""
import httpx
import pytest

from allps.storage.sqlite_store import SQLiteStore
from allps.web import app as web_app


@pytest.mark.asyncio
async def test_web_startup_and_reads_do_not_require_raw_database_access(monkeypatch, tmp_path):
    class StoreFacade:
        def __init__(self, db_path):
            self._store = SQLiteStore(db_path)

        @property
        def db(self):
            raise AssertionError("The web layer must use store methods, not the database connection")

        def __getattr__(self, name):
            return getattr(self._store, name)

    monkeypatch.setattr(web_app, "SQLiteStore", StoreFacade)
    app = web_app.create_app(db_path=str(tmp_path / "boundary.db"), mode="mock")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            assert (await client.get("/healthz")).json() == {"status": "ok"}
            config = (await client.get("/api/config")).json()
            assert len(config["available_teachers"]) == 5
            assert all("pin_hash" not in teacher for teacher in config["available_teachers"])
            assert (await client.get("/api/learners")).status_code == 401

            login = await client.post("/api/auth/login", json={"teacher_id": "TCH-OCHIENG", "pin": "5678"})
            assert login.status_code == 200
            learners = (await client.get("/api/learners")).json()
            assert [learner["learner_id"] for learner in learners] == ["LRN-001", "LRN-002", "LRN-003"]
            records = (await client.get("/api/learners/LRN-003/evidence")).json()
            record = next(item for item in records if item["subject"] == "English")
            detail = await client.get(f"/api/evidence/{record['evidence_id']}")
            assert detail.status_code == 200
            expected = {key: value for key, value in record.items() if key not in {"score", "max_score"}}
            assert detail.json() == expected
            assert (await client.get("/api/evidence/does-not-exist")).status_code == 404

            login = await client.post("/api/auth/login", json={"teacher_id": "TCH-BANDA", "pin": "1234"})
            assert login.status_code == 200
            assert (await client.get(f"/api/evidence/{record['evidence_id']}")).status_code == 403
