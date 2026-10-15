"""End-to-End Demonstration of the ALLPS Longitudinal Pedagogical Pipeline.

Milestone 03 Executable Specification:
Demonstrates the 5 canonical outcomes of the bounded AI architecture:
1. Trend Detection (Amara Kemboi) -> Validated AI Handover -> Teacher Review (ACCEPTED) -> Surfaced with SHA-256
2. Persistent Strength (Thabo Ndlovu) -> Validated AI Handover -> Teacher Review (ACCEPTED) -> Surfaced with SHA-256
3. Divergence / Conflicting Evidence (Naledi Mwangi) -> Validated AI Handover -> Teacher Review (REJECTED with context) -> Hidden
4. Safe AI Abstention (Insufficient Evidence) -> Deterministic Engine -> Clean Abstention -> Zero Review Items -> Hidden
5. Policy Rejection -> Intentionally Invalid LLM Draft (Indirect Peer Comparison, Deficit Labels, Causal Links) -> Gated & Blocked

Supports:
  --mode mock  : Offline, deterministic, instant (< 2s) execution for CI and challenge evaluators.
  --mode live  : Connects to local LM Studio / OpenAI-compatible endpoint at http://127.0.0.1:1234/v1.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any

# Ensure project root and src/ are on sys.path
root_dir = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, root_dir)
sys.path.insert(0, str(Path(root_dir) / "src"))

from allps.agent.adapter import (
    DeterministicMockClient,
    InferenceClient,
    InferenceError,
    LocalOpenAIClient,
)
from allps.agent.contracts import CandidateHandoverBrief, HandoverStatus
from allps.agent.orchestrator import AgentOrchestrator, OrchestrationResult
from allps.agent.validator import OutputValidator, ValidationResult
from allps.models.audit import AuditEntry
from allps.models.evidence import Evidence, EvidenceType, IngestionMethod
from allps.models.learner import Learner
from allps.runtime import (
    ExecutionMode,
    RuntimeRegistry,
    RuntimeSelectionError,
    RuntimeSelectionResult,
    RuntimeType,
)
from allps.models.review import ReviewItem, ReviewStatus
from allps.services.analysis_service import AnalysisService
from allps.services.evidence_service import EvidenceService
from allps.services.review_service import ReviewService
from allps.storage.sqlite_store import SQLiteStore

# Import synthetic seed dataset
from data.synthetic.seed_data import ALL_EVIDENCE, LEARNERS


def print_banner(text: str) -> None:
    print("\n" + "=" * 80, flush=True)
    print(f" {text}", flush=True)
    print("=" * 80, flush=True)


def print_step(num: int, title: str) -> None:
    print(f"\n[{num}] {title}", flush=True)
    print("-" * 80, flush=True)


async def setup_disposable_database(db_path: str) -> SQLiteStore:
    """Initialize a clean, disposable SQLite database and seed synthetic records."""
    store = SQLiteStore(db_path)
    await store.initialize()

    for learner in LEARNERS:
        await store.add_learner(learner)

    for ev in ALL_EVIDENCE:
        await store.add_evidence(ev)

    return store


def build_mock_responses(records_by_learner: dict[str, list[Evidence]]) -> dict[str, str]:
    """Dynamically build contract-compliant mock responses citing exact database UUIDs."""
    responses: dict[str, str] = {}

    # 1. Amara Kemboi (LRN-001) - Declining math trend
    l1_math = [r for r in records_by_learner.get("LRN-001", []) if r.subject == "Mathematics" and r.evidence_type == EvidenceType.ASSESSMENT]
    l1_att = [r for r in records_by_learner.get("LRN-001", []) if r.evidence_type == EvidenceType.ATTENDANCE]
    l1_eids = [r.evidence_id for r in l1_math]

    amara_payload = {
        "learner_id": "LRN-001",
        "status": "completed",
        "summary": "Demonstrated a downward trajectory in Grade 3 mathematics across terms 1, 2, and 3.",
        "findings": [
            {
                "observation": "Mathematics assessment scores decreased from 82 in Term 1 to 68 in Term 2 and 51 in Term 3.",
                "supporting_evidence_ids": l1_eids,
                "conflicting_evidence_ids": [],
                "co_occurring_factors": [
                    "Attendance declined from 48 days present in Term 1 to 38 days present in Term 3."
                ],
                "teacher_inquiries": [
                    "Consider foundational multiplication and division scaffolding in Term 1 Grade 4."
                ]
            }
        ],
        "contradictions": [],
        "limitations": [
            "Observations reflect one academic year in Grade 3."
        ],
        "abstention_reason": None
    }
    responses["LRN-001"] = json.dumps(amara_payload)

    # 2. Thabo Ndlovu (LRN-002) - Persistent science strength
    l2_sci = [r for r in records_by_learner.get("LRN-002", []) if r.subject == "Science" and r.evidence_type == EvidenceType.ASSESSMENT]
    l2_proj = [r for r in records_by_learner.get("LRN-002", []) if r.evidence_type == EvidenceType.PROJECT]
    l2_eids = [r.evidence_id for r in l2_sci]

    thabo_payload = {
        "learner_id": "LRN-002",
        "status": "completed",
        "summary": "Demonstrated persistent aptitude in Grade 3 science across terms 1, 2, and 3.",
        "findings": [
            {
                "observation": "Science assessment scores remained consistently high at 88 in Term 1, 91 in Term 2, and 89 in Term 3.",
                "supporting_evidence_ids": l2_eids,
                "conflicting_evidence_ids": [],
                "co_occurring_factors": [
                    "High attendance recorded with 49 days present in Term 2.",
                    "Completed Water Filtration Model project in Term 1."
                ],
                "teacher_inquiries": [
                    "Encourage regional science challenge participation or peer mentorship."
                ]
            }
        ],
        "contradictions": [],
        "limitations": [],
        "abstention_reason": None
    }
    responses["LRN-002"] = json.dumps(thabo_payload)

    # 3. Naledi Mwangi (LRN-003, English) - Conflicting observations
    l3_eng = [r for r in records_by_learner.get("LRN-003", []) if r.subject == "English" and r.evidence_type == EvidenceType.ASSESSMENT]
    l3_eids = [r.evidence_id for r in l3_eng]

    naledi_payload = {
        "learner_id": "LRN-003",
        "status": "completed",
        "summary": "Demonstrated stable reading comprehension scores alongside observational notes of quiet classroom engagement.",
        "findings": [
            {
                "observation": "English assessment scores remained stable at 78 in Term 1, 81 in Term 2, and 76 in Term 3.",
                "supporting_evidence_ids": l3_eids,
                "conflicting_evidence_ids": [],
                "co_occurring_factors": [
                    "Teacher observations in Terms 1 and 2 noted quiet classroom behavior and limited verbal participation."
                ],
                "teacher_inquiries": [
                    "Provide small-group discussion formats or written response options to assess spoken fluency."
                ]
            }
        ],
        "contradictions": [
            "Assessment performance indicates reading mastery while classroom observations indicate verbal withdrawal."
        ],
        "limitations": [
            "Learner self-reflection was only recorded in Term 3."
        ],
        "abstention_reason": None
    }
    responses["LRN-003"] = json.dumps(naledi_payload)

    # 4. Abstention payload for sparse science stream
    abstention_payload = {
        "learner_id": "LRN-003",
        "status": "abstained",
        "summary": "Insufficient longitudinal evidence in science to infer a reliable trajectory.",
        "findings": [],
        "contradictions": [],
        "limitations": [
            "Fewer than 3 comparable observation points recorded in science series; Term 2 assessment was water-damaged."
        ],
        "abstention_reason": "Insufficient longitudinal data: requires at least 3 comparable assessment points."
    }
    responses["target_subject=\"Science\""] = json.dumps(abstention_payload)

    return responses


async def run_demonstration(
    mode: str = "mock",
    endpoint: str = "http://127.0.0.1:1234/v1",
    model: str = "qwen3.5-4b-claude-4.6-opus-reasoning-distilled",
    db_path: str | None = None,
    keep_db: bool = False,
    timeout_seconds: float = 90.0,
) -> dict[str, Any]:
    """Execute the full Milestone 03 end-to-end demonstration."""
    is_temp_db = False
    if db_path is None:
        temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = temp_file.name
        temp_file.close()
        is_temp_db = True

    print_banner(f"ALLPS MILESTONE 03 -- END-TO-END SYSTEM DEMONSTRATION (Mode: {mode.upper()})")
    print(f"Database: {db_path} ({'disposable temporary' if is_temp_db else 'persisted'})", flush=True)

    # 1. Initialize and Seed
    print_step(1, "Setting up isolated database and seeding synthetic Kenyan records...")
    t0 = time.perf_counter()
    store = await setup_disposable_database(db_path)
    try:
        return await _execute_demo_pipeline(
            store=store,
            mode=mode,
            endpoint=endpoint,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    finally:
        await store.close()
        if is_temp_db and not keep_db:
            try:
                os.remove(db_path)
                for ext in ("-shm", "-wal"):
                    extra = db_path + ext
                    if os.path.exists(extra):
                        os.remove(extra)
            except Exception:
                pass


async def _execute_demo_pipeline(
    store: SQLiteStore,
    mode: str,
    endpoint: str,
    model: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    ev_srv = EvidenceService(store)
    an_srv = AnalysisService(ev_srv, store)
    rev_srv = ReviewService(store)
    validator = OutputValidator()

    # Preload records to construct exact citation mocks
    records_by_learner: dict[str, list[Evidence]] = {}
    for lid in ("LRN-001", "LRN-002", "LRN-003"):
        records_by_learner[lid] = await ev_srv.get_learner_history(lid)
    print(f"[SUCCESS] Database seeded with {len(LEARNERS)} learners and {len(ALL_EVIDENCE)} synthetic records", flush=True)

    # 2. Select Inference Adapter via RuntimeRegistry
    mock_responses = build_mock_responses(records_by_learner)
    print("\n[ALLPS] Initializing runtime...")

    registry = RuntimeRegistry()
    is_custom_ep = (endpoint != "http://127.0.0.1:1234/v1")

    selection, inference_client = await registry.select_runtime(
        mode=mode,
        preferred_model=model,
        custom_endpoint=endpoint if is_custom_ep else None,
        custom_timeout=timeout_seconds,
        mock_responses=mock_responses,
    )

    print("\n[ALLPS] Runtime Discovery & Selection Details:", flush=True)
    for detail in selection.discovery_details:
        prov = detail.get("provider", "Provider")
        base = detail.get("base_url", "")
        models_found = detail.get("models_found", [])
        if detail.get("reachable"):
            print(f"  * Provider '{prov}' ({base}): REACHABLE", flush=True)
            print(f"    - Discovered Models ({len(models_found)}): {models_found}", flush=True)
            if detail.get("selected_model"):
                print(f"    - Matched Model ID:   {detail['selected_model']}", flush=True)
            if detail.get("probe_ready"):
                lat = detail.get("probe_latency_ms", 0.0)
                print(f"    - Readiness Probe:    PASSED ({lat:.1f}ms latency)", flush=True)
            elif "probe_ready" in detail and not detail.get("probe_ready"):
                print(f"    - Readiness Probe:    FAILED ({detail.get('probe_error')})", flush=True)
        elif detail.get("reachable") is False:
            print(f"  * Provider '{prov}' ({base}): UNAVAILABLE ({detail.get('discovery_error')})", flush=True)

    print(f"  * Effective Selected Runtime: {selection.runtime_type.value.upper()} ({selection.provider_name})", flush=True)
    print(f"  * Effective Model ID:         {selection.model_id or 'N/A'}", flush=True)
    print(f"  * Inference Timeout:          {timeout_seconds}s", flush=True)
    if selection.is_fallback:
        print(f"  * Fallback Active:            YES ({selection.fallback_reason})", flush=True)
    else:
        print(f"  * Fallback Active:            NO (Primary AI Active)", flush=True)

    if mode == "mock":
        print("Using DeterministicMockClient for 100% offline, zero-dependency reproducible execution.", flush=True)

    print("\n[ALLPS] Starting learner analysis...", flush=True)

    orchestrator = AgentOrchestrator(
        evidence_service=ev_srv,
        analysis_service=an_srv,
        review_service=rev_srv,
        inference_client=inference_client,
        validator=validator,
        store=store,
    )

    demo_results: dict[str, Any] = {}

    # -----------------------------------------------------------------------
    # OUTCOME 1: Amara Kemboi (LRN-001) -- Declining Math Trend (Accepted)
    # -----------------------------------------------------------------------
    print_step(2, "Outcome 1: Amara Kemboi (LRN-001) -- Mathematics Declining Trend")
    t_start = time.perf_counter()
    res1 = await orchestrator.orchestrate_handover("LRN-001", subject="Mathematics", assigned_to="Mr. Banda")
    latency1_ms = (time.perf_counter() - t_start) * 1000

    print(f"Inference Latency:   {latency1_ms:.1f} ms", flush=True)
    print(f"Orchestration Status: {res1.status.upper()}", flush=True)
    assert res1.brief is not None, "Candidate brief must be present for LRN-001"
    assert res1.status == "success", f"Expected success, got {res1.status}"

    print(f"Validated Summary:   \"{res1.brief.summary}\"", flush=True)
    cited_eids_1 = res1.brief.findings[0].supporting_evidence_ids
    print(f"Citations Verified:  {cited_eids_1} (100% ground truth verified)", flush=True)

    # Dual-View Gate Check Before Review
    surfaced_before_1 = await rev_srv.get_surfaced_profile("LRN-001")
    print(f"Surfaced Profile (Pre-Review): {len(surfaced_before_1['patterns'])} patterns (PENDING finding strictly hidden)", flush=True)
    assert len(surfaced_before_1["patterns"]) == 0, "Unapproved finding must NOT be surfaced!"

    # Simulate Teacher Adjudication
    print("\n[SIMULATION: Explicit Teacher Review Simulation -- NOT Authenticated Human Review]")
    assert res1.review_id is not None
    review1 = await rev_srv.resolve_teacher_review(
        review_id=res1.review_id,
        status=ReviewStatus.ACCEPTED,
        reviewer_id="TCH-SIM-BANDA",
        teacher_notes="Confirmed mathematics decline across Grade 3. Recommend foundational fraction scaffolding in Term 1 Grade 4.",
    )
    print(f"Teacher Decision:    ACCEPTED by {review1.reviewer_id}", flush=True)
    print(f"SHA-256 Snapshot:    {review1.approved_content_hash}", flush=True)

    # Dual-View Gate Check After Review
    surfaced_after_1 = await rev_srv.get_surfaced_profile("LRN-001")
    print(f"Surfaced Profile (Post-Review): {len(surfaced_after_1['patterns'])} patterns (ACCEPTED finding now visible)", flush=True)
    assert len(surfaced_after_1["patterns"]) == 1, "Accepted finding must be surfaced!"

    demo_results["outcome_1"] = {
        "learner_id": "LRN-001",
        "status": "accepted",
        "latency_ms": latency1_ms,
        "hash": review1.approved_content_hash,
    }

    # -----------------------------------------------------------------------
    # OUTCOME 2: Thabo Ndlovu (LRN-002) -- Persistent Science Strength (Accepted)
    # -----------------------------------------------------------------------
    print_step(3, "Outcome 2: Thabo Ndlovu (LRN-002) -- Persistent Science Strength")
    t_start = time.perf_counter()
    res2 = await orchestrator.orchestrate_handover("LRN-002", subject="Science", assigned_to="Dr. Mensah")
    latency2_ms = (time.perf_counter() - t_start) * 1000

    print(f"Inference Latency:   {latency2_ms:.1f} ms", flush=True)
    print(f"Orchestration Status: {res2.status.upper()}", flush=True)
    assert res2.brief is not None
    assert res2.status == "success"

    print(f"Validated Summary:   \"{res2.brief.summary}\"", flush=True)
    cited_eids_2 = res2.brief.findings[0].supporting_evidence_ids
    print(f"Citations Verified:  {cited_eids_2} (100% ground truth verified)", flush=True)

    # Dual-View Gate Check Before Review
    surfaced_before_2 = await rev_srv.get_surfaced_profile("LRN-002")
    print(f"Surfaced Profile (Pre-Review): {len(surfaced_before_2['patterns'])} patterns (PENDING finding strictly hidden)", flush=True)
    assert len(surfaced_before_2["patterns"]) == 0

    # Simulate Teacher Adjudication
    print("\n[SIMULATION: Explicit Teacher Review Simulation -- NOT Authenticated Human Review]")
    assert res2.review_id is not None
    review2 = await rev_srv.resolve_teacher_review(
        review_id=res2.review_id,
        status=ReviewStatus.ACCEPTED,
        reviewer_id="TCH-SIM-MENSAH",
        teacher_notes="Persistent aptitude confirmed across assessments and practical project. Recommending for regional science challenge.",
    )
    print(f"Teacher Decision:    ACCEPTED by {review2.reviewer_id}", flush=True)
    print(f"SHA-256 Snapshot:    {review2.approved_content_hash}", flush=True)

    # Dual-View Gate Check After Review
    surfaced_after_2 = await rev_srv.get_surfaced_profile("LRN-002")
    print(f"Surfaced Profile (Post-Review): {len(surfaced_after_2['patterns'])} patterns (ACCEPTED finding now visible)", flush=True)
    assert len(surfaced_after_2["patterns"]) == 1

    demo_results["outcome_2"] = {
        "learner_id": "LRN-002",
        "status": "accepted",
        "latency_ms": latency2_ms,
        "hash": review2.approved_content_hash,
    }

    # -----------------------------------------------------------------------
    # OUTCOME 3: Naledi Mwangi (LRN-003) -- Conflicting Evidence (Rejected with Context)
    # -----------------------------------------------------------------------
    print_step(4, "Outcome 3: Naledi Mwangi (LRN-003) -- Divergent Scores vs Observations")
    t_start = time.perf_counter()
    res3 = await orchestrator.orchestrate_handover("LRN-003", subject="English", assigned_to="Ms. Achebe")
    latency3_ms = (time.perf_counter() - t_start) * 1000

    print(f"Inference Latency:   {latency3_ms:.1f} ms", flush=True)
    print(f"Orchestration Status: {res3.status.upper()}", flush=True)
    assert res3.brief is not None
    assert res3.status == "success"

    print(f"Validated Summary:   \"{res3.brief.summary}\"", flush=True)
    if res3.brief.contradictions:
        print(f"Contradictions:      {res3.brief.contradictions[0]}", flush=True)

    # Dual-View Gate Check Before Review
    surfaced_before_3 = await rev_srv.get_surfaced_profile("LRN-003")
    print(f"Surfaced Profile (Pre-Review): {len(surfaced_before_3['patterns'])} patterns (PENDING finding strictly hidden)", flush=True)
    assert len(surfaced_before_3["patterns"]) == 0

    # Simulate Teacher Rejection with Context
    print("\n[SIMULATION: Explicit Teacher Review Simulation -- NOT Authenticated Human Review]")
    assert res3.review_id is not None
    review3 = await rev_srv.resolve_teacher_review(
        review_id=res3.review_id,
        status=ReviewStatus.REJECTED,
        reviewer_id="TCH-SIM-ACHEBE",
        teacher_notes="Observations of quietness in Term 2 coincided with a temporary period of family bereavement. Learner is actively re-engaging; do not flag as chronic withdrawal.",
    )
    print(f"Teacher Decision:    REJECTED by {review3.reviewer_id}", flush=True)
    print(f"Contextual Reason:   \"{review3.teacher_notes}\"", flush=True)

    # Dual-View Gate Check After Review (Must Remain 0)
    surfaced_after_3 = await rev_srv.get_surfaced_profile("LRN-003")
    print(f"Surfaced Profile (Post-Review): {len(surfaced_after_3['patterns'])} patterns (REJECTED finding remains HIDDEN)", flush=True)
    assert len(surfaced_after_3["patterns"]) == 0, "Rejected finding must NEVER enter surfaced profile!"

    demo_results["outcome_3"] = {
        "learner_id": "LRN-003",
        "status": "rejected",
        "latency_ms": latency3_ms,
        "teacher_notes": review3.teacher_notes,
    }

    # -----------------------------------------------------------------------
    # OUTCOME 4: Safe Abstention on Insufficient / Incomparable Evidence
    # -----------------------------------------------------------------------
    print_step(5, "Outcome 4: Safe AI Abstention -- Insufficient Longitudinal Evidence")
    # LRN-003 in Science has only 2 records, one of which is water-damaged (result_unavailable)
    t_start = time.perf_counter()
    if mode in ("live", "auto", "deterministic"):
        # In live, auto, or deterministic mode, call orchestrator directly on science
        res4 = await orchestrator.orchestrate_handover("LRN-003", subject="Science")
    else:
        # In mock mode, deterministic mock returns abstention
        client_abstain = DeterministicMockClient(default_response=mock_responses["target_subject=\"Science\""])
        orch_abstain = AgentOrchestrator(
            evidence_service=ev_srv,
            analysis_service=an_srv,
            review_service=rev_srv,
            inference_client=client_abstain,
            validator=validator,
            store=store,
        )
        res4 = await orch_abstain.orchestrate_handover("LRN-003", subject="Science")
    latency4_ms = (time.perf_counter() - t_start) * 1000

    print(f"Inference Latency:   {latency4_ms:.1f} ms", flush=True)
    print(f"Orchestration Status: {res4.status.upper()}", flush=True)
    assert res4.status == "abstained", f"Expected abstained, got {res4.status}"
    assert res4.brief is not None
    assert res4.brief.status == HandoverStatus.ABSTAINED
    print(f"Abstention Reason:   \"{res4.brief.abstention_reason}\"", flush=True)
    print(f"Review Item Created: {res4.review_id is not None} (None created -> Zero noise for teachers)", flush=True)
    assert res4.review_id is None, "Abstained brief must NOT create a review item!"

    demo_results["outcome_4"] = {
        "learner_id": "LRN-003",
        "status": "abstained",
        "latency_ms": latency4_ms,
        "abstention_reason": res4.brief.abstention_reason,
    }

    # -----------------------------------------------------------------------
    # OUTCOME 5: Deterministic Policy Rejection (Indirect Peer Comparison)
    # -----------------------------------------------------------------------
    print_step(6, "Outcome 5: Deterministic Policy Rejection -- Indirect Peer Comparison & Deficit Screening")
    t_start = time.perf_counter()

    # Formulate an intentionally invalid draft targeting indirect peer-comparison language
    l1_math_recs = [r for r in records_by_learner["LRN-001"] if r.evidence_type == EvidenceType.ASSESSMENT and r.subject == "Mathematics"]
    l1_target_eid = l1_math_recs[-1].evidence_id if l1_math_recs else "mock-id"

    invalid_draft = json.dumps({
        "learner_id": "LRN-001",
        "status": "completed",
        "summary": "Learner is falling behind peers in arithmetic, performing below grade average relative to classmates, and is at the bottom of the class.",
        "findings": [
            {
                "observation": "Mathematics score was 51 in Term 3.",
                "supporting_evidence_ids": [l1_target_eid],
                "co_occurring_factors": [
                    "In comparison to classmates, attendance was lower."
                ],
                "teacher_inquiries": [
                    "How can the teacher help the student catch up with the class average?"
                ]
            }
        ],
        "contradictions": [],
        "limitations": []
    })

    invalid_client = DeterministicMockClient(default_response=invalid_draft)
    orch_invalid = AgentOrchestrator(
        evidence_service=ev_srv,
        analysis_service=an_srv,
        review_service=rev_srv,
        inference_client=invalid_client,
        validator=validator,
        store=store,
    )
    res5 = await orch_invalid.orchestrate_handover("LRN-001", subject="Mathematics")
    latency5_ms = (time.perf_counter() - t_start) * 1000

    print(f"Inference Latency:   {latency5_ms:.1f} ms", flush=True)
    print(f"Orchestration Status: {res5.status.upper()}", flush=True)
    assert res5.status == "validation_failed", f"Expected validation_failed, got {res5.status}"
    print(f"Violations Blocked ({len(res5.errors)} detected by OutputValidator):", flush=True)
    for idx, err in enumerate(res5.errors, 1):
        print(f"  * [Rule Violation {idx}] {err}", flush=True)

    # Verify specific indirect peer-comparison policy rejections
    assert any("Peer-ranking" in err for err in res5.errors), "Must reject indirect peer comparison"

    # Governance check: Draft was rejected at the gate, never creating a candidate brief
    assert res5.brief is None, "Validated brief must be None when validation fails"
    recent_audits = await store.get_audit_log(tool_name="ai_orchestrate_handover")
    assert any("failed: validation_error" in a.approval_state for a in recent_audits), "Audit log must record validation rejection"

    # Confirm invalid draft content never entered the surfaced profile
    surfaced_l1 = await rev_srv.get_surfaced_profile("LRN-001")
    for pat in surfaced_l1["patterns"]:
        assert "falling behind peers" not in pat["summary"], "Invalid peer-ranking text leaked into profile!"
        assert "bottom of the class" not in pat["summary"], "Invalid peer-ranking text leaked into profile!"
    print("Governance Status:   Gated before database insertion. Draft permanently discarded.", flush=True)

    demo_results["outcome_5"] = {
        "learner_id": "LRN-001",
        "status": "validation_failed",
        "latency_ms": latency5_ms,
        "violations_detected": len(res5.errors),
    }

    # -----------------------------------------------------------------------
    # AUDIT TRAIL VERIFICATION
    # -----------------------------------------------------------------------
    print_step(7, "Audit Log & Provenance Verification")
    audit_entries = await store.get_audit_log()
    print(f"Total Audit Trail Entries Logged: {len(audit_entries)}", flush=True)
    print("Recent Audit Events:", flush=True)
    for entry in audit_entries[-6:]:
        ts = entry.timestamp.strftime("%H:%M:%S")
        print(f"  [{ts}] {entry.tool_name:<26} state={entry.approval_state}", flush=True)

    demo_results["runtime_selection"] = {
        "mode": mode,
        "runtime_type": selection.runtime_type.value,
        "provider": selection.provider_name,
        "model": selection.model_id,
        "is_fallback": selection.is_fallback,
    }

    print_banner("ALLPS MILESTONE 03 -- EXECUTIVE DEMO RESULTS")
    print(f"Runtime Mode:      {mode.upper()}", flush=True)
    print(f"Active Runtime:    {selection.runtime_type.value.upper()} ({selection.provider_name})", flush=True)
    print(f"Model ID:          {selection.model_id or 'N/A'}", flush=True)
    print(f"Fallback Active:   {'YES (' + str(selection.fallback_reason) + ')' if selection.is_fallback else 'NO'}\n", flush=True)
    print(f"{'Outcome':<30} | {'Learner':<10} | {'Status':<16} | {'Dual-View Gate':<20} | {'Latency':<10}")
    print("-" * 96)
    print(f"{'1. Mathematics Decline':<30} | {'LRN-001':<10} | {'ACCEPTED':<16} | {'Surfaced (SHA-256)':<20} | {latency1_ms:.1f}ms")
    print(f"{'2. Science Persistence':<30} | {'LRN-002':<10} | {'ACCEPTED':<16} | {'Surfaced (SHA-256)':<20} | {latency2_ms:.1f}ms")
    print(f"{'3. Conflicting Evidence':<30} | {'LRN-003':<10} | {'REJECTED':<16} | {'Hidden (Zero Leak)':<20} | {latency3_ms:.1f}ms")
    print(f"{'4. Insufficient Records':<30} | {'LRN-003':<10} | {'ABSTAINED':<16} | {'Hidden (No Review)':<20} | {latency4_ms:.1f}ms")
    print(f"{'5. Indirect Peer Comparison':<30} | {'LRN-001':<10} | {'BLOCKED':<16} | {'Gated at Validator':<20} | {latency5_ms:.1f}ms")
    print("-" * 96)
    print("[SUCCESS] All 5 canonical outcomes verified against inviolable governance rules.\n", flush=True)

    return demo_results


def parse_args():
    parser = argparse.ArgumentParser(description="ALLPS Milestone 03 End-to-End System Demonstration")
    parser.add_argument(
        "--mode",
        choices=["mock", "live", "auto", "deterministic"],
        default="mock",
        help="Execution mode (choices: auto, live, deterministic, mock; default: mock)",
    )
    parser.add_argument("--endpoint", default="http://127.0.0.1:1234/v1", help="OpenAI-compatible inference endpoint")
    parser.add_argument("--model", default="allps-qwen35-base-4b", help="Model identifier (default: allps-qwen35-base-4b)")
    parser.add_argument("--db-path", default=None, help="Custom database path (defaults to disposable temporary SQLite file)")
    parser.add_argument("--keep-db", action="store_true", help="Keep disposable database file on exit")
    parser.add_argument("--timeout", type=float, default=90.0, help="Inference timeout in seconds (default: 90.0)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(
            run_demonstration(
                mode=args.mode,
                endpoint=args.endpoint,
                model=args.model,
                db_path=args.db_path,
                keep_db=args.keep_db,
                timeout_seconds=args.timeout,
            )
        )
    except RuntimeSelectionError as exc:
        print(f"\n[ALLPS ERROR] Runtime selection failed: {exc}\n", file=sys.stderr, flush=True)
        sys.exit(1)
