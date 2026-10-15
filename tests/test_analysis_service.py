"""Tests for AnalysisService longitudinal comparisons and regressions.

Verifies:
1. Same-term 8/10, 15/20, 60/100 does NOT produce an increasing across-term trend or a 52-point gain.
2. Compatible three-term 9/20, 12/20, 15/20 shows improvement.
3. 12/20, 17/20, 11/20 remains variable across terms without monotonic trajectory.
4. Missing results stay null; zero stays zero.
5. Separate subjects, grades, forms and rubric versions remain separate.
6. Rubric progression tracks ordinal advancement across terms.
7. Legacy insufficiently described records are safely excluded from numerical comparisons.
8. Records with missing comparison metadata are excluded; no invented "standard" defaults.
9. Compatibility checks enforce form identity AND version, measured skill, and explicit comparison authorization.
10. Trajectories distinguish unchanged, improving, declining, and fluctuating marks.
11. Rubrics evaluate versioned scale without blindly announcing progression on 3 periods.
12. Rubric levels are validated against defined scale; invalid levels rejected.
13. Contradictory missing/recorded outcomes and non-finite numbers rejected.
14. Assessment stage is kept distinct from school level; stage field is reconciled.
15. "result_unavailable" is preserved as distinct from "assessment_not_administered".
"""

from datetime import datetime, timezone
import math
import pytest
import pytest_asyncio

from allps.models import (
    AssessmentMissingStatus,
    AssessmentStage,
    Evidence,
    EvidenceType,
    IngestionMethod,
    Learner,
    PatternType,
    SchoolLevel,
)
from allps.services.analysis_service import AnalysisService
from allps.services.evidence_service import EvidenceService
from allps.storage.sqlite_store import SQLiteStore


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def store(tmp_path):
    db_file = tmp_path / "test_analysis.db"
    s = SQLiteStore(str(db_file))
    await s.initialize()
    yield s
    await s.close()


@pytest_asyncio.fixture
async def evidence_service(store):
    return EvidenceService(store)


@pytest_asyncio.fixture
async def analysis_service(evidence_service):
    return AnalysisService(evidence_service)


# ── Regression 1: Same-term 8/10, 15/20, 60/100 ─────────────────────


@pytest.mark.asyncio
async def test_same_term_different_scales_no_trend_no_gain(
    evidence_service, analysis_service
):
    """Same-term 8/10, 15/20, 60/100 must not produce an increasing across-term trend or a 52-point gain."""
    learner_id = "LRN-SAME-TERM"

    await evidence_service.record_evidence(
        learner_id=learner_id,
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Mr. Test",
        academic_year=2025,
        term=1,
        subject="Mathematics",
        content={"grade": "Grade 2", "score": 8, "max_score": 10, "assessment_event": "Quiz 1"},
        observed_at=_dt(2025, 2, 10),
        source_event_id="EV-ST-1",
    )
    await evidence_service.record_evidence(
        learner_id=learner_id,
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Mr. Test",
        academic_year=2025,
        term=1,
        subject="Mathematics",
        content={"grade": "Grade 2", "score": 15, "max_score": 20, "assessment_event": "CAT 1"},
        observed_at=_dt(2025, 3, 1),
        source_event_id="EV-ST-2",
    )
    await evidence_service.record_evidence(
        learner_id=learner_id,
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Mr. Test",
        academic_year=2025,
        term=1,
        subject="Mathematics",
        content={"grade": "Grade 2", "score": 60, "max_score": 100, "assessment_event": "Exam 1"},
        observed_at=_dt(2025, 3, 25),
        source_event_id="EV-ST-3",
    )

    patterns = await analysis_service.analyse_longitudinal_pattern(learner_id)

    # Must NOT produce an increasing across-term trend
    for pat in patterns:
        if pat["pattern_type"] == PatternType.TREND.value:
            assert "Improving" not in pat["summary"]
            assert "Increasing" not in pat["summary"]

    # Must NOT produce a 52-point gain
    baseline_changes = [
        p for p in patterns if p["pattern_type"] == PatternType.CHANGED_FROM_BASELINE.value
    ]
    assert len(baseline_changes) == 0, f"Expected 0 baseline changes, got: {baseline_changes}"

    # Must produce insufficient evidence
    insufficient = [
        p for p in patterns if p["pattern_type"] == PatternType.INSUFFICIENT_EVIDENCE.value
    ]
    assert len(insufficient) == 1
    limitations = insufficient[0]["limitations"]
    assert any("same academic term" in lim for lim in limitations)


# ── Regression 2: Compatible three-term 9/20, 12/20, 15/20 ──────────


@pytest.mark.asyncio
async def test_compatible_three_term_shows_improvement(
    evidence_service, analysis_service
):
    """Compatible three-term 9/20, 12/20, 15/20 shows improvement."""
    learner_id = "LRN-IMPROVING"

    scores = [9, 12, 15]
    for term_idx, score_val in enumerate(scores, start=1):
        await evidence_service.record_evidence(
            learner_id=learner_id,
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Mr. Banda",
            academic_year=2025,
            term=term_idx,
            subject="Mathematics",
            content={
                "grade": "Grade 2",
                "score": score_val,
                "max_score": 20,
                "form": "Form A",
                "form_version": "v1.0",
                "language": "English",
                "measured_skill": "addition",
                "comparison_authorized": True,
                "assessment_event": f"Term {term_idx} Standard Test",
            },
            observed_at=_dt(2025, term_idx * 3, 15),
            source_event_id=f"EV-IMP-{term_idx}",
        )

    patterns = await analysis_service.analyse_longitudinal_pattern(learner_id)

    trend_patterns = [
        p for p in patterns if p["pattern_type"] == PatternType.TREND.value
    ]
    assert len(trend_patterns) == 1
    assert "Improving" in trend_patterns[0]["summary"]
    assert "9/20 -> 12/20 -> 15/20" in trend_patterns[0]["summary"]
    assert len(trend_patterns[0]["supporting_evidence"]) == 3

    baseline_patterns = [
        p for p in patterns if p["pattern_type"] == PatternType.CHANGED_FROM_BASELINE.value
    ]
    assert len(baseline_patterns) == 1
    assert "Gain of 6 marks" in baseline_patterns[0]["summary"]


