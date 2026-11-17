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
import os
from pathlib import Path
from typing import Any, Literal
import uuid

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
from allps.models.handover import SectionReviewState, SubjectResponseType, TeacherRole
from allps.models.learner import Learner
from allps.models.review import ReviewItem, ReviewStatus
from allps.policies.label_policy import check_for_prohibited_labels
from allps.runtime import ExecutionMode, RuntimeRegistry
from allps.services.analysis_service import AnalysisService
from allps.services.evidence_service import EvidenceService
from allps.services.export_service import ExportService
from allps.services.handover_service import HandoverService
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
    class_id: str | None = Field(default=None, max_length=100)
    records: list[dict[str, Any]] = Field(..., min_length=1, max_length=5000)


class EnrollLearnerRequest(BaseModel):
    learner_id: str = Field(..., min_length=1, max_length=100)


class SectionReviewUpdateRequest(BaseModel):
    review_state: SectionReviewState
    approved_summary: str | None = Field(default=None, max_length=5000)
    teacher_notes: str | None = Field(default=None, max_length=5000)
    missing_evidence_disclosure: str | None = Field(default=None, max_length=2000)
    citations: list[str] = Field(default_factory=list)


class ClassReleaseRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)


class ReportViewRequest(BaseModel):
    scope: str | None = Field(default=None, max_length=120)


class SubjectResponseRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=120)
    response_type: SubjectResponseType = Field(default=SubjectResponseType.CONFIRMATION)
    content: str = Field(..., min_length=1, max_length=3000)
    related_change_id: str | None = Field(default=None, max_length=100)


class ChangeReviewRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)


class ReseedRequest(BaseModel):
    """Payload for workspace database seeding or reset."""

    mode: Literal["merge", "reset"] = Field(
        default="merge",
        description="'merge' idempotently adds missing demo records; 'reset' clears workspace data first.",
    )


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


def _require_handover_service(request: Request) -> HandoverService:
    svc = getattr(request.app.state, "handover_service", None)
    if svc is None:
        store: SQLiteStore = request.app.state.store
        svc = HandoverService(
            store,
            request.app.state.evidence_service,
            request.app.state.analysis_service,
        )
        request.app.state.handover_service = svc
    return svc


