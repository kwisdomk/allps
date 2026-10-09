"""AuditEntry domain model — tool call audit trail."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

import uuid


class AuditEntry(BaseModel):
    """An audit log entry recording an MCP tool invocation.

    Every tool call in ALLPS is logged for traceability, recording
    the tool name, input summary, output reference, and timestamp.
    """

    audit_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    tool_name: str = Field(..., min_length=1)
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_reference: str | None = Field(default=None)
    approval_state: str | None = Field(default=None)