# ── Regression 3: 12/20, 17/20, 11/20 remains variable ──────────────


@pytest.mark.asyncio
async def test_three_term_fluctuating_remains_variable(
    evidence_service, analysis_service
):
    """12/20, 17/20, 11/20 remains variable across terms."""
    learner_id = "LRN-VARIABLE"

    scores = [12, 17, 11]
    for term_idx, score_val in enumerate(scores, start=1):
        await evidence_service.record_evidence(
            learner_id=learner_id,
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Mr. Banda",
            academic_year=2025,
            term=term_idx,
            subject="Mathematics",
            content={
                "grade": "Grade 2",
                "score": score_val,
                "max_score": 20,
                "form": "Form A",
                "form_version": "v1.0",
                "language": "English",
                "measured_skill": "addition",
                "comparison_authorized": True,
            },
            observed_at=_dt(2025, term_idx * 3, 15),
            source_event_id=f"EV-VAR-{term_idx}",
        )

    patterns = await analysis_service.analyse_longitudinal_pattern(learner_id)

    trend_patterns = [
        p for p in patterns if p["pattern_type"] == PatternType.TREND.value
    ]
    assert len(trend_patterns) == 1
    assert "remains variable" in trend_patterns[0]["summary"]
    assert "without monotonic trajectory" in trend_patterns[0]["summary"]
    assert "Improving" not in trend_patterns[0]["summary"]
    assert "Declining" not in trend_patterns[0]["summary"]


# ── Regression 4: Missing results stay null; zero stays zero ────────


@pytest.mark.asyncio
async def test_missing_results_stay_null_zero_stays_zero(
    evidence_service, store, analysis_service
):
    """Missing results stay null; zero stays zero across model, storage, retrieval, and analysis."""
    learner_id = "LRN-NULL-ZERO"

    # Term 1: True zero (score 0 out of 20)
    ev_zero = await evidence_service.record_evidence(
        learner_id=learner_id,
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Mrs. Nkosi",
        academic_year=2025,
        term=1,
        subject="Mathematics",
        content={"grade": "Grade 2", "score": 0, "max_score": 20},
        observed_at=_dt(2025, 3, 10),
        source_event_id="EV-ZERO",
    )
    assert ev_zero.content["score"] == 0
    assert ev_zero.is_marks is True
    assert ev_zero.is_missing_outcome is False

    # Term 2: Missing outcome (absent with explicit reason)
    ev_absent = await evidence_service.record_evidence(
        learner_id=learner_id,
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Mrs. Nkosi",
        academic_year=2025,
        term=2,
        subject="Mathematics",
        content={
            "grade": "Grade 2",
            "status": "absent",
            "reason": "Illness (medical excuse provided)",
            "score": None,
            "max_score": 20,
        },
        observed_at=_dt(2025, 6, 10),
        source_event_id="EV-ABSENT",
    )
    assert ev_absent.content.get("score") is None
    assert ev_absent.is_missing_outcome is True
    assert ev_absent.content["status"] == "absent"

    # Storage round-trip check
    retrieved = await store.get_evidence_for_learner(learner_id)
    assert len(retrieved) == 2
    r_zero = [r for r in retrieved if r.source_event_id == "EV-ZERO"][0]
    r_absent = [r for r in retrieved if r.source_event_id == "EV-ABSENT"][0]

    assert r_zero.content["score"] == 0
    assert r_zero.is_marks is True

    assert r_absent.content["score"] is None
    assert r_absent.content["status"] == "absent"
    assert r_absent.is_missing_outcome is True

    # Analysis check: missing result must be excluded from numeric calculations
    patterns = await analysis_service.analyse_longitudinal_pattern(learner_id)
    assert patterns[0]["pattern_type"] == PatternType.INSUFFICIENT_EVIDENCE.value
    assert any("missing outcomes" in lim and "preserved as null" in lim for lim in patterns[0]["limitations"])


# ── Regression 5: Separate subjects, grades, forms, rubrics ─────────


