"""Live integration test against LM Studio.

Connects to the local model running at http://127.0.0.1:1234/v1,
retrieves real longitudinal records for Learner 001 (Amara Kemboi),
runs deterministic comparability analysis, synthesizes a candidate brief via LM Studio,
validates the output, and exercises the human review gate.
"""

import asyncio
import os
import sys
from pathlib import Path

# Ensure src/ is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from allps.agent.adapter import LocalOpenAIClient
from allps.agent.orchestrator import AgentOrchestrator, OrchestrationResult
from allps.models.review import ReviewStatus
from allps.services.analysis_service import AnalysisService
from allps.services.evidence_service import EvidenceService
from allps.services.review_service import ReviewService
from allps.storage.sqlite_store import SQLiteStore


async def main():
    print("=" * 70)
    print("ALLPS — Live LM Studio Integration Test")
    print("Endpoint: http://127.0.0.1:1234/v1")
    print("=" * 70)

    db_path = os.environ.get("ALLPS_DB_PATH", "allps_dev.db")
    print(f"\n[1] Connecting to database: {db_path}...")
    store = SQLiteStore(db_path)
    await store.initialize()

    ev_srv = EvidenceService(store)
    an_srv = AnalysisService(ev_srv, store)
    rev_srv = ReviewService(store)

    # Detect models on LM Studio
    client = LocalOpenAIClient(
        base_url="http://127.0.0.1:1234/v1",
        model="qwen3.5-4b-claude-4.6-opus-reasoning-distilled",
        timeout_seconds=90.0,
        max_retries=1,
    )

    orchestrator = AgentOrchestrator(
        evidence_service=ev_srv,
        analysis_service=an_srv,
        review_service=rev_srv,
        inference_client=client,
        store=store,
    )

    learner_id = "LRN-001"
    print(f"\n[2] Running live orchestrator for Learner '{learner_id}' (Amara Kemboi - Mathematics)...")
    result: OrchestrationResult = await orchestrator.orchestrate_handover(
        learner_id,
        subject="Mathematics",
        assigned_to="Mr. Banda",
    )

    print("\n" + "-" * 70)
    print(f"Orchestration Status: {result.status.upper()}")
    print(f"Review ID:           {result.review_id}")
    print(f"Pattern ID:          {result.pattern_id}")
    print("-" * 70)

    if result.status == "validation_failed":
        print("\n[!] VALIDATION REJECTED LLM DRAFT:")
        for err in result.errors:
            print(f"  * {err}")
        print("\nRaw Model Output:")
        print(result.raw_inference_output)
        return

    if result.status == "inference_failed":
        print("\n[!] INFERENCE FAILED:")
        for err in result.errors:
            print(f"  * {err}")
        return

    if result.brief:
        print("\n[SUCCESS] VALIDATED PEDAGOGICAL HANDOVER BRIEF:")
        print(f"Brief ID:    {result.brief.brief_id}")
        print(f"Status:      {result.brief.status.value}")
        print(f"Summary:     {result.brief.summary}")
        print(f"\nFindings ({len(result.brief.findings)}):")
        for idx, f in enumerate(result.brief.findings, 1):
            print(f"  [{idx}] Observation:  {f.observation}")
            print(f"      Citations:    {f.supporting_evidence_ids}")
            if f.co_occurring_factors:
                print(f"      Co-occurring: {f.co_occurring_factors}")
            if f.teacher_inquiries:
                print(f"      Inquiries:    {f.teacher_inquiries}")

        if result.brief.limitations:
            print(f"\nLimitations: {result.brief.limitations}")

    # Governance check: Is it in surfaced profile?
    surfaced_before = await rev_srv.get_surfaced_profile(learner_id)
    print(f"\n[3] Governance Check: Surfaced patterns before teacher review: {len(surfaced_before['patterns'])}")
    assert len(surfaced_before['patterns']) == 0, "Unapproved pattern should NOT be surfaced!"
    print("    -> Invariant held: Pattern is strictly gated from learner profile.")

    # Human Review Simulation
    if result.review_id:
        print(f"\n[4] Simulating Human Teacher Review (Mr. Banda resolving {result.review_id})...")
        approved = await rev_srv.resolve_teacher_review(
            review_id=result.review_id,
            status=ReviewStatus.ACCEPTED,
            reviewer_id="TCH-BANDA",
            teacher_notes="Confirmed mathematics decline across 2026. Needs foundational fraction scaffolding in Term 1 Grade 5.",
        )
        print("    -> Review Status:  ACCEPTED")
        print(f"    -> Reviewer ID:    {approved.reviewer_id}")
        print(f"    -> SHA-256 Hash:   {approved.approved_content_hash}")

        # Surfaced profile check after approval
        surfaced_after = await rev_srv.get_surfaced_profile(learner_id)
        print(f"\n[5] Surfaced patterns after teacher review: {len(surfaced_after['patterns'])}")
        assert len(surfaced_after['patterns']) >= 1, "Approved pattern SHOULD now be surfaced!"
        for p in surfaced_after['patterns']:
            print(f"    * Pattern [{p['pattern_type']}]: {p['summary']}")

    print("\n" + "=" * 70)
    print("SUCCESS: Live LM Studio test completed and fully verified!")
    print("=" * 70)

    await store.close()


if __name__ == "__main__":
    asyncio.run(main())
