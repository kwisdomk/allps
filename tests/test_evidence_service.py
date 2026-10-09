"""Tests for ALLPS evidence service."""

import pytest

from allps.models import EvidenceType, IngestionMethod
from allps.services.evidence_service import EvidenceService


@pytest.mark.asyncio
class TestRecordEvidence:
    async def test_record_and_retrieve(self, service: EvidenceService):
        evidence = await service.record_evidence(
            learner_id="LRN-001",
            evidence_type="assessment",
            source_system="school_sis",
            ingestion_method="api",
            source_type="teacher",
            source_reference="Mr. Test",
            academic_year=2025,
            term=1,
            content={"score": 75, "max_score": 100},
            observed_at="2025-03-15T00:00:00+00:00",
            subject="Mathematics",
        )

        assert evidence.learner_id == "LRN-001"
        assert evidence.evidence_type == EvidenceType.ASSESSMENT
        assert evidence.source_system == "school_sis"
        assert evidence.ingestion_method == IngestionMethod.API
        assert evidence.content["score"] == 75

    async def test_auto_creates_learner(
        self, service: EvidenceService, store
    ):
        await service.record_evidence(
            learner_id="NEW-LEARNER",
            evidence_type="attendance",
            source_system="attendance_system",
            ingestion_method="scheduled_sync",
            source_type="system",
            source_reference="attendance-system",
            academic_year=2025,
            term=1,
            content={"days_present": 45, "days_total": 50},
            observed_at="2025-03-28T00:00:00+00:00",
        )

        learner = await store.get_learner("NEW-LEARNER")
        assert learner is not None
        assert learner.learner_id == "NEW-LEARNER"

    async def test_creates_audit_entry(
        self, service: EvidenceService, store
    ):
        await service.record_evidence(
            learner_id="LRN-001",
            evidence_type="observation",
            source_system="allps",
            ingestion_method="manual_observation",
            source_type="teacher",
            source_reference="Mrs. Nkosi",
            academic_year=2025,
            term=1,
            content={"note": "Good participation"},
            observed_at="2025-03-20T00:00:00+00:00",
        )

        logs = await store.get_audit_log(tool_name="ingest_evidence")
        assert len(logs) == 1
        assert logs[0].input_summary["learner_id"] == "LRN-001"
        assert logs[0].input_summary["source_system"] == "allps"
        assert logs[0].input_summary["ingestion_method"] == "manual_observation"
        assert logs[0].output_reference is not None

    async def test_invalid_evidence_type_rejected(
        self, service: EvidenceService
    ):
        with pytest.raises(ValueError):
            await service.record_evidence(
                learner_id="LRN-001",
                evidence_type="invalid_type",
                source_system="school_sis",
                ingestion_method="api",
                source_type="teacher",
                source_reference="Mr. Test",
                academic_year=2025,
                term=1,
                content={},
                observed_at="2025-03-15T00:00:00+00:00",
            )

    async def test_invalid_ingestion_method_rejected(
        self, service: EvidenceService
    ):
        with pytest.raises(ValueError):
            await service.record_evidence(
                learner_id="LRN-001",
                evidence_type="assessment",
                source_system="school_sis",
                ingestion_method="invalid_channel",
                source_type="teacher",
                source_reference="Mr. Test",
                academic_year=2025,
                term=1,
                content={"score": 80},
                observed_at="2025-03-15T00:00:00+00:00",
            )

    async def test_evidence_has_provenance(
        self, service: EvidenceService
    ):
        evidence = await service.record_evidence(
            learner_id="LRN-001",
            evidence_type="observation",
            source_system="allps",
            ingestion_method="manual_observation",
            source_type="teacher",
            source_reference="Dr. Mensah",
            academic_year=2025,
            term=2,
            content={"note": "Test note"},
            observed_at="2025-06-15T10:30:00+02:00",
        )

        assert evidence.source_system == "allps"
        assert evidence.ingestion_method == IngestionMethod.MANUAL_OBSERVATION
        assert evidence.source_type == "teacher"
        assert evidence.source_reference == "Dr. Mensah"
        assert evidence.observed_at.tzinfo is not None
        assert evidence.recorded_at.tzinfo is not None


@pytest.mark.asyncio
class TestGetLearnerHistory:
    async def test_returns_chronological_order(
        self, service: EvidenceService
    ):
        # Record in reverse order
        for term_num in [3, 1, 2]:
            await service.record_evidence(
                learner_id="LRN-001",
                evidence_type="assessment",
                source_system="school_sis",
                ingestion_method="api",
                source_type="teacher",
                source_reference="Mr. Test",
                academic_year=2025,
                term=term_num,
                content={"score": term_num * 10},
                observed_at=f"2025-{term_num * 3:02d}-15T00:00:00+00:00",
            )

        history = await service.get_learner_history("LRN-001")
        terms = [e.term for e in history]
        assert terms == [1, 2, 3]

    async def test_filters_work(self, service: EvidenceService):
        await service.record_evidence(
            learner_id="LRN-001",
            evidence_type="assessment",
            source_system="school_sis",
            ingestion_method="api",
            source_type="teacher",
            source_reference="Mr. Test",
            academic_year=2025,
            term=1,
            content={"score": 80},
            observed_at="2025-03-15T00:00:00+00:00",
            subject="Mathematics",
        )
        await service.record_evidence(
            learner_id="LRN-001",
            evidence_type="attendance",
            source_system="attendance_system",
            ingestion_method="scheduled_sync",
            source_type="system",
            source_reference="system",
            academic_year=2025,
            term=1,
            content={"rate": 0.95},
            observed_at="2025-03-28T00:00:00+00:00",
        )

        results = await service.get_learner_history(
            "LRN-001", evidence_type="assessment"
        )
        assert len(results) == 1

    async def test_empty_history(self, service: EvidenceService):
        history = await service.get_learner_history("NONEXISTENT")
        assert history == []

    async def test_creates_audit_entry(
        self, service: EvidenceService, store
    ):
        await service.get_learner_history("LRN-001")

        logs = await store.get_audit_log(
            tool_name="get_learner_history"
        )
        assert len(logs) == 1