@pytest.mark.asyncio
async def test_separate_subjects_grades_forms_rubrics_remain_separate(
    evidence_service, analysis_service
):
    """Separate subjects, grades, forms and rubric versions must remain separate."""
    learner_id = "LRN-SEPARATION"

    # 1. Term 1: Mathematics Grade 1 Form A
    await evidence_service.record_evidence(
        learner_id=learner_id,
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2024,
        term=1,
        subject="Mathematics",
        content={
            "grade": "Grade 1",
            "score": 10,
            "max_score": 20,
            "form": "Form A",
            "form_version": "v1.0",
            "language": "English",
            "measured_skill": "addition",
            "comparison_authorized": True,
        },
        observed_at=_dt(2024, 3, 10),
        source_event_id="EV-SEP-1",
    )

    # 2. Term 2: English Grade 1 Form A -> Different subject!
    await evidence_service.record_evidence(
        learner_id=learner_id,
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2024,
        term=2,
        subject="English",
        content={
            "grade": "Grade 1",
            "score": 12,
            "max_score": 20,
            "form": "Form A",
            "form_version": "v1.0",
            "language": "English",
            "measured_skill": "reading",
            "comparison_authorized": True,
        },
        observed_at=_dt(2024, 6, 10),
        source_event_id="EV-SEP-2",
    )

    # 3. Term 3: Mathematics Grade 2 Form A -> Different grade!
    await evidence_service.record_evidence(
        learner_id=learner_id,
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher B",
        academic_year=2024,
        term=3,
        subject="Mathematics",
        content={
            "grade": "Grade 2",
            "score": 15,
            "max_score": 20,
            "form": "Form A",
            "form_version": "v1.0",
            "language": "English",
            "measured_skill": "addition",
            "comparison_authorized": True,
        },
        observed_at=_dt(2024, 9, 10),
        source_event_id="EV-SEP-3",
    )

    # 4. Term 3: Mathematics Grade 1 Form B -> Different form!
    await evidence_service.record_evidence(
        learner_id=learner_id,
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher B",
        academic_year=2024,
        term=3,
        subject="Mathematics",
        content={
            "grade": "Grade 1",
            "score": 18,
            "max_score": 20,
            "form": "Form B",
            "form_version": "v1.0",
            "language": "English",
            "measured_skill": "addition",
            "comparison_authorized": True,
        },
        observed_at=_dt(2024, 9, 15),
        source_event_id="EV-SEP-4",
    )

    patterns = await analysis_service.analyse_longitudinal_pattern(learner_id)

    # No series has >= 3 distinct terms in the same (grade, subject, form, scale)
    trend_patterns = [
        p for p in patterns if p["pattern_type"] == PatternType.TREND.value
    ]
    assert len(trend_patterns) == 0, f"Expected 0 trends across disparate series, got: {trend_patterns}"
    assert patterns[0]["pattern_type"] == PatternType.INSUFFICIENT_EVIDENCE.value


# ── Regression 6: Rubric Progression across terms ───────────────────


@pytest.mark.asyncio
async def test_rubric_progression_across_three_terms(
    evidence_service, analysis_service
):
    """Rubrics track advancing progression across terms without conversion to percentages."""
    learner_id = "LRN-RUBRIC"

    terms_and_levels = [(1, "Approaching Expectation"), (2, "Meeting Expectation"), (3, "Exceeding Expectation")]
    for term_idx, level_name in terms_and_levels:
        await evidence_service.record_evidence(
            learner_id=learner_id,
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Mrs. Achebe",
            academic_year=2025,
            term=term_idx,
            subject="English",
            content={
                "grade": "Grade 2",
                "form": "Oral Form A",
                "form_version": "v1.0",
                "language": "English",
                "measured_skill": "reading_fluency",
                "comparison_authorized": True,
                "rubric": "Early Literacy Fluency",
                "rubric_version": "v1.0",
                "scale": ["Below Expectation", "Approaching Expectation", "Meeting Expectation", "Exceeding Expectation"],
                "level": level_name,
            },
            observed_at=_dt(2025, term_idx * 3, 20),
            source_event_id=f"EV-RUB-{term_idx}",
        )

    patterns = await analysis_service.analyse_longitudinal_pattern(learner_id)
    assert len(patterns) == 1
    assert patterns[0]["pattern_type"] == PatternType.TREND.value
    assert "Advancing rubric progression" in patterns[0]["summary"]
    assert "Early Literacy Fluency" in patterns[0]["summary"]
    assert any("ordinal descriptors and have not been converted to percentage" in lim for lim in patterns[0]["limitations"])


# ── Regression 7: Insufficiently described legacy records excluded ──


@pytest.mark.asyncio
async def test_insufficiently_described_records_excluded_from_numerical_comparison(
    evidence_service, analysis_service
):
    """Legacy records without grade or subject are excluded from numerical comparisons."""
    learner_id = "LRN-LEGACY-INSUFFICIENT"

    for term_idx in range(1, 4):
        await evidence_service.record_evidence(
            learner_id=learner_id,
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Mr. Test",
            academic_year=2025,
            term=term_idx,
            subject="Mathematics",
            content={"score": 10 + term_idx, "max_score": 20},  # No grade specified!
            observed_at=_dt(2025, term_idx * 3, 10),
            source_event_id=f"EV-LEG-{term_idx}",
        )

    patterns = await analysis_service.analyse_longitudinal_pattern(learner_id)
    assert patterns[0]["pattern_type"] == PatternType.INSUFFICIENT_EVIDENCE.value
    assert any("excluded from numerical comparison" in lim for lim in patterns[0]["limitations"])


# ── Regression 8: Missing comparison metadata excluded; no invented defaults ──


