"""Tests for ALLPS SQLite storage layer."""

import pytest
from datetime import datetime, timezone

from allps.models import (
    AuditEntry,
    Evidence,
    EvidenceType,
    IngestionMethod,
    Learner,
)
from allps.storage.sqlite_store import SQLiteStore


@pytest.mark.asyncio
class TestLearnerStorage:
    async def test_add_and_retrieve_learner(self, store: SQLiteStore):
        learner = Learner(
            learner_id="LRN-001", display_name="Test Learner"
        )
        await store.add_learner(learner)

        retrieved = await store.get_learner("LRN-001")
        assert retrieved is not None
        assert retrieved.learner_id == "LRN-001"
        assert retrieved.display_name == "Test Learner"

    async def test_get_nonexistent_learner(self, store: SQLiteStore):
        result = await store.get_learner("DOES-NOT-EXIST")
        assert result is None

    async def test_learner_exists(self, store: SQLiteStore):
        learner = Learner(learner_id="LRN-001", display_name="Test")
        await store.add_learner(learner)

        assert await store.learner_exists("LRN-001") is True
        assert await store.learner_exists("LRN-999") is False


@pytest.mark.asyncio
class TestEvidenceStorage:
    async def _add_learner(
        self, store: SQLiteStore, learner_id: str = "LRN-001"
    ):
        await store.add_learner(
            Learner(learner_id=learner_id, display_name="Test")
        )

    def _make_evidence(self, **overrides) -> Evidence:
        defaults = {
            "learner_id": "LRN-001",
            "evidence_type": EvidenceType.ASSESSMENT,
            "source_system": "school_sis",
            "ingestion_method": IngestionMethod.API,
            "source_type": "teacher",
            "source_reference": "Mr. Test",
            "academic_year": 2025,
            "term": 1,
            "content": {"score": 80, "max_score": 100},
            "observed_at": datetime(2025, 3, 15, tzinfo=timezone.utc),
        }
        defaults.update(overrides)
        return Evidence(**defaults)

    async def test_add_and_retrieve_evidence(self, store: SQLiteStore):
        await self._add_learner(store)
        evidence = self._make_evidence()
        await store.add_evidence(evidence)

        results = await store.get_evidence_for_learner("LRN-001")
        assert len(results) == 1
        assert results[0].evidence_id == evidence.evidence_id
        assert results[0].content == {"score": 80, "max_score": 100}

    async def test_evidence_chronological_order(self, store: SQLiteStore):
        await self._add_learner(store)

        # Add in reverse chronological order
        await store.add_evidence(
            self._make_evidence(
                academic_year=2025,
                term=3,
                observed_at=datetime(2025, 9, 15, tzinfo=timezone.utc),
            )
        )
        await store.add_evidence(
            self._make_evidence(
                academic_year=2025,
                term=1,
                observed_at=datetime(2025, 3, 15, tzinfo=timezone.utc),
            )
        )
        await store.add_evidence(
            self._make_evidence(
                academic_year=2025,
                term=2,
                observed_at=datetime(2025, 6, 15, tzinfo=timezone.utc),
            )
        )

        results = await store.get_evidence_for_learner("LRN-001")
        terms = [r.term for r in results]
        assert terms == [1, 2, 3], (
            "Evidence should be chronologically ordered"
        )

    async def test_filter_by_evidence_type(self, store: SQLiteStore):
        await self._add_learner(store)
        await store.add_evidence(
            self._make_evidence(evidence_type=EvidenceType.ASSESSMENT)
        )
        await store.add_evidence(
            self._make_evidence(evidence_type=EvidenceType.ATTENDANCE, content={"status": "present"})
        )

        results = await store.get_evidence_for_learner(
            "LRN-001", evidence_type="assessment"
        )
        assert len(results) == 1
        assert results[0].evidence_type == EvidenceType.ASSESSMENT

    async def test_filter_by_academic_year(self, store: SQLiteStore):
        await self._add_learner(store)
        await store.add_evidence(
            self._make_evidence(
                academic_year=2024,
                observed_at=datetime(2024, 3, 15, tzinfo=timezone.utc),
            )
        )
        await store.add_evidence(
            self._make_evidence(
                academic_year=2025,
                observed_at=datetime(2025, 3, 15, tzinfo=timezone.utc),
            )
        )

        results = await store.get_evidence_for_learner(
            "LRN-001", academic_year=2025
        )
        assert len(results) == 1
        assert results[0].academic_year == 2025

    async def test_filter_by_term(self, store: SQLiteStore):
        await self._add_learner(store)
        await store.add_evidence(self._make_evidence(term=1))
        await store.add_evidence(self._make_evidence(term=2))

        results = await store.get_evidence_for_learner(
            "LRN-001", term=1
        )
        assert len(results) == 1
        assert results[0].term == 1

    async def test_filter_by_subject(self, store: SQLiteStore):
        await self._add_learner(store)
        await store.add_evidence(
            self._make_evidence(subject="Mathematics")
        )
        await store.add_evidence(
            self._make_evidence(subject="Science")
        )

        results = await store.get_evidence_for_learner(
            "LRN-001", subject="Mathematics"
        )
        assert len(results) == 1
        assert results[0].subject == "Mathematics"

    async def test_no_evidence_returns_empty(self, store: SQLiteStore):
        results = await store.get_evidence_for_learner("NONEXISTENT")
        assert results == []

    async def test_evidence_preserves_provenance(self, store: SQLiteStore):
        await self._add_learner(store)
        evidence = self._make_evidence(
            source_type="teacher",
            source_reference="Mrs. Nkosi",
        )
        await store.add_evidence(evidence)

        results = await store.get_evidence_for_learner("LRN-001")
        assert results[0].source_type == "teacher"
        assert results[0].source_reference == "Mrs. Nkosi"

    async def test_evidence_preserves_timestamps(self, store: SQLiteStore):
        await self._add_learner(store)
        obs = datetime(2025, 3, 15, 10, 30, tzinfo=timezone.utc)
        evidence = self._make_evidence(observed_at=obs)
        await store.add_evidence(evidence)

        results = await store.get_evidence_for_learner("LRN-001")
        assert results[0].observed_at == obs
        assert results[0].recorded_at.tzinfo is not None

    async def test_evidence_preserves_source_system_and_ingestion_method(
        self, store: SQLiteStore
    ):
        await self._add_learner(store)
        evidence = self._make_evidence(
            source_system="attendance_system",
            ingestion_method=IngestionMethod.SCHEDULED_SYNC,
        )
        await store.add_evidence(evidence)

        results = await store.get_evidence_for_learner("LRN-001")
        assert results[0].source_system == "attendance_system"
        assert results[0].ingestion_method == IngestionMethod.SCHEDULED_SYNC


@pytest.mark.asyncio
class TestAuditStorage:
    async def test_add_and_retrieve_audit(self, store: SQLiteStore):
        entry = AuditEntry(
            tool_name="ingest_evidence",
            input_summary={"learner_id": "LRN-001"},
            output_reference="ev-123",
        )
        await store.add_audit_entry(entry)

        logs = await store.get_audit_log()
        assert len(logs) == 1
        assert logs[0].tool_name == "ingest_evidence"

    async def test_filter_audit_by_tool(self, store: SQLiteStore):
        await store.add_audit_entry(
            AuditEntry(
                tool_name="ingest_evidence", input_summary={}
            )
        )
        await store.add_audit_entry(
            AuditEntry(
                tool_name="get_learner_history", input_summary={}
            )
        )

        logs = await store.get_audit_log(tool_name="ingest_evidence")
        assert len(logs) == 1
        assert logs[0].tool_name == "ingest_evidence"
