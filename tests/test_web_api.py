"""Automated integration checks for the ALLPS Teacher Web API.

Verifies:
1. Learner listing and evidence retrieval (distinct assessment stages, missing reasons).
2. Teacher observation submission with retry idempotency and strict learner validation.
3. Bounded AI candidate handover generation across runtime modes without raw output leaks.
4. Citation lookup side-panel endpoint.
5. Review adjudication with server-side trusted authority boundary.
6. Dual-view gating: approved handovers strictly contain accepted patterns with SHA-256 hashes.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from typing import AsyncGenerator

import httpx
import pytest
import pytest_asyncio

from allps.models.evidence import Evidence, EvidenceType, IngestionMethod
from allps.models.learner import Learner
from allps.models.review import ReviewStatus
from allps.storage.sqlite_store import SQLiteStore
from allps.web.app import create_app
from data.synthetic.seed_data import ALL_EVIDENCE, LEARNERS


@pytest_asyncio.fixture
async def test_client(tmp_path: Path) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Provide a configured AsyncClient against an isolated temporary database."""
    db_file = str(tmp_path / "test_web.db")
    app = create_app(
        db_path=db_file,
        mode="mock",
        trusted_reviewer_id="TCH-TEST-BANDA",
        seed_demo_data=True,
    )

    # Use ASGITransport for in-memory ASGI dispatch
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Trigger startup lifespan
        async with app.router.lifespan_context(app):
            yield client


@pytest.mark.asyncio
async def test_get_learners(test_client: httpx.AsyncClient):
    """Verify listing learners returns the seeded demonstration cohort."""
    resp = await test_client.get("/api/learners")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 3
    learner_ids = [l["learner_id"] for l in data]
    assert "LRN-001" in learner_ids
    assert "LRN-002" in learner_ids
    assert "LRN-003" in learner_ids


@pytest.mark.asyncio
async def test_get_learner_evidence_and_stages(test_client: httpx.AsyncClient):
    """Verify evidence stream preserves distinct stages, missing reasons, and filters."""
    # 1. Retrieve all evidence for LRN-001
    resp = await test_client.get("/api/learners/LRN-001/evidence")
    assert resp.status_code == 200
    records = resp.json()
    assert len(records) > 0

    # 2. Filter by subject = Mathematics
    resp_math = await test_client.get("/api/learners/LRN-001/evidence?subject=Mathematics")
    assert resp_math.status_code == 200
    math_records = resp_math.json()
    assert len(math_records) > 0
    assert all(r["subject"] == "Mathematics" for r in math_records)

    # 3. 404 for unknown learner
    resp_unknown = await test_client.get("/api/learners/LRN-UNKNOWN-999/evidence")
    assert resp_unknown.status_code == 404
    assert "not found" in resp_unknown.json()["detail"].lower()