@pytest.mark.asyncio
async def test_missing_comparison_metadata_excluded_no_invented_standard_defaults(
    evidence_service, analysis_service
):
    """Exclude records with missing comparison metadata; remove invented 'standard' form/language defaults."""
    learner_id = "LRN-NO-DEFAULTS"

    # Term 1: missing form
    await evidence_service.record_evidence(
        learner_id=learner_id,
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=1,
        subject="Mathematics",
        content={
            "grade": "Grade 2",
            "score": 12,
            "max_score": 20,
            "language": "English",
            "measured_skill": "addition",
            "comparison_authorized": True,
        },
        observed_at=_dt(2025, 3, 1),
        source_event_id="EV-DEF-1",
    )

    # Term 2: missing language
    await evidence_service.record_evidence(
        learner_id=learner_id,
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=2,
        subject="Mathematics",
        content={
            "grade": "Grade 2",
            "score": 14,
            "max_score": 20,
            "form": "Form A",
            "form_version": "v1.0",
            "measured_skill": "addition",
            "comparison_authorized": True,
        },
        observed_at=_dt(2025, 6, 1),
        source_event_id="EV-DEF-2",
    )

    # Term 3: missing measured_skill
    await evidence_service.record_evidence(
        learner_id=learner_id,
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=3,
        subject="Mathematics",
        content={
            "grade": "Grade 2",
            "score": 16,
            "max_score": 20,
            "form": "Form A",
            "form_version": "v1.0",
            "language": "English",
            "comparison_authorized": True,
        },
        observed_at=_dt(2025, 9, 1),
        source_event_id="EV-DEF-3",
    )

    patterns = await analysis_service.analyse_longitudinal_pattern(learner_id)

    # No series should be created using invented "standard" form or language
    trend_patterns = [p for p in patterns if p["pattern_type"] == PatternType.TREND.value]
    assert len(trend_patterns) == 0, f"Expected no trend due to missing metadata, got: {trend_patterns}"

    assert patterns[0]["pattern_type"] == PatternType.INSUFFICIENT_EVIDENCE.value
    assert any("missing comparison metadata" in lim for lim in patterns[0]["limitations"])


# ── Regression 9: Form version, measured skill, and authorization barrier ──


@pytest.mark.asyncio
async def test_form_version_skill_and_authorization_barrier(
    evidence_service, analysis_service
):
    """Include form identity AND version, measured skill, and explicit comparison authorization in compatibility checks."""
    # Subtest A: comparison_authorized is False or missing
    learner_unauth = "LRN-UNAUTH"
    for t_idx in (1, 2, 3):
        await evidence_service.record_evidence(
            learner_id=learner_unauth,
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=t_idx,
            subject="Mathematics",
            content={
                "grade": "Grade 2",
                "score": 10 + t_idx,
                "max_score": 20,
                "form": "Form A",
                "form_version": "v1.0",
                "language": "English",
                "measured_skill": "addition",
                "comparison_authorized": False,  # Unauthorized!
            },
            observed_at=_dt(2025, t_idx * 3, 1),
            source_event_id=f"EV-UNAUTH-{t_idx}",
        )

    patterns_unauth = await analysis_service.analyse_longitudinal_pattern(learner_unauth)
    assert patterns_unauth[0]["pattern_type"] == PatternType.INSUFFICIENT_EVIDENCE.value
    assert any("comparison authorization" in lim for lim in patterns_unauth[0]["limitations"])

    # Subtest B: Differing form versions across terms (v1.0, v2.0, v3.0)
    learner_ver = "LRN-DIFF-VER"
    vers = ["v1.0", "v2.0", "v3.0"]
    for t_idx, ver_val in enumerate(vers, start=1):
        await evidence_service.record_evidence(
            learner_id=learner_ver,
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=t_idx,
            subject="Mathematics",
            content={
                "grade": "Grade 2",
                "score": 10 + t_idx,
                "max_score": 20,
                "form": "Form A",
                "form_version": ver_val,
                "language": "English",
                "measured_skill": "addition",
                "comparison_authorized": True,
            },
            observed_at=_dt(2025, t_idx * 3, 1),
            source_event_id=f"EV-VER-{t_idx}",
        )

    patterns_ver = await analysis_service.analyse_longitudinal_pattern(learner_ver)
    trend_ver = [p for p in patterns_ver if p["pattern_type"] == PatternType.TREND.value]
    assert len(trend_ver) == 0
    assert patterns_ver[0]["pattern_type"] == PatternType.INSUFFICIENT_EVIDENCE.value

    # Subtest C: Differing measured skills across terms (addition, multiplication, geometry)
    learner_skill = "LRN-DIFF-SKILL"
    skills = ["addition", "multiplication", "geometry"]
    for t_idx, skill_val in enumerate(skills, start=1):
        await evidence_service.record_evidence(
            learner_id=learner_skill,
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=t_idx,
            subject="Mathematics",
            content={
                "grade": "Grade 2",
                "score": 10 + t_idx,
                "max_score": 20,
                "form": "Form A",
                "form_version": "v1.0",
                "language": "English",
                "measured_skill": skill_val,
                "comparison_authorized": True,
            },
            observed_at=_dt(2025, t_idx * 3, 1),
            source_event_id=f"EV-SKILL-{t_idx}",
        )

    patterns_skill = await analysis_service.analyse_longitudinal_pattern(learner_skill)
    trend_skill = [p for p in patterns_skill if p["pattern_type"] == PatternType.TREND.value]
    assert len(trend_skill) == 0
    assert patterns_skill[0]["pattern_type"] == PatternType.INSUFFICIENT_EVIDENCE.value


# ── Regression 10: Distinguish unchanged and declining marks ────────


