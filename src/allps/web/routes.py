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
from fastapi import APIRouter, Cookie, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from pydantic import BaseModel, Field, field_validator

from allps.agent.contracts import HandoverStatus
from allps.agent.orchestrator import AgentOrchestrator, OrchestrationResult
from allps.auth import (
    COOKIE_NAME,
    extract_api_key_from_headers,
    make_session_cookie,
    read_session_cookie,
    verify_ingest_api_key,
    verify_pin,
)
from allps.models.evidence import Evidence, EvidenceType, IngestionMethod
from allps.models.learner import Learner
from allps.models.review import ReviewItem, ReviewStatus
from allps.policies.label_policy import check_for_prohibited_labels
from allps.runtime import ExecutionMode, RuntimeRegistry
from allps.services.analysis_service import AnalysisService
from allps.services.evidence_service import EvidenceService
from allps.services.export_service import ExportService
from allps.services.intake_service import DuplicateFileError, IntakeService
from allps.services.review_service import ConflictError, ReviewService
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
    """Payload for submitting a teacher adjudication decision.

    expected_revision must match the review item's current revision.  Concurrent
    submissions sharing the same expected_revision will produce exactly one 200 and
    one 409 — there is no unconditional fallback.

    is_correction must be True when overriding an already-resolved decision.
    Corrections require the caller to hold an authenticated teacher session and to
    supply the revision returned by the most recent GET of this review item.
    """

    status: str = Field(..., description="accepted | rejected | needs_context")
    teacher_notes: str | None = Field(default=None, max_length=5000)
    expected_revision: int = Field(
        default=0,
        ge=0,
        description=(
            "Revision counter last seen by the caller.  The server rejects the "
            "request with 409 if the stored revision has advanced past this value."
        ),
    )
    is_correction: bool = Field(
        default=False,
        description=(
            "Set True to explicitly correct an already-resolved decision. "
            "Requires an authenticated teacher session and the current revision."
        ),
    )


class LoginRequest(BaseModel):
    teacher_id: str = Field(..., min_length=1, max_length=100)
    pin: str = Field(..., min_length=4, max_length=64)


class IngestRecordsRequest(BaseModel):
    """Batch ingestion payload from an external/native school results system."""

    source_system: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        description="Default originating system identifier (e.g. 'school_sis').",
    )
    ingestion_method: str = Field(default="api", max_length=60)
    source_type: str = Field(default="system", max_length=60)
    source_reference: str | None = Field(default=None, max_length=200)
    records: list[dict[str, Any]] = Field(..., min_length=1, max_length=5000)


# ─────────────────────────────────────────────────────────────────────────────
# Session helpers
# ─────────────────────────────────────────────────────────────────────────────


def _current_teacher_id(request: Request) -> str | None:
    """Extract and verify the signed session cookie.  Returns teacher_id or None."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return read_session_cookie(token)


def _require_teacher(request: Request) -> str:
    """Return the authenticated teacher_id or raise 401."""
    teacher_id = _current_teacher_id(request)
    if not teacher_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in required.",
        )
    return teacher_id


def _require_ingest_api_key(request: Request) -> None:
    """Enforce external system API-key authentication (fail-closed if unconfigured)."""
    expected_key: str | None = getattr(request.app.state, "ingest_api_key", None)
    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="External ingestion API key is not configured on this server (ALLPS_INGEST_API_KEY).",
        )
    supplied = extract_api_key_from_headers(
        authorization=request.headers.get("authorization"),
        x_api_key=request.headers.get("x-api-key"),
    )
    if not verify_ingest_api_key(supplied, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing ingestion API key.",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Auth endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/auth/login", status_code=status.HTTP_200_OK)
async def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    """PIN login.  Sets an HttpOnly session cookie on success."""
    store: SQLiteStore = request.app.state.store
    teacher = await store.get_teacher(payload.teacher_id)
    if not teacher or not verify_pin(payload.pin, teacher["pin_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid teacher ID or PIN.",
        )
    token = make_session_cookie(teacher["teacher_id"])
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="strict",
        max_age=60 * 60 * 12,
    )
    return {"teacher_id": teacher["teacher_id"], "display_name": teacher["display_name"]}


@router.post("/auth/logout", status_code=status.HTTP_200_OK)
async def logout(response: Response) -> dict[str, str]:
    """Clear the session cookie."""
    response.delete_cookie(key=COOKIE_NAME)
    return {"status": "logged_out"}


@router.get("/auth/me")
async def me(request: Request) -> dict[str, Any]:
    """Return the signed-in teacher or 401."""
    teacher_id = _require_teacher(request)
    store: SQLiteStore = request.app.state.store
    teacher = await store.get_teacher(teacher_id)
    if not teacher:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Teacher not found.")
    return {"teacher_id": teacher["teacher_id"], "display_name": teacher["display_name"]}


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/config")
async def get_system_config(request: Request) -> dict[str, Any]:
    """Retrieve runtime state, active teacher session, and approval authority availability."""
    app = request.app
    store: SQLiteStore = app.state.store
    teacher_id = _current_teacher_id(request)
    teacher = await store.get_teacher(teacher_id) if teacher_id else None

    available_teachers: list[dict[str, str]] = []
    async with store.db.execute(
        "SELECT teacher_id, display_name FROM teachers ORDER BY teacher_id ASC"
    ) as cursor:
        async for row in cursor:
            available_teachers.append({
                "teacher_id": row["teacher_id"],
                "display_name": row["display_name"],
            })

    return {
        "review_authority_available": teacher is not None,
        "authenticated_teacher": (
            {"teacher_id": teacher["teacher_id"], "display_name": teacher["display_name"]}
            if teacher
            else None
        ),
        "server_reviewer_id": teacher["teacher_id"] if teacher else None,
        "available_teachers": available_teachers,
        "default_mode": getattr(app.state, "default_mode", "auto"),
        "is_synthetic_demonstration": True,
        "authentication_type": "pin_session_cookie",
        "trust_notice": (
            "Prototype PIN Session: Teacher identity is verified via signed HttpOnly "
            "session cookie against local pilot accounts, not external school SSO."
        ),
        "trust_limitation_notice": (
            "Prototype PIN Session: Teacher identity is verified via signed HttpOnly "
            "session cookie against local pilot accounts, not external school SSO."
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
                "revision": 0,
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
                    "revision": r.revision,
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

    Reviewer identity comes from the signed session cookie — never from the request body.
    Unauthenticated requests are rejected with 401.

    Concurrency contract:
    - Supply the revision you last observed as expected_revision.
    - Two concurrent requests carrying the same expected_revision produce exactly
      one 200 OK and one 409 Conflict.
    - Set is_correction=True to override a previously-resolved decision.  Corrections
      require an authenticated session and the current (post-initial-decision) revision.
    """
    # 1. Require an authenticated session — reviewer identity comes from the cookie, not the body
    authenticated_teacher_id = _require_teacher(request)

    review_service: ReviewService = request.app.state.review_service
    store: SQLiteStore = request.app.state.store

    # 2. Check review item exists
    item = await store.get_review_item(review_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review item '{review_id}' does not exist.",
        )

    # 3. Resolve through ReviewService.
    #    authenticated_teacher_id (from the session) drives authority for corrections;
    #    reviewer_id on the record is also set to the authenticated identity.
    try:
        updated_item = await review_service.resolve_teacher_review(
            review_id=review_id,
            status=payload.status,
            reviewer_id=authenticated_teacher_id,
            teacher_notes=payload.teacher_notes,
            expected_revision=payload.expected_revision,
            is_correction=payload.is_correction,
            authenticated_teacher_id=authenticated_teacher_id,
        )
    except ConflictError as ce:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(ce),
        )
    except PermissionError as pe:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(pe),
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
        "revision": updated_item.revision + 1,  # reflects the new revision after the increment
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