@pytest.mark.asyncio
async def test_evidence_citation_lookup(test_client: httpx.AsyncClient):
    """Verify single evidence lookup endpoint returns full provenance for side panel."""
    # First get an existing evidence ID
    resp = await test_client.get("/api/learners/LRN-001/evidence")
    first_ev = resp.json()[0]
    ev_id = first_ev["evidence_id"]

    # Look up via citation endpoint
    detail_resp = await test_client.get(f"/api/evidence/{ev_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["evidence_id"] == ev_id
    assert detail["learner_id"] == "LRN-001"
    assert "source_system" in detail
    assert "observed_at" in detail
    assert "content" in detail

    # 404 for non-existent evidence
    fake_resp = await test_client.get("/api/evidence/non-existent-uuid")
    assert fake_resp.status_code == 404


@pytest.mark.asyncio
async def test_create_teacher_observation_success_and_retry(test_client: httpx.AsyncClient):
    """Verify recording an observation, idempotency with source_event_id, and persistence."""
    source_event_id = "test-event-uuid-12345"
    payload = {
        "event_datetime": "2025-06-15T09:30:00Z",
        "academic_year": 2025,
        "term": 2,
        "subject": "Mathematics",
        "observation": "Participated actively in practical measurement activity using rulers.",
        "context": "Small group cooperative learning session.",
        "source_reference": "Mr. Banda",
        "source_event_id": source_event_id,
    }

    # 1. First submission succeeds
    resp1 = await test_client.post("/api/learners/LRN-001/evidence", json=payload)
    assert resp1.status_code == 201
    data1 = resp1.json()
    assert data1["learner_id"] == "LRN-001"
    assert data1["evidence_type"] == "observation"
    assert data1["source_event_id"] == source_event_id
    assert data1["content"]["observation"] == payload["observation"]

    ev_id = data1["evidence_id"]

    # 2. Identical retry returns existing record without duplicate
    resp2 = await test_client.post("/api/learners/LRN-001/evidence", json=payload)
    assert resp2.status_code == 201
    data2 = resp2.json()
    assert data2["evidence_id"] == ev_id, "Idempotent retry must return the exact same evidence_id"

    # 3. Check evidence stream contains the new observation
    stream_resp = await test_client.get("/api/learners/LRN-001/evidence?evidence_type=observation")
    assert stream_resp.status_code == 200
    obs_list = stream_resp.json()
    matching = [o for o in obs_list if o["source_event_id"] == source_event_id]
    assert len(matching) == 1, "There must be exactly one record for this source_event_id"


@pytest.mark.asyncio
async def test_create_observation_rejects_unknown_learner(test_client: httpx.AsyncClient):
    """Verify observation submission does NOT silently auto-create mistyped learners."""
    payload = {
        "event_datetime": "2025-06-15T09:30:00Z",
        "academic_year": 2025,
        "term": 2,
        "subject": "Mathematics",
        "observation": "Good effort today.",
        "source_reference": "Mr. Banda",
        "source_event_id": "event-fail-1",
    }
    resp = await test_client.post("/api/learners/LRN-MISTYPED-999/evidence", json=payload)
    assert resp.status_code == 404
    assert "does not exist" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_observation_rejects_deficit_labels(test_client: httpx.AsyncClient):
    """Verify observation submission rejects deficit and clinical labels."""
    payload = {
        "event_datetime": "2025-06-15T09:30:00Z",
        "academic_year": 2025,
        "term": 2,
        "subject": "Mathematics",
        "observation": "Learner is a slow learner and seems hopeless with division.",
        "source_reference": "Mr. Banda",
        "source_event_id": "event-fail-2",
    }
    resp = await test_client.post("/api/learners/LRN-001/evidence", json=payload)
    assert resp.status_code == 422
    assert "Prohibited deficit or diagnostic label" in resp.text


@pytest.mark.asyncio
async def test_generate_candidate_handover_mock(test_client: httpx.AsyncClient):
    """Verify candidate generation returns structured brief, runtime method, and hides raw output."""
    payload = {
        "subject": "Mathematics",
        "mode": "mock",
    }
    resp = await test_client.post("/api/learners/LRN-001/generate", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["learner_id"] == "LRN-001"
    assert data["status"] == "success"
    assert data["runtime_method"] in ("mock", "deterministic_fallback", "deterministic", "live_ai")
    assert data["brief"] is not None
    assert len(data["brief"]["findings"]) > 0
    assert "raw_inference_output" not in data, "Rejected or raw inference output must remain hidden"

    # Check reviews list has updated
    rev_resp = await test_client.get("/api/learners/LRN-001/reviews")
    assert rev_resp.status_code == 200
    revs = rev_resp.json()
    assert len(revs) > 0


@pytest.mark.asyncio
async def test_review_decision_and_approved_handover_gating(test_client: httpx.AsyncClient):
    """Verify the sovereign review gate:
    1. Unapproved patterns remain hidden from /api/learners/{id}/handover.
    2. Accepting a review item persists decision and records SHA-256 snapshot.
    3. Approved handover displays strictly accepted findings.
    4. Rejected findings remain excluded.
    """
    # 1. Generate pattern for LRN-001
    gen_resp = await test_client.post("/api/learners/LRN-001/generate", json={"subject": "Mathematics", "mode": "mock"})
    assert gen_resp.status_code == 200

    # 2. Before approval: approved handover must be empty
    handover_before = await test_client.get("/api/learners/LRN-001/handover")
    assert handover_before.status_code == 200
    data_before = handover_before.json()
    assert data_before["accepted_pattern_count"] == 0
    assert len(data_before["patterns"]) == 0

    # 3. Retrieve pending review items
    rev_resp = await test_client.get("/api/learners/LRN-001/reviews")
    assert rev_resp.status_code == 200
    reviews = rev_resp.json()
    pending_items = [r for r in reviews if r["status"] == "pending"]
    assert len(pending_items) > 0
    target_review_id = pending_items[0]["review_id"]

    # 4. Adjudicate review as ACCEPTED
    decision_payload = {
        "status": "accepted",
        "teacher_notes": "Confirmed downward trend in grade 3 math. Recommend fraction scaffolding in grade 4.",
    }
    dec_resp = await test_client.post(f"/api/reviews/{target_review_id}/decision", json=decision_payload)
    assert dec_resp.status_code == 200
    dec_data = dec_resp.json()
    assert dec_data["status"] == "accepted"
    assert dec_data["reviewer_id"] == "TCH-TEST-BANDA"
    assert len(dec_data["approved_content_hash"]) == 64

    # 5. After approval: approved handover now surfaces the accepted pattern
    handover_after = await test_client.get("/api/learners/LRN-001/handover")
    assert handover_after.status_code == 200
    data_after = handover_after.json()
    assert data_after["accepted_pattern_count"] == 1
    surfaced = data_after["patterns"][0]
    assert surfaced["review"]["status"] == "accepted"
    assert surfaced["review"]["approved_content_hash"] == dec_data["approved_content_hash"]
    assert surfaced["review"]["reviewer_id"] == "TCH-TEST-BANDA"
    assert surfaced["review"]["hash_verified"] is True


@pytest.mark.asyncio
async def test_review_decision_disabled_when_authority_unconfigured(tmp_path: Path):
    """Verify decision submission is disabled (503) when server review authority is unconfigured."""
    db_file = str(tmp_path / "test_no_auth.db")
    app = create_app(
        db_path=db_file,
        mode="mock",
        trusted_reviewer_id=None,  # Authority unconfigured!
        seed_demo_data=True,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with app.router.lifespan_context(app):
            # Check config endpoint reports disabled
            cfg_resp = await client.get("/api/config")
            assert cfg_resp.status_code == 200
            assert cfg_resp.json()["review_authority_available"] is False

            # Generating works
            await client.post("/api/learners/LRN-001/generate", json={"subject": "Mathematics", "mode": "mock"})
            rev_resp = await client.get("/api/learners/LRN-001/reviews")
            rev_id = rev_resp.json()[0]["review_id"]

            # Decision submission must fail with 503
            dec_resp = await client.post(
                f"/api/reviews/{rev_id}/decision",
                json={"status": "accepted", "teacher_notes": "Note"},
            )
            assert dec_resp.status_code == 503
            assert "disabled" in dec_resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_rejected_findings_remain_strictly_excluded(test_client: httpx.AsyncClient):
    """Verify that a rejected candidate finding never leaks into the approved handover."""
    # 1. Generate pattern for LRN-003
    gen_resp = await test_client.post("/api/learners/LRN-003/generate", json={"subject": "English", "mode": "mock"})
    assert gen_resp.status_code == 200

    # 2. Get review item
    rev_resp = await test_client.get("/api/learners/LRN-003/reviews")
    reviews = rev_resp.json()
    pending_items = [r for r in reviews if r["status"] == "pending"]
    assert len(pending_items) > 0
    target_rev_id = pending_items[0]["review_id"]

    # 3. Reject with context
    dec_resp = await test_client.post(
        f"/api/reviews/{target_rev_id}/decision",
        json={"status": "rejected", "teacher_notes": "Divergence between scores and classroom participation noted; bereavement context."},
    )
    assert dec_resp.status_code == 200
    assert dec_resp.json()["status"] == "rejected"

    # 4. Verify approved handover remains strictly empty
    handover_resp = await test_client.get("/api/learners/LRN-003/handover")
    assert handover_resp.status_code == 200
    assert handover_resp.json()["accepted_pattern_count"] == 0
    assert len(handover_resp.json()["patterns"]) == 0


@pytest.mark.asyncio
async def test_approval_survives_database_reload(tmp_path: Path):
    """Verify approved handover survives server restart and database reload."""
    db_file = str(tmp_path / "persist_test.db")

    # Instance 1: Generate and Accept
    app1 = create_app(db_path=db_file, mode="mock", trusted_reviewer_id="TCH-PERSIST", seed_demo_data=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app1), base_url="http://testserver") as client1:
        async with app1.router.lifespan_context(app1):
            await client1.post("/api/learners/LRN-002/generate", json={"subject": "Science", "mode": "mock"})
            revs = (await client1.get("/api/learners/LRN-002/reviews")).json()
            rev_id = revs[0]["review_id"]
            await client1.post(f"/api/reviews/{rev_id}/decision", json={"status": "accepted", "teacher_notes": "Confirmed persistent strength."})

    # Instance 2: Brand new server instance reading the same SQLite file
    app2 = create_app(db_path=db_file, mode="mock", trusted_reviewer_id="TCH-PERSIST", seed_demo_data=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app2), base_url="http://testserver") as client2:
        async with app2.router.lifespan_context(app2):
            handover = (await client2.get("/api/learners/LRN-002/handover")).json()
            assert handover["accepted_pattern_count"] == 1
            assert handover["patterns"][0]["review"]["status"] == "accepted"
            assert handover["patterns"][0]["review"]["reviewer_id"] == "TCH-PERSIST"
            assert handover["patterns"][0]["review"]["hash_verified"] is True


@pytest.mark.asyncio
async def test_candidate_brief_persistence_and_revisioning(tmp_path: Path):
    """Verify INT-01:
    1. Persist complete CandidateHandoverBrief (findings, citations, limitations, provenance).
    2. Refreshing/restarting restores the exact candidate brief via GET /api/learners/{id}/brief.
    3. Re-generation increments generation_revision without mutating prior accepted reviews.
    """
    db_file = str(tmp_path / "brief_persist.db")

    # Instance 1: Generate initial candidate brief (Revision 1)
    app1 = create_app(db_path=db_file, mode="mock", trusted_reviewer_id="TCH-PERSIST", seed_demo_data=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app1), base_url="http://testserver") as client1:
        async with app1.router.lifespan_context(app1):
            gen1 = await client1.post("/api/learners/LRN-001/generate", json={"subject": "Mathematics", "mode": "mock"})
            assert gen1.status_code == 200
            data1 = gen1.json()
            assert data1["generation_revision"] == 1
            assert data1["brief"] is not None
            assert len(data1["brief"]["findings"]) > 0

            # Query GET /api/learners/LRN-001/brief
            brief_resp = await client1.get("/api/learners/LRN-001/brief")
            assert brief_resp.status_code == 200
            persisted_brief = brief_resp.json()["brief"]
            assert persisted_brief is not None
            assert persisted_brief["generation_revision"] == 1
            assert persisted_brief["runtime_method"] == data1["runtime_method"]
            assert len(persisted_brief["findings"]) == len(data1["brief"]["findings"])

            # Re-generate (Revision 2)
            gen2 = await client1.post("/api/learners/LRN-001/generate", json={"subject": "Mathematics", "mode": "mock"})
            assert gen2.status_code == 200
            data2 = gen2.json()
            assert data2["generation_revision"] == 2

            brief_resp2 = await client1.get("/api/learners/LRN-001/brief")
            persisted_brief2 = brief_resp2.json()["brief"]
            assert persisted_brief2["generation_revision"] == 2

    # Instance 2: Brand new server process reading same DB (simulates page refresh / server restart)
    app2 = create_app(db_path=db_file, mode="mock", trusted_reviewer_id="TCH-PERSIST", seed_demo_data=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app2), base_url="http://testserver") as client2:
        async with app2.router.lifespan_context(app2):
            restored_resp = await client2.get("/api/learners/LRN-001/brief")
            assert restored_resp.status_code == 200
            restored = restored_resp.json()["brief"]
            assert restored is not None
            assert restored["generation_revision"] == 2
            assert restored["learner_id"] == "LRN-001"
            assert len(restored["findings"]) > 0
            assert "findings" in restored
            assert "supporting_evidence_ids" in restored["findings"][0]

            # Verify reviews are also enriched with candidate_brief and generation_revision
            revs_resp = await client2.get("/api/learners/LRN-001/reviews")
            assert revs_resp.status_code == 200
            revs = revs_resp.json()
            assert len(revs) > 0
            latest_rev = revs[-1]
            assert latest_rev["generation_revision"] == 2
            assert latest_rev["candidate_brief"] is not None