@pytest.mark.asyncio
async def test_distinguish_unchanged_and_declining_marks_trajectories(
    evidence_service, analysis_service
):
    """Distinguish unchanged, improving, declining, and fluctuating marks."""
    # Unchanged: 15/20, 15/20, 15/20 across 3 terms
    learner_unchanged = "LRN-UNCHANGED"
    for t_idx in (1, 2, 3):
        await evidence_service.record_evidence(
            learner_id=learner_unchanged,
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=t_idx,
            subject="Mathematics",
            content={
                "grade": "Grade 2",
                "score": 15,
                "max_score": 20,
                "form": "Form A",
                "form_version": "v1.0",
                "language": "English",
                "measured_skill": "addition",
                "comparison_authorized": True,
            },
            observed_at=_dt(2025, t_idx * 3, 1),
            source_event_id=f"EV-UNCH-{t_idx}",
        )

    patterns_unc = await analysis_service.analyse_longitudinal_pattern(learner_unchanged)
    trend_unc = [p for p in patterns_unc if p["pattern_type"] == PatternType.TREND.value]
    assert len(trend_unc) == 1
    assert "Unchanged across-term performance" in trend_unc[0]["summary"]
    assert "15/20 -> 15/20 -> 15/20" in trend_unc[0]["summary"]
    assert "remains variable" not in trend_unc[0]["summary"]
    assert "Improving" not in trend_unc[0]["summary"]
    assert "Declining" not in trend_unc[0]["summary"]
    # No baseline change pattern should be reported when delta is 0
    base_unc = [p for p in patterns_unc if p["pattern_type"] == PatternType.CHANGED_FROM_BASELINE.value]
    assert len(base_unc) == 0

    # Declining: 18/20, 14/20, 10/20 across 3 terms
    learner_dec = "LRN-DECLINING"
    scores_dec = [18, 14, 10]
    for t_idx, s_val in enumerate(scores_dec, start=1):
        await evidence_service.record_evidence(
            learner_id=learner_dec,
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=t_idx,
            subject="Mathematics",
            content={
                "grade": "Grade 2",
                "score": s_val,
                "max_score": 20,
                "form": "Form A",
                "form_version": "v1.0",
                "language": "English",
                "measured_skill": "addition",
                "comparison_authorized": True,
            },
            observed_at=_dt(2025, t_idx * 3, 1),
            source_event_id=f"EV-DEC-{t_idx}",
        )

    patterns_dec = await analysis_service.analyse_longitudinal_pattern(learner_dec)
    trend_dec = [p for p in patterns_dec if p["pattern_type"] == PatternType.TREND.value]
    assert len(trend_dec) == 1
    assert "Declining across-term trend" in trend_dec[0]["summary"]
    assert "18/20 -> 14/20 -> 10/20" in trend_dec[0]["summary"]

    base_dec = [p for p in patterns_dec if p["pattern_type"] == PatternType.CHANGED_FROM_BASELINE.value]
    assert len(base_dec) == 1
    assert "Drop of 8 marks" in base_dec[0]["summary"]


# ── Regression 11: Rubrics do not announce progression merely because 3 periods exist ──


@pytest.mark.asyncio
async def test_rubric_unchanged_declining_fluctuating_not_blind_progression(
    evidence_service, analysis_service
):
    """Do not announce rubric progression merely because three periods exist."""
    scale = ["Below Expectation", "Approaching Expectation", "Meeting Expectation", "Exceeding Expectation"]

    # 1. Unchanged Rubric: Meeting -> Meeting -> Meeting
    learner_unc = "LRN-RUB-UNCHANGED"
    for t_idx in (1, 2, 3):
        await evidence_service.record_evidence(
            learner_id=learner_unc,
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=t_idx,
            subject="English",
            content={
                "grade": "Grade 2",
                "form": "Oral Form A",
                "form_version": "v1.0",
                "language": "English",
                "measured_skill": "fluency",
                "comparison_authorized": True,
                "rubric": "Reading Rubric",
                "rubric_version": "v1.0",
                "scale": scale,
                "level": "Meeting Expectation",
            },
            observed_at=_dt(2025, t_idx * 3, 1),
            source_event_id=f"EV-RUNC-{t_idx}",
        )

    patterns_unc = await analysis_service.analyse_longitudinal_pattern(learner_unc)
    assert len(patterns_unc) == 1
    assert patterns_unc[0]["pattern_type"] == PatternType.TREND.value
    assert "Unchanged rubric performance" in patterns_unc[0]["summary"]
    assert "Advancing" not in patterns_unc[0]["summary"]
    assert "Rubric progression" not in patterns_unc[0]["summary"]

    # 2. Declining Rubric: Exceeding -> Meeting -> Approaching
    learner_dec = "LRN-RUB-DECLINE"
    dec_lvls = ["Exceeding Expectation", "Meeting Expectation", "Approaching Expectation"]
    for t_idx, lvl in enumerate(dec_lvls, start=1):
        await evidence_service.record_evidence(
            learner_id=learner_dec,
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=t_idx,
            subject="English",
            content={
                "grade": "Grade 2",
                "form": "Oral Form A",
                "form_version": "v1.0",
                "language": "English",
                "measured_skill": "fluency",
                "comparison_authorized": True,
                "rubric": "Reading Rubric",
                "rubric_version": "v1.0",
                "scale": scale,
                "level": lvl,
            },
            observed_at=_dt(2025, t_idx * 3, 1),
            source_event_id=f"EV-RDEC-{t_idx}",
        )

    patterns_dec = await analysis_service.analyse_longitudinal_pattern(learner_dec)
    assert len(patterns_dec) == 1
    assert patterns_dec[0]["pattern_type"] == PatternType.TREND.value
    assert "Declining rubric trajectory" in patterns_dec[0]["summary"]
    assert "Advancing" not in patterns_dec[0]["summary"]

    # 3. Fluctuating Rubric: Approaching -> Meeting -> Approaching
    learner_fluc = "LRN-RUB-FLUC"
    fluc_lvls = ["Approaching Expectation", "Meeting Expectation", "Approaching Expectation"]
    for t_idx, lvl in enumerate(fluc_lvls, start=1):
        await evidence_service.record_evidence(
            learner_id=learner_fluc,
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=t_idx,
            subject="English",
            content={
                "grade": "Grade 2",
                "form": "Oral Form A",
                "form_version": "v1.0",
                "language": "English",
                "measured_skill": "fluency",
                "comparison_authorized": True,
                "rubric": "Reading Rubric",
                "rubric_version": "v1.0",
                "scale": scale,
                "level": lvl,
            },
            observed_at=_dt(2025, t_idx * 3, 1),
            source_event_id=f"EV-RFLUC-{t_idx}",
        )

    patterns_fluc = await analysis_service.analyse_longitudinal_pattern(learner_fluc)
    assert len(patterns_fluc) == 1
    assert patterns_fluc[0]["pattern_type"] == PatternType.TREND.value
    assert "remains variable" in patterns_fluc[0]["summary"]
    assert "without monotonic trajectory" in patterns_fluc[0]["summary"]