@router.get("/learners/{learner_id}/handover/export")
async def export_approved_handover(
    learner_id: str,
    request: Request,
    format: str = Query("pdf", description="pdf | html | md | json"),
    download: bool = Query(True, description="Set true for attachment download, false for inline view"),
) -> Response:
    """Export the strictly human-approved learner handover document.

    Enforces the Dual-View Gate: only ACCEPTED findings with verified SHA-256
    content hashes and their cited evidence provenance are included.
    """
    store: SQLiteStore = request.app.state.store
    export_service: ExportService = request.app.state.export_service

    if not await store.learner_exists(learner_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Learner '{learner_id}' not found.",
        )

    try:
        content, media_type, ext = await export_service.export_handover(learner_id, fmt=format)
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(val_err),
        )

    disposition = "attachment" if download else "inline"
    safe_id = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in learner_id)
    filename = f"allps_handover_{safe_id}.{ext}"

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# External System Ingestion Endpoints (API-Key Authenticated)
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/ingest/records", status_code=status.HTTP_200_OK)
async def ingest_external_records(
    payload: IngestRecordsRequest,
    request: Request,
) -> dict[str, Any]:
    """Ingest structured evidence records from a native school results or SIS system.

    Protected by API-key auth (X-API-Key or Authorization: Bearer).
    Supports assessments, attendance, observations, reflections, and projects,
    with Level 1 (source_event_id) and Level 2 (canonical_fingerprint) dedup.
    """
    _require_ingest_api_key(request)
    intake_service: IntakeService = request.app.state.intake_service

    summary = await intake_service.ingest_records(
        payload.records,
        default_source_system=payload.source_system,
        default_ingestion_method=payload.ingestion_method,
        default_source_type=payload.source_type,
        default_source_reference=payload.source_reference,
    )
    return summary.model_dump(mode="json")


@router.post("/ingest/file", status_code=status.HTTP_201_CREATED)
async def ingest_external_file(
    request: Request,
    file: UploadFile = File(...),
    source_system: str = Form(..., min_length=1, max_length=120),
    import_method: str = Form("csv_import", max_length=60),
    imported_by: str | None = Form(None, max_length=120),
    notes: str | None = Form(None, max_length=2000),
) -> dict[str, Any]:
    """Ingest a CSV or JSON school export file with SHA-256 ImportManifest tracking.

    Protected by API-key auth (X-API-Key or Authorization: Bearer).
    Re-uploading the same file bytes from the same source_system returns 409 Conflict.
    """
    _require_ingest_api_key(request)
    intake_service: IntakeService = request.app.state.intake_service

    file_bytes = await file.read()
    try:
        summary = await intake_service.ingest_file(
            file_bytes=file_bytes,
            file_name=file.filename or "upload",
            source_system=source_system,
            import_method=import_method,
            imported_by=imported_by,
            notes=notes,
        )
    except DuplicateFileError as dup_err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(dup_err),
                "existing_manifest": dup_err.manifest.model_dump(mode="json"),
            },
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(val_err),
        )

    return summary.model_dump(mode="json")


@router.get("/ingest/manifests")
async def list_ingest_manifests(
    request: Request,
    source_system: str | None = Query(None),
) -> list[dict[str, Any]]:
    """List file import manifests (requires either ingest API key or authenticated teacher session)."""
    teacher_id = _current_teacher_id(request)
    if not teacher_id:
        _require_ingest_api_key(request)
    store: SQLiteStore = request.app.state.store
    return await store.list_import_manifests(source_system=source_system)
