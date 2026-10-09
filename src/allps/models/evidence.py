"""Evidence domain model — the core data unit in ALLPS."""

from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Annotated
import math

from pydantic import BaseModel, Field, field_validator, model_validator, PlainValidator, PlainSerializer

import uuid

def _deep_freeze(v: Any) -> Any:
    if isinstance(v, MappingProxyType):
        return v
    if isinstance(v, dict):
        return MappingProxyType({k: _deep_freeze(val) for k, val in v.items()})
    if isinstance(v, list):
        return tuple(_deep_freeze(val) for val in v)
    if isinstance(v, set):
        return frozenset(_deep_freeze(val) for val in v)
    return v

def _validate_mapping_proxy(v: Any) -> MappingProxyType:
    return _deep_freeze(v)

FrozenDictType = Annotated[
    MappingProxyType[str, Any],
    PlainValidator(_validate_mapping_proxy),
    PlainSerializer(lambda x: dict(x), return_type=dict)
]


class EvidenceType(str, Enum):
    """Types of learner evidence that ALLPS can record."""

    ASSESSMENT = "assessment"
    ATTENDANCE = "attendance"
    OBSERVATION = "observation"
    LEARNER_REFLECTION = "learner_reflection"
    PROJECT = "project"


class IngestionMethod(str, Enum):
    """Mechanisms by which evidence is ingested into ALLPS."""

    API = "api"
    WEBHOOK = "webhook"
    SCHEDULED_SYNC = "scheduled_sync"
    CSV_IMPORT = "csv_import"
    MANUAL_OBSERVATION = "manual_observation"
    LEARNER_PULSE = "learner_pulse"
    SYNTHETIC = "synthetic"


class Evidence(BaseModel):
    """A single piece of learner evidence with full provenance.

    Evidence is immutable once recorded. Each record captures what was
    observed, who observed it, when it was observed, and when it was
    recorded in ALLPS.

    ALLPS is not the authoritative gradebook — evidence may originate
    from an external SIS, LMS, attendance system, CSV import, learner
    pulse, or direct teacher observations. Both the originating
    source_system and ingestion_method are explicitly preserved.

    The content field is a flexible dict for evidence-type-specific
    payloads (e.g., {"score": 72, "max_score": 100} for assessments).
    """

    evidence_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    learner_id: str = Field(..., min_length=1)
    evidence_type: EvidenceType

    # System origin and ingestion channel
    source_system: str = Field(
        ...,
        min_length=1,
        description=(
            "Originating system, e.g. 'school_sis', 'moodle', "
            "'attendance_system', 'allps', 'csv_import', 'synthetic_dataset'"
        ),
    )
    ingestion_method: IngestionMethod = Field(
        ...,
        description="Ingestion mechanism/channel, e.g. 'manual_observation', 'api'",
    )

    source_event_id: str | None = Field(
        default=None,
        description="Stable unique identifier from the source system for idempotent ingestion.",
    )

    # Provenance
    source_type: str = Field(
        ...,
        min_length=1,
        description=(
            "Who/what provided this evidence, "
            "e.g. 'teacher', 'system', 'learner'"
        ),
    )
    source_reference: str = Field(
        ...,
        min_length=1,
        description=(
            "Specific source identifier, "
            "e.g. 'Mrs. Nkosi', 'attendance-system-v2'"
        ),
    )

    # Academic time (sortable)
    academic_year: int = Field(..., ge=2000, le=2100)
    term: int = Field(..., ge=1, le=4)

    # Optional subject
    subject: str | None = Field(default=None)

    # Flexible payload (Immutable)
    content: FrozenDictType = Field(
        ..., description="Evidence-type-specific payload"
    )

    # Timestamps
    observed_at: datetime = Field(
        ...,
        description="When the observation/event occurred (timezone-aware)",
    )
    recorded_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this was recorded in ALLPS",
    )

    @field_validator("observed_at", "recorded_at")
    @classmethod
    def must_be_timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("Datetime must be timezone-aware")
        return v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_content_payloads(self) -> "Evidence":
        """Validate known evidence types (Assessment, Attendance)."""
        if self.evidence_type == EvidenceType.ASSESSMENT:
            has_score = "score" in self.content and "max_score" in self.content
            has_fluency = "value" in self.content and "unit" in self.content

            if not has_score and not has_fluency:
                raise ValueError("Assessment evidence must contain either ('score' and 'max_score') or ('value' and 'unit')")

            if has_score:
                score = self.content["score"]
                max_score = self.content["max_score"]
                if isinstance(score, bool) or isinstance(max_score, bool) or not isinstance(score, (int, float)) or not isinstance(max_score, (int, float)):
                    raise ValueError("'score' and 'max_score' must be numeric (not boolean)")
                if not math.isfinite(score) or not math.isfinite(max_score):
                    raise ValueError("Numeric fields must be finite")
                if max_score <= 0:
                    raise ValueError("'max_score' must be greater than 0")
                if score < 0 or score > max_score:
                    raise ValueError("'score' must be between 0 and 'max_score'")

            if has_fluency:
                value = self.content["value"]
                unit = self.content["unit"]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError("'value' must be numeric (not boolean)")
                if not math.isfinite(value):
                    raise ValueError("'value' must be finite")
                if not isinstance(unit, str) or not unit:
                    raise ValueError("'unit' must be a non-empty string")

        elif self.evidence_type == EvidenceType.ATTENDANCE:
            has_daily = "status" in self.content
            has_term = "days_present" in self.content and "days_total" in self.content

            if not has_daily and not has_term:
                raise ValueError("Attendance evidence must contain either 'status' or ('days_present' and 'days_total')")

            if has_daily:
                if self.content["status"] not in ("present", "absent", "late"):
                    raise ValueError("Attendance status must be 'present', 'absent', or 'late'")

            if has_term:
                dp = self.content["days_present"]
                dt = self.content["days_total"]
                if isinstance(dp, bool) or isinstance(dt, bool) or not isinstance(dp, int) or not isinstance(dt, int):
                    raise ValueError("'days_present' and 'days_total' must be integers (not boolean)")
                if dt <= 0:
                    raise ValueError("'days_total' must be greater than 0")
                if dp < 0 or dp > dt:
                    raise ValueError("'days_present' must be between 0 and 'days_total'")

        return self

    model_config = {"frozen": True}