# ── Regression 12: Rubric scale validation against defined, versioned scale ──


@pytest.mark.asyncio
async def test_rubric_scale_validation_against_defined_scale(evidence_service):
    """Validate rubric levels against a defined, versioned scale. Reject invalid levels."""
    # Valid level against custom scale passes
    ev_valid = await evidence_service.record_evidence(
        learner_id="LRN-VAL-RUB",
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=1,
        subject="Art",
        content={
            "grade": "Grade 3",
            "rubric": "Sculpture Rubric",
            "rubric_version": "v1.0",
            "scale": ["Novice", "Intermediate", "Master"],
            "level": "Intermediate",
        },
        observed_at=_dt(2025, 3, 1),
    )
    assert ev_valid.is_rubric is True

    # Invalid level against custom scale is rejected
    with pytest.raises(ValueError, match="is invalid against defined scale"):
        await evidence_service.record_evidence(
            learner_id="LRN-VAL-RUB",
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=1,
            subject="Art",
            content={
                "grade": "Grade 3",
                "rubric": "Sculpture Rubric",
                "rubric_version": "v1.0",
                "scale": ["Novice", "Intermediate", "Master"],
                "level": "Grandmaster",  # Not in scale!
            },
            observed_at=_dt(2025, 3, 1),
        )

    # Unknown level without defined scale is rejected
    with pytest.raises(ValueError, match="cannot be validated against a defined, versioned scale"):
        await evidence_service.record_evidence(
            learner_id="LRN-VAL-RUB",
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=1,
            subject="Art",
            content={
                "grade": "Grade 3",
                "rubric": "Custom Rubric",
                "rubric_version": "v1.0",
                "level": "Random Tier",
            },
            observed_at=_dt(2025, 3, 1),
        )


# ── Regression 13: Reject contradictory outcomes and non-finite numeric fields ──


@pytest.mark.asyncio
async def test_reject_contradictory_outcomes_and_non_finite_numeric_fields(
    evidence_service,
):
    """Reject contradictory missing/recorded outcomes and non-finite numeric fields."""
    learner_id = "LRN-CONTRADICT"

    # 1. Missing status + numeric score -> rejected
    with pytest.raises(ValueError, match="Contradictory outcome: missing assessment status cannot have a numeric score"):
        await evidence_service.record_evidence(
            learner_id=learner_id,
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=1,
            subject="Math",
            content={
                "status": "absent",
                "reason": "Illness",
                "score": 15,
                "max_score": 20,
            },
            observed_at=_dt(2025, 3, 1),
        )

    # 2. Missing status + rubric level -> rejected
    with pytest.raises(ValueError, match="Contradictory outcome: missing assessment status cannot have a rubric level"):
        await evidence_service.record_evidence(
            learner_id=learner_id,
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=1,
            subject="English",
            content={
                "status": "result_unavailable",
                "reason": "Lost exam paper",
                "rubric": "Reading",
                "rubric_version": "v1.0",
                "level": "Meeting Expectation",
            },
            observed_at=_dt(2025, 3, 1),
        )

    # 3. Numeric score + rubric level -> rejected
    with pytest.raises(ValueError, match="Contradictory outcome: cannot contain both numeric marks and rubric level"):
        await evidence_service.record_evidence(
            learner_id=learner_id,
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=1,
            subject="English",
            content={
                "score": 15,
                "max_score": 20,
                "rubric": "Reading",
                "rubric_version": "v1.0",
                "level": "Meeting Expectation",
            },
            observed_at=_dt(2025, 3, 1),
        )

    # 4. Non-finite numbers: inf, -inf, nan -> rejected
    with pytest.raises(ValueError, match="Non-finite numeric value"):
        await evidence_service.record_evidence(
            learner_id=learner_id,
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=1,
            subject="Math",
            content={"score": float("inf"), "max_score": 20},
            observed_at=_dt(2025, 3, 1),
        )

    with pytest.raises(ValueError, match="Non-finite numeric value"):
        await evidence_service.record_evidence(
            learner_id=learner_id,
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=1,
            subject="Math",
            content={"score": 10, "max_score": float("nan")},
            observed_at=_dt(2025, 3, 1),
        )


# ── Regression 14: Stage reconciliation and separation from school level ──


@pytest.mark.asyncio
async def test_stage_reconciliation_and_separation_from_school_level(evidence_service):
    """Keep assessment stage (opener/midterm/end-term) separate from school level."""
    # Assessment with distinct assessment_stage and school_level
    ev1 = await evidence_service.record_evidence(
        learner_id="LRN-STAGE-1",
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=1,
        subject="Math",
        content={
            "grade": "Grade 2",
            "score": 15,
            "max_score": 20,
            "assessment_stage": "end_term",
            "school_level": "lower_primary",
        },
        observed_at=_dt(2025, 3, 25),
    )
    assert ev1.assessment_stage == "end_term"
    assert ev1.school_level == "lower_primary"

    # Preview field stage="opener" reconciles to assessment_stage
    ev2 = await evidence_service.record_evidence(
        learner_id="LRN-STAGE-2",
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=1,
        subject="Math",
        content={
            "grade": "Grade 2",
            "score": 10,
            "max_score": 20,
            "stage": "opener",
        },
        observed_at=_dt(2025, 1, 10),
    )
    assert ev2.assessment_stage == "opener"
    assert ev2.school_level is None

    # Preview field stage="early_years" reconciles to school_level
    ev3 = await evidence_service.record_evidence(
        learner_id="LRN-STAGE-3",
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=1,
        subject="Math",
        content={
            "grade": "Grade 2",
            "score": 12,
            "max_score": 20,
            "stage": "early_years",
        },
        observed_at=_dt(2025, 1, 15),
    )
    assert ev3.school_level == "early_years"
    assert ev3.assessment_stage is None


