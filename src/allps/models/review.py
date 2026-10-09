"""ReviewItem domain model — teacher review of surfaced patterns."""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

import uuid


class ReviewStatus(str, Enum):
    """Status of a teacher review."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NEEDS_CONTEXT = "needs_context"


class ReviewItem(BaseModel):
    """A review item created when a pattern is flagged for teacher review.

    This is the source of truth for the human-review status of a pattern.
    Teachers can accept, reject, or request additional context.
    """

    review_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    pattern_id: str = Field(..., min_length=1)
    assigned_to: str | None = Field(default=None)
    status: ReviewStatus = Field(default=ReviewStatus.PENDING)
    teacher_notes: str | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    resolved_at: datetime | None = Field(default=None)
