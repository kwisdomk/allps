"""Evidence service — business logic for recording and retrieving evidence.

Evidence is immutable once recorded. This service handles:
- Validation via Pydantic models
- Learner auto-registration (Phase 1 convenience)
- Audit logging of every tool invocation
"""

from datetime import datetime, timezone

from allps.models import (
    AuditEntry,
    Evidence,
    EvidenceType,
    IngestionMethod,
    Learner,
)
from allps.storage.sqlite_store import SQLiteStore


class EvidenceService:
    """Service layer for evidence operations.

    Handles validation, learner auto-registration, and audit logging.
    """

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    async def record_evidence(
        self,
        *,
        learner_id: str,
        evidence_type: str | EvidenceType,
        source_system: str,
        ingestion_method: str | IngestionMethod,
        source_type: str,
        source_reference: str,
        academic_year: int,
        term: int,
        content: dict,
        observed_at: str | datetime,
        subject: str | None = None,
    ) -> Evidence:
        """Record a new piece of evidence with provenance.

        Auto-creates the learner if they don't exist yet (Phase 1).
        Logs an audit entry for the tool call.
        Evidence is immutable once recorded.
        """
        # Parse observed_at if string
        if isinstance(observed_at, str):
            obs_dt = datetime.fromisoformat(observed_at)
        else:
            obs_dt = observed_at

        # Ensure timezone-aware
        if obs_dt.tzinfo is None:
            obs_dt = obs_dt.replace(tzinfo=timezone.utc)

        # Parse enums
        ev_type = (
            EvidenceType(evidence_type)
            if isinstance(evidence_type, str)
            else evidence_type
        )
        ing_method = (
            IngestionMethod(ingestion_method)
            if isinstance(ingestion_method, str)
            else ingestion_method
        )

        # Ensure learner exists (auto-create for Phase 1)
        if not await self._store.learner_exists(learner_id):
            learner = Learner(
                learner_id=learner_id,
                display_name=f"Learner {learner_id}",
            )
            await self._store.add_learner(learner)

        # Create evidence record
        evidence = Evidence(
            learner_id=learner_id,
            evidence_type=ev_type,
            source_system=source_system,
            ingestion_method=ing_method,
            source_type=source_type,
            source_reference=source_reference,
            academic_year=academic_year,
            term=term,
            subject=subject,
            content=content,
            observed_at=obs_dt,
        )

        # Store evidence (immutable)
        await self._store.add_evidence(evidence)

        # Audit log
        audit = AuditEntry(
            tool_name="ingest_evidence",
            input_summary={
                "learner_id": learner_id,
                "evidence_type": ev_type.value,
                "source_system": source_system,
                "ingestion_method": ing_method.value,
                "evidence_id": evidence.evidence_id,
            },
            output_reference=evidence.evidence_id,
        )
        await self._store.add_audit_entry(audit)

        return evidence

    ingest_evidence = record_evidence

    async def get_learner_history(
        self,
        learner_id: str,
        *,
        evidence_type: str | None = None,
        academic_year: int | None = None,
        term: int | None = None,
        subject: str | None = None,
    ) -> list[Evidence]:
        """Retrieve chronologically ordered evidence for a learner.

        Results are ordered by academic_year, term, observed_at.
        Logs an audit entry for the tool call.
        """
        records = await self._store.get_evidence_for_learner(
            learner_id,
            evidence_type=evidence_type,
            academic_year=academic_year,
            term=term,
            subject=subject,
        )

        # Audit log
        audit = AuditEntry(
            tool_name="get_learner_history",
            input_summary={
                "learner_id": learner_id,
                "filters": {
                    "evidence_type": evidence_type,
                    "academic_year": academic_year,
                    "term": term,
                    "subject": subject,
                },
            },
            output_reference=f"{len(records)} records returned",
        )
        await self._store.add_audit_entry(audit)

        return records
