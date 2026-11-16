"""Regression coverage for feature/teacher-review-authority.

Scenarios:
  A. Valid authenticated teacher decision (accept, reject, needs_context)
  B. Unauthenticated request → 401
  C. Wrong PIN → 401
  D. MCP attempt to approve → PermissionError
  E. MCP non-approval verbs (reject, needs_context) still work
  F. Two concurrent human submissions for the same review (same revision) →
     exactly one 200 and one ConflictError (revision-based optimistic lock)
  G. Approved decision survives restart (handover after re-init)
  H. /api/auth/me returns teacher; /api/auth/logout clears it
  I. Deliberate teacher correction after reloading the updated review
  J. Stale correction (wrong expected_revision) → ConflictError
  K. MCP attempt using teacher-looking reviewer_id → blocked for corrections
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncGenerator

import httpx
import pytest
import pytest_asyncio

from allps.mcp.server import set_service
from allps.services.evidence_service import EvidenceService
from allps.services.review_service import ConflictError, ReviewService
from allps.storage.sqlite_store import SQLiteStore
from allps.web.app import create_app


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_app(db_file: str):
    return create_app(db_path=db_file, mode="mock", seed_demo_data=True)


async def _logged_in_client(app, teacher_id: str, pin: str) -> httpx.AsyncClient:
    """Return an AsyncClient with a valid session cookie."""
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return client


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def auth_client(tmp_path: Path) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Authenticated client (TCH-BANDA) with a seeded pending review."""
    db_file = str(tmp_path / "auth.db")
    app = _make_app(db_file)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with app.router.lifespan_context(app):
            r = await client.post("/api/auth/login", json={"teacher_id": "TCH-BANDA", "pin": "1234"})
            assert r.status_code == 200, r.text
            # Seed a pending review
            await client.post("/api/learners/LRN-001/generate", json={"mode": "mock"})
            yield client


