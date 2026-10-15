"""Thin Web API routes for ALLPS Teacher Interface.

Coordinates with existing ALLPS domain services through explicit contracts:
- EvidenceService & SQLiteStore for evidence and observations
- AgentOrchestrator & RuntimeRegistry for candidate handover generation
- ReviewService for human teacher review and sovereign profile gating
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any
import uuid

import aiosqlite
from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator

from allps.agent.contracts import HandoverStatus
from allps.agent.orchestrator import AgentOrchestrator, OrchestrationResult
from allps.models.evidence import Evidence, EvidenceType, IngestionMethod
from allps.models.learner import Learner
from allps.models.review import ReviewItem, ReviewStatus
from allps.policies.label_policy import check_for_prohibited_labels
from allps.runtime import ExecutionMode, RuntimeRegistry
from allps.services.analysis_service import AnalysisService
from allps.services.evidence_service import EvidenceService
from allps.services.review_service import ReviewService
from allps.storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["teacher_api"])


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response Models
# ─────────────────────────────────────────────────────────────────────────────


class ObservationCreateRequest(BaseModel):
    """Payload for submitting a direct teacher observation."""

    event_datetime: datetime = Field(
        ...,
        description="When the observation occurred (must be timezone-aware or ISO string)",
    )
    academic_year: int = Field(..., ge=2000, le=2100)
    term: int = Field(..., ge=1, le=4)
    subject: str | None = Field(default=None, max_length=100)
    observation: str = Field(
        ...,
        min_length=3,
        max_length=5000,
        description="Factual pedagogical observation without diagnostic or deficit labels.",
    )
    context: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional classroom context or co-occurring factors without causal claims.",
    )
    source_reference: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Attributed educator name or role (e.g. 'Mr. Banda').",
    )
    source_event_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Stable source event ID for retry idempotency.",
    )

    @field_validator("event_datetime")
    @classmethod
    def ensure_timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            # Assume UTC if naive, but keep explicit awareness
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @field_validator("observation", "context")
    @classmethod
    def reject_deficit_labels(cls, v: str | None) -> str | None:
        if not v:
            return v
        bad = check_for_prohibited_labels(v)
        if bad:
            raise ValueError(
                f"Prohibited deficit or diagnostic label detected: '{bad}'. "
                "Observations must use factual, non-deficit descriptions."
            )
        return v


class GenerateBriefRequest(BaseModel):
    """Payload for requesting AI handover brief generation."""

    subject: str | None = Field(default=None)
    mode: str = Field(default="auto", description="mock | deterministic | auto | live")


class ReviewDecisionRequest(BaseModel):
    """Payload for submitting a teacher adjudication decision."""

    status: str = Field(..., description="accepted | rejected | needs_context")
    teacher_notes: str | None = Field(default=None, max_length=5000)


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/config")
async def get_system_config(request: Request) -> dict[str, Any]:
    """Retrieve runtime state and approval authority availability."""
    app = request.app
    trusted_reviewer_id = getattr(app.state, "trusted_reviewer_id", None)
    return {
        "review_authority_available": bool(trusted_reviewer_id and trusted_reviewer_id.strip()),
        "server_reviewer_id": trusted_reviewer_id,
        "default_mode": getattr(app.state, "default_mode", "auto"),
        "is_synthetic_demonstration": True,
        "authentication_type": "prototype_server_configured",
        "trust_notice": (
            "Prototype Trust Limitation: The server reviewer ID is a demonstration setting, "
            "not a verified authentication token or SSO identity."
        ),
        "trust_limitation_notice": (
            "Prototype Trust Limitation: The server reviewer ID is a demonstration setting, "
            "not a verified authentication token or SSO identity."
        ),
        "trust_notice": (
            "Prototype Trust Limitation: The server reviewer ID is a demonstration setting, "
            "not a verified authentication token or SSO identity."
        ),
    }


@router.get("/learners")
async def list_learners(request: Request) -> list[dict[str, Any]]:
    """List all learners available in the store."""
    store: SQLiteStore = request.app.state.store
    db = store.db

    learners: list[dict[str, Any]] = []
    async with db.execute("SELECT learner_id, display_name, created_at FROM learners ORDER BY learner_id ASC") as cursor:
        async for row in cursor:
            learners.append({
                "learner_id": row["learner_id"],
                "display_name": row["display_name"],
                "created_at": row["created_at"],
            })

    return learners


@router.get("/learners/{learner_id}/evidence")
async def get_learner_evidence(
    learner_id: str,
    request: Request,
    subject: str | None = Query(None),
    academic_year: int | None = Query(None),
    term: int | None = Query(None),
    evidence_type: str | None = Query(None),
) -> list[dict[str, Any]]:
    """Retrieve chronological evidence records for a learner with optional filters."""
    store: SQLiteStore = request.app.state.store

    if not await store.learner_exists(learner_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Learner '{learner_id}' not found in system records.",
        )

    records: list[Evidence] = await store.get_evidence_for_learner(
        learner_id,
        evidence_type=evidence_type,
        academic_year=academic_year,
        term=term,
        subject=subject,
    )

    out: list[dict[str, Any]] = []
    for r in records:
        content_dict = r.content if isinstance(r.content, dict) else dict(r.content)
        out.append({
            "evidence_id": r.evidence_id,
            "learner_id": r.learner_id,
            "evidence_type": r.evidence_type.value,
            "source_system": r.source_system,
            "ingestion_method": r.ingestion_method.value,
            "source_event_id": r.source_event_id,
            "source_type": r.source_type,
            "source_reference": r.source_reference,
            "academic_year": r.academic_year,
            "term": r.term,
            "subject": r.subject,
            "observed_at": r.observed_at.isoformat(),
            "recorded_at": r.recorded_at.isoformat(),
            "content": content_dict,
            # Computed helpers for clean UI display
            "assessment_stage": r.assessment_stage,
            "measured_skill": r.measured_skill,
            "grade": r.grade,
            "is_missing_outcome": r.is_missing_outcome,
            "missing_status": content_dict.get("status") if r.is_missing_outcome else None,
            "missing_reason": content_dict.get("reason") if r.is_missing_outcome else None,
            "score": content_dict.get("score"),
            "max_score": content_dict.get("max_score"),
            "comparison_authorized": r.comparison_authorized,
        })

    return out


@router.get("/evidence/{evidence_id}")
async def get_evidence_detail(evidence_id: str, request: Request) -> dict[str, Any]:
    """Retrieve an individual evidence record by ID for side panel citation inspection."""
    store: SQLiteStore = request.app.state.store
    db = store.db

    async with db.execute("SELECT * FROM evidence WHERE evidence_id = ?", (evidence_id,)) as cursor:
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Evidence record '{evidence_id}' does not exist.",
            )

        content = json.loads(row["content"])
        ev = Evidence(
            evidence_id=row["evidence_id"],
            learner_id=row["learner_id"],
            evidence_type=EvidenceType(row["evidence_type"]),
            source_system=row["source_system"],
            ingestion_method=IngestionMethod(row["ingestion_method"]),
            source_event_id=row["source_event_id"],
            source_type=row["source_type"],
            source_reference=row["source_reference"],
            academic_year=row["academic_year"],
            term=row["term"],
            subject=row["subject"],
            content=content,
            observed_at=datetime.fromisoformat(row["observed_at"]),
            recorded_at=datetime.fromisoformat(row["recorded_at"]),
        )

        return {
            "evidence_id": ev.evidence_id,
            "learner_id": ev.learner_id,
            "evidence_type": ev.evidence_type.value,
            "source_system": ev.source_system,
            "ingestion_method": ev.ingestion_method.value,
            "source_event_id": ev.source_event_id,
            "source_type": ev.source_type,
            "source_reference": ev.source_reference,
            "academic_year": ev.academic_year,
            "term": ev.term,
            "subject": ev.subject,
            "observed_at": ev.observed_at.isoformat(),
            "recorded_at": ev.recorded_at.isoformat(),
            "content": content,
            "assessment_stage": ev.assessment_stage,
            "measured_skill": ev.measured_skill,
            "grade": ev.grade,
            "is_missing_outcome": ev.is_missing_outcome,
            "missing_status": content.get("status") if ev.is_missing_outcome else None,
            "missing_reason": content.get("reason") if ev.is_missing_outcome else None,
            "comparison_authorized": ev.comparison_authorized,
        }


@router.post("/learners/{learner_id}/evidence", status_code=status.HTTP_201_CREATED)
async def create_teacher_observation(
    learner_id: str,
    payload: ObservationCreateRequest,
    request: Request,
) -> dict[str, Any]:
    """Ingest a direct teacher observation using EvidenceService.
    
    Guarantees:
    - Learner existence check (prevents silent creation from mistyped IDs).
    - Stable source_event_id preserves idempotency across retries.
    - Deficit and diagnostic labels are strictly rejected.
    - Preserves timezone-aware event time separately from recorded time.
    """
    store: SQLiteStore = request.app.state.store
    evidence_service: EvidenceService = request.app.state.evidence_service

    # Strict check: Do not silently create learner on mistyped ID
    if not await store.learner_exists(learner_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cannot record observation: Learner '{learner_id}' does not exist.",
        )

    content: dict[str, Any] = {
        "observation": payload.observation.strip(),
        "note": payload.observation.strip(),
    }
    if payload.context:
        content["context"] = payload.context.strip()

    try:
        ev: Evidence = await evidence_service.record_evidence(
            learner_id=learner_id,
            evidence_type=EvidenceType.OBSERVATION,
            source_system="allps_teacher_web",
            ingestion_method=IngestionMethod.MANUAL_OBSERVATION,
            source_type="teacher",
            source_reference=payload.source_reference.strip(),
            academic_year=payload.academic_year,
            term=payload.term,
            subject=payload.subject.strip() if payload.subject else None,
            content=content,
            observed_at=payload.event_datetime,
            source_event_id=payload.source_event_id,
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(val_err),
        )

    return {
        "evidence_id": ev.evidence_id,
        "learner_id": ev.learner_id,
        "evidence_type": ev.evidence_type.value,
        "academic_year": ev.academic_year,
        "term": ev.term,
        "subject": ev.subject,
        "observed_at": ev.observed_at.isoformat(),
        "recorded_at": ev.recorded_at.isoformat(),
        "source_reference": ev.source_reference,
        "source_event_id": ev.source_event_id,
        "content": ev.content if isinstance(ev.content, dict) else dict(ev.content),
    }


@router.post("/learners/{learner_id}/generate")
async def generate_candidate_handover(
    learner_id: str,
    payload: GenerateBriefRequest,
    request: Request,
) -> dict[str, Any]:
    """Execute bounded AI transition handover synthesis for a learner.

    The browser never calls LM Studio directly. Runtime selection, provider discovery,
    input context bounding, and output validation are orchestrated server-side.
    Raw rejected LLM output is strictly hidden.
    """
    store: SQLiteStore = request.app.state.store
    evidence_service: EvidenceService = request.app.state.evidence_service
    analysis_service: AnalysisService = request.app.state.analysis_service
    review_service: ReviewService = request.app.state.review_service
    runtime_registry: RuntimeRegistry = request.app.state.runtime_registry

    if not await store.learner_exists(learner_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Learner '{learner_id}' not found.",
        )

    # 1. Select runtime client
    try:
        selection, inference_client = await runtime_registry.select_runtime(
            mode=payload.mode,
            mock_responses=getattr(request.app.state, "mock_responses", None),
        )
    except Exception as exc:
        logger.error("Runtime selection failure for mode '%s': %s", payload.mode, exc)
        return {
            "learner_id": learner_id,
            "status": "inference_failed",
            "runtime_method": "unavailable",
            "review_id": None,
            "pattern_id": None,
            "brief": None,
            "errors": [f"Runtime selection failed: {str(exc)}"],
        }

    # 2. Instantiate orchestrator
    orchestrator = AgentOrchestrator(
        evidence_service=evidence_service,
        analysis_service=analysis_service,
        review_service=review_service,
        inference_client=inference_client,
        store=store,
    )

    # 3. Execute bounded cycle
    res: OrchestrationResult = await orchestrator.orchestrate_handover(
        learner_id=learner_id,
        subject=payload.subject,
    )

    # 4. Format contract response (Hide raw model output)
    brief_data: dict[str, Any] | None = None
    if res.brief:
        brief_data = res.brief.model_dump(mode="json")

    return {
        "learner_id": res.learner_id,
        "status": res.status,  # "success", "abstained", "validation_failed", "inference_failed"
        "runtime_method": res.runtime_info.get("runtime_method", selection.runtime_type.value),
        "review_id": res.review_id,
        "pattern_id": res.pattern_id,
        "generation_revision": getattr(res, "generation_revision", 1),
        "brief": brief_data,
        "errors": res.errors,
    }


@router.get("/learners/{learner_id}/brief")
async def get_learner_latest_brief(learner_id: str, request: Request) -> dict[str, Any]:
    """Retrieve the latest persisted candidate brief for a learner (INT-01).

    Ensures refreshing the browser restores the actual candidate brief,
    including findings, citations, co-occurring context, teacher inquiries,
    generation revision, and runtime provenance.
    """
    store: SQLiteStore = request.app.state.store

    if not await store.learner_exists(learner_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Learner '{learner_id}' not found.",
        )

    brief = await store.get_latest_candidate_brief(learner_id)
    return {
        "learner_id": learner_id,
        "brief": brief,
    }


@router.get("/learners/{learner_id}/reviews")
async def get_learner_reviews(learner_id: str, request: Request) -> list[dict[str, Any]]:
    """Retrieve saved candidate findings, their human review status, and associated candidate briefs."""
    store: SQLiteStore = request.app.state.store

    if not await store.learner_exists(learner_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Learner '{learner_id}' not found.",
        )

    patterns = await store.get_patterns_for_learner(learner_id)
    reviews_out: list[dict[str, Any]] = []

    for p in patterns:
        brief = await store.get_candidate_brief_by_pattern(p.pattern_id)
        review_items: list[ReviewItem] = await store.get_review_items_for_pattern(p.pattern_id)
        if not review_items:
            # Pattern exists without active review item yet
            reviews_out.append({
                "review_id": None,
                "pattern_id": p.pattern_id,
                "pattern_type": p.pattern_type.value,
                "summary": p.summary,
                "supporting_evidence_ids": p.supporting_evidence,
                "conflicting_evidence_ids": p.conflicting_evidence,
                "limitations": p.limitations,
                "generated_at": p.generated_at.isoformat(),
                "status": "pending",
                "teacher_notes": None,
                "reviewer_id": None,
                "resolved_at": None,
                "approved_content_hash": None,
                "assigned_to": None,
                "candidate_brief": brief,
                "generation_revision": brief.get("generation_revision", 1) if brief else 1,
            })
        else:
            for r in review_items:
                reviews_out.append({
                    "review_id": r.review_id,
                    "pattern_id": p.pattern_id,
                    "pattern_type": p.pattern_type.value,
                    "summary": p.summary,
                    "supporting_evidence_ids": p.supporting_evidence,
                    "conflicting_evidence_ids": p.conflicting_evidence,
                    "limitations": p.limitations,
                    "generated_at": p.generated_at.isoformat(),
                    "status": r.status.value,
                    "teacher_notes": r.teacher_notes,
                    "reviewer_id": r.reviewer_id,
                    "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
                    "approved_content_hash": r.approved_content_hash,
                    "assigned_to": r.assigned_to,
                    "candidate_brief": brief,
                    "generation_revision": brief.get("generation_revision", 1) if brief else 1,
                })

    return reviews_out


@router.post("/reviews/{review_id}/decision")
async def submit_review_decision(
    review_id: str,
    payload: ReviewDecisionRequest,
    request: Request,
) -> dict[str, Any]:
    """Submit human teacher adjudication for a candidate finding.

    Human Authority Boundary:
    - Reviewer identity is obtained strictly server-side (from server configuration/session).
    - Browser-supplied teacher identity is not authentication.
    - If trusted server-side authority is unavailable, submission is disabled.
    """
    app = request.app
    trusted_reviewer_id = getattr(app.state, "trusted_reviewer_id", None)
    review_service: ReviewService = app.state.review_service
    store: SQLiteStore = app.state.store

    # 1. Check if trusted server-side human authority is configured
    if not trusted_reviewer_id or not trusted_reviewer_id.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Review decision submission is disabled: Trusted server-side human review authority "
                "is not configured or is under active repair by the backend instance."
            ),
        )

    # 2. Check if review item exists
    item = await store.get_review_item(review_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review item '{review_id}' does not exist.",
        )

    # 3. Resolve review through ReviewService using server-side reviewer identity
    try:
        updated_item = await review_service.resolve_teacher_review(
            review_id=review_id,
            status=payload.status,
            reviewer_id=trusted_reviewer_id,
            teacher_notes=payload.teacher_notes,
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(val_err),
        )

    return {
        "review_id": updated_item.review_id,
        "pattern_id": updated_item.pattern_id,
        "status": updated_item.status.value,
        "reviewer_id": updated_item.reviewer_id,
        "teacher_notes": updated_item.teacher_notes,
        "resolved_at": updated_item.resolved_at.isoformat() if updated_item.resolved_at else None,
        "approved_content_hash": updated_item.approved_content_hash,
    }


@router.get("/learners/{learner_id}/handover")
async def get_approved_handover(learner_id: str, request: Request) -> dict[str, Any]:
    """Retrieve the published transition handover profile for a learner.

    Dual-View Gate Enforcement:
    - Exposes strictly ACCEPTED patterns verified with cryptographic SHA-256 hash snapshot.
    - Pending, rejected, and needs-context items remain completely absent.
    - Survives page refreshes.
    """
    store: SQLiteStore = request.app.state.store
    review_service: ReviewService = request.app.state.review_service

    if not await store.learner_exists(learner_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Learner '{learner_id}' not found.",
        )

    profile = await review_service.get_surfaced_profile(learner_id)
    return profile