# ── Regression 15: Distinct missing statuses (result unavailable vs not administered) ──


@pytest.mark.asyncio
async def test_distinct_missing_statuses_result_unavailable_vs_not_administered(
    evidence_service, store
):
    """Preserve 'result unavailable' as distinct from 'assessment not administered'."""
    learner_id = "LRN-DIST-MISSING"

    # 1. Result unavailable (assessment sat for, but lost/corrupted)
    ev_unavail = await evidence_service.record_evidence(
        learner_id=learner_id,
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=1,
        subject="Science",
        content={
            "grade": "Grade 4",
            "status": "result_unavailable",
            "reason": "Test paper damaged by rain during courier transit",
            "max_score": 50,
        },
        observed_at=_dt(2025, 3, 20),
        source_event_id="EV-UNAVAIL-1",
    )
    assert ev_unavail.content["status"] == "result_unavailable"
    assert ev_unavail.is_missing_outcome is True

    # 2. Assessment not administered (event cancelled / school closed)
    ev_not_admin = await evidence_service.record_evidence(
        learner_id=learner_id,
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=2,
        subject="Science",
        content={
            "grade": "Grade 4",
            "status": "assessment_not_administered",
            "reason": "School closed due to national election holiday",
            "max_score": 50,
        },
        observed_at=_dt(2025, 6, 20),
        source_event_id="EV-NOTADMIN-1",
    )
    assert ev_not_admin.content["status"] == "assessment_not_administered"
    assert ev_not_admin.is_missing_outcome is True

    # Verify both stay distinct in SQLite round-trip
    retrieved = await store.get_evidence_for_learner(learner_id)
    assert len(retrieved) == 2
    r_unavail = [r for r in retrieved if r.source_event_id == "EV-UNAVAIL-1"][0]
    r_not_admin = [r for r in retrieved if r.source_event_id == "EV-NOTADMIN-1"][0]

    assert r_unavail.content["status"] == "result_unavailable"
    assert r_unavail.content["reason"] == "Test paper damaged by rain during courier transit"

    assert r_not_admin.content["status"] == "assessment_not_administered"
    assert r_not_admin.content["reason"] == "School closed due to national election holiday"


# ── Regression 16: Different rubric scales must not produce a shared trend ──


@pytest.mark.asyncio
async def test_different_rubric_scales_do_not_produce_shared_trend(
    evidence_service, analysis_service
):
    """Different rubric scales (e.g. 4-level vs 3-level) must not produce a shared trend."""
    learner_id = "LRN-DIFF-SCALES"

    # Term 1: 4-level scale, level: Approaching Expectation
    await evidence_service.record_evidence(
        learner_id=learner_id,
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=1,
        subject="Art",
        content={
            "grade": "Grade 3",
            "form": "Practical",
            "form_version": "v1.0",
            "language": "English",
            "measured_skill": "drawing",
            "comparison_authorized": True,
            "rubric": "Art Rubric",
            "rubric_version": "v1.0",
            "scale": ["Below Expectation", "Approaching Expectation", "Meeting Expectation", "Exceeding Expectation"],
            "level": "Approaching Expectation",
        },
        observed_at=_dt(2025, 3, 1),
    )

    # Term 2: 3-level scale, level: Proficient (differing scale!)
    await evidence_service.record_evidence(
        learner_id=learner_id,
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=2,
        subject="Art",
        content={
            "grade": "Grade 3",
            "form": "Practical",
            "form_version": "v1.0",
            "language": "English",
            "measured_skill": "drawing",
            "comparison_authorized": True,
            "rubric": "Art Rubric",
            "rubric_version": "v1.0",
            "scale": ["Novice", "Proficient", "Master"],
            "level": "Proficient",
        },
        observed_at=_dt(2025, 6, 1),
    )

    # Term 3: 4-level scale, level: Meeting Expectation
    await evidence_service.record_evidence(
        learner_id=learner_id,
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=3,
        subject="Art",
        content={
            "grade": "Grade 3",
            "form": "Practical",
            "form_version": "v1.0",
            "language": "English",
            "measured_skill": "drawing",
            "comparison_authorized": True,
            "rubric": "Art Rubric",
            "rubric_version": "v1.0",
            "scale": ["Below Expectation", "Approaching Expectation", "Meeting Expectation", "Exceeding Expectation"],
            "level": "Meeting Expectation",
        },
        observed_at=_dt(2025, 9, 1),
    )

    patterns = await analysis_service.analyse_longitudinal_pattern(learner_id)
    trend_patterns = [p for p in patterns if p["pattern_type"] == "trend"]
    assert len(trend_patterns) == 0
    assert patterns[0]["pattern_type"] == PatternType.INSUFFICIENT_EVIDENCE.value


# ── Regression 17: Equivalent scales (registered ID vs explicit list) group together ──


