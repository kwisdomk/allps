"""ALLPS MCP Server — exposes evidence tools over the Model Context Protocol.

Phase 1 tools (implemented):
  - ingest_evidence: Ingest a new piece of learner evidence with provenance
  - get_learner_history: Retrieve chronologically ordered learner history

Phase 2 tools (not yet implemented — do NOT register):
  - analyse_longitudinal_pattern: Deterministic longitudinal analysis
  - flag_pattern_for_review: Create a review item for teacher

Run with:
    python -m allps.mcp.server
    # or
    allps-mcp
"""

import os
from typing import Any

try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except (ImportError, ModuleNotFoundError):
    from mcp.server.fastmcp import FastMCP

from allps.services.evidence_service import EvidenceService
from allps.storage.sqlite_store import SQLiteStore

mcp = FastMCP("allps")

_service: EvidenceService | None = None


async def _get_service() -> EvidenceService:
    """Lazy-initialize the evidence service with SQLite store."""
    global _service
    if _service is None:
        db_path = os.environ.get("ALLPS_DB_PATH", "allps.db")
        store = SQLiteStore(db_path)
        await store.initialize()
        _service = EvidenceService(store)
    return _service


def set_service(service: EvidenceService | None) -> None:
    """Override the service instance (for testing)."""
    global _service
    _service = service


@mcp.tool(
    description=(
        "Ingest a new piece of learner evidence with full provenance and system origin. "
        "Evidence is immutable once recorded. Auto-creates the learner "
        "if they do not yet exist in the system."
    )
)
async def ingest_evidence(
    learner_id: str,
    evidence_type: str,
    source_system: str,
    ingestion_method: str,
    source_type: str,
    source_reference: str,
    academic_year: int,
    term: int,
    content: dict[str, Any],
    observed_at: str,
    subject: str | None = None,
) -> dict[str, Any]:
    """Ingest a new piece of learner evidence.

    Args:
        learner_id: Unique identifier for the learner.
        evidence_type: One of: assessment, attendance, observation,
                       learner_reflection, project.
        source_system: Originating system (e.g., 'school_sis', 'moodle',
                       'attendance_system', 'allps', 'csv_import').
        ingestion_method: Ingestion mechanism (one of: api, webhook,
                          scheduled_sync, csv_import, manual_observation,
                          learner_pulse, synthetic).
        source_type: Who/what provided this evidence
                     (e.g., 'teacher', 'system', 'learner').
        source_reference: Specific source identifier
                          (e.g., 'Mrs. Nkosi').
        academic_year: Academic year as integer (e.g., 2025).
        term: Term number (1-4).
        content: Evidence-specific payload
                 (e.g., {"score": 72, "max_score": 100}).
        observed_at: ISO 8601 datetime string for when the observation
                     occurred.
        subject: Optional subject name (e.g., 'Mathematics').

    Returns:
        The recorded evidence as a dictionary.
    """
    service = await _get_service()
    evidence = await service.record_evidence(
        learner_id=learner_id,
        evidence_type=evidence_type,
        source_system=source_system,
        ingestion_method=ingestion_method,
        source_type=source_type,
        source_reference=source_reference,
        academic_year=academic_year,
        term=term,
        content=content,
        observed_at=observed_at,
        subject=subject,
    )
    return evidence.model_dump(mode="json")


# Alias for backwards compatibility
record_evidence = ingest_evidence


@mcp.tool(
    description=(
        "Retrieve the full chronologically ordered evidence history "
        "for a learner. Supports optional filters by evidence type, "
        "academic year, term, and subject. Results are ordered by "
        "academic_year, term, then observed_at."
    )
)
async def get_learner_history(
    learner_id: str,
    evidence_type: str | None = None,
    academic_year: int | None = None,
    term: int | None = None,
    subject: str | None = None,
) -> dict[str, Any]:
    """Get all evidence for a learner, ordered chronologically.

    Args:
        learner_id: Unique identifier for the learner.
        evidence_type: Optional filter — one of: assessment, attendance,
                       observation, learner_reflection, project.
        academic_year: Optional filter by academic year.
        term: Optional filter by term number (1-4).
        subject: Optional filter by subject name.

    Returns:
        Dictionary with learner_id, record_count, and evidence list.
    """
    service = await _get_service()
    records = await service.get_learner_history(
        learner_id=learner_id,
        evidence_type=evidence_type,
        academic_year=academic_year,
        term=term,
        subject=subject,
    )
    return {
        "learner_id": learner_id,
        "record_count": len(records),
        "evidence": [r.model_dump(mode="json") for r in records],
    }


def main() -> None:
    """Run the ALLPS MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