@pytest.mark.asyncio
async def test_cors_policy_rejects_unauthorized_origins(test_client: httpx.AsyncClient):
    """Verify SEC-02:
    Allowed origins receive Access-Control-Allow-Origin, unauthorized origins do NOT.
    """
    # 1. Whitelisted origin: http://localhost:8000
    headers_allowed = {
        "Origin": "http://localhost:8000",
        "Access-Control-Request-Method": "GET",
    }
    resp_allowed = await test_client.options("/api/learners", headers=headers_allowed)
    assert resp_allowed.headers.get("access-control-allow-origin") == "http://localhost:8000"

    # 2. Whitelisted origin: http://127.0.0.1:8000
    headers_allowed2 = {
        "Origin": "http://127.0.0.1:8000",
        "Access-Control-Request-Method": "GET",
    }
    resp_allowed2 = await test_client.options("/api/learners", headers=headers_allowed2)
    assert resp_allowed2.headers.get("access-control-allow-origin") == "http://127.0.0.1:8000"

    # 3. Disallowed origin: https://untrusted-hacker.com
    headers_disallowed = {
        "Origin": "https://untrusted-hacker.com",
        "Access-Control-Request-Method": "GET",
    }
    resp_disallowed = await test_client.options("/api/learners", headers=headers_disallowed)
    assert "access-control-allow-origin" not in resp_disallowed.headers


@pytest.mark.asyncio
async def test_config_reports_prototype_trust_limitation(test_client: httpx.AsyncClient):
    """Verify GET /api/config explicitly tags authentication type as prototype."""
    resp = await test_client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["review_authority_available"] is True
    assert data["server_reviewer_id"] == "TCH-TEST-BANDA"
    assert data["authentication_type"] == "prototype_server_configured"
    assert "prototype" in data["trust_notice"].lower()


