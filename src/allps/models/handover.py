"""Class handover, teacher assignment, release, receipt, response, and diff models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from allps.policies.label_policy import validate_text_for_prohibited_labels


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_safe_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    validate_text_for_prohibited_labels(value, field_name=field_name)
    return value


class TeacherRole(str, Enum):
    """Assigned school responsibility for a teacher within a class."""

    CLASS_TEACHER = "class_teacher"
    SUBJECT_TEACHER = "subject_teacher"


class EvidenceAvailabilityStatus(str, Enum):
    """System-determined evidence sufficiency/gap state (separate from review state)."""

    SUFFICIENT = "sufficient"
    INSUFFICIENT_ASSESSMENT_HISTORY = "insufficient_assessment_history"
    ASSESSMENT_NOT_CONDUCTED = "assessment_not_conducted"
    NO_DATA_AVAILABLE = "no_data_available"
    MISSING_RESULT = "missing_result"
    SOURCE_TRACE_NOT_FOUND = "source_trace_not_found"


class SectionReviewState(str, Enum):
    """Class-teacher completion state for each required learner review section."""

    NOT_REVIEWED = "not_reviewed"
    NEEDS_CLARIFICATION = "needs_clarification"
    REVIEWED_INCOMPLETE = "reviewed_incomplete"
    READY_FOR_RELEASE = "ready_for_release"


class ReceiptStatus(str, Enum):
    """Separate viewing vs. receipt-acknowledgment states for released reports."""

    NOT_VIEWED = "not_viewed"
    VIEWED = "viewed"
    ACKNOWLEDGED = "acknowledged"


class SubjectResponseType(str, Enum):
    """Kind of attributed child response appended beneath a published Subject Review."""

    CONFIRMATION = "confirmation"
    ADDITIONAL_OBSERVATION = "additional_observation"
    QUESTION = "question"


class DiffSeverity(str, Enum):
    """Structured severity classification of new evidence after a class release."""

    NONE = "none"
    MINOR = "minor"
    MAJOR = "major"


class ChangeProgressStatus(str, Enum):
    """Tracked follow-up progression for post-release updates."""

    NOT_OPENED = "not_opened"
    OPENED = "opened"
    RESPONSE_ADDED = "response_added"
    REVIEWED_BY_CLASS_TEACHER = "reviewed_by_class_teacher"
    NEW_VERSION_RELEASED = "new_version_released"


class SchoolClass(BaseModel):
    """A school class cohort for an academic year and term."""

    class_id: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=200)
    grade: str = Field(..., min_length=1, max_length=100)
    academic_year: int = Field(..., ge=2000, le=2100)
    term: int = Field(..., ge=1, le=4)
    created_at: datetime = Field(default_factory=_utc_now)

    model_config = ConfigDict(frozen=True)


class ClassEnrollment(BaseModel):
    """Associates a learner with a specific school class."""

    class_id: str = Field(..., min_length=1, max_length=100)
    learner_id: str = Field(..., min_length=1, max_length=100)
    enrolled_at: datetime = Field(default_factory=_utc_now)

    model_config = ConfigDict(frozen=True)


class TeacherAssignment(BaseModel):
    """Assigns a teacher to a class either as class_teacher or subject_teacher."""

    assignment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    teacher_id: str = Field(..., min_length=1, max_length=100)
    class_id: str = Field(..., min_length=1, max_length=100)
    role: TeacherRole
    subject: Optional[str] = Field(default=None, max_length=120)
    created_at: datetime = Field(default_factory=_utc_now)

    model_config = ConfigDict(frozen=True)


class SectionReview(BaseModel):
    """Draft/approved readiness slot authored by the class teacher before class release."""

    section_review_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    class_id: str = Field(..., min_length=1, max_length=100)
    learner_id: str = Field(..., min_length=1, max_length=100)
    scope: str = Field(..., min_length=1, max_length=120)
    review_state: SectionReviewState = Field(default=SectionReviewState.NOT_REVIEWED)
    approved_summary: Optional[str] = Field(default=None, max_length=5000)
    teacher_notes: Optional[str] = Field(default=None, max_length=5000)
    missing_evidence_disclosure: Optional[str] = Field(default=None, max_length=2000)
    citations: tuple[str, ...] = Field(default=())
    reviewed_by: Optional[str] = Field(default=None, max_length=100)
    reviewed_at: Optional[datetime] = Field(default=None)
    updated_at: datetime = Field(default_factory=_utc_now)

    model_config = ConfigDict(frozen=True)

    @field_validator("approved_summary", "teacher_notes", "missing_evidence_disclosure")
    @classmethod
    def check_labels(cls, v: Optional[str], info: Any) -> Optional[str]:
        return _validate_safe_text(v, info.field_name)


class ClassRelease(BaseModel):
    """Immutable versioned handover publication for an entire class cohort."""

    release_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    class_id: str = Field(..., min_length=1, max_length=100)
    version_number: int = Field(..., ge=1)
    released_by: str = Field(..., min_length=1, max_length=100)
    released_by_name: str = Field(..., min_length=1, max_length=200)
    released_at: datetime = Field(default_factory=_utc_now)
    frozen_enrollment: tuple[str, ...] = Field(default=())
    frozen_subjects: tuple[str, ...] = Field(default=())
    notes: Optional[str] = Field(default=None, max_length=2000)

    model_config = ConfigDict(frozen=True)

    @field_validator("notes")
    @classmethod
    def check_notes(cls, v: Optional[str]) -> Optional[str]:
        return _validate_safe_text(v, "notes")


def compute_published_section_hash(
    *,
    class_id: str,
    learner_id: str,
    scope: str,
    review_state: str,
    approved_summary: str,
    teacher_notes: str | None,
    missing_evidence_disclosure: str | None,
    citations: tuple[str, ...] | list[str],
    approved_by: str,
) -> str:
    """Compute canonical SHA-256 snapshot hash over published section text, notes, disclosure, and citations."""
    payload = {
        "class_id": class_id,
        "learner_id": learner_id,
        "scope": scope,
        "review_state": review_state,
        "approved_summary": approved_summary,
        "teacher_notes": teacher_notes or "",
        "missing_evidence_disclosure": missing_evidence_disclosure or "",
        "citations": list(citations),
        "approved_by": approved_by,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PublishedReportSection(BaseModel):
    """Frozen published Student Review or Subject Review snapshot inside a ClassRelease."""

    published_section_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    release_id: str = Field(..., min_length=1, max_length=100)
    class_id: str = Field(..., min_length=1, max_length=100)
    learner_id: str = Field(..., min_length=1, max_length=100)
    scope: str = Field(..., min_length=1, max_length=120)
    section_title: str = Field(..., min_length=1, max_length=200)
    review_state: SectionReviewState
    evidence_availability: dict[str, Any] = Field(default_factory=dict)
    approved_summary: str = Field(..., min_length=1, max_length=5000)
    teacher_notes: Optional[str] = Field(default=None, max_length=5000)
    missing_evidence_disclosure: Optional[str] = Field(default=None, max_length=2000)
    citations: tuple[str, ...] = Field(default=())
    approved_content_hash: str = Field(default="", max_length=128)
    evidence_fingerprints: dict[str, Any] = Field(default_factory=dict)
    analysis_signature: dict[str, Any] = Field(default_factory=dict)
    approved_by: str = Field(..., min_length=1, max_length=100)
    approved_by_name: str = Field(..., min_length=1, max_length=200)
    approved_at: datetime
    released_by: str = Field(..., min_length=1, max_length=100)
    released_at: datetime = Field(default_factory=_utc_now)

    model_config = ConfigDict(frozen=True)

    @model_validator(mode="before")
    @classmethod
    def populate_content_hash(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("approved_content_hash"):
            rv = data.get("review_state")
            rv_str = rv.value if hasattr(rv, "value") else str(rv or "")
            data = dict(data)
            data["approved_content_hash"] = compute_published_section_hash(
                class_id=str(data.get("class_id", "")),
                learner_id=str(data.get("learner_id", "")),
                scope=str(data.get("scope", "")),
                review_state=rv_str,
                approved_summary=str(data.get("approved_summary", "")),
                teacher_notes=data.get("teacher_notes"),
                missing_evidence_disclosure=data.get("missing_evidence_disclosure"),
                citations=list(data.get("citations") or ()),
                approved_by=str(data.get("approved_by", "")),
            )
        return data

    def verify_content_hash(self) -> bool:
        """Verify stored approved_content_hash against current frozen fields."""
        expected = compute_published_section_hash(
            class_id=self.class_id,
            learner_id=self.learner_id,
            scope=self.scope,
            review_state=self.review_state.value,
            approved_summary=self.approved_summary,
            teacher_notes=self.teacher_notes,
            missing_evidence_disclosure=self.missing_evidence_disclosure,
            citations=self.citations,
            approved_by=self.approved_by,
        )
        return bool(self.approved_content_hash) and self.approved_content_hash == expected


class ReportViewEvent(BaseModel):
    """Append-only audit record when a teacher opens an accessible published review."""

    view_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    release_id: str = Field(..., min_length=1, max_length=100)
    class_id: str = Field(..., min_length=1, max_length=100)
    learner_id: str = Field(..., min_length=1, max_length=100)
    scope: str = Field(..., min_length=1, max_length=120)
    teacher_id: str = Field(..., min_length=1, max_length=100)
    teacher_name: str = Field(..., min_length=1, max_length=200)
    viewed_at: datetime = Field(default_factory=_utc_now)

    model_config = ConfigDict(frozen=True)


class ReportReceipt(BaseModel):
    """Per-teacher viewing summary and separate explicit receipt acknowledgment."""

    receipt_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    release_id: str = Field(..., min_length=1, max_length=100)
    class_id: str = Field(..., min_length=1, max_length=100)
    learner_id: str = Field(..., min_length=1, max_length=100)
    teacher_id: str = Field(..., min_length=1, max_length=100)
    teacher_name: str = Field(..., min_length=1, max_length=200)
    subject: Optional[str] = Field(default=None, max_length=120)
    status: ReceiptStatus = Field(default=ReceiptStatus.NOT_VIEWED)
    first_viewed_at: Optional[datetime] = Field(default=None)
    last_viewed_at: Optional[datetime] = Field(default=None)
    view_count: int = Field(default=0, ge=0)
    acknowledged_at: Optional[datetime] = Field(default=None)

    model_config = ConfigDict(frozen=True)


class SubjectResponse(BaseModel):
    """Attributed child response attached underneath a published Subject Review."""

    response_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    release_id: str = Field(..., min_length=1, max_length=100)
    published_section_id: str = Field(..., min_length=1, max_length=100)
    class_id: str = Field(..., min_length=1, max_length=100)
    learner_id: str = Field(..., min_length=1, max_length=100)
    subject: str = Field(..., min_length=1, max_length=120)
    teacher_id: str = Field(..., min_length=1, max_length=100)
    teacher_name: str = Field(..., min_length=1, max_length=200)
    response_type: SubjectResponseType = Field(default=SubjectResponseType.CONFIRMATION)
    content: str = Field(..., min_length=1, max_length=3000)
    related_change_id: Optional[str] = Field(default=None, max_length=100)
    created_at: datetime = Field(default_factory=_utc_now)

    model_config = ConfigDict(frozen=True)

    @field_validator("content")
    @classmethod
    def check_content(cls, v: str) -> str:
        res = _validate_safe_text(v, "content")
        assert res is not None
        return res


class PostReleaseChange(BaseModel):
    """Tracked post-release evidence update classified as minor vs. major."""

    change_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    release_id: str = Field(..., min_length=1, max_length=100)
    class_id: str = Field(..., min_length=1, max_length=100)
    learner_id: str = Field(..., min_length=1, max_length=100)
    scope: str = Field(..., min_length=1, max_length=120)
    severity: DiffSeverity
    headline: str = Field(..., min_length=1, max_length=500)
    explanation: str = Field(..., min_length=1, max_length=3000)
    why_it_matters: str = Field(..., min_length=1, max_length=3000)
    comparison: dict[str, Any] = Field(default_factory=dict)
    new_evidence_ids: tuple[str, ...] = Field(default=())
    opened_by_teacher_id: Optional[str] = Field(default=None, max_length=100)
    opened_by_name: Optional[str] = Field(default=None, max_length=200)
    opened_at: Optional[datetime] = Field(default=None)
    response_id: Optional[str] = Field(default=None, max_length=100)
    response_added_by_name: Optional[str] = Field(default=None, max_length=200)
    response_added_at: Optional[datetime] = Field(default=None)
    reviewed_by_class_teacher_id: Optional[str] = Field(default=None, max_length=100)
    reviewed_by_name: Optional[str] = Field(default=None, max_length=200)
    reviewed_at: Optional[datetime] = Field(default=None)
    review_resolution_notes: Optional[str] = Field(default=None, max_length=2000)
    superseded_by_release_id: Optional[str] = Field(default=None, max_length=100)
    superseded_version_number: Optional[int] = Field(default=None, ge=1)
    created_at: datetime = Field(default_factory=_utc_now)

    model_config = ConfigDict(frozen=True)
