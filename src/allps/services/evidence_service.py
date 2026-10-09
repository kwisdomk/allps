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
        self._after_insert_hook = None
        self._force_audit_fail = False

    @staticmethod
    def _find_observation_difference(e1: Evidence, e2: Evidence) -> str | None:
        """Find the differing field between validated observations, or None if identical."""
        from allps.models.evidence import _deep_unfreeze
        if e1.learner_id != e2.learner_id:
            return "learner"
        if e1.academic_year != e2.academic_year:
            return "year"
        if e1.term != e2.term:
            return "term"
        if e1.subject != e2.subject:
            return "subject"
        if e1.observed_at != e2.observed_at:
            return "timestamp"
        if e1.evidence_type != e2.evidence_type:
            return "type"
        if (
            e1.source_system != e2.source_system
            or e1.ingestion_method != e2.ingestion_method
            or e1.source_type != e2.source_type
            or e1.source_reference != e2.source_reference
        ):
            return "provenance"
        if _deep_unfreeze(e1.content) != _deep_unfreeze(e2.content):
            return "content"
        return None

    @classmethod
    def _observations_equal(cls, e1: Evidence, e2: Evidence) -> bool:
        """Compare the validated, normalized observation."""
        return cls._find_observation_difference(e1, e2) is None

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
        source_event_id: str | None = None,
        subject: str | None = None,
    ) -> Evidence:
        """Record a new piece of evidence with provenance.

        Auto-creates the learner if they don't exist yet (Phase 1).
        Logs an audit entry for the tool call.
        Evidence is immutable once recorded.
        """
        try:
            # Parse observed_at if string
            if isinstance(observed_at, str):
                obs_dt = datetime.fromisoformat(observed_at)
            else:
                obs_dt = observed_at

            # Reject timezone-free
            if obs_dt.tzinfo is None:
                raise ValueError("Datetime must be timezone-aware")
            obs_dt = obs_dt.astimezone(timezone.utc)

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

            # Create evidence record (validates content, time, types)
            evidence = Evidence(
                learner_id=learner_id,
                evidence_type=ev_type,
                source_system=source_system,
                ingestion_method=ing_method,
                source_event_id=source_event_id,
                source_type=source_type,
                source_reference=source_reference,
                academic_year=academic_year,
                term=term,
                subject=subject,
                content=content,
                observed_at=obs_dt,
            )

            # Full-observation idempotency check
            if source_event_id:
                existing = await self._store.get_evidence_by_source_event(source_system, source_event_id)
                if existing:
                    diff_field = self._find_observation_difference(existing, evidence)
                    if diff_field is None:
                        retry_audit = AuditEntry(
                            tool_name="ingest_evidence",
                            input_summary={
                                "learner_id": existing.learner_id,
                                "evidence_type": existing.evidence_type.value,
                                "source_system": existing.source_system,
                                "ingestion_method": existing.ingestion_method.value,
                                "source_event_id": existing.source_event_id,
                                "evidence_id": existing.evidence_id,
                                "retry": True,
                            },
                            output_reference=existing.evidence_id,
                        )
                        await self._store.add_audit_entry(retry_audit)
                        return existing
                    else:
                        raise ValueError(f"Conflict: event {source_event_id} already exists with different {diff_field}")


            audit = AuditEntry(
                tool_name="ingest_evidence",
                input_summary={
                    "learner_id": learner_id,
                    "evidence_type": ev_type.value,
                    "source_system": source_system,
                    "ingestion_method": ing_method.value,
                    "source_event_id": source_event_id,
                    "evidence_id": evidence.evidence_id,
                },
                output_reference=evidence.evidence_id,
            )

            # Transaction ownership: isolated dedicated connection
            async with self._store.transaction() as conn:
                # Ensure learner exists (auto-create for Phase 1)
                if not await self._store.learner_exists(learner_id, conn=conn):
                    learner = Learner(
                        learner_id=learner_id,
                        display_name=f"Learner {learner_id}",
                    )
                    await self._store.add_learner(learner, commit=False, conn=conn)

                # Store evidence (immutable)
                await self._store.add_evidence(evidence, commit=False, conn=conn)

                # Test pause hook
                if getattr(self, "_after_insert_hook", None):
                    await self._after_insert_hook()

                # Test force failure hook
                if getattr(self, "_force_audit_fail", False):
                    raise RuntimeError("Forced audit failure")

                # Audit log in same transaction
                await self._store.add_audit_entry(audit, commit=False, conn=conn)

        except Exception as e:
            try:
                failure_audit = AuditEntry(
                    tool_name="ingest_evidence",
                    input_summary={
                        "learner_id": learner_id,
                        "source_system": source_system,
                        "source_event_id": source_event_id,
                    },
                    output_reference=f"Failed: {str(e)}",
                )
                await self._store.add_audit_entry(failure_audit)
            except Exception as audit_err:
                import logging
                logging.getLogger(__name__).error("Failed to record failure audit entry: %s", audit_err)
            raise

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
        try:
            await self._store.add_audit_entry(audit)
        except Exception as audit_err:
            import logging
            logging.getLogger(__name__).error("Failed to record history audit: %s", audit_err)
            raise

        return records

