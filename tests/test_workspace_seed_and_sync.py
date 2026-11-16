"""Tests for idempotent CLI seeding, DB status diagnostics, and UI reseed/reset endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from allps.models.learner import Learner
from allps.storage.sqlite_store import SQLiteStore
from allps.web.app import create_app
from data.synthetic.seed_data import ALL_EVIDENCE, LEARNERS, seed_database


@pytest.mark.asyncio
async def test_seed_database_is_idempotent_and_supports_reset(tmp_path: Path):
    """Running seed_database repeatedly never raises IntegrityError; reset=True restores clean state."""
    db_file = str(tmp_path / "idempotent_seed.db")

    first = await seed_database(db_file)
    assert first["learners_added"] == len(LEARNERS)
    assert first["learners_skipped"] == 0
    assert first["evidence_added"] == len(ALL_EVIDENCE)
    assert first["evidence_skipped"] == 0

    # Second run against already-seeded DB must skip cleanly without IntegrityError
    second = await seed_database(db_file)
    assert second["learners_added"] == 0
    assert second["learners_skipped"] == len(LEARNERS)
    assert second["evidence_added"] == 0
    assert second["evidence_skipped"] == len(ALL_EVIDENCE)
    assert second["total_learners"] == len(LEARNERS)
    assert second["total_evidence"] == len(ALL_EVIDENCE)

    # Add custom learner directly, verify merge preserves it and reset clears it
    store = SQLiteStore(db_file)
    await store.initialize()
    try:
        await store.add_learner(Learner(learner_id="LRN-CUSTOM", display_name="Custom Learner"))
        status_before_reset = await store.get_database_status()
        assert status_before_reset["learners_count"] == len(LEARNERS) + 1
    finally:
        await store.close()

    reset_summary = await seed_database(db_file, reset=True)
    assert reset_summary["reset"] is True
    assert reset_summary["learners_added"] == len(LEARNERS)
    assert reset_summary["evidence_added"] == len(ALL_EVIDENCE)
    assert reset_summary["total_learners"] == len(LEARNERS)
    assert reset_summary["total_evidence"] == len(ALL_EVIDENCE)


@pytest.mark.asyncio
async def test_web_db_status_seed_merge_and_reset_flow(tmp_path: Path):
    """Starting from an empty DB, UI/API can inspect status, seed missing data, detect new observations, and reset."""
    db_file = str(tmp_path / "workspace_sync.db")
    app = create_app(db_path=db_file, mode="mock", seed_demo_data=False)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with app.router.lifespan_context(app):
            # 1. Starts empty when seed_demo_data=False
            empty_status = await client.get("/api/db/status")
            assert empty_status.status_code == 200
            empty_data = empty_status.json()
            assert empty_data["db_name"] == "workspace_sync.db"
            assert empty_data["learners_count"] == 0
            assert empty_data["evidence_count"] == 0
            assert empty_data["has_demo_learners"] is False

            # 2. Seed missing demo data via UI/API (merge mode)
            merge_resp = await client.post("/api/db/reseed", json={"mode": "merge"})
            assert merge_resp.status_code == 200
            merge_data = merge_resp.json()
            assert merge_data["learners_added"] == len(LEARNERS)
            assert merge_data["evidence_added"] == len(ALL_EVIDENCE)
            assert merge_data["db_status"]["has_demo_learners"] is True

            # 3. Re-running merge skips all existing without error
            merge_again = await client.post("/api/db/reseed", json={"mode": "merge"})
            assert merge_again.status_code == 200
            assert merge_again.json()["learners_added"] == 0
            assert merge_again.json()["evidence_added"] == 0

            # 4. Record a new observation and confirm /api/db/status surfaces it in recent_evidence
            obs_resp = await client.post(
                "/api/learners/LRN-001/evidence",
                json={
                    "event_datetime": datetime(2025, 10, 2, 9, 30, tzinfo=timezone.utc).isoformat(),
                    "academic_year": 2025,
                    "term": 3,
                    "subject": "Mathematics",
                    "observation": "Learner worked through fraction manipulatives with partner.",
                    "source_reference": "Mr. Banda",
                    "source_event_id": "SYNC-TEST-OBS-1",
                },
            )
            assert obs_resp.status_code == 201
            obs_id = obs_resp.json()["evidence_id"]

            updated_status = await client.get("/api/db/status")
            assert updated_status.status_code == 200
            upd_data = updated_status.json()
            assert upd_data["evidence_count"] == len(ALL_EVIDENCE) + 1
            assert upd_data["recent_evidence"][0]["evidence_id"] == obs_id

            # 5. Merge still preserves the newly added observation
            merge_preserve = await client.post("/api/db/reseed", json={"mode": "merge"})
            assert merge_preserve.status_code == 200
            assert merge_preserve.json()["total_evidence"] == len(ALL_EVIDENCE) + 1

            # 6. Reset clears custom observation & restores baseline demo counts, preserving teacher login
            reset_resp = await client.post("/api/db/reseed", json={"mode": "reset"})
            assert reset_resp.status_code == 200
            reset_data = reset_resp.json()
            assert reset_data["total_learners"] == len(LEARNERS)
            assert reset_data["total_evidence"] == len(ALL_EVIDENCE)

            login_resp = await client.post(
                "/api/auth/login", json={"teacher_id": "TCH-BANDA", "pin": "1234"}
            )
            assert login_resp.status_code == 200

            # 7. Root HTML renders sync, seed, and reset confirmation dialog controls
            index_resp = await client.get("/")
            assert index_resp.status_code == 200
            html = index_resp.text
            assert 'id="btn-refresh-data"' in html
            assert 'id="btn-seed-merge"' in html
            assert 'id="reset-db-dialog"' in html
            assert 'id="workspace-status-banner"' in html


@pytest.mark.asyncio
async def test_web_reseed_blocked_when_disabled(tmp_path: Path):
    """Verify POST /api/db/reseed returns 403 when allow_demo_reset=False."""
    db_file = str(tmp_path / "locked_workspace.db")
    app = create_app(
        db_path=db_file,
        mode="mock",
        seed_demo_data=False,
        allow_demo_reset=False,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with app.router.lifespan_context(app):
            status_resp = await client.get("/api/db/status")
            assert status_resp.status_code == 200
            assert status_resp.json()["allow_demo_reset"] is False

            reseed_resp = await client.post("/api/db/reseed", json={"mode": "merge"})
            assert reseed_resp.status_code == 403


@pytest.mark.asyncio
async def test_web_autoseed_resolves_repo_root_outside_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Console entrypoints (e.g. allps-web) must auto-seed even without repo root in sys.path."""
    repo_root = str(Path(__file__).resolve().parent.parent)
    filtered_path = [p for p in sys.path if Path(p or ".").resolve() != Path(repo_root)]
    monkeypatch.setattr(sys, "path", filtered_path)
    sys.modules.pop("data.synthetic.seed_data", None)
    sys.modules.pop("data.synthetic", None)
    sys.modules.pop("data", None)

    db_file = str(tmp_path / "console_entrypoint_autoseed.db")
    app = create_app(db_path=db_file, mode="mock", seed_demo_data=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/api/db/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["learners_count"] == len(LEARNERS)
            assert data["evidence_count"] == len(ALL_EVIDENCE)


def test_seed_data_cli_positional_and_status(tmp_path: Path):
    """CLI seeding accepts positional db_path and --status without error."""
    repo_root = Path(__file__).resolve().parent.parent
    db_file = tmp_path / "cli_seed.db"

    res_seed = subprocess.run(
        [sys.executable, "-m", "data.synthetic.seed_data", str(db_file)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res_seed.returncode == 0, res_seed.stderr
    assert "Learners: +3 added" in res_seed.stdout

    res_status = subprocess.run(
        [sys.executable, "-m", "data.synthetic.seed_data", "--status", str(db_file)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res_status.returncode == 0, res_status.stderr
    assert "Learners: 3 | Evidence: 27" in res_status.stdout


def test_example_runners_avoid_seed_type_error_and_trace_overwrite():
    """Verify run_live_lmstudio uses seed_store and MCP runners default traces under tmp/."""
    repo_root = Path(__file__).resolve().parent.parent

    live_src = (repo_root / "examples" / "run_live_lmstudio.py").read_text(encoding="utf-8")
    assert "seed_database(store)" not in live_src
    assert "await seed_store(store" in live_src

    mcp_runner_src = (repo_root / "examples" / "run_agentic_mcp_import.py").read_text(encoding="utf-8")
    assert 'default="data/trace_agentic_mcp_run.json"' not in mcp_runner_src
    assert '"tmp"' in mcp_runner_src

    mcp_agent_src = (repo_root / "src" / "allps" / "agent" / "mcp_agent.py").read_text(encoding="utf-8")
    assert 'default="data/trace_agentic_mcp_run.json"' not in mcp_agent_src
    assert 'Path("tmp") / "traces"' in mcp_agent_src
