"""Tests for peer-ranking and comparative language detection in OutputValidator.

Specifically validates the closure of the 'indirect peer-comparison' gap:
Ensures the deterministic validator rejects both blatant rank declarations
and indirect norm-referencing language (e.g., 'falling behind peers',
'below grade average', 'relative to classmates', 'bottom of the class'),
while allowing legitimate pedagogical collaboration and baseline self-comparisons.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import pytest

from allps.agent.contracts import CandidateHandoverBrief
from allps.agent.validator import OutputValidator
from allps.models.evidence import Evidence, EvidenceType, IngestionMethod


def make_evidence(learner_id: str = "LRN-001", evidence_id: str = "EV-1") -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        learner_id=learner_id,
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Mr. Banda",
        academic_year=2026,
        term=1,
        subject="Mathematics",
        content={"score": 82.0, "max_score": 100.0},
        observed_at=datetime(2026, 3, 15, tzinfo=timezone.utc),
    )


class TestPeerComparisonValidatorGap:
    """Test suite verifying robust detection of indirect peer comparisons."""

    @pytest.fixture
    def validator(self) -> OutputValidator:
        return OutputValidator()

    @pytest.fixture
    def base_evidence(self) -> list[Evidence]:
        return [make_evidence("LRN-001", "EV-1")]

    def _make_payload(self, text: str, learner_id: str = "LRN-001") -> str:
        return json.dumps({
            "learner_id": learner_id,
            "status": "completed",
            "summary": text,
            "findings": [
                {
                    "observation": "Mathematics score was 82 in Term 1.",
                    "supporting_evidence_ids": ["EV-1"],
                    "co_occurring_factors": [],
                    "teacher_inquiries": []
                }
            ],
            "contradictions": [],
            "limitations": []
        })

    # 1. Direct Peer Ranking Rejections
    @pytest.mark.parametrize("phrase", [
        "Learner is ranked bottom 10% in mathematics.",
        "Student is ranked top 5% across Grade 3.",
        "Learner is ranked 1st in the class.",
        "Ranked last among exam participants.",
        "Learner was categorized in bottom 20% on term assessments.",
    ])
    def test_direct_peer_ranking_rejected(self, validator, base_evidence, phrase):
        payload = self._make_payload(phrase)
        result = validator.validate(payload, base_evidence, expected_learner_id="LRN-001")
        assert result.is_valid is False
        assert any("Peer-ranking language detected" in err for err in result.errors)

    # 2. Indirect Peer Comparison Rejections (Gap Closure)
    @pytest.mark.parametrize("indirect_phrase", [
        "Learner is falling behind peers in arithmetic skills.",
        "Observations suggest student is trailing behind classmates.",
        "Mathematics test performance is below grade average.",
        "Scored above class average on the mid-term test.",
        "Observed performance is at the bottom of the class.",
        "Learner is in the bottom of the cohort in engagement.",
        "Relative to classmates, the learner shows reduced homework return.",
        "Relative to their peers, attendance is lower.",
        "In comparison with other students, student speaks less in group tasks.",
        "In comparison to classmates, test scores dropped.",
        "Student is lagging behind peers in multi-digit multiplication.",
        "Learner is ahead of peers in reading comprehension.",
        "Student was underperforming classmates in lab demonstrations.",
        "Classified in the bottom quartile of the grade.",
        "Norm-referenced indicators show slower pace.",
    ])
    def test_indirect_peer_comparison_rejected(self, validator, base_evidence, indirect_phrase):
        payload = self._make_payload(indirect_phrase)
        result = validator.validate(payload, base_evidence, expected_learner_id="LRN-001")
        assert result.is_valid is False
        assert any("Peer-ranking language detected" in err for err in result.errors), (
            f"Expected indirect peer comparison rejection for '{indirect_phrase}', got errors: {result.errors}"
        )

    # 3. Legitimate Pedagogical Contexts (False Positive Prevention)
    @pytest.mark.parametrize("legitimate_phrase", [
        "Student actively benefited from peer collaboration during science inquiry.",
        "Teacher recommended structured peer study support for fraction practice.",
        "Participated effectively in peer tutoring sessions.",
        "Demonstrated improvement relative to Term 1 baseline.",
        "Score changed by -16% relative to personal baseline.",
        "Attended 48 out of 50 total school days in Grade 3.",
        "Curriculum objectives aligned with Grade 3 mathematics standards.",
    ])
    def test_legitimate_pedagogical_language_allowed(self, validator, base_evidence, legitimate_phrase):
        payload = self._make_payload(legitimate_phrase)
        result = validator.validate(payload, base_evidence, expected_learner_id="LRN-001")
        # Should NOT fail for peer ranking
        peer_ranking_errors = [err for err in result.errors if "Peer-ranking" in err]
        assert not peer_ranking_errors, f"False positive peer ranking error on legitimate phrase: {peer_ranking_errors}"
