"""Evidence domain model — the core data unit in ALLPS."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

import uuid


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

    # Flexible payload
    content: dict[str, Any] = Field(
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
        return v

    model_config = {"frozen": True}