# ─────────────────────────────────────────────────────────────────────────────
# A. Valid authenticated teacher decisions
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_accept_decision(auth_client: httpx.AsyncClient):
    """Authenticated teacher can accept a pending review."""
    rev_id = await _first_pending(auth_client, "LRN-001")
    resp = await auth_client.post(
        f"/api/reviews/{rev_id}/decision",
        json={"status": "accepted", "teacher_notes": "Solid longitudinal trend confirmed."},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["reviewer_id"] == "TCH-BANDA"
    assert len(data["approved_content_hash"]) == 64


@pytest.mark.asyncio
async def test_valid_reject_decision(tmp_path: Path):
    """Authenticated teacher can reject a pending review."""
    db_file = str(tmp_path / "rej.db")
    app = _make_app(db_file)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with app.router.lifespan_context(app):
            await client.post("/api/auth/login", json={"teacher_id": "TCH-OCHIENG", "pin": "5678"})
            await client.post("/api/learners/LRN-002/generate", json={"mode": "mock"})
            rev_id = await _first_pending(client, "LRN-002")
            resp = await client.post(
                f"/api/reviews/{rev_id}/decision",
                json={"status": "rejected", "teacher_notes": "Insufficient supporting evidence."},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "rejected"
            assert resp.json()["reviewer_id"] == "TCH-OCHIENG"


@pytest.mark.asyncio
async def test_valid_needs_context_decision(auth_client: httpx.AsyncClient):
    """Authenticated teacher can set needs_context."""
    rev_id = await _first_pending(auth_client, "LRN-001")
    resp = await auth_client.post(
        f"/api/reviews/{rev_id}/decision",
        json={"status": "needs_context", "teacher_notes": "Need term 3 record before deciding."},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "needs_context"


# ─────────────────────────────────────────────────────────────────────────────
# B. Unauthenticated request
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unauthenticated_decision_rejected(tmp_path: Path):
    """No session cookie → 401, not 200 or 422."""
    db_file = str(tmp_path / "unauth.db")
    app = _make_app(db_file)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with app.router.lifespan_context(app):
            await client.post("/api/learners/LRN-001/generate", json={"mode": "mock"})
            rev_id = await _first_pending(client, "LRN-001")
            resp = await client.post(
                f"/api/reviews/{rev_id}/decision",
                json={"status": "accepted"},
            )
            assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_requires_login(tmp_path: Path):
    """GET /api/auth/me returns 401 without a cookie."""
    db_file = str(tmp_path / "me.db")
    app = _make_app(db_file)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/api/auth/me")
            assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# C. Wrong PIN
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wrong_pin_rejected(tmp_path: Path):
    """Wrong PIN returns 401 and does not set a session."""
    db_file = str(tmp_path / "badpin.db")
    app = _make_app(db_file)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with app.router.lifespan_context(app):
            resp = await client.post(
                "/api/auth/login", json={"teacher_id": "TCH-BANDA", "pin": "wrong"}
            )
            assert resp.status_code == 401
            # /me must still be 401 — no cookie was set
            me = await client.get("/api/auth/me")
            assert me.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# D. MCP attempt to approve
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mcp_cannot_approve(tmp_path: Path):
    """MCP resolve_teacher_review with status='accepted' raises PermissionError."""
    import importlib
    mcp_server = importlib.import_module("allps.mcp.server")

    db_file = str(tmp_path / "mcp_block.db")
    store = SQLiteStore(db_file)
    await store.initialize()
    ev_service = EvidenceService(store)
    rev_service = ReviewService(store)
    set_service(ev_service, rev_service)

    with pytest.raises(PermissionError, match="MCP clients cannot approve"):
        await mcp_server.resolve_teacher_review(
            review_id="fake-review-id",
            status="accepted",
            reviewer_id="TCH-BANDA",
        )

    await store.close()


# ─────────────────────────────────────────────────────────────────────────────
# E. MCP non-approval verbs work
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mcp_can_reject(tmp_path: Path):
    """MCP may submit 'rejected' on a pending review."""
    import importlib
    mcp_server = importlib.import_module("allps.mcp.server")

    db_file = str(tmp_path / "mcp_reject.db")
    store = SQLiteStore(db_file)
    await store.initialize()
    from allps.models.learner import Learner
    learner = Learner(learner_id="LRN-MCP", display_name="Mcp Learner")
    await store.add_learner(learner)

    ev_service = EvidenceService(store)
    rev_service = ReviewService(store)
    set_service(ev_service, rev_service)

    # Seed a pattern + review item directly
    from allps.models.pattern import Pattern, PatternType
    from allps.models.review import ReviewItem, ReviewStatus
    import uuid

    pattern = Pattern(
        learner_id="LRN-MCP",
        pattern_type=PatternType.TREND,
        summary="Test pattern for MCP reject",
        supporting_evidence=[],
        conflicting_evidence=[],
        limitations=[],
    )
    await store.add_pattern(pattern)
    review = ReviewItem(pattern_id=pattern.pattern_id, status=ReviewStatus.PENDING)
    await store.add_review_item(review)

    result = await mcp_server.resolve_teacher_review(
        review_id=review.review_id,
        status="rejected",
        reviewer_id="TCH-BANDA",
        teacher_notes="Not enough data.",
        expected_revision=0,
    )
    assert result["status"] == "rejected"

    await store.close()


@pytest.mark.asyncio
async def test_mcp_can_needs_context(tmp_path: Path):
    """MCP may submit 'needs_context' on a pending review."""
    import importlib
    mcp_server = importlib.import_module("allps.mcp.server")

    db_file = str(tmp_path / "mcp_nc.db")
    store = SQLiteStore(db_file)
    await store.initialize()
    from allps.models.learner import Learner
    learner = Learner(learner_id="LRN-NC", display_name="NC Learner")
    await store.add_learner(learner)

    ev_service = EvidenceService(store)
    rev_service = ReviewService(store)
    set_service(ev_service, rev_service)

    from allps.models.pattern import Pattern, PatternType
    from allps.models.review import ReviewItem, ReviewStatus

    pattern = Pattern(
        learner_id="LRN-NC",
        pattern_type=PatternType.TREND,
        summary="Test pattern for MCP needs_context",
        supporting_evidence=[],
        conflicting_evidence=[],
        limitations=[],
    )
    await store.add_pattern(pattern)
    review = ReviewItem(pattern_id=pattern.pattern_id, status=ReviewStatus.PENDING)
    await store.add_review_item(review)

    result = await mcp_server.resolve_teacher_review(
        review_id=review.review_id,
        status="needs_context",
        reviewer_id="agent:feedback_recorder",
        teacher_notes="Requesting additional classroom context.",
        expected_revision=0,
    )
    assert result["status"] == "needs_context"

    await store.close()


# ─────────────────────────────────────────────────────────────────────────────
# F. Two concurrent human submissions — exactly one wins (revision-based lock)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_decisions_exactly_one_wins(tmp_path: Path):
    """Two concurrent human submissions on the same pending review with the same
    expected_revision (0) must produce exactly one success and one ConflictError.

    This validates that the unconditional fallback is gone: there is no path by
    which two callers sharing the same expected_revision can both succeed.
    """
    db_file = str(tmp_path / "concurrent.db")
    store = SQLiteStore(db_file)
    await store.initialize()

    from allps.models.learner import Learner
    from allps.models.pattern import Pattern, PatternType
    from allps.models.review import ReviewItem, ReviewStatus

    learner = Learner(learner_id="LRN-CONC", display_name="Concurrent Test")
    await store.add_learner(learner)

    pattern = Pattern(
        learner_id="LRN-CONC",
        pattern_type=PatternType.TREND,
        summary="Concurrent decision test pattern",
        supporting_evidence=[],
        conflicting_evidence=[],
        limitations=[],
    )
    await store.add_pattern(pattern)
    review = ReviewItem(pattern_id=pattern.pattern_id, status=ReviewStatus.PENDING)
    await store.add_review_item(review)

    # Register TCH-BANDA as a teacher so corrections don't fail on teacher lookup
    from allps.auth import hash_pin
    await store.add_teacher("TCH-BANDA", "Mr. Banda", hash_pin("1234"))
    await store.add_teacher("TCH-OCHIENG", "Ms. Ochieng", hash_pin("5678"))

    rev_service = ReviewService(store)

    successes = []
    conflicts = []

    async def attempt(teacher_id: str):
        try:
            item = await rev_service.resolve_teacher_review(
                review_id=review.review_id,
                status="accepted",
                reviewer_id=teacher_id,
                expected_revision=0,  # both callers read revision=0
                is_correction=False,
                authenticated_teacher_id=None,
            )
            successes.append(teacher_id)
        except ConflictError as e:
            conflicts.append(str(e))

    # Two human teachers both submit with expected_revision=0
    await asyncio.gather(
        attempt("TCH-BANDA"),
        attempt("TCH-OCHIENG"),
    )

    assert len(successes) == 1, f"Expected exactly 1 winner, got {successes}"
    assert len(conflicts) == 1, f"Expected exactly 1 conflict, got {conflicts}"
    # The conflict must mention the concurrency failure, not silently succeed
    assert "conflict" in conflicts[0].lower() or "revision" in conflicts[0].lower() or "already resolved" in conflicts[0].lower()

    await store.close()


# ─────────────────────────────────────────────────────────────────────────────
# G. Approved decision survives restart
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approved_handover_survives_restart(tmp_path: Path):
    """Accept a review, close the store, re-open — handover must still contain the decision."""
    db_file = str(tmp_path / "restart.db")
    app = _make_app(db_file)
    transport = httpx.ASGITransport(app=app)

    # First boot: generate + accept
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with app.router.lifespan_context(app):
            await client.post("/api/auth/login", json={"teacher_id": "TCH-BANDA", "pin": "1234"})
            await client.post("/api/learners/LRN-001/generate", json={"mode": "mock"})
            rev_id = await _first_pending(client, "LRN-001")
            dec = await client.post(
                f"/api/reviews/{rev_id}/decision",
                json={"status": "accepted", "teacher_notes": "Carry forward."},
            )
            assert dec.status_code == 200

    # Second boot: new app instance, same DB
    app2 = _make_app(db_file)
    transport2 = httpx.ASGITransport(app=app2)
    async with httpx.AsyncClient(transport=transport2, base_url="http://testserver") as client2:
        async with app2.router.lifespan_context(app2):
            handover = await client2.get("/api/learners/LRN-001/handover")
            assert handover.status_code == 200
            data = handover.json()
            assert data["accepted_pattern_count"] == 1
            assert data["patterns"][0]["review"]["reviewer_id"] == "TCH-BANDA"


# ─────────────────────────────────────────────────────────────────────────────
# H. Login / logout / me
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_logout_me(tmp_path: Path):
    """Login sets cookie, /me returns teacher, logout clears it."""
    db_file = str(tmp_path / "session.db")
    app = _make_app(db_file)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with app.router.lifespan_context(app):
            # Before login
            assert (await client.get("/api/auth/me")).status_code == 401

            # Login
            r = await client.post("/api/auth/login", json={"teacher_id": "TCH-OCHIENG", "pin": "5678"})
            assert r.status_code == 200
            assert r.json()["teacher_id"] == "TCH-OCHIENG"

            # Me
            me = await client.get("/api/auth/me")
            assert me.status_code == 200
            assert me.json()["teacher_id"] == "TCH-OCHIENG"

            # Logout
            lo = await client.post("/api/auth/logout")
            assert lo.status_code == 200

            # After logout
            assert (await client.get("/api/auth/me")).status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# I. Deliberate teacher correction after reloading the updated review
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_teacher_correction_after_initial_decision(tmp_path: Path):
    """Teacher can correct a prior non-pending decision by supplying is_correction=True
    and the revision returned after the initial decision.

    Scenario: needs_context → accepted (correction).
    The correction must:
    - succeed with HTTP 200
    - record the authenticated teacher_id as reviewer_id
    - increment the revision
    - surface the pattern in the handover profile
    """
    db_file = str(tmp_path / "correction.db")
    app = _make_app(db_file)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with app.router.lifespan_context(app):
            await client.post("/api/auth/login", json={"teacher_id": "TCH-BANDA", "pin": "1234"})
            await client.post("/api/learners/LRN-001/generate", json={"mode": "mock"})

            # Step 1: initial decision — needs_context at revision 0
            rev_id = await _first_pending(client, "LRN-001")
            nc_resp = await client.post(
                f"/api/reviews/{rev_id}/decision",
                json={
                    "status": "needs_context",
                    "teacher_notes": "Need term 3 context.",
                    "expected_revision": 0,
                    "is_correction": False,
                },
            )
            assert nc_resp.status_code == 200, nc_resp.text
            nc_data = nc_resp.json()
            assert nc_data["status"] == "needs_context"
            new_revision = nc_data["revision"]  # the revision after the write
            assert new_revision == 1  # incremented from 0 → 1

            # Reload the review list to confirm the current revision
            reviews_resp = await client.get("/api/learners/LRN-001/reviews")
            reviews = reviews_resp.json()
            updated_review = next(r for r in reviews if r["review_id"] == rev_id)
            assert updated_review["revision"] == 1

            # Step 2: correction — accepted at revision 1
            corr_resp = await client.post(
                f"/api/reviews/{rev_id}/decision",
                json={
                    "status": "accepted",
                    "teacher_notes": "Context received — confirmed.",
                    "expected_revision": 1,
                    "is_correction": True,
                },
            )
            assert corr_resp.status_code == 200, corr_resp.text
            corr_data = corr_resp.json()
            assert corr_data["status"] == "accepted"
            assert corr_data["reviewer_id"] == "TCH-BANDA"
            assert corr_data["revision"] == 2  # incremented from 1 → 2
            assert len(corr_data["approved_content_hash"]) == 64

            # Step 3: the pattern must now surface in the handover
            handover = await client.get("/api/learners/LRN-001/handover")
            assert handover.status_code == 200
            hdata = handover.json()
            assert hdata["accepted_pattern_count"] == 1
            assert hdata["patterns"][0]["review"]["reviewer_id"] == "TCH-BANDA"


# ─────────────────────────────────────────────────────────────────────────────
# J. Stale correction (wrong expected_revision) → ConflictError
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stale_correction_returns_conflict(tmp_path: Path):
    """A correction that carries an out-of-date expected_revision must return 409.

    Scenario: initial decision succeeds (revision 0 → 1); a second caller
    attempts to correct using stale revision 0 → must get 409, not 200.
    """
    db_file = str(tmp_path / "stale_corr.db")
    app = _make_app(db_file)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with app.router.lifespan_context(app):
            await client.post("/api/auth/login", json={"teacher_id": "TCH-BANDA", "pin": "1234"})
            await client.post("/api/learners/LRN-001/generate", json={"mode": "mock"})

            # Initial decision at revision 0
            rev_id = await _first_pending(client, "LRN-001")
            initial = await client.post(
                f"/api/reviews/{rev_id}/decision",
                json={"status": "rejected", "expected_revision": 0},
            )
            assert initial.status_code == 200
            assert initial.json()["revision"] == 1

            # Stale correction — supplies old revision 0 instead of current 1
            stale = await client.post(
                f"/api/reviews/{rev_id}/decision",
                json={
                    "status": "accepted",
                    "teacher_notes": "Correcting with stale revision.",
                    "expected_revision": 0,  # stale — should be 1
                    "is_correction": True,
                },
            )
            assert stale.status_code == 409, stale.text
            assert "conflict" in stale.json()["detail"].lower() or "revision" in stale.json()["detail"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# J-2. Stale initial decision (wrong expected_revision on a pending review) → 409
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stale_initial_decision_returns_conflict(tmp_path: Path):
    """An initial decision that supplies an incorrect expected_revision on a still-pending
    review must return 409 — the caller's declared revision is now enforced for initial decisions.

    Scenario: review is at revision 0; caller supplies expected_revision=5 → must get 409.
    """
    db_file = str(tmp_path / "stale_initial.db")
    app = _make_app(db_file)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with app.router.lifespan_context(app):
            await client.post("/api/auth/login", json={"teacher_id": "TCH-BANDA", "pin": "1234"})
            await client.post("/api/learners/LRN-001/generate", json={"mode": "mock"})

            rev_id = await _first_pending(client, "LRN-001")
            # Review is at revision 0; caller lies about having seen revision 5
            stale = await client.post(
                f"/api/reviews/{rev_id}/decision",
                json={
                    "status": "rejected",
                    "teacher_notes": "Submitting with wrong revision.",
                    "expected_revision": 5,  # wrong — actual is 0
                    "is_correction": False,
                },
            )
            assert stale.status_code == 409, stale.text
            assert "revision" in stale.json()["detail"].lower() or "conflict" in stale.json()["detail"].lower()

            # Review must still be pending — the stale write was rejected
            revs = (await client.get(f"/api/learners/LRN-001/reviews")).json()
            still_pending = [r for r in revs if r["review_id"] == rev_id and r["status"] == "pending"]
            assert still_pending, "Stale write must not have changed the review status"


# ─────────────────────────────────────────────────────────────────────────────
# K. MCP attempt using teacher-looking reviewer_id cannot correct
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mcp_teacher_id_cannot_correct(tmp_path: Path):
    """MCP resolve_teacher_review cannot override an existing decision even if
    the reviewer_id looks like a legitimate teacher identifier.

    This test verifies that:
    1. The MCP tool correctly routes through the initial-decision path (is_correction=False).
    2. Calling it on an already-resolved review produces a ConflictError (wrapped as ValueError).
    3. No correction is possible over MCP regardless of the reviewer_id supplied.
    """
    import importlib
    mcp_server = importlib.import_module("allps.mcp.server")

    db_file = str(tmp_path / "mcp_override.db")
    store = SQLiteStore(db_file)
    await store.initialize()

    from allps.models.learner import Learner
    from allps.models.pattern import Pattern, PatternType
    from allps.models.review import ReviewItem, ReviewStatus

    learner = Learner(learner_id="LRN-MCP-OVRD", display_name="Override Test")
    await store.add_learner(learner)

    pattern = Pattern(
        learner_id="LRN-MCP-OVRD",
        pattern_type=PatternType.TREND,
        summary="Pattern for MCP override test",
        supporting_evidence=[],
        conflicting_evidence=[],
        limitations=[],
    )
    await store.add_pattern(pattern)
    review = ReviewItem(pattern_id=pattern.pattern_id, status=ReviewStatus.PENDING)
    await store.add_review_item(review)

    ev_service = EvidenceService(store)
    rev_service = ReviewService(store)
    set_service(ev_service, rev_service)

    # First: MCP makes an initial needs_context decision — should succeed
    result = await mcp_server.resolve_teacher_review(
        review_id=review.review_id,
        status="needs_context",
        reviewer_id="TCH-BANDA",  # teacher-looking ID
        teacher_notes="Needs more context.",
        expected_revision=0,
    )
    assert result["status"] == "needs_context"

    # Second: MCP attempts to override/correct the decision using the same tool.
    # The MCP tool always sets is_correction=False, so it will hit the ConflictError
    # because the review is no longer pending.
    with pytest.raises((ValueError, ConflictError)):
        await mcp_server.resolve_teacher_review(
            review_id=review.review_id,
            status="rejected",
            reviewer_id="TCH-BANDA",  # still teacher-looking
            teacher_notes="Trying to override.",
            expected_revision=1,
        )

    # Verify the stored status is still needs_context — not overridden
    final_item = await store.get_review_item(review.review_id)
    assert final_item.status == ReviewStatus.NEEDS_CONTEXT

    set_service(None)
    await store.close()


# ─────────────────────────────────────────────────────────────────────────────
# L. Full Two-Teacher Handover & Competing Revision Conflict Workflow
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_two_teacher_handover_and_competing_revision_workflow(tmp_path: Path):
    """End-to-end two-teacher handover across session switch, correction, and 409 conflict."""
    db_file = str(tmp_path / "two_teacher_handover.db")
    app = _make_app(db_file)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with app.router.lifespan_context(app):
            # Unauthenticated config reports authority unavailable
            cfg0 = (await client.get("/api/config")).json()
            assert cfg0["review_authority_available"] is False
            assert cfg0["authenticated_teacher"] is None

            # Teacher 1 (TCH-BANDA) logs in
            login1 = await client.post(
                "/api/auth/login", json={"teacher_id": "TCH-BANDA", "pin": "1234"}
            )
            assert login1.status_code == 200, login1.text
            cfg1 = (await client.get("/api/config")).json()
            assert cfg1["review_authority_available"] is True
            assert cfg1["authenticated_teacher"]["teacher_id"] == "TCH-BANDA"

            # Record observation
            obs_resp = await client.post(
                "/api/learners/LRN-001/evidence",
                json={
                    "event_datetime": "2025-11-10T09:00:00Z",
                    "academic_year": 2025,
                    "term": 3,
                    "subject": "Mathematics",
                    "observation": "Demonstrated geometric reasoning during group blocks activity.",
                    "context": "Concrete manipulatives station.",
                    "source_reference": "Mr. Banda",
                    "source_event_id": "two-teacher-obs-001",
                },
            )
            assert obs_resp.status_code == 201, obs_resp.text

            # Generate candidate handover brief
            gen_resp = await client.post(
                "/api/learners/LRN-001/generate",
                json={"subject": "Mathematics", "mode": "mock"},
            )
            assert gen_resp.status_code == 200, gen_resp.text
            assert gen_resp.json()["status"] == "success"

            # Teacher 1 marks pending review as needs_context at expected_revision=0
            reviews1 = (await client.get("/api/learners/LRN-001/reviews")).json()
            pending1 = [r for r in reviews1 if r["status"] == "pending"]
            assert pending1
            review_id = pending1[0]["review_id"]
            assert pending1[0]["revision"] == 0

            dec1 = await client.post(
                f"/api/reviews/{review_id}/decision",
                json={
                    "status": "needs_context",
                    "teacher_notes": "Awaiting incoming Grade 4 teacher verification.",
                    "expected_revision": 0,
                    "is_correction": False,
                },
            )
            assert dec1.status_code == 200, dec1.text
            assert dec1.json()["status"] == "needs_context"
            assert dec1.json()["reviewer_id"] == "TCH-BANDA"
            assert dec1.json()["revision"] == 1

            # Handover remains empty prior to acceptance
            handover_mid = (await client.get("/api/learners/LRN-001/handover")).json()
            assert handover_mid["accepted_pattern_count"] == 0

            # Teacher 1 logs out; Teacher 2 (TCH-OCHIENG) logs in
            await client.post("/api/auth/logout")
            login2 = await client.post(
                "/api/auth/login", json={"teacher_id": "TCH-OCHIENG", "pin": "5678"}
            )
            assert login2.status_code == 200, login2.text
            cfg2 = (await client.get("/api/config")).json()
            assert cfg2["review_authority_available"] is True
            assert cfg2["authenticated_teacher"]["teacher_id"] == "TCH-OCHIENG"

            # Teacher 2 inspects review at revision 1
            reviews2 = (await client.get("/api/learners/LRN-001/reviews")).json()
            target_rev = next(r for r in reviews2 if r["review_id"] == review_id)
            assert target_rev["status"] == "needs_context"
            assert target_rev["revision"] == 1

            # Teacher 2 submits explicit correction to accepted at revision 1 -> revision 2
            dec2 = await client.post(
                f"/api/reviews/{review_id}/decision",
                json={
                    "status": "accepted",
                    "teacher_notes": "Verified context with Mr. Banda; accepted for Grade 4 transition.",
                    "expected_revision": 1,
                    "is_correction": True,
                },
            )
            assert dec2.status_code == 200, dec2.text
            dec2_data = dec2.json()
            assert dec2_data["status"] == "accepted"
            assert dec2_data["reviewer_id"] == "TCH-OCHIENG"
            assert dec2_data["revision"] == 2
            assert len(dec2_data["approved_content_hash"]) == 64

            # Competing stale submission with expected_revision=1 must return 409 Conflict
            stale = await client.post(
                f"/api/reviews/{review_id}/decision",
                json={
                    "status": "rejected",
                    "teacher_notes": "Competing stale decision.",
                    "expected_revision": 1,
                    "is_correction": True,
                },
            )
            assert stale.status_code == 409, stale.text

            # Approved handover surfaces the pattern attributed to TCH-OCHIENG with verified hash
            handover_final = (await client.get("/api/learners/LRN-001/handover")).json()
            assert handover_final["accepted_pattern_count"] == 1
            surfaced = handover_final["patterns"][0]["review"]
            assert surfaced["reviewer_id"] == "TCH-OCHIENG"
            assert surfaced["approved_content_hash"] == dec2_data["approved_content_hash"]
            assert surfaced["hash_verified"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────────────────────────


async def _first_pending(client: httpx.AsyncClient, learner_id: str) -> str:
    resp = await client.get(f"/api/learners/{learner_id}/reviews")
    assert resp.status_code == 200, resp.text
    pending = [r for r in resp.json() if r["status"] == "pending"]
    assert pending, f"No pending reviews for {learner_id}"
    return pending[0]["review_id"]
