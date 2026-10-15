"""Comprehensive automated tests for ALLPS runtime discovery, selection, and graceful degradation.

Covers:
1. LM Studio reachable with matching, functional model.
2. Provider reachable but requested model missing.
3. Model listed but loading fails (probe failure).
4. Connection refused.
5. Inference timeout during discovery/probe.
6. Malformed provider response.
7. Ollama fallback when LM Studio is unavailable.
8. Both providers unavailable.
9. Explicit live mode refusing silent fallback.
10. Auto mode selecting deterministic analysis.
11. Mock mode regression tests.
12. Validator rejecting unsupported or fabricated evidence citations.
13. Deterministic fallback preserving teacher-review and audit requirements.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import httpx

from allps.agent.adapter import (
    DeterministicMockClient,
    InferenceClient,
    InferenceError,
    InferenceTimeoutError,
    InferenceUnavailableError,
)
from allps.agent.contracts import CandidateHandoverBrief, HandoverStatus
from allps.agent.orchestrator import AgentOrchestrator, OrchestrationResult
from allps.agent.validator import OutputValidator
from allps.models.evidence import Evidence, EvidenceType, IngestionMethod
from allps.models.learner import Learner
from allps.models.review import ReviewStatus
from allps.runtime.deterministic import DeterministicAnalysisClient
from allps.runtime.discovery import ProviderDiscoveryService
from allps.runtime.models import (
    ExecutionMode,
    ProviderConfig,
    ProviderType,
    RuntimeType,
)
from allps.runtime.registry import (
    ResilientInferenceClient,
    RuntimeRegistry,
    RuntimeSelectionError,
)
from allps.services.analysis_service import AnalysisService
from allps.services.evidence_service import EvidenceService
from allps.services.review_service import ReviewService
from allps.storage.sqlite_store import SQLiteStore
from data.synthetic.seed_data import ALL_EVIDENCE, LEARNERS


# ---------------------------------------------------------------------------
# Test Helpers & Seed Setup
# ---------------------------------------------------------------------------

async def create_seeded_store(tmp_path: Path) -> SQLiteStore:
    db_file = str(tmp_path / "test_runtime.db")
    store = SQLiteStore(db_file)
    await store.initialize()
    for l in LEARNERS:
        await store.add_learner(l)
    for e in ALL_EVIDENCE:
        await store.add_evidence(e)
    return store


# ---------------------------------------------------------------------------
# 1. LM Studio reachable with matching, functional model
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_1_lmstudio_matching_functional_model():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={"data": [{"id": "qwen3.5-4b-claude-4.6-opus-reasoning-distilled"}]},
            )
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": "pong"}}]},
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    disc_service = ProviderDiscoveryService(client=client)
    registry = RuntimeRegistry(discovery_service=disc_service)

    selection, adapter = await registry.select_runtime(
        mode=ExecutionMode.AUTO,
        preferred_model="qwen3.5-4b-claude-4.6-opus-reasoning-distilled",
    )

    assert selection.runtime_type == RuntimeType.LIVE_AI
    assert selection.provider_name == "LM Studio"
    assert selection.model_id == "qwen3.5-4b-claude-4.6-opus-reasoning-distilled"
    assert not selection.is_fallback


# ---------------------------------------------------------------------------
# 2. Provider reachable but requested model missing
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_2_model_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={"data": [{"id": "mistral-7b-instruct"}]},
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    disc_service = ProviderDiscoveryService(client=client)

    config = ProviderConfig(
        name="LM Studio",
        provider_type=ProviderType.LM_STUDIO,
        base_url="http://127.0.0.1:1234/v1",
        preferred_models=["specific-unloaded-model-xyz"],
    )
    res = await disc_service.discover_models(config)
    assert res.is_reachable
    assert res.selected_model is None
    assert "not found in available models" in (res.error_message or "")


def test_case_2b_matching_not_overly_permissive():
    """Verify runtime discovery cannot select unintended models through overly permissive substring matches."""
    svc = ProviderDiscoveryService()

    # Case A: Available model is a short substring of preferred model — MUST NOT match
    preferred = ["qwen3.5-4b-claude-4.6-opus-reasoning-distilled"]
    unintended_models = ["claude", "opus", "base", "4b", "reasoning"]
    for unintended in unintended_models:
        selected = svc._select_best_matching_model([unintended], preferred)
        assert selected is None, f"Overly permissive match: selected '{selected}' for pref '{preferred[0]}'"

    # Case B: Available model contains the full preferred identifier — SHOULD match
    available_with_quant = ["qwen3.5-4b-claude-4.6-opus-reasoning-distilled-Q4_K_M.gguf"]
    selected = svc._select_best_matching_model(available_with_quant, preferred)
    assert selected == available_with_quant[0]

    # Case C: Separator normalization matches ':' vs '-'
    assert svc._select_best_matching_model(["qwen2.5-7b"], ["qwen2.5:7b"]) == "qwen2.5-7b"
    assert svc._select_best_matching_model(["qwen2.5:7b"], ["qwen2.5-7b"]) == "qwen2.5:7b"

    # Case D: Repo prefix normalization
    assert svc._select_best_matching_model(["meta-llama/Llama-3-8B"], ["llama-3-8b"]) == "meta-llama/Llama-3-8B"
    assert svc._select_best_matching_model(["meta-llama/Llama-3-70B"], ["llama-3-8b"]) is None


# ---------------------------------------------------------------------------
# 3. Model listed but loading / probe fails
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_3_model_listed_probe_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={"data": [{"id": "qwen2.5-7b-instruct"}]},
            )
        if request.url.path.endswith("/chat/completions"):
            # Model listed, but memory allocation / load failed
            return httpx.Response(
                500,
                json={"error": "Failed to load model weights into VRAM"},
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    disc_service = ProviderDiscoveryService(client=client)
    config = ProviderConfig(
        name="LM Studio",
        provider_type=ProviderType.LM_STUDIO,
        base_url="http://127.0.0.1:1234/v1",
    )
    probe_res = await disc_service.probe_model_readiness(config, "qwen2.5-7b-instruct")
    assert not probe_res.is_ready
    assert "HTTP status 500" in (probe_res.error_message or "")


# ---------------------------------------------------------------------------
# 4. Connection refused
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_4_connection_refused():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused by localhost:1234")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    disc_service = ProviderDiscoveryService(client=client)
    config = ProviderConfig(
        name="LM Studio",
        provider_type=ProviderType.LM_STUDIO,
        base_url="http://127.0.0.1:1234/v1",
    )
    res = await disc_service.discover_models(config)
    assert not res.is_reachable
    assert "Connection refused" in (res.error_message or "")


# ---------------------------------------------------------------------------
# 5. Inference timeout during probe
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_5_inference_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Read timed out after 5.0s")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    disc_service = ProviderDiscoveryService(client=client)
    config = ProviderConfig(
        name="LM Studio",
        provider_type=ProviderType.LM_STUDIO,
        base_url="http://127.0.0.1:1234/v1",
        probe_timeout_seconds=5.0,
    )
    probe_res = await disc_service.probe_model_readiness(config, "slow-model")
    assert not probe_res.is_ready
    assert "timed out" in (probe_res.error_message or "").lower()


# ---------------------------------------------------------------------------
# 6. Malformed provider response
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_6_malformed_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>Not an API</body></html>", headers={"content-type": "text/html"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    disc_service = ProviderDiscoveryService(client=client)
    config = ProviderConfig(
        name="LM Studio",
        provider_type=ProviderType.LM_STUDIO,
        base_url="http://127.0.0.1:1234/v1",
    )
    res = await disc_service.discover_models(config)
    assert not res.is_reachable
    assert "Discovery failed" in (res.error_message or "") or "Malformed" in (res.error_message or "")


# ---------------------------------------------------------------------------
# 7. Ollama fallback when LM Studio is unavailable
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_7_ollama_fallback_when_lmstudio_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        # LM Studio is down
        if "1234" in str(request.url):
            raise httpx.ConnectError("LM Studio offline")
        # Ollama is up
        if "11434" in str(request.url):
            if request.url.path.endswith("/models"):
                return httpx.Response(200, json={"data": [{"id": "mistral:7b"}]})
            if request.url.path.endswith("/chat/completions"):
                return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    disc_service = ProviderDiscoveryService(client=client)
    registry = RuntimeRegistry(discovery_service=disc_service)

    selection, adapter = await registry.select_runtime(mode=ExecutionMode.AUTO)
    assert selection.runtime_type == RuntimeType.LIVE_AI
    assert selection.provider_name == "Ollama"
    assert selection.model_id == "mistral:7b"


# ---------------------------------------------------------------------------
# 8. Both providers unavailable
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_8_both_providers_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Port unreachable")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    disc_service = ProviderDiscoveryService(client=client)
    registry = RuntimeRegistry(discovery_service=disc_service)

    selection, adapter = await registry.select_runtime(mode=ExecutionMode.AUTO)
    assert selection.runtime_type == RuntimeType.DETERMINISTIC
    assert selection.is_fallback
    assert "AI providers unavailable" in (selection.fallback_reason or "")
    assert isinstance(adapter, DeterministicAnalysisClient)


# ---------------------------------------------------------------------------
# 9. Explicit live mode refusing silent fallback
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_9_live_mode_refuses_silent_fallback():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("No AI runtime running")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    disc_service = ProviderDiscoveryService(client=client)
    registry = RuntimeRegistry(discovery_service=disc_service)

    with pytest.raises(RuntimeSelectionError) as exc_info:
        await registry.select_runtime(mode=ExecutionMode.LIVE)

    assert "Live AI execution requested, but no verified inference provider is ready" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 10. Auto mode selecting deterministic analysis when providers down
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_10_auto_mode_selects_deterministic(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Offline")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    disc_service = ProviderDiscoveryService(client=client)
    registry = RuntimeRegistry(discovery_service=disc_service)

    selection, adapter = await registry.select_runtime(mode=ExecutionMode.AUTO)
    assert selection.runtime_type == RuntimeType.DETERMINISTIC
    assert selection.is_fallback

    # Run actual orchestration with this deterministic adapter
    store = await create_seeded_store(tmp_path)
    ev_srv = EvidenceService(store)
    an_srv = AnalysisService(ev_srv, store)
    rev_srv = ReviewService(store)

    orch = AgentOrchestrator(
        evidence_service=ev_srv,
        analysis_service=an_srv,
        review_service=rev_srv,
        inference_client=adapter,
        store=store,
    )
    result = await orch.orchestrate_handover("LRN-001", subject="Mathematics")
    assert result.status == "success"
    assert result.brief is not None
    assert "[Deterministic Analysis]" in result.brief.summary
    assert result.runtime_info.get("runtime_method") == "deterministic"
    await store.close()


# ---------------------------------------------------------------------------
# 11. Mock mode regression tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_11_mock_mode_selection():
    registry = RuntimeRegistry()
    selection, adapter = await registry.select_runtime(mode=ExecutionMode.MOCK)
    assert selection.runtime_type == RuntimeType.MOCK
    assert isinstance(adapter, DeterministicMockClient)


# ---------------------------------------------------------------------------
# 12. Validator rejecting unsupported or fabricated evidence citations
# ---------------------------------------------------------------------------
def test_case_12_validator_rejects_fabricated_citations():
    validator = OutputValidator()
    # Create valid synthetic record
    ev = Evidence(
        evidence_id="valid-ev-001",
        learner_id="LRN-001",
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="sis",
        ingestion_method=IngestionMethod.API,
        source_type="file",
        source_reference="test.csv",
        academic_year=2026,
        term=1,
        content={"score": 82, "max_score": 100},
        grade="Grade 3",
        subject="Mathematics",
        observed_at="2026-03-15T08:00:00Z",
    )

    # Draft with hallucinated evidence ID
    bad_draft = json.dumps({
        "learner_id": "LRN-001",
        "status": "completed",
        "summary": "Learner scored 82 marks in Term 1.",
        "findings": [
            {
                "observation": "Mathematics score was 82.",
                "supporting_evidence_ids": ["hallucinated-id-999"],
                "co_occurring_factors": [],
                "teacher_inquiries": []
            }
        ]
    })

    val_res = validator.validate(bad_draft, retrieved_evidence=[ev], expected_learner_id="LRN-001")
    assert not val_res.is_valid
    assert any("non-existent or unauthorized evidence_id" in e for e in val_res.errors)


# ---------------------------------------------------------------------------
# 13. Deterministic fallback preserving teacher-review and audit requirements
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_13_deterministic_fallback_preserves_governance(tmp_path: Path):
    store = await create_seeded_store(tmp_path)
    ev_srv = EvidenceService(store)
    an_srv = AnalysisService(ev_srv, store)
    rev_srv = ReviewService(store)

    # Simulate resilient client where primary fails mid-execution and falls back to deterministic
    failing_primary = DeterministicMockClient(should_fail_connection=True)
    resilient_client = ResilientInferenceClient(
        primary_client=failing_primary,
        fallback_client=DeterministicAnalysisClient(),
        allow_fallback=True,
    )

    orch = AgentOrchestrator(
        evidence_service=ev_srv,
        analysis_service=an_srv,
        review_service=rev_srv,
        inference_client=resilient_client,
        store=store,
    )

    # Execute handover
    res = await orch.orchestrate_handover("LRN-001", subject="Mathematics", assigned_to="Mr. Banda")
    assert res.status == "success"
    assert res.brief is not None
    assert res.review_id is not None
    assert resilient_client.used_fallback
    assert res.runtime_info.get("runtime_method") == "deterministic_fallback"

    # Dual-view gate before review: must be 0
    surfaced_before = await rev_srv.get_surfaced_profile("LRN-001")
    assert len(surfaced_before["patterns"]) == 0

    # Human teacher adjudication
    review = await rev_srv.resolve_teacher_review(
        review_id=res.review_id,
        status=ReviewStatus.ACCEPTED,
        reviewer_id="TCH-BANDA",
        teacher_notes="Verified via deterministic fallback.",
    )
    assert review.status == ReviewStatus.ACCEPTED
    assert review.approved_content_hash is not None

    # Dual-view gate after review: must be surfaced
    surfaced_after = await rev_srv.get_surfaced_profile("LRN-001")
    assert len(surfaced_after["patterns"]) == 1

    # Audit log check: must record deterministic_fallback
    audits = await store.get_audit_log(tool_name="ai_orchestrate_handover")
    assert any("deterministic_fallback" in a.approval_state for a in audits)

    await store.close()


# ---------------------------------------------------------------------------
# 14. Explicit model selection: different fine-tune superstring rejected
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_14_different_finetune_superstring_rejected():
    constructed_model = "unintended-qwen3.5-4b-claude-4.6-opus-reasoning-distilled-different-finetune"
    requested = "qwen3.5-4b-claude-4.6-opus-reasoning-distilled"

    # Direct selector verification
    selected = ProviderDiscoveryService._select_best_matching_model(
        available_models=[constructed_model],
        preferred_models=[requested],
    )
    assert selected is None, f"Superstring match must be rejected, but got {selected}"

    # Registry verification in AUTO mode: must not select constructed_model; falls back to deterministic
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": constructed_model}]})
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    disc = ProviderDiscoveryService(client=client)
    reg = RuntimeRegistry(discovery_service=disc)

    # In AUTO mode: falls back to deterministic analysis because requested model is absent
    sel, _ = await reg.select_runtime(mode=ExecutionMode.AUTO, preferred_model=requested)
    assert sel.runtime_type == RuntimeType.DETERMINISTIC
    assert sel.is_fallback is True
    assert "not found in available models" in (sel.fallback_reason or "")

    # In LIVE mode: strictly raises RuntimeSelectionError
    with pytest.raises(RuntimeSelectionError, match="no verified inference provider is ready"):
        await reg.select_runtime(mode=ExecutionMode.LIVE, preferred_model=requested)


# ---------------------------------------------------------------------------
# 15. Explicit model selection: requested Qwen absent but Mistral available
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_15_requested_qwen_absent_mistral_available():
    requested = "qwen3.5-4b-claude-4.6-opus-reasoning-distilled"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "mistral-7b-instruct"}]})
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "pong"}}]})
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    disc = ProviderDiscoveryService(client=client)
    reg = RuntimeRegistry(discovery_service=disc)

    # In AUTO mode: must NOT select Mistral; must fall back to deterministic
    sel, _ = await reg.select_runtime(mode=ExecutionMode.AUTO, preferred_model=requested)
    assert sel.runtime_type == RuntimeType.DETERMINISTIC
    assert sel.is_fallback is True
    assert sel.model_id is None or sel.model_id != "mistral-7b-instruct"

    # In LIVE mode: must strictly fail with RuntimeSelectionError rather than hijacking Mistral
    with pytest.raises(RuntimeSelectionError, match="no verified inference provider is ready"):
        await reg.select_runtime(mode=ExecutionMode.LIVE, preferred_model=requested)


# ---------------------------------------------------------------------------
# 16. Explicit model selection: exact requested model and configured alias
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_16_exact_and_configured_alias_matching():
    requested = "qwen3.5-4b-claude-4.6-opus-reasoning-distilled"

    # Exact match
    selected = ProviderDiscoveryService._select_best_matching_model(
        available_models=["mistral-7b-instruct", requested],
        preferred_models=[requested],
    )
    assert selected == requested

    # Configured alias match
    selected_alias = ProviderDiscoveryService._select_best_matching_model(
        available_models=["allps-qwen35-base-4b"],
        preferred_models=[requested],
        model_aliases={requested: ["allps-qwen35-base-4b"]},
    )
    assert selected_alias == "allps-qwen35-base-4b"


# ---------------------------------------------------------------------------
# 17. Failure followed by recovery: per-request runtime provenance
# ---------------------------------------------------------------------------
class FlakyPrimaryClient(InferenceClient):
    """Fails on call 1, succeeds on call 2."""

    def __init__(self, valid_json_output: str) -> None:
        self.call_count = 0
        self.valid_json_output = valid_json_output

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        self.call_count += 1
        if self.call_count == 1:
            raise InferenceTimeoutError("Primary inference timed out on request 1")
        return self.valid_json_output


@pytest.mark.asyncio
async def test_case_17_failure_followed_by_recovery_provenance(tmp_path: Path):
    store = await create_seeded_store(tmp_path)
    ev_srv = EvidenceService(store)
    an_srv = AnalysisService(ev_srv, store)
    rev_srv = ReviewService(store)
    records = await ev_srv.get_learner_history("LRN-001", subject="Mathematics")
    real_ev_ids = [records[0].evidence_id, records[1].evidence_id]

    valid_response = json.dumps({
        "learner_id": "LRN-001",
        "status": "completed",
        "summary": "Learner demonstrates steady progression across three terms.",
        "findings": [
            {
                "observation": "Mathematics scores showed steady progression over academic terms.",
                "supporting_evidence_ids": real_ev_ids,
                "conflicting_evidence_ids": [],
                "co_occurring_factors": ["High attendance record"],
                "teacher_inquiries": ["How to sustain progression into term 3?"]
            }
        ],
        "contradictions": [],
        "limitations": [],
        "abstention_reason": None,
    })

    flaky_primary = FlakyPrimaryClient(valid_json_output=valid_response)
    resilient_client = ResilientInferenceClient(
        primary_client=flaky_primary,
        fallback_client=DeterministicAnalysisClient(),
        allow_fallback=True,
    )

    orch = AgentOrchestrator(
        evidence_service=ev_srv,
        analysis_service=an_srv,
        review_service=rev_srv,
        inference_client=resilient_client,
        store=store,
    )

    # Request 1: Primary fails -> Fallback succeeds
    res1 = await orch.orchestrate_handover("LRN-001", subject="Mathematics", assigned_to="Teacher A")
    assert res1.status == "success"
    assert res1.runtime_info.get("runtime_method") == "deterministic_fallback"
    assert resilient_client.used_fallback is True

    # Check Audit Log for Request 1
    audits = await store.get_audit_log(tool_name="ai_orchestrate_handover")
    assert len(audits) == 1
    assert audits[0].input_summary["runtime_method"] == "deterministic_fallback"
    assert "deterministic_fallback" in audits[0].approval_state

    # Request 2: Primary recovers -> Live AI succeeds
    res2 = await orch.orchestrate_handover("LRN-001", subject="Mathematics", assigned_to="Teacher A")
    assert res2.status == "success"
    assert res2.runtime_info.get("runtime_method") == "live_ai"
    # Provenance flag MUST be reset to False, not carry over from request 1
    assert resilient_client.used_fallback is False

    # Check Audit Log: entry 0 is request 1, entry 1 is request 2 (ORDER BY timestamp ASC)
    audits_after = await store.get_audit_log(tool_name="ai_orchestrate_handover")
    assert len(audits_after) == 2
    assert audits_after[0].input_summary["runtime_method"] == "deterministic_fallback"
    assert "deterministic_fallback" in audits_after[0].approval_state

    assert audits_after[1].input_summary["runtime_method"] == "live_ai"
    assert "deterministic_fallback" not in audits_after[1].approval_state
    assert audits_after[1].approval_state == "pending_teacher_review"

    await store.close()


# ---------------------------------------------------------------------------
# 18. Validation rejection never triggers fallback
# ---------------------------------------------------------------------------
class DeficitPrimaryClient(InferenceClient):
    """Returns syntactically valid JSON that violates governance rules (deficit label)."""

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        return json.dumps({
            "learner_id": "LRN-001",
            "status": "completed",
            "summary": "Student is a slow learner in reading and lazy in class.",
            "findings": [
                {
                    "observation": "Student is a slow learner.",
                    "supporting_evidence_ids": ["EVD-001"],
                    "conflicting_evidence_ids": [],
                    "co_occurring_factors": [],
                    "teacher_inquiries": []
                }
            ],
            "contradictions": [],
            "limitations": [],
            "abstention_reason": None,
        })


@pytest.mark.asyncio
async def test_case_18_validation_rejection_refuses_fallback(tmp_path: Path):
    store = await create_seeded_store(tmp_path)
    ev_srv = EvidenceService(store)
    an_srv = AnalysisService(ev_srv, store)
    rev_srv = ReviewService(store)

    deficit_client = DeficitPrimaryClient()
    fallback_client = DeterministicAnalysisClient()

    resilient_client = ResilientInferenceClient(
        primary_client=deficit_client,
        fallback_client=fallback_client,
        allow_fallback=True,
    )

    orch = AgentOrchestrator(
        evidence_service=ev_srv,
        analysis_service=an_srv,
        review_service=rev_srv,
        inference_client=resilient_client,
        store=store,
    )

    # Execute handover with invalid AI draft
    res = await orch.orchestrate_handover("LRN-001", subject="Mathematics")

    # MUST be validation_failed, NOT success via fallback
    assert res.status == "validation_failed"
    assert res.brief is None
    assert any("prohibited deficit" in e.lower() for e in res.errors)

    # Resilient client fallback MUST NOT have been triggered
    assert resilient_client.used_fallback is False

    # Audit log check: records validation failure, never fallback
    audits = await store.get_audit_log(tool_name="ai_orchestrate_handover")
    assert len(audits) == 1
    assert "failed: validation_error" in audits[0].approval_state
    assert "deterministic_fallback" not in audits[0].approval_state

    await store.close()


# ---------------------------------------------------------------------------
# 19. Teacher review authority boundary & accepted-only profile filtering
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_19_teacher_review_authority_boundary(tmp_path: Path):
    store = await create_seeded_store(tmp_path)
    rev_srv = ReviewService(store)

    # 1. AgentOrchestrator has no review resolution capability
    assert not hasattr(AgentOrchestrator, "resolve_teacher_review")
    assert not hasattr(AgentOrchestrator, "approve_pattern")

    # 2. Autonomous bot identifiers strictly rejected on approval attempts
    for bot_id in ["agent:allps", "bot_reviewer", "llm-adjudicator", "autonomous_system"]:
        assert rev_srv.is_autonomous_agent(bot_id) is True

    # 3. Accepted-only profile filtering: pending and rejected items never surface
    from allps.models.pattern import Pattern, PatternType
    pat_pending = Pattern(
        pattern_id="PAT-PEND-1",
        learner_id="LRN-001",
        pattern_type=PatternType.TREND,
        summary="Pending pattern not yet reviewed.",
        supporting_evidence=["EVD-001"],
        limitations=[],
    )
    pat_rejected = Pattern(
        pattern_id="PAT-REJ-1",
        learner_id="LRN-001",
        pattern_type=PatternType.TREND,
        summary="Rejected pattern due to uncalibrated instrument.",
        supporting_evidence=["EVD-001"],
        limitations=[],
    )
    await store.add_pattern(pat_pending)
    await store.add_pattern(pat_rejected)

    rev_p = await rev_srv.flag_pattern_for_review("PAT-PEND-1")
    rev_r = await rev_srv.flag_pattern_for_review("PAT-REJ-1")

    # Reject rev_r as teacher
    await rev_srv.resolve_teacher_review(
        review_id=rev_r.review_id,
        status=ReviewStatus.REJECTED,
        reviewer_id="teacher:mrs_smith",
        teacher_notes="Instrument uncalibrated.",
    )

    # Profile must remain empty because neither is accepted
    profile = await rev_srv.get_surfaced_profile("LRN-001")
    assert profile["accepted_pattern_count"] == 0
    assert len(profile["patterns"]) == 0

    await store.close()


# ---------------------------------------------------------------------------
# 20. Explicit model selection requires exact provider ID or configured alias
# ---------------------------------------------------------------------------
def test_case_20_explicit_model_selection_namespace_isolation():
    available = [
        "other-publisher/qwen3.5-4b",
        "approved-publisher/mistral-7b",
    ]

    # 1. Requesting approved-publisher/qwen3.5-4b without alias MUST be rejected
    # even though basename 'qwen3.5-4b' matches 'other-publisher/qwen3.5-4b'
    matched = ProviderDiscoveryService._select_explicit_model(
        available_models=available,
        preferred_models=["approved-publisher/qwen3.5-4b"],
        model_aliases={},
    )
    assert matched is None

    # 2. Configured alias explicitly approves it
    aliases = {
        "approved-publisher/qwen3.5-4b": ["other-publisher/qwen3.5-4b"]
    }
    matched_aliased = ProviderDiscoveryService._select_explicit_model(
        available_models=available,
        preferred_models=["approved-publisher/qwen3.5-4b"],
        model_aliases=aliases,
    )
    assert matched_aliased == "other-publisher/qwen3.5-4b"

    # 3. Exact match with namespace
    available_with_approved = [
        "approved-publisher/qwen3.5-4b",
        "other-publisher/qwen3.5-4b",
    ]
    matched_exact = ProviderDiscoveryService._select_explicit_model(
        available_models=available_with_approved,
        preferred_models=["approved-publisher/qwen3.5-4b"],
        model_aliases={},
    )
    assert matched_exact == "approved-publisher/qwen3.5-4b"

    # 4. Quantization suffix is NOT stripped automatically on explicit path
    available_quant = ["approved-publisher/qwen3.5-4b-q4_k_m"]
    matched_quant = ProviderDiscoveryService._select_explicit_model(
        available_models=available_quant,
        preferred_models=["approved-publisher/qwen3.5-4b"],
        model_aliases={},
    )
    assert matched_quant is None


# ---------------------------------------------------------------------------
# 21. Overlapping concurrent requests preserve isolated provenance & audit
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_21_overlapping_concurrent_requests_provenance_isolation(tmp_path: Path):
    import asyncio

    store = await create_seeded_store(tmp_path)
    ev_srv = EvidenceService(store)
    an_srv = AnalysisService(ev_srv, store)
    rev_srv = ReviewService(store)

    history = await ev_srv.get_learner_history("LRN-001", subject="Mathematics")
    real_ev = next(e for e in history if e.evidence_type == EvidenceType.ASSESSMENT)
    real_score = real_ev.content.get("score")
    real_id = real_ev.evidence_id

    ai_draft = json.dumps({
        "learner_id": "LRN-001",
        "status": "completed",
        "summary": "AI Live analysis shows steady performance.",
        "findings": [
            {
                "observation": f"Mathematics score was {real_score}.",
                "supporting_evidence_ids": [real_id],
                "conflicting_evidence_ids": [],
                "co_occurring_factors": [],
                "teacher_inquiries": ["How to sustain progress?"],
            }
        ],
        "contradictions": [],
        "limitations": [],
        "abstention_reason": None,
    })

    class ConcurrencyProbeClient:
        def __init__(self) -> None:
            self.call_count = 0

        async def generate(
            self,
            prompt: str,
            system_prompt: str | None = None,
            response_format: dict | None = None,
        ) -> str:
            self.call_count += 1
            call_idx = self.call_count
            if call_idx == 1:
                # Request 1: Slow failure that engages fallback
                await asyncio.sleep(0.05)
                raise InferenceError("Slow primary connection failure")
            else:
                # Request 2: Fast live AI success
                await asyncio.sleep(0.01)
                return ai_draft

    primary_client = ConcurrencyProbeClient()
    resilient_client = ResilientInferenceClient(
        primary_client=primary_client,
        fallback_client=DeterministicAnalysisClient(),
        allow_fallback=True,
    )

    orch = AgentOrchestrator(
        evidence_service=ev_srv,
        analysis_service=an_srv,
        review_service=rev_srv,
        inference_client=resilient_client,
        store=store,
    )

    # Launch both requests concurrently
    task1 = asyncio.create_task(orch.orchestrate_handover("LRN-001", subject="Mathematics"))
    task2 = asyncio.create_task(orch.orchestrate_handover("LRN-001", subject="Mathematics"))

    res1, res2 = await asyncio.gather(task1, task2)

    # Request 1 must be deterministic_fallback
    assert res1.status == "success"
    assert res1.runtime_info.get("runtime_method") == "deterministic_fallback"
    assert "[Deterministic Analysis]" in res1.brief.summary

    # Request 2 must be live_ai
    assert res2.status == "success"
    assert res2.runtime_info.get("runtime_method") == "live_ai"
    assert "[Deterministic Analysis]" not in res2.brief.summary

    # Verify audit entries in SQLite store
    audits = await store.get_audit_log(tool_name="ai_orchestrate_handover")
    assert len(audits) == 2

    # Find audit entries corresponding to each method
    fb_audit = next(
        a for a in audits if a.input_summary.get("runtime_method") == "deterministic_fallback"
    )
    live_audit = next(
        a for a in audits if a.input_summary.get("runtime_method") == "live_ai"
    )

    assert "deterministic_fallback: Slow primary connection failure" in fb_audit.approval_state
    assert live_audit.approval_state == "pending_teacher_review"
    assert "deterministic_fallback" not in live_audit.approval_state

    await store.close()


