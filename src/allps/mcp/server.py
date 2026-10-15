"""ALLPS MCP Server — exposes evidence and governance tools over the Model Context Protocol.

Exposed tools:
  - ingest_evidence: Ingest a new piece of learner evidence with provenance
  - get_learner_history: Retrieve chronologically ordered learner history
  - analyse_longitudinal_pattern: Deterministic longitudinal pattern analysis
  - flag_pattern_for_review: Flag candidate pattern for teacher review
  - resolve_teacher_review: Sovereign human teacher adjudication
  - get_pending_reviews: Retrieve pending review items for teacher inbox
  - get_surfaced_profile: Retrieve published learner profile (human-accepted patterns only)

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
from allps.services.analysis_service import AnalysisService
from allps.services.review_service import ReviewService
from allps.storage.sqlite_store import SQLiteStore

mcp = FastMCP("allps")

_service: EvidenceService | None = None
_analysis_service: AnalysisService | None = None
_review_service: ReviewService | None = None


async def _get_service() -> EvidenceService:
    """Lazy-initialize the evidence service with SQLite store."""
    global _service
    if _service is None:
        db_path = os.environ.get("ALLPS_DB_PATH", "allps.db")
        store = SQLiteStore(db_path)
        await store.initialize()
        _service = EvidenceService(store)
    return _service


async def _get_analysis_service() -> AnalysisService:
    """Get or create the analysis service instance."""
    global _analysis_service
    if _analysis_service is None:
        evidence_srv = await _get_service()
        _analysis_service = AnalysisService(evidence_srv)
    return _analysis_service


async def _get_review_service() -> ReviewService:
    """Get or create the review service instance."""
    global _review_service
    if _review_service is None:
        evidence_srv = await _get_service()
        store = getattr(evidence_srv, "store", None) or getattr(evidence_srv, "_store", None)
        _review_service = ReviewService(store)
    return _review_service


def set_service(
    service: EvidenceService | None,
    review_service: ReviewService | None = None,
) -> None:
    """Override the service instance (for testing)."""
    global _service, _analysis_service, _review_service
    _service = service
    if service is not None:
        _analysis_service = AnalysisService(service)
        store = getattr(service, "store", None) or getattr(service, "_store", None)
        _review_service = review_service or (ReviewService(store) if store else None)
    else:
        _analysis_service = None
        _review_service = None


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
    source_event_id: str | None = None,
    subject: str | None = None,
) -> dict[str, Any]:
    """Ingest a new piece of learner evidence."""
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
        source_event_id=source_event_id,
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
    """Get all evidence for a learner, ordered chronologically."""
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


@mcp.tool(
    description=(
        "Analyse longitudinal patterns for a learner, optionally filtered by evidence type and subject. "
        "Returns a list of pattern objects with supporting evidence and limitations."
    )
)
async def analyse_longitudinal_pattern(
    learner_id: str,
    evidence_type: str | None = None,
    subject: str | None = None,
) -> list[dict[str, Any]]:
    """Wrapper for AnalysisService.analyse_longitudinal_pattern."""
    analysis_srv = await _get_analysis_service()
    patterns = await analysis_srv.analyse_longitudinal_pattern(
        learner_id,
        evidence_type=evidence_type,
        subject=subject,
    )
    return patterns


# ---------------------------------------------------------------------
# Phase 2 Governance & Teacher Review Tools
# ---------------------------------------------------------------------

@mcp.tool(
    description=(
        "Flag a candidate longitudinal pattern for sovereign human teacher review. "
        "Enters candidate pattern into the teacher review inbox in PENDING state."
    )
)
async def flag_pattern_for_review(
    pattern_id: str,
    assigned_to: str | None = None,
) -> dict[str, Any]:
    """Flag a pattern for human teacher review."""
    review_srv = await _get_review_service()
    item = await review_srv.flag_pattern_for_review(
        pattern_id=pattern_id,
        assigned_to=assigned_to,
    )
    return item.model_dump(mode="json")


@mcp.tool(
    description=(
        "Resolve a candidate pattern review. Autonomous MCP clients may record notes, "
        "reject, or request context ('needs_context', 'rejected'), but are strictly prohibited "
        "from self-approving ('accepted'). Formal approval must be mediated by authenticated "
        "human teachers via the trusted backend ReviewService."
    )
)
async def resolve_teacher_review(
    review_id: str,
    status: str,
    reviewer_id: str,
    teacher_notes: str | None = None,
) -> dict[str, Any]:
    """Resolve a review item with human teacher adjudication."""
    clean_status = status.strip().lower() if isinstance(status, str) else str(status)
    if clean_status in ("accepted", "reviewstatus.accepted"):
        raise PermissionError(
            "Autonomous MCP clients cannot self-approve findings. "
            "Human teacher approval must occur via the trusted backend ReviewService."
        )
    review_srv = await _get_review_service()
    item = await review_srv.resolve_teacher_review(
        review_id=review_id,
        status=status,
        reviewer_id=reviewer_id,
        teacher_notes=teacher_notes,
    )
    return item.model_dump(mode="json")


@mcp.tool(
    description=(
        "Retrieve all review items pending teacher adjudication, "
        "optionally filtered by assigned teacher identifier."
    )
)
async def get_pending_reviews(
    assigned_to: str | None = None,
) -> list[dict[str, Any]]:
    """Get all pending review items."""
    review_srv = await _get_review_service()
    items = await review_srv.get_pending_reviews(assigned_to=assigned_to)
    return [i.model_dump(mode="json") for i in items]


@mcp.tool(
    description=(
        "Retrieve published learner profile, strictly exposing patterns that have been "
        "reviewed and accepted by a human teacher. Unreviewed, pending, or rejected patterns are excluded."
    )
)
async def get_surfaced_profile(
    learner_id: str,
) -> dict[str, Any]:
    """Get published learner profile with strictly human-accepted patterns."""
    review_srv = await _get_review_service()
    return await review_srv.get_surfaced_profile(learner_id)


def main() -> None:
    """Run the ALLPS MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