async def _authorize_learner(request: Request, learner_id: str) -> tuple[str, dict[str, Any]]:
    """Require authenticated teacher assigned to learner_id's class (401/404/403)."""
    teacher_id = _require_teacher(request)
    store: SQLiteStore = request.app.state.store
    if not await store.learner_exists(learner_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Learner '{learner_id}' not found in system records (does not exist).",
        )
    handover_svc = _require_handover_service(request)
    try:
        access = await handover_svc.get_teacher_learner_access(teacher_id, learner_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return teacher_id, access


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
        secure=getattr(request.app.state, "secure_cookies", False),
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
    is_hosted = bool(getattr(app.state, "hosted", False))
    show_demo_credentials = not is_hosted

    available_teachers: list[dict[str, Any]] = []
    if show_demo_credentials:
        from allps.web.app import _PILOT_TEACHERS
        pilot_pin_map = {tid: pin for tid, _, pin in _PILOT_TEACHERS}
        for row in await store.list_teachers():
            assignments = await store.get_teacher_assignments(row["teacher_id"])
            roles = [
                f"Class teacher ({a.class_id})"
                if a.role.value == "class_teacher"
                else f"{a.subject} teacher ({a.class_id})"
                for a in assignments
            ]
            pilot_pin = pilot_pin_map.get(row["teacher_id"])
            demo_pin = (
                pilot_pin
                if pilot_pin and verify_pin(pilot_pin, row["pin_hash"])
                else None
            )
            available_teachers.append({
                "teacher_id": row["teacher_id"],
                "display_name": row["display_name"],
                "role_summary": ", ".join(roles) if roles else "Teacher",
                "demo_pin": demo_pin,
            })

    handover_svc = _require_handover_service(request)
    workspace = await handover_svc.get_teacher_workspace(teacher_id) if teacher else None

    return {
        "review_authority_available": teacher is not None,
        "authenticated_teacher": (
            {"teacher_id": teacher["teacher_id"], "display_name": teacher["display_name"]}
            if teacher
            else None
        ),
        "workspace": workspace,
        "server_reviewer_id": teacher["teacher_id"] if teacher else None,
        "available_teachers": available_teachers,
        "show_demo_credentials": show_demo_credentials,
        "hosted": is_hosted,
        "allow_demo_reset": getattr(app.state, "allow_demo_reset", False),
        "inference_provider": (
            os.environ.get("ALLPS_AI_PROVIDER", "AMD Token Lab")
            if is_hosted else None
        ),
        "default_mode": getattr(app.state, "default_mode", "auto"),
        "is_synthetic_demonstration": getattr(app.state, "is_synthetic", True),
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


def _serialize_learner(learner: Learner) -> dict[str, Any]:
    """Serialize a Learner model for the web API."""
    return {
        "learner_id": learner.learner_id,
        "display_name": learner.display_name,
        "created_at": learner.created_at.isoformat(),
    }


def _serialize_evidence(ev: Evidence, *, include_scores: bool = False) -> dict[str, Any]:
    """Serialize an Evidence model for API responses."""
    content_dict = ev.content if isinstance(ev.content, dict) else dict(ev.content)
    payload: dict[str, Any] = {
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
        "content": content_dict,
        "assessment_stage": ev.assessment_stage,
        "measured_skill": ev.measured_skill,
        "grade": ev.grade,
        "is_missing_outcome": ev.is_missing_outcome,
        "missing_status": content_dict.get("status") if ev.is_missing_outcome else None,
        "missing_reason": content_dict.get("reason") if ev.is_missing_outcome else None,
        "comparison_authorized": ev.comparison_authorized,
    }
    if include_scores:
        payload["score"] = content_dict.get("score")
        payload["max_score"] = content_dict.get("max_score")
    return payload


@router.get("/learners")
async def list_learners(
    request: Request,
    class_id: str | None = Query(
        None,
        description="Optional class ID to return only learners enrolled in that assigned class.",
    ),
) -> list[dict[str, Any]]:
    """List learners enrolled in classes assigned to the signed-in teacher."""
    teacher_id = _require_teacher(request)
    store: SQLiteStore = request.app.state.store
    handover_svc = _require_handover_service(request)

    if class_id is not None:
        if await store.get_class(class_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Class '{class_id}' does not exist.",
            )
        try:
            await handover_svc.assert_class_access(teacher_id, class_id)
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        enrolled = await store.get_class_learners(class_id)
        return [_serialize_learner(learner) for learner in enrolled]

    permitted_ids = await handover_svc.get_permitted_learner_ids(teacher_id)
    if not permitted_ids:
        return []

    all_learners = await store.list_learners()
    return [
        _serialize_learner(learner)
        for learner in all_learners
        if learner.learner_id in permitted_ids
    ]


@router.get("/learners/{learner_id}/evidence")
async def get_learner_evidence(
    learner_id: str,
    request: Request,
    subject: str | None = Query(None),
    academic_year: int | None = Query(None),
    term: int | None = Query(None),
    evidence_type: str | None = Query(None),
) -> list[dict[str, Any]]:
    """Retrieve chronological evidence records for a permitted learner scoped to the teacher's role."""
    teacher_id, access = await _authorize_learner(request, learner_id)
    store: SQLiteStore = request.app.state.store

    if not access["is_class_teacher"] and subject is not None:
        if subject not in access["allowed_subjects"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Teacher '{teacher_id}' is not assigned to subject '{subject}'.",
            )

    records: list[Evidence] = await store.get_evidence_for_learner(
        learner_id,
        evidence_type=evidence_type,
        academic_year=academic_year,
        term=term,
        subject=subject,
    )
    if not access["is_class_teacher"]:
        allowed_set = set(access["allowed_subjects"])
        records = [r for r in records if r.subject is None or r.subject in allowed_set]

    return [_serialize_evidence(r, include_scores=True) for r in records]


@router.get("/evidence/{evidence_id}")
async def get_evidence_detail(evidence_id: str, request: Request) -> dict[str, Any]:
    """Retrieve an individual evidence record by ID after verifying class and subject access."""
    teacher_id = _require_teacher(request)
    store: SQLiteStore = request.app.state.store
    handover_svc = _require_handover_service(request)

    ev = await store.get_evidence_by_id(evidence_id)
    if ev is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evidence record '{evidence_id}' does not exist.",
        )

    try:
        await handover_svc.assert_evidence_access(teacher_id, ev)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    return _serialize_evidence(ev, include_scores=False)


@router.post("/learners/{learner_id}/evidence", status_code=status.HTTP_201_CREATED)
async def create_teacher_observation(
    learner_id: str,
    payload: ObservationCreateRequest,
    request: Request,
) -> dict[str, Any]:
    """Ingest a direct teacher observation using EvidenceService and update post-release diffs."""
    teacher_id, access = await _authorize_learner(request, learner_id)
    evidence_service: EvidenceService = request.app.state.evidence_service
    handover_svc = _require_handover_service(request)

    clean_subject = payload.subject.strip() if payload.subject else None
    if not access["is_class_teacher"] and clean_subject is not None:
        if clean_subject not in access["allowed_subjects"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Teacher '{teacher_id}' cannot record observations for '{clean_subject}'.",
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
            subject=clean_subject,
            content=content,
            observed_at=payload.event_datetime,
            source_event_id=payload.source_event_id,
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(val_err),
        )

    await handover_svc.evaluate_post_release_changes_for_learner(learner_id)

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
    """Execute bounded AI transition handover synthesis for a permitted learner (class teacher only)."""
    teacher_id, access = await _authorize_learner(request, learner_id)
    if not access["is_class_teacher"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the assigned class teacher can generate pre-release candidate handover briefs.",
        )
    store: SQLiteStore = request.app.state.store
    evidence_service: EvidenceService = request.app.state.evidence_service
    analysis_service: AnalysisService = request.app.state.analysis_service
    review_service: ReviewService = request.app.state.review_service
    runtime_registry: RuntimeRegistry = request.app.state.runtime_registry

    target_subject = payload.subject

    # 1. Select runtime client
    try:
        selection, inference_client = await runtime_registry.select_runtime(
            mode=(getattr(request.app.state, "default_mode", "live")
                  if getattr(request.app.state, "hosted", False) else payload.mode),
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
        subject=target_subject,
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
    """Retrieve the latest persisted candidate brief for a permitted learner (class teacher only)."""
    _, access = await _authorize_learner(request, learner_id)
    if not access["is_class_teacher"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the assigned class teacher can access pre-release candidate briefs.",
        )
    store: SQLiteStore = request.app.state.store
    brief = await store.get_latest_candidate_brief(learner_id)
    return {
        "learner_id": learner_id,
        "brief": brief,
    }


@router.get("/learners/{learner_id}/reviews")
async def get_learner_reviews(learner_id: str, request: Request) -> list[dict[str, Any]]:
    """Retrieve saved candidate findings for pre-release review (class teacher only)."""
    _, access = await _authorize_learner(request, learner_id)
    if not access["is_class_teacher"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the assigned class teacher can inspect pre-release candidate reviews.",
        )
    store: SQLiteStore = request.app.state.store

    patterns = await store.get_patterns_for_learner(learner_id)

    reviews_out: list[dict[str, Any]] = []
    for p in patterns:
        brief = await store.get_candidate_brief_by_pattern(p.pattern_id)
        review_items: list[ReviewItem] = await store.get_review_items_for_pattern(p.pattern_id)
        if not review_items:
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
    """Submit human teacher adjudication for a permitted candidate finding."""
    authenticated_teacher_id = _require_teacher(request)

    review_service: ReviewService = request.app.state.review_service
    store: SQLiteStore = request.app.state.store

    item = await store.get_review_item(review_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review item '{review_id}' does not exist.",
        )

    pattern = await store.get_pattern(item.pattern_id)
    if pattern is not None:
        _, access = await _authorize_learner(request, pattern.learner_id)
        if not access["is_class_teacher"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the assigned class teacher can approve or resolve candidate findings; subject teachers contribute attributed responses.",
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
    """Retrieve role-scoped approved handover findings and published class handover sections."""
    teacher_id, access = await _authorize_learner(request, learner_id)
    store: SQLiteStore = request.app.state.store
    review_service: ReviewService = request.app.state.review_service
    handover_svc = _require_handover_service(request)

    profile = await review_service.get_surfaced_profile(learner_id)
    published_view = await handover_svc.get_learner_published_handover_view(learner_id, teacher_id)
    published_release = published_view.get("release")
    patterns = list(profile.get("patterns", []))
    if not access["is_class_teacher"]:
        if published_release is None:
            patterns = []
        else:
            rel_ts = str(published_release.get("released_at") or "")
            all_eids = [
                eid
                for p in patterns
                for eid in (p.get("supporting_evidence", []) + p.get("conflicting_evidence", []))
            ]
            ev_map = await store.get_evidence_by_ids(all_eids)
            allowed_set = set(access["allowed_subjects"])
            patterns = [
                p
                for p in patterns
                if ExportService._pattern_permitted_for_subjects(p, ev_map, allowed_set)
                and str((p.get("review") or {}).get("resolved_at") or "") <= rel_ts
            ]

    return {
        **profile,
        "accepted_pattern_count": len(patterns),
        "patterns": patterns,
        "published_release": published_release,
        "published_sections": published_view.get("sections", []),
        "receipts": published_view.get("receipts", []),
        "viewing_history": published_view.get("viewing_history", []),
        "changes": published_view.get("changes", []),
    }


@router.get("/learners/{learner_id}/handover/export")
async def export_approved_handover(
    learner_id: str,
    request: Request,
    format: str = Query("pdf", description="pdf | html | md | json"),
    download: bool = Query(True, description="Set true for attachment download, false for inline view"),
) -> Response:
    """Export the role-scoped, strictly human-approved learner handover document."""
    teacher_id, access = await _authorize_learner(request, learner_id)
    export_service: ExportService = request.app.state.export_service

    try:
        content, media_type, ext = await export_service.export_handover(
            learner_id,
            fmt=format,
            teacher_id=teacher_id,
            allowed_subjects=access["allowed_subjects"],
            is_class_teacher=access["is_class_teacher"],
        )
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
    """Ingest structured evidence records from a native school results or SIS system."""
    _require_ingest_api_key(request)
    intake_service: IntakeService = request.app.state.intake_service
    handover_svc = _require_handover_service(request)

    summary = await intake_service.ingest_records(
        payload.records,
        default_source_system=payload.source_system,
        default_ingestion_method=payload.ingestion_method,
        default_source_type=payload.source_type,
        default_source_reference=payload.source_reference,
        default_class_id=payload.class_id,
    )
    touched_learners = {r["learner_id"] for r in summary.results if r.get("status") == "created"}
    for lid in sorted(touched_learners):
        await handover_svc.evaluate_post_release_changes_for_learner(lid)
    return summary.model_dump(mode="json")


_MAX_IMPORT_BYTES = 10 * 1024 * 1024  # 10 MiB


def _parse_optional_int(raw: str | None, field_name: str, *, min_val: int, max_val: int) -> int | None:
    if raw is None or not raw.strip():
        return None
    try:
        val = int(raw.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid integer for '{field_name}': '{raw}'.",
        ) from exc
    if val < min_val or val > max_val:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"'{field_name}' must be between {min_val} and {max_val}.",
        )
    return val


def _parse_optional_positive_float(raw: str | None, field_name: str) -> float | None:
    if raw is None or not raw.strip():
        return None
    try:
        val = float(raw.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid number for '{field_name}': '{raw}'.",
        ) from exc
    if val <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"'{field_name}' must be greater than 0.",
        )
    return val


async def _execute_file_import(
    request: Request,
    *,
    file: UploadFile,
    source_system: str,
    import_method: str,
    imported_by: str | None,
    notes: str | None,
    default_class_id: str | None,
    enforce_class_id: str | None = None,
    allowed_subjects: set[str] | None = None,
    default_source_reference: str | None = None,
    academic_year: str | None = None,
    term: str | None = None,
    observed_at: str | None = None,
    max_score: str | None = None,
    grade: str | None = None,
    assessment_stage: str | None = None,
    form_name: str | None = None,
    form_version: str | None = None,
    language: str | None = None,
    comparison_authorized: bool = False,
) -> dict[str, Any]:
    """Shared file-ingestion orchestration for SIS API-key uploads and teacher UI uploads."""
    intake_service: IntakeService = request.app.state.intake_service
    handover_svc = _require_handover_service(request)

    parsed_year = _parse_optional_int(academic_year, "academic_year", min_val=2000, max_val=2100)
    parsed_term = _parse_optional_int(term, "term", min_val=1, max_val=4)
    parsed_max = _parse_optional_positive_float(max_score, "max_score")

    file_bytes = await file.read()
    if len(file_bytes) > _MAX_IMPORT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Uploaded file exceeds the 10 MiB size limit.",
        )

    try:
        summary = await intake_service.ingest_file(
            file_bytes=file_bytes,
            file_name=file.filename or "upload",
            source_system=source_system,
            import_method=import_method,
            imported_by=imported_by,
            notes=notes.strip() if isinstance(notes, str) and notes.strip() else None,
            default_class_id=default_class_id,
            enforce_class_id=enforce_class_id,
            allowed_subjects=allowed_subjects,
            default_academic_year=parsed_year,
            default_term=parsed_term,
            default_observed_at=observed_at.strip() if isinstance(observed_at, str) and observed_at.strip() else None,
            default_max_score=parsed_max,
            default_grade=grade.strip() if isinstance(grade, str) and grade.strip() else None,
            default_assessment_stage=(
                assessment_stage.strip() if isinstance(assessment_stage, str) and assessment_stage.strip() else None
            ),
            default_form=form_name.strip() if isinstance(form_name, str) and form_name.strip() else None,
            default_form_version=(
                form_version.strip() if isinstance(form_version, str) and form_version.strip() else None
            ),
            default_language=language.strip() if isinstance(language, str) and language.strip() else None,
            default_comparison_authorized=True if comparison_authorized else None,
            default_source_reference=default_source_reference,
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
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(val_err),
        )

    touched_learners = {r["learner_id"] for r in summary.results if r.get("status") == "created"}
    for lid in sorted(touched_learners):
        await handover_svc.evaluate_post_release_changes_for_learner(lid)
    return summary.model_dump(mode="json")


