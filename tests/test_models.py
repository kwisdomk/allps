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

    def test_reject_conflicting_comparison_authorized_aliases(self):
        """Conflicting comparison-authorization aliases must be rejected; explicit false never overridden by true."""
        # Conflicting aliases: comparison_authorized=True, comparable=False
        with pytest.raises(ValueError, match="Conflicting comparison-authorization aliases"):
            self._make_evidence(
                content={
                    "score": 15,
                    "max_score": 20,
                    "comparison_authorized": True,
                    "comparable": False,
                }
            )

        # Conflicting aliases: comparison_authorized=False, is_comparable=True
        with pytest.raises(ValueError, match="Conflicting comparison-authorization aliases"):
            self._make_evidence(
                content={
                    "score": 15,
                    "max_score": 20,
                    "comparison_authorized": False,
                    "is_comparable": True,
                }
            )

        # Non-conflicting false alias must result in comparison_authorized=False
        e_false = self._make_evidence(
            content={
                "score": 15,
                "max_score": 20,
                "comparison_authorized": False,
            }
        )
        assert e_false.comparison_authorized is False

    def test_reject_booleans_and_non_numerics_in_marks_and_fluency(self):
        """Booleans and non-numeric values must be rejected in marks and fluency fields."""
        # Booleans in marks
        with pytest.raises(ValueError, match="'score' must be a numeric value, not boolean or non-numeric"):
            self._make_evidence(content={"score": True, "max_score": 20})

        with pytest.raises(ValueError, match="'max_score' must be a numeric value, not boolean or non-numeric"):
            self._make_evidence(content={"score": 15, "max_score": False})

        # Non-numeric in marks
        with pytest.raises(ValueError, match="'score' must be a numeric value"):
            self._make_evidence(content={"score": "15", "max_score": 20})

        # Booleans in fluency
        with pytest.raises(ValueError, match="Fluency 'value' must be a numeric value, not boolean or non-numeric"):
            self._make_evidence(content={"value": True, "unit": "cwpm"})

        # Non-numeric in fluency
        with pytest.raises(ValueError, match="Fluency 'value' must be a numeric value"):
            self._make_evidence(content={"value": "fast", "unit": "cwpm"})

        # Valid fluency
        e_fluency = self._make_evidence(content={"value": 45.5, "unit": "cwpm"})
        assert e_fluency.is_fluency is True

    def test_treat_null_outcome_fields_as_absent(self):
        """Treat null outcome fields as absent when checking contradictions."""
        # Missing assessment status with explicit null score/level/value fields must not raise contradiction
        e_missing = self._make_evidence(
            content={
                "status": "absent",
                "reason": "Illness verified by parent",
                "score": None,
                "max_score": None,
                "level": None,
                "value": None,
            }
        )
        assert e_missing.is_missing_outcome is True
        assert e_missing.content["score"] is None

        # Result unavailable with null level
        e_unavail = self._make_evidence(
            content={
                "status": "result_unavailable",
                "reason": "Exam script misplaced",
                "level": None,
            }
        )
        assert e_unavail.is_missing_outcome is True

    def test_rubric_scale_validation_targeted(self):
        """Use complete rubric scale definition consistently in validation."""
        # Unrecognized scale identifier
        with pytest.raises(ValueError, match="Unrecognized rubric scale identifier"):
            self._make_evidence(
                content={
                    "rubric": "Reading",
                    "rubric_version": "v1.0",
                    "scale": "unknown_scale_v99",
                    "level": "Level 1",
                }
            )

        # Invalid level against valid registered scale
        with pytest.raises(ValueError, match="is invalid against defined scale"):
            self._make_evidence(
                content={
                    "rubric": "Reading",
                    "rubric_version": "v1.0",
                    "scale": "cbc_4_level_v1",
                    "level": "Invalid Tier",
                }
            )

        # Valid registered scale
        e_rubric = self._make_evidence(
            content={
                "rubric": "Reading",
                "rubric_version": "v1.0",
                "scale": "cbc_4_level_v1",
                "level": "Meeting Expectation",
            }
        )
        assert e_rubric.is_rubric is True


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
            kwargs = {"pattern_id": "pat-001", "status": status}
            if status in (ReviewStatus.ACCEPTED, ReviewStatus.REJECTED, ReviewStatus.NEEDS_CONTEXT):
                kwargs["reviewer_id"] = "teacher:mrs_ngcobo"
            if status == ReviewStatus.ACCEPTED:
                kwargs["approved_content_hash"] = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            r = ReviewItem(**kwargs)
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
