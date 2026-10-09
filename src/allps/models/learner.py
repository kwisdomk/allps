"""Learner domain model."""

from datetime import datetime, timezone

from pydantic import BaseModel, Field

import uuid


class Learner(BaseModel):
    """Represents a learner in the ALLPS system.

    A learner is an individual whose longitudinal evidence is tracked.
    ALLPS collects observations, not identities — the display_name is
    for teacher reference only.
    """

    learner_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    display_name: str = Field(..., min_length=1, max_length=200)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    model_config = {"frozen": True}