@router.post("/ingest/file", status_code=status.HTTP_201_CREATED)
async def ingest_external_file(
    request: Request,
    file: UploadFile = File(...),
    source_system: str = Form(..., min_length=1, max_length=120),
    import_method: str = Form("csv_import", max_length=60),
    imported_by: str | None = Form(None, max_length=120),
    notes: str | None = Form(None, max_length=2000),
    class_id: str | None = Form(None, max_length=100),
    academic_year: str | None = Form(None, max_length=16),
    term: str | None = Form(None, max_length=16),
    observed_at: str | None = Form(None, max_length=64),
    max_score: str | None = Form(None, max_length=32),
    grade: str | None = Form(None, max_length=60),
    assessment_stage: str | None = Form(None, max_length=40),
    form: str | None = Form(None, max_length=120),
    form_version: str | None = Form(None, max_length=60),
    language: str | None = Form(None, max_length=60),
    comparison_authorized: bool = Form(False),
) -> dict[str, Any]:
    """Ingest a CSV or JSON school export file with SHA-256 ImportManifest tracking."""
    _require_ingest_api_key(request)
    return await _execute_file_import(
        request,
        file=file,
        source_system=source_system,
        import_method=import_method,
        imported_by=imported_by,
        notes=notes,
        default_class_id=class_id,
        academic_year=academic_year,
        term=term,
        observed_at=observed_at,
        max_score=max_score,
        grade=grade,
        assessment_stage=assessment_stage,
        form_name=form,
        form_version=form_version,
        language=language,
        comparison_authorized=comparison_authorized,
    )


