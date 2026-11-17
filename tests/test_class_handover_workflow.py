"""Comprehensive E2E tests for ALLPS Class Handover, Availability, Release, Accountability, Responses & Diffs."""

from __future__ import annotations

from pathlib import Path
from typing import AsyncGenerator

import httpx
import pytest
import pytest_asyncio

from allps.models.evidence import EvidenceType, IngestionMethod
from allps.models.learner import Learner
from allps.models.pattern import Pattern, PatternType
from allps.models.review import ReviewItem
from allps.web.app import create_app

INGEST_KEY = "class-handover-test-key"


@pytest_asyncio.fixture
async def handover_env(tmp_path: Path) -> AsyncGenerator[tuple[httpx.AsyncClient, object], None]:
    """Isolated FastAPI app seeded with school classes, 5 teachers, and 3 Grade 3 Blue learners."""
    db_file = str(tmp_path / "handover_e2e.db")
    app = create_app(
        db_path=db_file,
        mode="deterministic",
        seed_demo_data=True,
        ingest_api_key=INGEST_KEY,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with app.router.lifespan_context(app):
            yield client, app


async def _login(client: httpx.AsyncClient, teacher_id: str, pin: str) -> None:
    resp = await client.post("/api/auth/login", json={"teacher_id": teacher_id, "pin": pin})
    assert resp.status_code == 200, resp.text


async def _resolve_all_pending_findings(client: httpx.AsyncClient, learner_id: str) -> None:
    revs = (await client.get(f"/api/learners/{learner_id}/reviews")).json()
    for rev in revs:
        if rev["status"] == "pending" and rev["review_id"]:
            dec = await client.post(
                f"/api/reviews/{rev['review_id']}/decision",
                json={
                    "status": "accepted",
                    "teacher_notes": "Verified longitudinal record before class handover release.",
                    "expected_revision": rev["revision"],
                    "is_correction": False,
                },
            )
            assert dec.status_code == 200, dec.text


async def _prepare_and_release_g3_blue(client: httpx.AsyncClient) -> dict:
    """Resolve pending findings for Grade 3 Blue, complete all 4 review slots per learner, and release v1."""
    await _login(client, "TCH-OCHIENG", "5678")
    for lid in ("LRN-001", "LRN-002", "LRN-003"):
        await client.post(f"/api/learners/{lid}/generate", json={"mode": "deterministic"})
        await _resolve_all_pending_findings(client, lid)

        summaries = {
            "student": f"{lid} overall attendance and classroom engagement documented cleanly across terms.",
            "Mathematics": f"{lid} Mathematics longitudinal profile reviewed and verified against stored assessments.",
            "English": f"{lid} English reading and classroom participation reviewed carefully with evidence notes.",
            "Science": f"{lid} Science inquiry and practical work reviewed against term evidence.",
        }
        for scope, text in summaries.items():
            # Mark English/Science on learners with no subject data as reviewed_incomplete or ready
            avail_resp = await client.get(f"/api/learners/{lid}/availability")
            assert avail_resp.status_code == 200
            scope_avail = avail_resp.json()["scopes"][scope]
            state = (
                "ready_for_release"
                if scope_avail["status"] == "sufficient"
                else "reviewed_incomplete"
            )
            disclosure = None if state == "ready_for_release" else scope_avail["human_message"]
            upd = await client.post(
                f"/api/classes/CLS-G3-BLUE/learners/{lid}/sections/{scope}",
                json={
                    "review_state": state,
                    "approved_summary": text,
                    "missing_evidence_disclosure": disclosure,
                },
            )
            assert upd.status_code == 200, upd.text

    rel_resp = await client.post("/api/classes/CLS-G3-BLUE/release", json={"notes": "End of Term 3 Grade 3 Blue Release"})
    assert rel_resp.status_code == 201, rel_resp.text
    return rel_resp.json()["release"]


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 1: School Structure & Strict Permission Enforcement
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_school_structure_and_permissions(handover_env):
    client, _ = handover_env

    # Unauthenticated requests fail closed with 401
    assert (await client.get("/api/learners")).status_code == 401
    assert (await client.get("/api/learners/LRN-001/evidence")).status_code == 401
    assert (await client.get("/api/workspace")).status_code == 401

    # Class teacher (Ms. Ochieng) sees all 3 Grade 3 Blue learners and full class workspace
    await _login(client, "TCH-OCHIENG", "5678")
    ws = (await client.get("/api/workspace")).json()
    assert ws["teacher_id"] == "TCH-OCHIENG"
    assert any(c["class_id"] == "CLS-G3-BLUE" and c["role"] == "class_teacher" for c in ws["classes"])

    all_l1_ev = (await client.get("/api/learners/LRN-001/evidence")).json()
    all_l3_ev = (await client.get("/api/learners/LRN-003/evidence")).json()
    math_ev_id = next(e["evidence_id"] for e in all_l1_ev if e["subject"] == "Mathematics")
    english_ev_id = next(e["evidence_id"] for e in all_l3_ev if e["subject"] == "English")

    # Unrelated teacher (Mrs. Kamau, Grade 4 Red) sees zero Grade 3 Blue learners and gets 403 everywhere
    await _login(client, "TCH-KAMAU", "4567")
    assert (await client.get("/api/learners")).json() == []
    assert (await client.get("/api/learners/LRN-001/evidence")).status_code == 403
    assert (await client.get(f"/api/evidence/{math_ev_id}")).status_code == 403
    assert (await client.get("/api/learners/LRN-001/reviews")).status_code == 403
    assert (await client.get("/api/learners/LRN-001/handover")).status_code == 403
    assert (await client.get("/api/learners/LRN-001/handover/export?format=json")).status_code == 403
    assert (await client.get("/api/classes/CLS-G3-BLUE/readiness")).status_code == 403

    # Subject teacher (Mr. Banda, Mathematics) can access Mathematics evidence, blocked on English/Science & class-teacher writes
    await _login(client, "TCH-BANDA", "1234")
    assert len((await client.get("/api/learners")).json()) == 3
    assert (await client.get(f"/api/evidence/{math_ev_id}")).status_code == 200
    assert (await client.get(f"/api/evidence/{english_ev_id}")).status_code == 403
    assert (await client.get("/api/learners/LRN-003/evidence?subject=English")).status_code == 403

    banda_l3_ev = (await client.get("/api/learners/LRN-003/evidence")).json()
    assert all(e["subject"] in (None, "Mathematics") for e in banda_l3_ev)

    assert (
        await client.post(
            "/api/classes/CLS-G3-BLUE/learners/LRN-001/sections/Mathematics",
            json={"review_state": "ready_for_release", "approved_summary": "Unauthorized subject edit"},
        )
    ).status_code == 403
    assert (await client.post("/api/classes/CLS-G3-BLUE/release", json={})).status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 2: Evidence Availability vs. Teacher Review Completion & Blocking
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evidence_availability_vs_review_completion_and_blocking(handover_env):
    client, app = handover_env
    store = app.state.store
    ev_srv = app.state.evidence_service

    # Add learners testing 2-of-3 longitudinal rule, 1-of-2 baseline rule, and 4 gap classifications
    for lid, name in [
        ("LRN-AVAIL-2OF3", "Amina Partial"),
        ("LRN-AVAIL-BASE", "Brian Baseline"),
        ("LRN-AVAIL-GAPS", "Chao Gaps"),
    ]:
        await store.add_learner(Learner(learner_id=lid, display_name=name))
        await store.enroll_learner("CLS-G3-BLUE", lid)

    # LRN-AVAIL-2OF3: 2 of 3 comparable Mathematics assessments
    for term, score, dt in [(1, 72, "2026-03-10T09:00:00Z"), (2, 76, "2026-06-15T09:00:00Z")]:
        await ev_srv.record_evidence(
            learner_id="LRN-AVAIL-2OF3",
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="system",
            source_reference="Mr. Banda",
            academic_year=2026,
            term=term,
            subject="Mathematics",
            observed_at=dt,
            content={
                "grade": "Grade 3",
                "score": score,
                "max_score": 100,
                "measured_skill": "fractions",
                "form": "Term Test",
                "form_version": "v1",
                "language": "English",
                "comparison_authorized": True,
            },
        )

    # LRN-AVAIL-BASE: 1 of 2 assessments under a 2-point baseline comparison rule
    await ev_srv.record_evidence(
        learner_id="LRN-AVAIL-BASE",
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="diagnostic_screener",
        ingestion_method=IngestionMethod.API,
        source_type="system",
        source_reference="Ms. Wanjiku",
        academic_year=2026,
        term=1,
        subject="English",
        observed_at="2026-02-05T09:00:00Z",
        content={
            "grade": "Grade 3",
            "score": 40,
            "max_score": 50,
            "measured_skill": "oral_fluency",
            "form": "Screener",
            "form_version": "v1",
            "language": "English",
            "comparison_rule": "baseline_change",
            "comparison_authorized": True,
        },
    )

    # LRN-AVAIL-GAPS:
    # - Mathematics: Assessment not conducted
    # - English: zero records -> No data available
    # - Science: Missing result WITH unknown source trace
    await ev_srv.record_evidence(
        learner_id="LRN-AVAIL-GAPS",
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="system",
        source_reference="Exam Office",
        academic_year=2026,
        term=1,
        subject="Mathematics",
        observed_at="2026-03-10T09:00:00Z",
        content={
            "status": "assessment_not_administered",
            "reason": "Term 1 paper cancelled due to calendar adjustment.",
        },
    )
    await ev_srv.record_evidence(
        learner_id="LRN-AVAIL-GAPS",
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="system",
        source_reference="unknown",
        academic_year=2026,
        term=1,
        subject="Science",
        observed_at="2026-03-11T09:00:00Z",
        content={
            "status": "result_unavailable",
            "reason": "Expected end-of-term score sheet not located.",
            "source_trace_found": False,
        },
    )

    await _login(client, "TCH-OCHIENG", "5678")

    # Check 2 of 3 availability preserves both available results & explains unmet conclusion
    avail_2of3 = (await client.get("/api/learners/LRN-AVAIL-2OF3/availability")).json()["scopes"]["Mathematics"]
    assert avail_2of3["status"] == "insufficient_assessment_history"
    assert "2 of 3" in avail_2of3["label"]
    assert "Two of the three required assessments" in avail_2of3["human_message"]
    assert len(avail_2of3["available_results"]) == 2
    assert "improving" in avail_2of3["unmet_conclusion"].lower()

    # Check 1 of 2 baseline rule uses 2, NOT hardcoded 3; adding 2nd makes it sufficient
    avail_base1 = (await client.get("/api/learners/LRN-AVAIL-BASE/availability")).json()["scopes"]["English"]
    assert avail_base1["status"] == "insufficient_assessment_history"
    assert avail_base1["available_count"] == 1
    assert avail_base1["required_count"] == 2
    assert "One of the two required assessments" in avail_base1["human_message"]

    await ev_srv.record_evidence(
        learner_id="LRN-AVAIL-BASE",
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="diagnostic_screener",
        ingestion_method=IngestionMethod.API,
        source_type="system",
        source_reference="Ms. Wanjiku",
        academic_year=2026,
        term=2,
        subject="English",
        observed_at="2026-06-05T09:00:00Z",
        content={
            "grade": "Grade 3",
            "score": 46,
            "max_score": 50,
            "measured_skill": "oral_fluency",
            "form": "Screener",
            "form_version": "v1",
            "language": "English",
            "comparison_rule": "baseline_change",
            "comparison_authorized": True,
        },
    )
    avail_base2 = (await client.get("/api/learners/LRN-AVAIL-BASE/availability")).json()["scopes"]["English"]
    assert avail_base2["status"] == "sufficient"

    # Check 4 distinct gap situations
    gaps = (await client.get("/api/learners/LRN-AVAIL-GAPS/availability")).json()["scopes"]
    assert gaps["Mathematics"]["status"] == "assessment_not_conducted"
    assert gaps["English"]["status"] == "no_data_available"
    assert "does not know why" in gaps["English"]["human_message"].lower()
    assert gaps["Science"]["status"] == "source_trace_not_found"

    # Teacher review state remains NOT_REVIEWED even when no pending findings exist
    readiness = (await client.get("/api/classes/CLS-G3-BLUE/readiness")).json()
    gaps_row = next(l for l in readiness["learners"] if l["learner_id"] == "LRN-AVAIL-GAPS")
    assert gaps_row["slots"]["English"]["review_state"] == "not_reviewed"
    assert gaps_row["slots"]["English"]["pending_findings_count"] == 0
    assert readiness["can_release"] is False

    # Student Review rejects embedded subject mark trajectories
    leak_resp = await client.post(
        "/api/classes/CLS-G3-BLUE/learners/LRN-001/sections/student",
        json={
            "review_state": "ready_for_release",
            "approved_summary": "Mathematics scores dropped 82/100 -> 68/100 -> 54/100 across terms.",
        },
    )
    assert leak_resp.status_code == 422

    # Release class blocked when any slot is not_reviewed or needs_clarification
    rel_blocked = await client.post("/api/classes/CLS-G3-BLUE/release", json={})
    assert rel_blocked.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 3: Frozen Class Release v1 & Role-Scoped Exports
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_frozen_class_release_and_role_scoped_exports(handover_env):
    client, _ = handover_env
    release = await _prepare_and_release_g3_blue(client)
    assert release["version_number"] == 1
    assert set(release["frozen_enrollment"]) == {"LRN-001", "LRN-002", "LRN-003"}

    # Subject teacher (Mr. Banda, Mathematics) receives ONLY Student Review + Mathematics Review
    await _login(client, "TCH-BANDA", "1234")
    pub = (await client.get("/api/learners/LRN-001/published")).json()
    assert pub["release"]["release_id"] == release["release_id"]
    scopes = [s["scope"] for s in pub["sections"]]
    assert scopes == ["Mathematics", "student"] or set(scopes) == {"student", "Mathematics"}
    assert "English" not in scopes and "Science" not in scopes

    # Handover JSON & Markdown exports are role-scoped to Student Review + Mathematics
    exp_json = (await client.get("/api/learners/LRN-001/handover/export?format=json")).json()
    exp_scopes = {s["scope"] for s in exp_json["published_sections"]}
    assert exp_scopes == {"student", "Mathematics"}

    exp_md = (await client.get("/api/learners/LRN-001/handover/export?format=md")).text
    assert "Mathematics Review" in exp_md
    assert "Student Review" in exp_md
    assert "English Review" not in exp_md and "Science Review" not in exp_md


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 4: Viewing History & Last Opened vs. Separate Acknowledgment
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_viewing_history_separate_from_acknowledgment(handover_env):
    client, _ = handover_env
    release = await _prepare_and_release_g3_blue(client)
    rel_id = release["release_id"]

    await _login(client, "TCH-BANDA", "1234")

    # Before opening: last_opened is None, acknowledged is False
    before = (await client.get("/api/learners/LRN-001/published")).json()
    math_sec_before = next(s for s in before["sections"] if s["scope"] == "Mathematics")
    assert math_sec_before["last_opened"] is None
    assert math_sec_before["acknowledgment"]["acknowledged"] is False

    # First open -> records Viewed + viewing_history, stays unacknowledged
    v1 = await client.post(f"/api/releases/{rel_id}/learners/LRN-001/view", json={"scope": "Mathematics"})
    assert v1.status_code == 200
    assert v1.json()["receipt"]["status"] == "viewed"
    assert v1.json()["receipt"]["view_count"] == 1

    # Second open -> increments view_count & keeps full viewing history
    v2 = await client.post(f"/api/releases/{rel_id}/learners/LRN-001/view", json={"scope": "Mathematics"})
    assert v2.status_code == 200
    assert v2.json()["receipt"]["view_count"] == 2
    assert v2.json()["receipt"]["status"] == "viewed"

    mid = (await client.get("/api/learners/LRN-001/published")).json()
    math_sec_mid = next(s for s in mid["sections"] if s["scope"] == "Mathematics")
    assert math_sec_mid["last_opened"]["display"].startswith("Last opened by Mr. Banda")
    assert len(math_sec_mid["viewing_history"]) == 2
    assert math_sec_mid["acknowledgment"]["acknowledged"] is False

    # Explicit acknowledgment recorded separately
    ack = await client.post(f"/api/releases/{rel_id}/learners/LRN-001/acknowledge")
    assert ack.status_code == 200
    assert ack.json()["status"] == "acknowledged"
    assert ack.json()["acknowledged_at"] is not None

    # Subsequent view does NOT downgrade acknowledgment
    v3 = await client.post(f"/api/releases/{rel_id}/learners/LRN-001/view", json={"scope": "Mathematics"})
    assert v3.status_code == 200
    assert v3.json()["receipt"]["status"] == "acknowledged"
    assert v3.json()["receipt"]["view_count"] == 3

    after = (await client.get("/api/learners/LRN-001/published")).json()
    math_sec_after = next(s for s in after["sections"] if s["scope"] == "Mathematics")
    assert math_sec_after["acknowledgment"]["acknowledged"] is True
    assert math_sec_after["acknowledgment"]["display"].startswith("Acknowledged by Mr. Banda")


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 5: Attached Subject Responses & Isolation
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_attached_subject_responses_and_isolation(handover_env):
    client, _ = handover_env
    release = await _prepare_and_release_g3_blue(client)
    rel_id = release["release_id"]

    # Ms. Wanjiku (English) cannot respond to Mathematics or use deficit labels
    await _login(client, "TCH-WANJIKU", "2345")
    forbidden_resp = await client.post(
        f"/api/releases/{rel_id}/learners/LRN-001/responses",
        json={"subject": "Mathematics", "response_type": "confirmation", "content": "Attempt from wrong subject"},
    )
    assert forbidden_resp.status_code == 403

    # Mr. Banda attaches response beneath unchanged Mathematics parent review
    await _login(client, "TCH-BANDA", "1234")
    bad_label_resp = await client.post(
        f"/api/releases/{rel_id}/learners/LRN-001/responses",
        json={"subject": "Mathematics", "response_type": "confirmation", "content": "Learner seems a slow learner."},
    )
    assert bad_label_resp.status_code == 422

    ok_resp = await client.post(
        f"/api/releases/{rel_id}/learners/LRN-001/responses",
        json={
            "subject": "Mathematics",
            "response_type": "confirmation",
            "content": "I have also observed this difficulty with fractions during class exercises. I will record further observations.",
        },
    )
    assert ok_resp.status_code == 201

    pub_banda = (await client.get("/api/learners/LRN-001/published")).json()
    math_sec = next(s for s in pub_banda["sections"] if s["scope"] == "Mathematics")
    assert "Mathematics historical" in math_sec["approved_summary"] or "approved" in math_sec["approved_summary"] or "Mathematics" in math_sec["approved_summary"]
    assert len(math_sec["responses"]) == 1
    assert math_sec["responses"][0]["teacher_name"] == "Mr. Banda"

    # Class teacher sees Mr. Banda's child response; English teacher does not
    await _login(client, "TCH-OCHIENG", "5678")
    pub_ct = (await client.get("/api/learners/LRN-001/published")).json()
    ct_math = next(s for s in pub_ct["sections"] if s["scope"] == "Mathematics")
    assert len(ct_math["responses"]) == 1

    await _login(client, "TCH-WANJIKU", "2345")
    pub_eng = (await client.get("/api/learners/LRN-001/published")).json()
    assert all(s["scope"] != "Mathematics" for s in pub_eng["sections"])


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 6: Post-Release Minor vs. Major Changes & 5-Step Progress Lifecycle
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_release_minor_and_major_changes_and_progress_lifecycle(handover_env):
    client, _ = handover_env

    # Ensure LRN-002 Science starts with an improving trajectory (88 -> 90 -> 92) before release v1
    # Check existing seed evidence or ingest comparable 2026 terms to establish clear baseline before v1
    headers = {"X-API-Key": INGEST_KEY}
    pre_release_sci = [
        {
            "learner_id": "LRN-002",
            "class_id": "CLS-G3-BLUE",
            "evidence_type": "assessment",
            "source_system": "school_sis",
            "ingestion_method": "api",
            "source_event_id": "SCI-BASE-1",
            "source_type": "system",
            "source_reference": "Mr. Otieno",
            "academic_year": 2026,
            "term": 1,
            "subject": "Science",
            "observed_at": "2026-03-12T09:00:00Z",
            "content": {
                "grade": "Grade 3",
                "score": 88,
                "max_score": 100,
                "measured_skill": "scientific_inquiry",
                "form": "Unit Check",
                "form_version": "v1",
                "language": "English",
                "comparison_authorized": True,
            },
        },
        {
            "learner_id": "LRN-002",
            "class_id": "CLS-G3-BLUE",
            "evidence_type": "assessment",
            "source_system": "school_sis",
            "ingestion_method": "api",
            "source_event_id": "SCI-BASE-2",
            "source_type": "system",
            "source_reference": "Mr. Otieno",
            "academic_year": 2026,
            "term": 2,
            "subject": "Science",
            "observed_at": "2026-06-12T09:00:00Z",
            "content": {
                "grade": "Grade 3",
                "score": 90,
                "max_score": 100,
                "measured_skill": "scientific_inquiry",
                "form": "Unit Check",
                "form_version": "v1",
                "language": "English",
                "comparison_authorized": True,
            },
        },
        {
            "learner_id": "LRN-002",
            "class_id": "CLS-G3-BLUE",
            "evidence_type": "assessment",
            "source_system": "school_sis",
            "ingestion_method": "api",
            "source_event_id": "SCI-BASE-3",
            "source_type": "system",
            "source_reference": "Mr. Otieno",
            "academic_year": 2026,
            "term": 3,
            "subject": "Science",
            "observed_at": "2026-09-12T09:00:00Z",
            "content": {
                "grade": "Grade 3",
                "score": 92,
                "max_score": 100,
                "measured_skill": "scientific_inquiry",
                "form": "Unit Check",
                "form_version": "v1",
                "language": "English",
                "comparison_authorized": True,
            },
        },
    ]
    assert (await client.post("/api/ingest/records", json={"records": pre_release_sci}, headers=headers)).status_code == 200

    release_v1 = await _prepare_and_release_g3_blue(client)
    rel_v1_id = release_v1["release_id"]

    # A) Minor update on LRN-001 Mathematics (82 -> 68 -> 54 declining, now Term 1 2026 = 50 -> still declining)
    minor_rec = {
        "learner_id": "LRN-001",
        "class_id": "CLS-G3-BLUE",
        "evidence_type": "assessment",
        "source_system": "school_sis",
        "ingestion_method": "api",
        "source_event_id": "MATH-POST-MINOR-1",
        "source_type": "system",
        "source_reference": "Mr. Banda",
        "academic_year": 2026,
        "term": 1,
        "subject": "Mathematics",
        "observed_at": "2026-03-10T09:00:00Z",
        "content": {
            "grade": "Grade 3",
            "score": 50,
            "max_score": 100,
            "measured_skill": "multiplication_and_division",
            "form": "Term Test",
            "form_version": "v1.0",
            "language": "English",
            "comparison_authorized": True,
        },
    }
    ing_minor = await client.post("/api/ingest/records", json={"records": [minor_rec]}, headers=headers)
    assert ing_minor.status_code == 200 and ing_minor.json()["accepted_count"] == 1

    await _login(client, "TCH-BANDA", "1234")
    pub_minor = (await client.get("/api/learners/LRN-001/published")).json()
    math_changes = [c for c in pub_minor["changes"] if c["scope"] == "Mathematics"]
    assert len(math_changes) == 1
    assert math_changes[0]["severity"] == "minor"
    assert "Small update:" in math_changes[0]["headline"]
    assert len(math_changes[0]["comparison"]["new_results"]) == 1
    assert len(math_changes[0]["comparison"]["earlier_results"]) >= 3

    # B) Major change on LRN-002 Science: small mark shift (92 -> 90 in Year 2027 Term 1) reverses improving -> variable!
    major_rec = {
        "learner_id": "LRN-002",
        "class_id": "CLS-G3-BLUE",
        "evidence_type": "assessment",
        "source_system": "school_sis",
        "ingestion_method": "api",
        "source_event_id": "SCI-POST-MAJOR-1",
        "source_type": "system",
        "source_reference": "Mr. Otieno",
        "academic_year": 2027,
        "term": 1,
        "subject": "Science",
        "observed_at": "2027-02-10T09:00:00Z",
        "content": {
            "grade": "Grade 3",
            "score": 90,
            "max_score": 100,
            "measured_skill": "scientific_inquiry",
            "form": "Unit Check",
            "form_version": "v1",
            "language": "English",
            "comparison_authorized": True,
        },
    }
    ing_major = await client.post("/api/ingest/records", json={"records": [major_rec]}, headers=headers)
    assert ing_major.status_code == 200 and ing_major.json()["accepted_count"] == 1

    # Class teacher sees Major change in attention queue at Step 1: Not opened
    await _login(client, "TCH-OCHIENG", "5678")
    ws_ct = (await client.get("/api/workspace")).json()
    major_att = [a for a in ws_ct["needs_attention"] if a["kind"] == "major_change" and a["learner_id"] == "LRN-002"]
    assert len(major_att) == 1
    change_obj = major_att[0]["change"]
    change_id = change_obj["change_id"]
    assert change_obj["severity"] == "major"
    assert "Important change:" in change_obj["headline"]
    assert change_obj["progress_status"] == "not_opened"

    # Step 2: Science teacher (Mr. Otieno) opens the report -> Opened by Mr. Otieno
    await _login(client, "TCH-OTIENO", "3456")
    await client.post(f"/api/releases/{rel_v1_id}/learners/LRN-002/view", json={"scope": "Science"})
    pub_otieno = (await client.get("/api/learners/LRN-002/published")).json()
    sci_change_2 = next(c for c in pub_otieno["changes"] if c["change_id"] == change_id)
    assert sci_change_2["progress_status"] == "opened"
    assert "Opened by Mr. Otieno" in sci_change_2["progress_label"]

    # Step 3: Mr. Otieno adds a response -> Response added
    await client.post(
        f"/api/releases/{rel_v1_id}/learners/LRN-002/responses",
        json={
            "subject": "Science",
            "response_type": "additional_observation",
            "content": "Observed minor dip on new lab write-up; will check safety protocol focus next week.",
            "related_change_id": change_id,
        },
    )
    pub_otieno_3 = (await client.get("/api/learners/LRN-002/published")).json()
    sci_change_3 = next(c for c in pub_otieno_3["changes"] if c["change_id"] == change_id)
    assert sci_change_3["progress_status"] == "response_added"

    # Step 4: Ms. Ochieng marks change reviewed -> Reviewed by Ms. Ochieng
    await _login(client, "TCH-OCHIENG", "5678")
    rev_chg = await client.post(
        f"/api/classes/CLS-G3-BLUE/changes/{change_id}/review",
        json={"notes": "Reviewed with Mr. Otieno; updating Science handover section for v2."},
    )
    assert rev_chg.status_code == 200
    assert rev_chg.json()["progress_status"] == "reviewed_by_class_teacher"
    assert "Reviewed by Ms. Ochieng" in rev_chg.json()["progress_label"]

    # Step 5: Ms. Ochieng updates Science section and releases v2 -> New version released
    await client.post(
        "/api/learners/LRN-002/generate",
        json={"subject": "Science", "mode": "deterministic"},
    )
    await _resolve_all_pending_findings(client, "LRN-002")
    await client.post(
        "/api/classes/CLS-G3-BLUE/learners/LRN-002/sections/Science",
        json={
            "review_state": "ready_for_release",
            "approved_summary": "Updated v2 Science review incorporating Year 2027 Term 1 unit check results.",
        },
    )
    rel_v2 = await client.post("/api/classes/CLS-G3-BLUE/release", json={"notes": "Version 2 update"})
    assert rel_v2.status_code == 201
    assert rel_v2.json()["release"]["version_number"] == 2

    all_changes = (await client.get("/api/classes/CLS-G3-BLUE/changes")).json()
    v1_chg_final = next(c for c in all_changes if c["change_id"] == change_id)
    assert v1_chg_final["progress_status"] == "new_version_released"
    assert v1_chg_final["superseded_version_number"] == 2


@pytest.mark.asyncio
async def test_spa_renders_class_handover_controls(handover_env):
    client, _ = handover_env
    html_resp = await client.get("/")
    assert html_resp.status_code == 200
    assert "teacher-workspace-strip" in html_resp.text
    assert "class-select" in html_resp.text
    assert 'data-tab="class-handover"' in html_resp.text
    assert "view-class-handover" in html_resp.text


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 7: Independent Boundary Checks (Drafts, Approvals, Citations, Hashes & Uncalibrated Evidence)
# ─────────────────────────────────────────────────────────────────────────────


async def _seed_private_math_pattern(app) -> tuple[Pattern, ReviewItem]:
    items = await app.state.evidence_service.get_learner_history("LRN-001")
    citation = next(e.evidence_id for e in items if e.subject == "Mathematics")
    pattern = Pattern(
        learner_id="LRN-001",
        pattern_type=PatternType.TREND,
        summary="PRIVATE Mathematics finding awaiting class release.",
        supporting_evidence=[citation],
    )
    await app.state.store.add_pattern(pattern)
    item = ReviewItem(pattern_id=pattern.pattern_id)
    await app.state.store.add_review_item(item)
    return pattern, item


@pytest.mark.asyncio
async def test_subject_teacher_cannot_approve_private_candidate(handover_env):
    client, app = handover_env
    _, item = await _seed_private_math_pattern(app)
    await _login(client, "TCH-BANDA", "1234")
    response = await client.post(
        f"/api/reviews/{item.review_id}/decision",
        json={
            "status": "accepted",
            "expected_revision": 0,
            "teacher_notes": "Subject teacher should only append a response.",
        },
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_subject_teacher_cannot_read_draft_reviews_or_readiness(handover_env):
    client, app = handover_env
    await _seed_private_math_pattern(app)
    await _login(client, "TCH-OCHIENG", "5678")
    response = await client.post(
        "/api/classes/CLS-G3-BLUE/learners/LRN-001/sections/student",
        json={
            "review_state": "needs_clarification",
            "approved_summary": "PRIVATE student draft before release.",
        },
    )
    assert response.status_code == 200, response.text
    await _login(client, "TCH-BANDA", "1234")
    reviews = await client.get("/api/learners/LRN-001/reviews")
    readiness = await client.get("/api/classes/CLS-G3-BLUE/readiness")
    assert reviews.status_code == 403
    assert readiness.status_code == 403
    assert "PRIVATE" not in reviews.text and "PRIVATE" not in readiness.text


@pytest.mark.asyncio
async def test_accepted_finding_cannot_export_before_class_release(handover_env):
    client, app = handover_env
    _, item = await _seed_private_math_pattern(app)
    await _login(client, "TCH-OCHIENG", "5678")
    approval = await client.post(
        f"/api/reviews/{item.review_id}/decision",
        json={"status": "accepted", "expected_revision": 0},
    )
    assert approval.status_code == 200, approval.text
    await _login(client, "TCH-BANDA", "1234")
    handover = await client.get("/api/learners/LRN-001/handover")
    exported = await client.get("/api/learners/LRN-001/handover/export?format=json")
    assert "PRIVATE" not in handover.text and "PRIVATE" not in exported.text


@pytest.mark.asyncio
async def test_student_review_rejects_another_learner_subject_citation(handover_env):
    client, app = handover_env
    foreign = next(
        e
        for e in await app.state.evidence_service.get_learner_history("LRN-003")
        if e.subject == "English"
    )
    own_math = next(
        e
        for e in await app.state.evidence_service.get_learner_history("LRN-001")
        if e.subject == "Mathematics"
    )
    await _login(client, "TCH-OCHIENG", "5678")
    # 1. Citation from another learner rejected (422)
    response_foreign = await client.post(
        "/api/classes/CLS-G3-BLUE/learners/LRN-001/sections/student",
        json={
            "review_state": "ready_for_release",
            "approved_summary": "Whole-learner attendance context reviewed.",
            "citations": [foreign.evidence_id],
        },
    )
    assert response_foreign.status_code == 422, response_foreign.text

    # 2. Subject citation inside Student Review rejected (422)
    response_subj = await client.post(
        "/api/classes/CLS-G3-BLUE/learners/LRN-001/sections/student",
        json={
            "review_state": "ready_for_release",
            "approved_summary": "Whole-learner attendance context reviewed.",
            "citations": [own_math.evidence_id],
        },
    )
    assert response_subj.status_code == 422, response_subj.text


@pytest.mark.asyncio
async def test_math_teacher_cannot_read_latest_english_candidate_brief(handover_env):
    client, _ = handover_env
    await _login(client, "TCH-OCHIENG", "5678")
    generated = await client.post(
        "/api/learners/LRN-003/generate",
        json={"subject": "English", "mode": "deterministic"},
    )
    assert generated.status_code == 200 and generated.json().get("brief"), generated.text
    await _login(client, "TCH-BANDA", "1234")
    response = await client.get("/api/learners/LRN-003/brief")
    assert response.status_code == 403 or response.json().get("brief") is None, response.text


@pytest.mark.asyncio
async def test_uncalibrated_new_assessment_is_not_claimed_to_confirm_finding_and_published_hash_verified(handover_env):
    client, app = handover_env
    await _prepare_and_release_g3_blue(client)

    # Verify published sections store and verify a 64-hex SHA-256 approved_content_hash
    await _login(client, "TCH-BANDA", "1234")
    pub = (await client.get("/api/learners/LRN-001/published")).json()
    for sec in pub["sections"]:
        assert len(sec["approved_content_hash"]) == 64
        assert sec["hash_verified"] is True

    await app.state.evidence_service.record_evidence(
        learner_id="LRN-001",
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="independent_review",
        ingestion_method=IngestionMethod.API,
        source_type="system",
        source_reference="Exam office",
        academic_year=2026,
        term=4,
        subject="Mathematics",
        observed_at="2026-11-16T10:00:00Z",
        content={
            "grade": "Grade 3",
            "score": 95,
            "max_score": 100,
            "form": "Uncalibrated new assessment",
            "form_version": "new",
            "language": "English",
            "measured_skill": "different_skill",
            "comparison_authorized": False,
        },
    )
    changes = await app.state.handover_service.evaluate_post_release_changes_for_learner("LRN-001")
    math = [c for c in changes if c.scope == "Mathematics"]
    assert math and all(c.severity.value != "minor" for c in math), [c.model_dump(mode="json") for c in math]
