"""Pattern domain model — surfaced longitudinal patterns."""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

import uuid


class PatternType(str, Enum):
    """Types of longitudinal patterns ALLPS can surface."""

    TREND = "trend"
    PERSISTENCE = "persistence"
    CONVERGENCE = "convergence"
    DIVERGENCE = "divergence"
    CHANGED_FROM_BASELINE = "changed_from_baseline"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class Pattern(BaseModel):
    """A candidate longitudinal pattern surfaced by ALLPS.

    Patterns are always backed by supporting evidence and must go
    through teacher review via a ReviewItem before being acted upon.

    Note: review_status lives on ReviewItem, not here. ReviewItem is
    the source of truth for human-review state.
    """

    pattern_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    learner_id: str = Field(..., min_length=1)
    pattern_type: PatternType
    summary: str = Field(..., min_length=1)
    supporting_evidence: list[str] = Field(
        default_factory=list, description="List of evidence_ids"
    )
    conflicting_evidence: list[str] = Field(
        default_factory=list, description="List of evidence_ids"
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Known limitations of this pattern",
    )
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    model_config = {"frozen": True}
