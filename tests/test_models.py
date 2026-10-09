"""Tests for ALLPS domain models."""

import pytest
from datetime import datetime, timezone

from allps.models import (
    AuditEntry,
    Evidence,
    EvidenceType,
    IngestionMethod,
    Learner,
    Pattern,
    PatternType,
    ReviewItem,
    ReviewStatus,
)


class TestLearner:
    def test_create_valid_learner(self):
        learner = Learner(display_name="Test Learner")
        assert learner.display_name == "Test Learner"
        assert learner.learner_id  # auto-generated UUID
        assert learner.created_at.tzinfo is not None

    def test_learner_requires_display_name(self):
        with pytest.raises(Exception):
            Learner(display_name="")

    def test_learner_is_frozen(self):
        learner = Learner(display_name="Test")
        with pytest.raises(Exception):
            learner.display_name = "Changed"


class TestEvidence:
    def _make_evidence(self, **overrides):
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

    def test_create_valid_evidence(self):
        e = self._make_evidence()
        assert e.evidence_type == EvidenceType.ASSESSMENT
        assert e.source_system == "school_sis"
        assert e.ingestion_method == IngestionMethod.API
        assert e.academic_year == 2025
        assert e.term == 1
        assert e.observed_at.tzinfo is not None
        assert e.recorded_at.tzinfo is not None

    def test_evidence_requires_timezone_aware_observed_at(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            self._make_evidence(observed_at=datetime(2025, 3, 15))

    def test_evidence_invalid_type(self):
        with pytest.raises(ValueError):
            self._make_evidence(evidence_type="invalid_type")

    def test_evidence_term_range(self):
        with pytest.raises(Exception):
            self._make_evidence(term=0)
        with pytest.raises(Exception):
            self._make_evidence(term=5)

    def test_evidence_academic_year_range(self):
        with pytest.raises(Exception):
            self._make_evidence(academic_year=1999)

    def test_evidence_is_frozen(self):
        e = self._make_evidence()
        with pytest.raises(Exception):
            e.content = {"changed": True}

    def test_all_evidence_types_valid(self):
        for et in EvidenceType:
            content = {"score": 80, "max_score": 100} if et == EvidenceType.ASSESSMENT else \
                      {"status": "present"} if et == EvidenceType.ATTENDANCE else {"some": "data"}
            e = self._make_evidence(evidence_type=et, content=content)
            assert e.evidence_type == et

    def test_all_ingestion_methods_valid(self):
        for method in IngestionMethod:
            e = self._make_evidence(ingestion_method=method)
            assert e.ingestion_method == method

    def test_invalid_ingestion_method_rejected(self):
        with pytest.raises(ValueError):
            self._make_evidence(ingestion_method="invalid_channel")

    def test_source_system_required(self):
        with pytest.raises(Exception):
            self._make_evidence(source_system="")

    def test_provenance_fields_required(self):
        """source_type and source_reference are required."""
        with pytest.raises(Exception):
            Evidence(
                learner_id="LRN-001",
                evidence_type=EvidenceType.ASSESSMENT,
                source_system="school_sis",
                ingestion_method=IngestionMethod.API,
                source_type="",  # empty not allowed (min_length=1)
                source_reference="Mr. Test",
                academic_year=2025,
                term=1,
                content={"score": 80},
                observed_at=datetime(2025, 3, 15, tzinfo=timezone.utc),
            )
        with pytest.raises(Exception):
            Evidence(
                learner_id="LRN-001",
                evidence_type=EvidenceType.ASSESSMENT,
                source_system="school_sis",
                ingestion_method=IngestionMethod.API,
                source_type="teacher",
                source_reference="",  # empty not allowed
                academic_year=2025,
                term=1,
                content={"score": 80},
                observed_at=datetime(2025, 3, 15, tzinfo=timezone.utc),
            )

    def test_academic_year_is_int(self):
        e = self._make_evidence(academic_year=2025)
        assert isinstance(e.academic_year, int)

    def test_term_is_int(self):
        e = self._make_evidence(term=3)
        assert isinstance(e.term, int)


class TestPattern:
    def test_create_pattern(self):
        p = Pattern(
            learner_id="LRN-001",
            pattern_type=PatternType.TREND,
            summary="Declining maths scores over 3 terms",
            supporting_evidence=["ev-1", "ev-2"],
            limitations=["Only 3 data points"],
        )
        assert p.pattern_type == PatternType.TREND
        assert len(p.supporting_evidence) == 2

    def test_pattern_has_no_review_status(self):
        """review_status belongs on ReviewItem, not Pattern."""
        p = Pattern(
            learner_id="LRN-001",
            pattern_type=PatternType.PERSISTENCE,
            summary="Test",
        )
        assert not hasattr(p, "review_status")

    def test_all_pattern_types_valid(self):
        for pt in PatternType:
            p = Pattern(
                learner_id="LRN-001", pattern_type=pt, summary="Test"
            )
            assert p.pattern_type == pt


class TestReviewItem:
    def test_create_review_item(self):
        r = ReviewItem(pattern_id="pat-001")
        assert r.status == ReviewStatus.PENDING
        assert r.assigned_to is None
        assert r.resolved_at is None

    def test_review_statuses(self):
        for status in ReviewStatus:
            r = ReviewItem(pattern_id="pat-001", status=status)
            assert r.status == status


class TestAuditEntry:
    def test_create_audit_entry(self):
        a = AuditEntry(
            tool_name="ingest_evidence",
            input_summary={"learner_id": "LRN-001"},
            output_reference="ev-123",
        )
        assert a.tool_name == "ingest_evidence"
        assert a.timestamp.tzinfo is not None