@router.post("/classes/{class_id}/import", status_code=status.HTTP_201_CREATED)
async def import_class_school_report(
    class_id: str,
    request: Request,
    file: UploadFile = File(...),
    source_system: str = Form("school_report_csv", min_length=1, max_length=120),
    academic_year: str | None = Form(None, max_length=16),
    term: str | None = Form(None, max_length=16),
    observed_at: str | None = Form(None, max_length=64),
    max_score: str | None = Form(None, max_length=32),
    grade: str | None = Form(None, max_length=60),
    assessment_stage: str | None = Form(None, max_length=40),
    form: str | None = Form(None, max_length=120),
    form_version: str | None = Form(None, max_length=60),
    language: str | None = Form(None, max_length=60),
    comparison_authorized: bool = Form(False),
    notes: str | None = Form(None, max_length=2000),
) -> dict[str, Any]:
    """Teacher-authenticated endpoint to import a school mark-sheet CSV or ALLPS export JSON for an assigned class."""
    teacher_id = _require_teacher(request)
    store: SQLiteStore = request.app.state.store
    school_cls = await store.get_class(class_id)
    if school_cls is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Class '{class_id}' does not exist.",
        )

    handover_svc = _require_handover_service(request)
    try:
        assignments = await handover_svc.assert_class_access(teacher_id, class_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    is_class_teacher = any(a.role == TeacherRole.CLASS_TEACHER for a in assignments)
    allowed_subjects = None if is_class_teacher else {a.subject for a in assignments if a.subject}
    teacher = await store.get_teacher(teacher_id)
    teacher_name = teacher["display_name"] if teacher else teacher_id

    return await _execute_file_import(
        request,
        file=file,
        source_system=source_system,
        import_method="csv_import",
        imported_by=teacher_id,
        notes=notes,
        default_class_id=class_id,
        enforce_class_id=class_id,
        allowed_subjects=allowed_subjects,
        default_source_reference=teacher_name,
        academic_year=academic_year,
        term=term,
        observed_at=observed_at,
        max_score=max_score,
        grade=grade,
        assessment_stage=assessment_stage,
        form_name=form,
        form_version=form_version,
        language=language,
        comparison_authorized=comparison_authorized,
    )


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


# ─────────────────────────────────────────────────────────────────────────────
# Workspace Database Status & Demo Reseed Endpoints
# ─────────────────────────────────────────────────────────────────────────────


async def _build_db_status_payload(request: Request, recent_limit: int = 5) -> dict[str, Any]:
    store: SQLiteStore = request.app.state.store
    raw_status = await store.get_database_status(recent_limit=recent_limit)
    raw_db_path = getattr(request.app.state, "db_path", None) or raw_status.pop("db_path", "allps.db")
    raw_status.pop("db_path", None)
    db_name = ":memory:" if raw_db_path == ":memory:" else Path(str(raw_db_path)).name
    has_demo_learners = all(
        [
            await store.learner_exists("LRN-001"),
            await store.learner_exists("LRN-002"),
            await store.learner_exists("LRN-003"),
        ]
    )
    return {
        **raw_status,
        "db_name": db_name,
        "allow_demo_reset": bool(getattr(request.app.state, "allow_demo_reset", True)),
        "has_demo_learners": has_demo_learners,
    }


@router.get("/db/status")
async def get_db_status(
    request: Request,
    recent_limit: int = Query(5, ge=1, le=25),
) -> dict[str, Any]:
    """Return live database counts, freshness timestamps, and recent evidence/audit records."""
    _require_teacher(request)
    return await _build_db_status_payload(request, recent_limit=recent_limit)


@router.post("/db/reseed")
async def reseed_workspace_database(
    payload: ReseedRequest,
    request: Request,
) -> dict[str, Any]:
    """Idempotently seed missing demo data ('merge') or wipe and re-seed ('reset')."""
    actor = _require_teacher(request)
    if not getattr(request.app.state, "allow_demo_reset", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace demo seeding/reset is disabled on this server.",
        )

    store: SQLiteStore = request.app.state.store
    ev_service: EvidenceService = request.app.state.evidence_service

    try:
        from data.synthetic.seed_data import seed_store
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Synthetic seed dataset is unavailable in this installation: {exc}",
        ) from exc

    reset = payload.mode == "reset"
    summary = await seed_store(store, reset=reset, actor=actor)

    # Keep offline mock synthesis aligned with the refreshed dataset
    from allps.web.app import build_mock_responses_from_store
    request.app.state.mock_responses = await build_mock_responses_from_store(store, ev_service)

    db_status = await _build_db_status_payload(request)
    if reset:
        message = (
            f"Reset workspace and re-seeded {summary['learners_added']} learners and "
            f"{summary['evidence_added']} evidence records."
        )
    elif summary["learners_added"] == 0 and summary["evidence_added"] == 0:
        message = (
            f"No new demo records added ({summary['learners_skipped']} learners and "
            f"{summary['evidence_skipped']} evidence records already present)."
        )
    else:
        message = (
            f"Added +{summary['learners_added']} learners and +{summary['evidence_added']} "
            f"evidence records ({summary['evidence_skipped']} existing skipped)."
        )

    return {
        "mode": payload.mode,
        "message": message,
        "learners_added": summary["learners_added"],
        "learners_skipped": summary["learners_skipped"],
        "evidence_added": summary["evidence_added"],
        "evidence_skipped": summary["evidence_skipped"],
        "total_learners": summary["total_learners"],
        "total_evidence": summary["total_evidence"],
        "cleared": summary["cleared"],
        "db_status": db_status,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Class Handover, Readiness, Releases, Receipts, Responses & Diffs
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/workspace")
async def get_teacher_workspace_endpoint(request: Request) -> dict[str, Any]:
    """Return signed-in teacher's roles, assigned classes, and attention queue."""
    teacher_id = _require_teacher(request)
    handover_svc = _require_handover_service(request)
    try:
        return await handover_svc.get_teacher_workspace(teacher_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/classes/{class_id}/enroll", status_code=status.HTTP_200_OK)
async def enroll_learner_in_class(
    class_id: str,
    payload: EnrollLearnerRequest,
    request: Request,
) -> dict[str, Any]:
    """Enroll an existing learner in class_id (class_teacher only)."""
    teacher_id = _require_teacher(request)
    store: SQLiteStore = request.app.state.store
    handover_svc = _require_handover_service(request)
    if await store.get_class(class_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Class '{class_id}' not found.")
    try:
        await handover_svc.assert_class_access(teacher_id, class_id, require_class_teacher=True)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if not await store.learner_exists(payload.learner_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Learner '{payload.learner_id}' not found.",
        )
    enrollment = await store.enroll_learner(class_id, payload.learner_id)
    return enrollment.model_dump(mode="json")


@router.get("/classes/{class_id}/readiness")
async def get_class_readiness_endpoint(class_id: str, request: Request) -> dict[str, Any]:
    """Return class readiness view with separated evidence availability and review states (class teacher only)."""
    teacher_id = _require_teacher(request)
    handover_svc = _require_handover_service(request)
    try:
        await handover_svc.assert_class_access(teacher_id, class_id, require_class_teacher=True)
        return await handover_svc.get_class_readiness(class_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("/learners/{learner_id}/availability")
async def get_learner_evidence_availability(learner_id: str, request: Request) -> dict[str, Any]:
    """Return system-computed evidence availability per permitted scope for learner_id."""
    _, access = await _authorize_learner(request, learner_id)
    store: SQLiteStore = request.app.state.store
    handover_svc = _require_handover_service(request)

    if access["is_class_teacher"]:
        classes = await store.get_learner_classes(learner_id)
        if classes:
            scopes = await handover_svc.get_required_scopes_for_class(classes[0].class_id)
        else:
            scopes = ["student", "Mathematics", "English", "Science"]
    else:
        scopes = ["student"] + access["allowed_subjects"]

    availability = {}
    for scope in scopes:
        availability[scope] = await handover_svc.compute_evidence_availability(learner_id, scope)
    return {
        "learner_id": learner_id,
        "scopes": availability,
    }


@router.post("/classes/{class_id}/learners/{learner_id}/sections/{scope}")
async def update_learner_section_review(
    class_id: str,
    learner_id: str,
    scope: str,
    payload: SectionReviewUpdateRequest,
    request: Request,
) -> dict[str, Any]:
    """Create or update a Student Review or Subject Review readiness slot (class_teacher only)."""
    teacher_id = _require_teacher(request)
    handover_svc = _require_handover_service(request)
    try:
        return await handover_svc.update_section_review(
            class_id=class_id,
            learner_id=learner_id,
            scope=scope,
            teacher_id=teacher_id,
            review_state=payload.review_state.value,
            approved_summary=payload.approved_summary,
            teacher_notes=payload.teacher_notes,
            missing_evidence_disclosure=payload.missing_evidence_disclosure,
            citations=payload.citations,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/classes/{class_id}/release", status_code=status.HTTP_201_CREATED)
async def release_class_handover(
    class_id: str,
    request: Request,
    payload: ClassReleaseRequest | None = None,
) -> dict[str, Any]:
    """Freeze and publish an immutable versioned class handover (class_teacher only)."""
    teacher_id = _require_teacher(request)
    handover_svc = _require_handover_service(request)
    try:
        return await handover_svc.release_class(
            class_id=class_id,
            teacher_id=teacher_id,
            notes=payload.notes if payload else None,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/classes/{class_id}/releases")
async def list_class_releases_endpoint(class_id: str, request: Request) -> list[dict[str, Any]]:
    """List immutable handover releases for class_id."""
    teacher_id = _require_teacher(request)
    store: SQLiteStore = request.app.state.store
    handover_svc = _require_handover_service(request)
    try:
        await handover_svc.assert_class_access(teacher_id, class_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    releases = await store.list_class_releases(class_id)
    return [r.model_dump(mode="json") for r in releases]


@router.get("/learners/{learner_id}/published")
async def get_learner_published_report(learner_id: str, request: Request) -> dict[str, Any]:
    """Return role-scoped published sections, receipts, viewing history, responses, and updates."""
    teacher_id, _ = await _authorize_learner(request, learner_id)
    handover_svc = _require_handover_service(request)
    return await handover_svc.get_learner_published_handover_view(learner_id, teacher_id)


@router.post("/releases/{release_id}/learners/{learner_id}/view")
async def record_released_report_view(
    release_id: str,
    learner_id: str,
    request: Request,
    payload: ReportViewRequest | None = None,
) -> dict[str, Any]:
    """Log an append-only viewing event for accountability without marking receipt acknowledged."""
    teacher_id = _require_teacher(request)
    handover_svc = _require_handover_service(request)
    try:
        return await handover_svc.record_report_view(
            release_id=release_id,
            learner_id=learner_id,
            teacher_id=teacher_id,
            scope=payload.scope if payload else None,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/releases/{release_id}/learners/{learner_id}/acknowledge")
async def acknowledge_released_report(
    release_id: str,
    learner_id: str,
    request: Request,
) -> dict[str, Any]:
    """Explicitly record receipt acknowledgment separately from viewing."""
    teacher_id = _require_teacher(request)
    handover_svc = _require_handover_service(request)
    try:
        return await handover_svc.acknowledge_report(
            release_id=release_id,
            learner_id=learner_id,
            teacher_id=teacher_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/releases/{release_id}/learners/{learner_id}/responses", status_code=status.HTTP_201_CREATED)
async def add_published_subject_response(
    release_id: str,
    learner_id: str,
    payload: SubjectResponseRequest,
    request: Request,
) -> dict[str, Any]:
    """Attach an attributed subject-teacher response beneath the unchanged approved Subject Review."""
    teacher_id = _require_teacher(request)
    handover_svc = _require_handover_service(request)
    try:
        return await handover_svc.add_subject_response(
            release_id=release_id,
            learner_id=learner_id,
            subject=payload.subject,
            teacher_id=teacher_id,
            response_type=payload.response_type.value,
            content=payload.content,
            related_change_id=payload.related_change_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/classes/{class_id}/changes")
async def list_class_post_release_changes(class_id: str, request: Request) -> list[dict[str, Any]]:
    """List post-release updates (minor/major) for class_id scoped by teacher role."""
    teacher_id = _require_teacher(request)
    store: SQLiteStore = request.app.state.store
    handover_svc = _require_handover_service(request)
    try:
        assignments = await handover_svc.assert_class_access(teacher_id, class_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    learners = await store.get_class_learners(class_id)
    for l in learners:
        await handover_svc.evaluate_post_release_changes_for_learner(l.learner_id)

    changes = await store.get_post_release_changes(class_id=class_id)
    is_ct = any(a.role.value == "class_teacher" for a in assignments)
    allowed_scopes = (
        None
        if is_ct
        else ({"student"} | {a.subject for a in assignments if a.subject})
    )
    out = []
    for ch in changes:
        if allowed_scopes is not None and ch.scope not in allowed_scopes:
            continue
        out.append(handover_svc._serialize_change(ch))
    return out


@router.post("/classes/{class_id}/changes/{change_id}/review")
async def review_post_release_change_endpoint(
    class_id: str,
    change_id: str,
    request: Request,
    payload: ChangeReviewRequest | None = None,
) -> dict[str, Any]:
    """Record class-teacher review of an active post-release change item."""
    teacher_id = _require_teacher(request)
    handover_svc = _require_handover_service(request)
    try:
        return await handover_svc.mark_change_reviewed(
            class_id=class_id,
            change_id=change_id,
            teacher_id=teacher_id,
            notes=payload.notes if payload else None,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
