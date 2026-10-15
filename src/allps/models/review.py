"""ReviewItem domain model — teacher review of surfaced patterns."""

from datetime import datetime, timezone
from enum import Enum
import uuid

from pydantic import BaseModel, Field, model_validator


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

    # Workstream 2 Governance Attributes
    reviewer_id: str | None = Field(
        default=None,
        description="Explicit identifier of the human teacher reviewer who resolved this item.",
    )
    approved_content_hash: str | None = Field(
        default=None,
        description="SHA-256 hash of the exact approved pattern summary snapshot at time of approval.",
    )

    @model_validator(mode="after")
    def validate_resolution_metadata(self) -> "ReviewItem":
        """Ensure human authority and content snapshot hash are recorded on acceptance."""
        if self.status == ReviewStatus.ACCEPTED:
            if not self.reviewer_id or not self.reviewer_id.strip():
                raise ValueError(
                    "Review resolution to 'accepted' requires an explicit human reviewer_id."
                )
            if not self.approved_content_hash or not self.approved_content_hash.strip():
                raise ValueError(
                    "Review resolution to 'accepted' requires an approved_content_hash snapshot."
                )
            if self.resolved_at is None:
                self.resolved_at = datetime.now(timezone.utc)
        elif self.status in (ReviewStatus.REJECTED, ReviewStatus.NEEDS_CONTEXT):
            if not self.reviewer_id or not self.reviewer_id.strip():
                raise ValueError(
                    f"Review resolution to '{self.status.value}' requires an explicit human reviewer_id."
                )
            if self.resolved_at is None:
                self.resolved_at = datetime.now(timezone.utc)
        return self
