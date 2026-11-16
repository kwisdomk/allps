"""Import manifest domain model.

An ImportManifest records the identity of a file-level import event.
Its SHA-256 hash of the raw file bytes allows the system to detect
when the exact same source file is submitted again, preventing a
repeated import from silently doubling evidence counts.

File-level deduplication is separate from record-level deduplication.
A CSV containing 50 rows shares one file hash. Individual row identity
is tracked separately via the canonical_fingerprint on each Evidence record.
"""

from datetime import datetime, timezone
import uuid

from pydantic import BaseModel, Field


class ImportManifest(BaseModel):
    """Record of a single file import event.

    Created when a CSV or JSON file is ingested.
    Immutable once created.
    """

    manifest_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Who imported it and from where
    source_system: str = Field(..., min_length=1)
    file_name: str = Field(..., min_length=1)
    import_method: str = Field(
        ...,
        description="e.g. 'csv_import', 'mcp_import', 'api_batch'",
    )

    # File identity — SHA-256 of the raw file bytes (hex string, 64 chars)
    file_sha256: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="Lowercase hex SHA-256 of the raw file content.",
    )

    # Import outcome
    row_count: int = Field(..., ge=0, description="Number of data rows in the file.")
    accepted_count: int = Field(..., ge=0, description="Records successfully ingested.")
    rejected_count: int = Field(..., ge=0, description="Records rejected during validation.")
    duplicate_count: int = Field(
        default=0,
        ge=0,
        description="Records skipped because a fingerprint-identical record already exists.",
    )

    imported_by: str | None = Field(
        default=None,
        description="Reviewer/teacher identity that triggered the import, if available.",
    )

    imported_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    notes: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional free-text notes about this import (e.g. source school, cohort).",
    )

    model_config = {"frozen": True}
