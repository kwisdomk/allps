"""Tests for Phase 2: Safety Policies, Teacher Review Gate, and Profile Surfacing.

Covers:
1. Label policy & prohibited diagnostic/deficit terminology screening.
2. ReviewItem domain validation and human reviewer requirements.
3. ReviewService adjudication and hard blocking of autonomous agents.
4. Auto-generation and deduplication of review items in AnalysisService.
5. Dual-view learner profile filtering (only accepted patterns surfaced).
6. Cryptographic SHA-256 content snapshot integrity verification.
7. Phase 2 MCP server tool integration over direct Python calls and stdio wire protocol.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import pytest

from allps.models.evidence import Evidence, EvidenceType, IngestionMethod
from allps.models.learner import Learner
from allps.models.pattern import Pattern, PatternType
from allps.models.review import ReviewItem, ReviewStatus
from allps.policies.label_policy import (
    check_for_prohibited_labels,
    scan_content_for_prohibited_labels,
    validate_text_for_prohibited_labels,
)
from allps.services.analysis_service import AnalysisService
from allps.services.evidence_service import EvidenceService
from allps.services.review_service import ReviewService
from allps.storage.sqlite_store import SQLiteStore
from allps.mcp.server import (
    flag_pattern_for_review,
    get_pending_reviews,
    get_surfaced_profile,
    resolve_teacher_review,
    set_service,
)


# ---------------------------------------------------------------------------
# 1. Label Policy & Deficit Screening
# ---------------------------------------------------------------------------

class TestLabelPolicy:
    """Screening for deficit labels and unauthorized clinical diagnoses."""

    @pytest.mark.parametrize(
        "bad_phrase",
        [
            "Student is a slow learner in reading",
            "Observed to be lazy during math exercises",
            "Teacher called student dumb and uncooperative",
            "He is stupid and hopeless at writing",
            "Known problem child in grade 4",
            "This student has adhd and cannot focus",
            "Diagnosis of a.d.h.d. noted by assistant",
            "Learner exhibits autistic traits",
            "Child has dyslexia and struggles with decoding",
            "Bipolar episodes observed in class",
        ],
    )
    def test_prohibited_labels_detected(self, bad_phrase: str):
        found = check_for_prohibited_labels(bad_phrase)
        assert len(found) > 0, f"Expected prohibited label in '{bad_phrase}'"
        with pytest.raises(ValueError, match="Prohibited deficit or diagnostic label"):
            validate_text_for_prohibited_labels(bad_phrase)

    @pytest.mark.parametrize(
        "legitimate_phrase",
        [
            "Learner requires additional scaffolding for multi-step algebraic proofs.",
            "Demonstrated steady progress in reading fluency across Term 1 and Term 2.",
            "Learner completed 15 out of 20 items in the allocated time.",
            "Spoke at a slow, measured tempo during the oral presentation.",
            "Added 5 marks to the baseline assessment score.",
            "Student benefited from peer collaboration during group science inquiry.",
        ],
    )
    def test_legitimate_pedagogical_language_allowed(self, legitimate_phrase: str):
        found = check_for_prohibited_labels(legitimate_phrase)
        assert found == [], f"Unexpected label detected in '{legitimate_phrase}': {found}"
        # Should not raise
        validate_text_for_prohibited_labels(legitimate_phrase)

    def test_scan_content_nested_structure(self):
        payload = {
            "score": 75,
            "observations": [
                {"teacher": "Ms. Smith", "note": "Engaged and participated actively"},
                {"teacher": "Mr. Jones", "note": "Student is a slow learner"},
            ],
        }
        with pytest.raises(ValueError, match="Prohibited deficit or diagnostic label detected in content.observations"):
            scan_content_for_prohibited_labels(payload)

    async def test_evidence_service_rejects_prohibited_labels(self, tmp_path: Path):
        db_path = str(tmp_path / "test_labels.db")
        store = SQLiteStore(db_path)
        await store.initialize()
        service = EvidenceService(store)

        try:
            with pytest.raises(ValueError, match="Prohibited deficit or diagnostic label"):
                await service.record_evidence(
                    learner_id="LRN-POLICY-01",
                    evidence_type="observation",
                    source_system="sis",
                    ingestion_method="manual_observation",
                    source_type="teacher",
                    source_reference="Staff Member",
                    academic_year=2025,
                    term=1,
                    content={"note": "Learner is lazy during group work"},
                    observed_at=datetime.now(timezone.utc),
                )

            # Confirm database has not stored the prohibited evidence
            history = await service.get_learner_history("LRN-POLICY-01")
            assert len(history) == 0
        finally:
            await store.close()


# ---------------------------------------------------------------------------
# 2. ReviewItem Domain Model Validation
# ---------------------------------------------------------------------------

class TestReviewItemModel:
    """Model invariants for ReviewItem and resolution metadata."""

    def test_create_pending_review_item(self):
        item = ReviewItem(pattern_id="pat-100", assigned_to="teacher-01")
        assert item.status == ReviewStatus.PENDING
        assert item.pattern_id == "pat-100"
        assert item.reviewer_id is None
        assert item.approved_content_hash is None
        assert item.resolved_at is None

    def test_accepted_requires_reviewer_id_and_content_hash(self):
        # Missing reviewer_id
        with pytest.raises(ValueError, match="requires an explicit human reviewer_id"):
            ReviewItem(
                pattern_id="pat-100",
                status=ReviewStatus.ACCEPTED,
                approved_content_hash="abc123hash",
            )

        # Missing approved_content_hash
        with pytest.raises(ValueError, match="requires an approved_content_hash"):
            ReviewItem(
                pattern_id="pat-100",
                status=ReviewStatus.ACCEPTED,
                reviewer_id="teacher:jane",
            )

        # Valid acceptance
        valid_item = ReviewItem(
            pattern_id="pat-100",
            status=ReviewStatus.ACCEPTED,
            reviewer_id="teacher:jane",
            approved_content_hash="abc123hash",
        )
        assert valid_item.status == ReviewStatus.ACCEPTED
        assert valid_item.resolved_at is not None

    def test_rejected_and_needs_context_require_reviewer_id(self):
        with pytest.raises(ValueError, match="requires an explicit human reviewer_id"):
            ReviewItem(pattern_id="pat-100", status=ReviewStatus.REJECTED)

        with pytest.raises(ValueError, match="requires an explicit human reviewer_id"):
            ReviewItem(pattern_id="pat-100", status=ReviewStatus.NEEDS_CONTEXT)

        # Valid rejection with reviewer_id
        rejected = ReviewItem(
            pattern_id="pat-100",
            status=ReviewStatus.REJECTED,
            reviewer_id="teacher:jane",
            teacher_notes="Evidence is incomplete",
        )
        assert rejected.status == ReviewStatus.REJECTED
        assert rejected.resolved_at is not None


# ---------------------------------------------------------------------------
# 3. ReviewService & Autonomous Agent Hard-Block
# ---------------------------------------------------------------------------

class TestReviewServiceGovernance:
    """Teacher review adjudication, agent blocking, and hash generation."""

    @pytest.fixture
    async def review_env(self, tmp_path: Path):
        db_path = str(tmp_path / "test_review_gov.db")
        store = SQLiteStore(db_path)
        await store.initialize()
        review_srv = ReviewService(store)

        await store.add_learner(Learner(learner_id="LRN-999", display_name="Learner 999"))

        # Seed sample pattern
        pattern = Pattern(
            pattern_id="PAT-SEED-01",
            learner_id="LRN-999",
            pattern_type=PatternType.TREND,
            summary="Declining mathematics performance across terms 1, 2, and 3 (75 -> 65 -> 50)",
            supporting_evidence=["EVD-1", "EVD-2", "EVD-3"],
            limitations=[],
        )
        await store.add_pattern(pattern)

        yield store, review_srv, pattern
        await store.close()

    @pytest.mark.parametrize(
        "bot_id",
        [
            "agent",
            "agent:orchestrator",
            "bot",
            "bot:reviewer",
            "system",
            "autonomous_agent",
            "llm:gemini",
            "ai:tutor",
            "synthetic_evaluator",
            "pydantic_ai_agent",
        ],
    )
    def test_is_autonomous_agent_detection(self, bot_id: str):
        assert ReviewService.is_autonomous_agent(bot_id) is True

    @pytest.mark.parametrize(
        "human_id",
        [
            "teacher:sarah_connor",
            "TCHR-882",
            "mrs_higgins",
            "principal_skinner",
            "educator_davis",
        ],
    )
    def test_human_educator_id_detection(self, human_id: str):
        assert ReviewService.is_autonomous_agent(human_id) is False

    async def test_agent_cannot_self_approve_pattern(self, review_env):
        store, review_srv, pattern = review_env

        review_item = await review_srv.flag_pattern_for_review(pattern.pattern_id)

        with pytest.raises(ValueError, match="is prohibited from approving patterns"):
            await review_srv.resolve_teacher_review(
                review_id=review_item.review_id,
                status="accepted",
                reviewer_id="agent:allps_orchestrator",
                teacher_notes="Automated self-approval attempt",
            )

        # Confirm review item is still PENDING in database
        persisted = await store.get_review_item(review_item.review_id)
        assert persisted.status == ReviewStatus.PENDING

    async def test_human_teacher_can_accept_and_generates_sha256_hash(self, review_env):
        store, review_srv, pattern = review_env

        review_item = await review_srv.flag_pattern_for_review(pattern.pattern_id)
        resolved = await review_srv.resolve_teacher_review(
            review_id=review_item.review_id,
            status="accepted",
            reviewer_id="teacher:mrs_smith",
            teacher_notes="Verified against classroom markbook; pattern accepted.",
        )

        assert resolved.status == ReviewStatus.ACCEPTED
        assert resolved.reviewer_id == "teacher:mrs_smith"
        expected_hash = hashlib.sha256(pattern.summary.strip().encode("utf-8")).hexdigest()
        assert resolved.approved_content_hash == expected_hash

        # Confirm in storage
        persisted = await store.get_review_item(review_item.review_id)
        assert persisted.status == ReviewStatus.ACCEPTED
        assert persisted.approved_content_hash == expected_hash

    async def test_flag_pattern_deduplicates_pending_items(self, review_env):
        store, review_srv, pattern = review_env

        item1 = await review_srv.flag_pattern_for_review(pattern.pattern_id)
        item2 = await review_srv.flag_pattern_for_review(pattern.pattern_id)

        assert item1.review_id == item2.review_id

        # Verify only one item in database
        items = await store.get_review_items_for_pattern(pattern.pattern_id)
        assert len(items) == 1


# ---------------------------------------------------------------------------
# 4. Dual-View Learner Profile & Cryptographic Integrity
# ---------------------------------------------------------------------------

class TestDualViewProfileSurfacing:
    """Strict profile filtering ensuring unaccepted patterns are never surfaced."""

    @pytest.fixture
    async def profile_env(self, tmp_path: Path):
        db_path = str(tmp_path / "test_profile_gov.db")
        store = SQLiteStore(db_path)
        await store.initialize()
        review_srv = ReviewService(store)

        await store.add_learner(Learner(learner_id="LRN-DUAL", display_name="Learner Dual"))

        # Seed 3 patterns for learner LRN-DUAL
        pat_accepted = Pattern(
            pattern_id="PAT-ACC",
            learner_id="LRN-DUAL",
            pattern_type=PatternType.TREND,
            summary="Consistent improvement across terms 1, 2, 3 in English (55 -> 68 -> 80)",
            supporting_evidence=["EVD-A1", "EVD-A2", "EVD-A3"],
            limitations=[],
        )
        pat_pending = Pattern(
            pattern_id="PAT-PEND",
            learner_id="LRN-DUAL",
            pattern_type=PatternType.CHANGED_FROM_BASELINE,
            summary="Drop from baseline in Science",
            supporting_evidence=["EVD-P1", "EVD-P2"],
            limitations=[],
        )
        pat_rejected = Pattern(
            pattern_id="PAT-REJ",
            learner_id="LRN-DUAL",
            pattern_type=PatternType.TREND,
            summary="Spurious correlation in attendance",
            supporting_evidence=["EVD-R1"],
            limitations=[],
        )

        await store.add_pattern(pat_accepted)
        await store.add_pattern(pat_pending)
        await store.add_pattern(pat_rejected)

        # Flag all three
        rev_acc = await review_srv.flag_pattern_for_review("PAT-ACC")
        rev_pend = await review_srv.flag_pattern_for_review("PAT-PEND")
        rev_rej = await review_srv.flag_pattern_for_review("PAT-REJ")

        # Resolve: 1 accepted, 1 left pending, 1 rejected
        await review_srv.resolve_teacher_review(
            rev_acc.review_id,
            status="accepted",
            reviewer_id="teacher:dr_watson",
            teacher_notes="Valid progression",
        )
        await review_srv.resolve_teacher_review(
            rev_rej.review_id,
            status="rejected",
            reviewer_id="teacher:dr_watson",
            teacher_notes="Invalid data collection timing",
        )

        yield store, review_srv
        await store.close()

    async def test_get_surfaced_profile_strictly_includes_accepted_only(self, profile_env):
        store, review_srv = profile_env

        profile = await review_srv.get_surfaced_profile("LRN-DUAL")
        assert profile["learner_id"] == "LRN-DUAL"
        assert profile["accepted_pattern_count"] == 1

        surfaced_pattern_ids = [p["pattern_id"] for p in profile["patterns"]]
        assert surfaced_pattern_ids == ["PAT-ACC"]
        assert "PAT-PEND" not in surfaced_pattern_ids
        assert "PAT-REJ" not in surfaced_pattern_ids

        # Verify hash verification succeeded
        pattern_data = profile["patterns"][0]
        assert pattern_data["review"]["status"] == "accepted"
        assert pattern_data["review"]["hash_verified"] is True

    async def test_detects_post_approval_tampering_or_drift(self, profile_env):
        store, review_srv = profile_env

        # Deliberately tamper with the pattern summary in the patterns table
        await store.db.execute(
            "UPDATE patterns SET summary = 'Tampered summary by rogue process' WHERE pattern_id = 'PAT-ACC'"
        )
        await store.db.commit()

        # Query surfaced profile: tampered pattern must be excluded
        profile = await review_srv.get_surfaced_profile("LRN-DUAL")
        assert profile["accepted_pattern_count"] == 0
        assert profile["patterns"] == []

    async def test_surfaced_profile_excludes_finding_when_hash_fails(self, tmp_path: Path):
        """Regression test: get_surfaced_profile must exclude a finding whose approval hash check fails, while preserving valid findings."""
        db_path = str(tmp_path / "test_hash_exclude.db")
        store = SQLiteStore(db_path)
        await store.initialize()
        review_srv = ReviewService(store)

        try:
            await store.add_learner(Learner(learner_id="LRN-HASH-TEST", display_name="Hash Learner"))

            pat1 = Pattern(
                pattern_id="PAT-VALID",
                learner_id="LRN-HASH-TEST",
                pattern_type=PatternType.TREND,
                summary="Valid pattern 1 summary",
                supporting_evidence=["EVD-1"],
                limitations=[],
            )
            pat2 = Pattern(
                pattern_id="PAT-TAMPERED",
                learner_id="LRN-HASH-TEST",
                pattern_type=PatternType.TREND,
                summary="Original pattern 2 summary",
                supporting_evidence=["EVD-2"],
                limitations=[],
            )
            await store.add_pattern(pat1)
            await store.add_pattern(pat2)

            rev1 = await review_srv.flag_pattern_for_review(pat1.pattern_id)
            rev2 = await review_srv.flag_pattern_for_review(pat2.pattern_id)

            await review_srv.resolve_teacher_review(
                rev1.review_id,
                status="accepted",
                reviewer_id="teacher:jane",
            )
            await review_srv.resolve_teacher_review(
                rev2.review_id,
                status="accepted",
                reviewer_id="teacher:jane",
            )

            # Both are accepted initially
            init_profile = await review_srv.get_surfaced_profile("LRN-HASH-TEST")
            assert init_profile["accepted_pattern_count"] == 2
            assert {p["pattern_id"] for p in init_profile["patterns"]} == {"PAT-VALID", "PAT-TAMPERED"}

            # Tamper PAT-TAMPERED summary in patterns table so actual_hash != approved_content_hash
            await store.db.execute(
                "UPDATE patterns SET summary = 'Corrupted summary' WHERE pattern_id = 'PAT-TAMPERED'"
            )
            await store.db.commit()

            # Query profile again: PAT-TAMPERED must be strictly excluded, PAT-VALID retained
            filtered_profile = await review_srv.get_surfaced_profile("LRN-HASH-TEST")
            assert filtered_profile["accepted_pattern_count"] == 1
            surfaced_ids = [p["pattern_id"] for p in filtered_profile["patterns"]]
            assert surfaced_ids == ["PAT-VALID"]
            assert "PAT-TAMPERED" not in surfaced_ids
        finally:
            await store.close()


# ---------------------------------------------------------------------------
# 5. Analysis Service Integration (Auto-review Generation & Deduplication)
# ---------------------------------------------------------------------------

class TestAnalysisIntegrationWithReview:
    """Candidate patterns generated by AnalysisService are automatically queued for teacher review."""

    async def test_analysis_generates_and_deduplicates_review_items(self, tmp_path: Path):
        db_path = str(tmp_path / "test_analysis_auto_rev.db")
        store = SQLiteStore(db_path)
        await store.initialize()
        evidence_srv = EvidenceService(store)
        analysis_srv = AnalysisService(evidence_srv)

        try:
            # Ingest 3 comparable terms for LRN-AUTO
            for term, score in [(1, 60), (2, 70), (3, 85)]:
                await evidence_srv.record_evidence(
                    learner_id="LRN-AUTO",
                    evidence_type="assessment",
                    source_system="sis",
                    ingestion_method="api",
                    source_type="teacher",
                    source_reference="Teacher A",
                    academic_year=2025,
                    term=term,
                    content={
                        "score": score,
                        "max_score": 100,
                        "grade": "Grade 4",
                        "subject": "Mathematics",
                        "measured_skill": "multiplication",
                        "form": "quiz",
                        "form_version": "v1",
                        "language": "en",
                        "comparison_authorized": True,
                    },
                    observed_at=f"2025-0{term*3}-15T10:00:00+00:00",
                    subject="Mathematics",
                )

            # First analysis run
            patterns1 = await analysis_srv.analyse_longitudinal_pattern("LRN-AUTO", subject="Mathematics")
            assert len(patterns1) >= 1
            trend1 = [p for p in patterns1 if p["pattern_type"] == "trend"][0]
            assert "review_id" in trend1
            assert trend1["review_status"] == "pending"

            # Check that ReviewItem was persisted in store
            pending_items = await store.get_pending_reviews()
            assert any(item.review_id == trend1["review_id"] for item in pending_items)

            # Second analysis run (should deduplicate and return same review_id)
            patterns2 = await analysis_srv.analyse_longitudinal_pattern("LRN-AUTO", subject="Mathematics")
            trend2 = [p for p in patterns2 if p["pattern_type"] == "trend"][0]
            assert trend2["review_id"] == trend1["review_id"]

            # Verify no inbox spam occurred
            pending_items_after = await store.get_pending_reviews()
            matching = [i for i in pending_items_after if i.review_id == trend1["review_id"]]
            assert len(matching) == 1
        finally:
            await store.close()


# ---------------------------------------------------------------------------
# 6. MCP Protocol Wire Integration for Phase 2 Tools
# ---------------------------------------------------------------------------

class TestMCPPhase2WireProtocol:
    """Test full Phase 2 review governance workflow over stdio MCP wire protocol."""

    async def test_mcp_phase2_tools_wire_protocol(self, tmp_path: Path):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        db_path = str(tmp_path / "test_mcp_wire_phase2.db")
        # Ingest 3 comparable assessments into the DB before server launch
        init_store = SQLiteStore(db_path)
        await init_store.initialize()
        init_srv = EvidenceService(init_store)

        for term, score in [(1, 80), (2, 70), (3, 55)]:
            await init_srv.record_evidence(
                learner_id="LRN-WIRE-PHASE2",
                evidence_type="assessment",
                source_system="sis",
                ingestion_method="api",
                source_type="teacher",
                source_reference="Mr. Davis",
                academic_year=2025,
                term=term,
                content={
                    "score": score,
                    "max_score": 100,
                    "grade": "Grade 5",
                    "subject": "Mathematics",
                    "measured_skill": "algebra",
                    "form": "standard_term",
                    "form_version": "v2",
                    "language": "en",
                    "comparison_authorized": True,
                },
                observed_at=f"2025-0{term*3}-10T09:00:00+00:00",
                subject="Mathematics",
            )
        await init_store.close()

        env = os.environ.copy()
        env["ALLPS_DB_PATH"] = db_path
        env["PYTHONUNBUFFERED"] = "1"
        src_path = str(Path(__file__).resolve().parent.parent / "src")
        env["PYTHONPATH"] = src_path + (os.pathsep + env.get("PYTHONPATH", "") if env.get("PYTHONPATH") else "")

        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "allps.mcp.server"],
            env=env,
        )

        async with stdio_client(server_params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()

                # 1. Run analyse_longitudinal_pattern via MCP
                anal_res = await session.call_tool(
                    "analyse_longitudinal_pattern",
                    arguments={"learner_id": "LRN-WIRE-PHASE2", "subject": "Mathematics"},
                )
                assert anal_res.content
                patterns = [json.loads(c.text) for c in anal_res.content]
                assert len(patterns) >= 1
                trend_pat = [p for p in patterns if p["pattern_type"] == "trend"][0]
                assert "review_id" in trend_pat
                review_id = trend_pat["review_id"]

                # 2. Check get_pending_reviews via MCP
                inbox_res = await session.call_tool("get_pending_reviews", arguments={})
                assert inbox_res.content
                pending_inbox = [json.loads(c.text) for c in inbox_res.content]
                assert any(item["review_id"] == review_id for item in pending_inbox)

                # 3. Check get_surfaced_profile before approval (MUST BE EMPTY)
                prof_before = await session.call_tool(
                    "get_surfaced_profile",
                    arguments={"learner_id": "LRN-WIRE-PHASE2"},
                )
                assert prof_before.content
                prof_before_data = json.loads(prof_before.content[0].text)
                assert prof_before_data["accepted_pattern_count"] == 0
                assert prof_before_data["patterns"] == []

                # 4. Autonomous MCP client attempts self-approval -> MUST BE REJECTED (GOV-02)
                resolve_res = await session.call_tool(
                    "resolve_teacher_review",
                    arguments={
                        "review_id": review_id,
                        "status": "accepted",
                        "reviewer_id": "teacher:mr_davis",
                        "teacher_notes": "Attempted self-approval via autonomous MCP client.",
                    },
                )
                assert resolve_res.is_error is True
                assert any("resolve_teacher_review" in c.text or "cannot self-approve" in c.text for c in resolve_res.content)

                # 4b. Sovereign human teacher resolves review via trusted backend path
                backend_store = SQLiteStore(db_path)
                await backend_store.initialize()
                backend_review_srv = ReviewService(backend_store)
                await backend_review_srv.resolve_teacher_review(
                    review_id=review_id,
                    status=ReviewStatus.ACCEPTED,
                    reviewer_id="teacher:mr_davis",
                    teacher_notes="Pattern validated; learner needs targeted intervention.",
                )
                await backend_store.close()

                # 5. Check get_surfaced_profile after approval (MUST CONTAIN PATTERN)
                prof_after = await session.call_tool(
                    "get_surfaced_profile",
                    arguments={"learner_id": "LRN-WIRE-PHASE2"},
                )
                assert prof_after.content
                prof_after_data = json.loads(prof_after.content[0].text)
                assert prof_after_data["accepted_pattern_count"] == 1
                assert prof_after_data["patterns"][0]["review"]["hash_verified"] is True