@pytest.mark.asyncio
async def test_equivalent_scales_group_together(evidence_service, analysis_service):
    """Equivalent rubric scales with registered identifier and explicit list resolve to same series."""
    learner_id = "LRN-SAME-SCALE"
    terms_and_scales = [
        (1, "cbc_4_level_v1", "Approaching Expectation"),
        (2, ["Below Expectation", "Approaching Expectation", "Meeting Expectation", "Exceeding Expectation"], "Meeting Expectation"),
        (3, "cbc_4_level_v1", "Exceeding Expectation"),
    ]
    for term_idx, scale_val, lvl in terms_and_scales:
        await evidence_service.record_evidence(
            learner_id=learner_id,
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=term_idx,
            subject="English",
            content={
                "grade": "Grade 2",
                "form": "Oral Form A",
                "form_version": "v1.0",
                "language": "English",
                "measured_skill": "fluency",
                "comparison_authorized": True,
                "rubric": "Literacy Rubric",
                "rubric_version": "v1.0",
                "scale": scale_val,
                "level": lvl,
            },
            observed_at=_dt(2025, term_idx * 3, 1),
        )

    patterns = await analysis_service.analyse_longitudinal_pattern(learner_id)
    assert len(patterns) == 1
    assert patterns[0]["pattern_type"] == PatternType.TREND.value
    assert "Advancing rubric progression" in patterns[0]["summary"]


# ── Regression 18: Preserve assessment stage distinctions in analysis ──


@pytest.mark.asyncio
async def test_preserve_assessment_stage_distinctions(evidence_service, analysis_service):
    """Assessment stages (opener, midterm, end_term, cat) must not be silently combined into a shared trend."""
    learner_id = "LRN-STAGES"
    stages = [(1, "opener", 10), (2, "midterm", 14), (3, "end_term", 18)]
    for term_idx, stage_name, score in stages:
        await evidence_service.record_evidence(
            learner_id=learner_id,
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=term_idx,
            subject="Mathematics",
            content={
                "grade": "Grade 2",
                "form": "Math Test",
                "form_version": "v1.0",
                "language": "English",
                "measured_skill": "addition",
                "comparison_authorized": True,
                "assessment_stage": stage_name,
                "score": score,
                "max_score": 20,
            },
            observed_at=_dt(2025, term_idx * 3, 1),
        )

    patterns = await analysis_service.analyse_longitudinal_pattern(learner_id)
    trend_patterns = [p for p in patterns if p["pattern_type"] == "trend"]
    assert len(trend_patterns) == 0
    assert patterns[0]["pattern_type"] == PatternType.INSUFFICIENT_EVIDENCE.value


# ── Regression 19: Ordinal rubric ranks not averaged within period ──


@pytest.mark.asyncio
async def test_ordinal_rubric_ranks_not_averaged_within_period(
    evidence_service, analysis_service
):
    """Multiple rubric assessments in the same period with conflicting ranks are not averaged into fractions."""
    learner_id = "LRN-ORD-NO-AVG"
    # Term 1 has two conflicting evaluations: rank 0 and rank 1
    await evidence_service.record_evidence(
        learner_id=learner_id,
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher 1",
        academic_year=2025,
        term=1,
        subject="Reading",
        content={
            "grade": "Grade 2",
            "form": "Oral",
            "form_version": "v1.0",
            "language": "English",
            "measured_skill": "reading",
            "comparison_authorized": True,
            "rubric": "Reading Rubric",
            "rubric_version": "v1.0",
            "scale": "cbc_4_level_v1",
            "level": "Below Expectation",
        },
        observed_at=_dt(2025, 3, 1),
    )
    await evidence_service.record_evidence(
        learner_id=learner_id,
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher 2",
        academic_year=2025,
        term=1,
        subject="Reading",
        content={
            "grade": "Grade 2",
            "form": "Oral",
            "form_version": "v1.0",
            "language": "English",
            "measured_skill": "reading",
            "comparison_authorized": True,
            "rubric": "Reading Rubric",
            "rubric_version": "v1.0",
            "scale": "cbc_4_level_v1",
            "level": "Approaching Expectation",
        },
        observed_at=_dt(2025, 3, 2),
    )
    # Term 2: Approaching Expectation
    await evidence_service.record_evidence(
        learner_id=learner_id,
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher 1",
        academic_year=2025,
        term=2,
        subject="Reading",
        content={
            "grade": "Grade 2",
            "form": "Oral",
            "form_version": "v1.0",
            "language": "English",
            "measured_skill": "reading",
            "comparison_authorized": True,
            "rubric": "Reading Rubric",
            "rubric_version": "v1.0",
            "scale": "cbc_4_level_v1",
            "level": "Approaching Expectation",
        },
        observed_at=_dt(2025, 6, 1),
    )
    # Term 3: Meeting Expectation
    await evidence_service.record_evidence(
        learner_id=learner_id,
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher 1",
        academic_year=2025,
        term=3,
        subject="Reading",
        content={
            "grade": "Grade 2",
            "form": "Oral",
            "form_version": "v1.0",
            "language": "English",
            "measured_skill": "reading",
            "comparison_authorized": True,
            "rubric": "Reading Rubric",
            "rubric_version": "v1.0",
            "scale": "cbc_4_level_v1",
            "level": "Meeting Expectation",
        },
        observed_at=_dt(2025, 9, 1),
    )

    patterns = await analysis_service.analyse_longitudinal_pattern(learner_id)
    assert len(patterns) == 1
    assert "Advancing rubric progression" not in patterns[0]["summary"]
    assert "conflicting ordinal rubric ratings" in patterns[0]["summary"]
    assert any("Multiple conflicting ordinal ratings in the same period cannot be averaged" in lim for lim in patterns[0]["limitations"])
