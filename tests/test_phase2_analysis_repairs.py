"""Regression tests for Phase 2 analysis repairs.

Verifies:
1. Rejection of conflicting assessment-stage, measured-skill, and rubric-level aliases.
   Preservation of distinction between assessment stage and school level.
   Exercised through: model validation, ingestion service, SQLite store, and stdio MCP wire protocol.
   Includes equal-alias controls.
2. Explicit null checks for rubric levels: valid zero-level rubrics on declared scales.
3. Relevant missing and excluded evidence included in returned limitations even when
   a valid pattern exists, keeping missing outcomes distinct from contradictory evidence.
4. Explicit insufficient-evidence response for empty history.
5. Fluency longitudinal analysis contract (does not report insufficient periods when 3 compatible exist).
6. Two-period baseline summary formatting (prints term number, not period tuple).
"""

import json
import os
import sys
from pathlib import Path
import pytest

from allps.models.evidence import Evidence, EvidenceType, IngestionMethod
from allps.models.learner import Learner
from allps.models.pattern import PatternType
from allps.services.evidence_service import EvidenceService
from allps.services.analysis_service import AnalysisService, _get_rubric_rank
from allps.storage.sqlite_store import SQLiteStore


# =============================================================================
# 1. Stage-Conflict Rejection: Model, Ingestion, SQLite, MCP, and Equal-Alias
# =============================================================================

def test_model_rejects_conflicting_assessment_stage_aliases():
    """Model validation rejects conflicting assessment_stage vs stage aliases."""
    with pytest.raises(ValueError, match="Conflicting assessment-stage aliases"):
        Evidence(
            learner_id="LRN-STAGE-01",
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=1,
            content={
                "score": 15,
                "max_score": 20,
                "grade": "Grade 2",
                "form": "Form A",
                "form_version": "v1.0",
                "language": "English",
                "measured_skill": "addition",
                "comparison_authorized": True,
                "assessment_stage": "end_term",
                "stage": "opener",  # Conflicting assessment stage!
            },
            observed_at="2025-03-20T10:00:00+00:00",
        )


def test_model_accepts_equal_assessment_stage_aliases():
    """Equal-alias control: identical assessment_stage and stage values succeed."""
    ev = Evidence(
        learner_id="LRN-STAGE-02",
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=1,
        content={
            "score": 15,
            "max_score": 20,
            "grade": "Grade 2",
            "form": "Form A",
            "form_version": "v1.0",
            "language": "English",
            "measured_skill": "addition",
            "comparison_authorized": True,
            "assessment_stage": "end_term",
            "stage": "end_term",  # Equal-alias control!
        },
        observed_at="2025-03-20T10:00:00+00:00",
    )
    assert ev.assessment_stage == "end_term"


def test_model_preserves_distinction_between_stage_and_school_level():
    """stage='lower_primary' resolves to school_level without conflicting with assessment_stage."""
    ev = Evidence(
        learner_id="LRN-STAGE-03",
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=1,
        content={
            "score": 15,
            "max_score": 20,
            "grade": "Grade 2",
            "form": "Form A",
            "form_version": "v1.0",
            "language": "English",
            "measured_skill": "addition",
            "comparison_authorized": True,
            "assessment_stage": "end_term",
            "stage": "lower_primary",  # Educational band, not timing milestone
        },
        observed_at="2025-03-20T10:00:00+00:00",
    )
    assert ev.assessment_stage == "end_term"
    assert ev.school_level == "lower_primary"


def test_model_rejects_conflicting_school_level_aliases():
    """Model rejects conflicting school_level vs stage educational tier aliases."""
    with pytest.raises(ValueError, match="Conflicting school-level aliases"):
        Evidence(
            learner_id="LRN-STAGE-04",
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=1,
            content={
                "score": 15,
                "max_score": 20,
                "grade": "Grade 2",
                "form": "Form A",
                "form_version": "v1.0",
                "language": "English",
                "measured_skill": "addition",
                "comparison_authorized": True,
                "school_level": "lower_primary",
                "stage": "upper_primary",  # Conflicting school level!
            },
            observed_at="2025-03-20T10:00:00+00:00",
        )


@pytest.mark.asyncio
async def test_ingestion_service_and_sqlite_stage_conflict_and_equal_control(tmp_path):
    """Exercise stage-conflict rejection and equal-alias control through service and SQLite."""
    db_file = tmp_path / "stage_conflict.db"
    store = SQLiteStore(str(db_file))
    await store.initialize()
    service = EvidenceService(store)

    learner_id = "LRN-STAGE-SRV"

    # 1. Ingestion rejection on conflict
    with pytest.raises(ValueError, match="Conflicting assessment-stage aliases"):
        await service.record_evidence(
            learner_id=learner_id,
            evidence_type="assessment",
            source_system="school_sis",
            ingestion_method="api",
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=1,
            subject="Mathematics",
            content={
                "score": 15,
                "max_score": 20,
                "grade": "Grade 2",
                "form": "Form A",
                "form_version": "v1.0",
                "language": "English",
                "measured_skill": "addition",
                "comparison_authorized": True,
                "assessment_stage": "opener",
                "stage": "end_term",  # Conflict!
            },
            observed_at="2025-01-15T10:00:00+00:00",
        )

    # Verify no record was stored in SQLite
    records = await store.get_evidence_for_learner(learner_id)
    assert len(records) == 0

    # 2. Equal-alias control succeeds and stores cleanly in SQLite
    ev_stored = await service.record_evidence(
        learner_id=learner_id,
        evidence_type="assessment",
        source_system="school_sis",
        ingestion_method="api",
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=1,
        subject="Mathematics",
        content={
            "score": 15,
            "max_score": 20,
            "grade": "Grade 2",
            "form": "Form A",
            "form_version": "v1.0",
            "language": "English",
            "measured_skill": "addition",
            "comparison_authorized": True,
            "assessment_stage": "opener",
            "stage": "opener",  # Equal-alias control!
        },
        observed_at="2025-01-15T10:00:00+00:00",
    )
    assert ev_stored.assessment_stage == "opener"

    # Verify SQLite round-trip
    records = await store.get_evidence_for_learner(learner_id)
    assert len(records) == 1
    assert records[0].assessment_stage == "opener"

    await store.close()


@pytest.mark.asyncio
async def test_mcp_wire_protocol_stage_conflict_and_equal_control(tmp_path):
    """Exercise stage-conflict rejection and equal-alias control over actual stdio MCP."""
    db_file = tmp_path / "mcp_stage.db"
    store = SQLiteStore(str(db_file))
    await store.initialize()
    await store.add_learner(
        Learner(learner_id="PROTO-STAGE-01", display_name="Proto Stage Learner")
    )
    await store.close()

    env = os.environ.copy()
    env["ALLPS_DB_PATH"] = str(db_file)
    src_dir = str(Path(__file__).parent.parent / "src")
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")

    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "allps.mcp.server"],
        env=env,
    )

    async with stdio_client(server_params) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()

            # 1. Conflicting stage aliases over MCP wire protocol -> returns error
            conflict_res = await session.call_tool(
                "ingest_evidence",
                arguments={
                    "learner_id": "PROTO-STAGE-01",
                    "evidence_type": "assessment",
                    "source_system": "school_sis",
                    "ingestion_method": "api",
                    "source_type": "teacher",
                    "source_reference": "Teacher A",
                    "academic_year": 2025,
                    "term": 1,
                    "subject": "Mathematics",
                    "content": {
                        "score": 18,
                        "max_score": 20,
                        "grade": "Grade 2",
                        "form": "Form A",
                        "form_version": "v1.0",
                        "language": "English",
                        "measured_skill": "addition",
                        "comparison_authorized": True,
                        "assessment_stage": "end_term",
                        "stage": "opener",  # Conflicting!
                    },
                    "observed_at": "2025-03-20T10:00:00+00:00",
                },
            )
            assert conflict_res.is_error

            # 2. Equal-alias control over MCP wire protocol -> succeeds
            success_res = await session.call_tool(
                "ingest_evidence",
                arguments={
                    "learner_id": "PROTO-STAGE-01",
                    "evidence_type": "assessment",
                    "source_system": "school_sis",
                    "ingestion_method": "api",
                    "source_type": "teacher",
                    "source_reference": "Teacher A",
                    "academic_year": 2025,
                    "term": 1,
                    "subject": "Mathematics",
                    "content": {
                        "score": 18,
                        "max_score": 20,
                        "grade": "Grade 2",
                        "form": "Form A",
                        "form_version": "v1.0",
                        "language": "English",
                        "measured_skill": "addition",
                        "comparison_authorized": True,
                        "assessment_stage": "end_term",
                        "stage": "end_term",  # Equal-alias control!
                    },
                    "observed_at": "2025-03-20T10:00:00+00:00",
                },
            )
            assert not success_res.is_error
            data = json.loads(success_res.content[0].text)
            assert data["content"]["assessment_stage"] == "end_term"


# =============================================================================
# 2. Conflicting Measured-Skill and Rubric-Level Aliases
# =============================================================================

def test_model_rejects_conflicting_measured_skill_aliases():
    """Model validation rejects conflicting measured_skill vs skill aliases."""
    with pytest.raises(ValueError, match="Conflicting measured-skill aliases"):
        Evidence(
            learner_id="LRN-SKILL-01",
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=1,
            content={
                "score": 15,
                "max_score": 20,
                "measured_skill": "addition",
                "skill": "subtraction",  # Conflict!
            },
            observed_at="2025-01-15T10:00:00+00:00",
        )


def test_model_accepts_equal_measured_skill_aliases():
    """Equal-alias control: matching measured_skill and skill succeed."""
    ev = Evidence(
        learner_id="LRN-SKILL-02",
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=1,
        content={
            "score": 15,
            "max_score": 20,
            "measured_skill": "addition",
            "skill": "addition",  # Equal-alias control!
        },
        observed_at="2025-01-15T10:00:00+00:00",
    )
    assert ev.measured_skill == "addition"


def test_model_rejects_conflicting_rubric_level_aliases():
    """Model validation rejects conflicting level vs rubric_level aliases."""
    with pytest.raises(ValueError, match="Conflicting rubric-level aliases"):
        Evidence(
            learner_id="LRN-RLVL-01",
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="school_sis",
            ingestion_method=IngestionMethod.API,
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=1,
            content={
                "rubric": "Reading Rubric",
                "rubric_version": "v1.0",
                "scale": ["Below Expectation", "Approaching Expectation", "Meeting Expectation"],
                "level": "Approaching Expectation",
                "rubric_level": "Meeting Expectation",  # Conflict!
            },
            observed_at="2025-01-15T10:00:00+00:00",
        )


def test_model_accepts_equal_rubric_level_aliases():
    """Equal-alias control: matching level and rubric_level succeed."""
    ev = Evidence(
        learner_id="LRN-RLVL-02",
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="school_sis",
        ingestion_method=IngestionMethod.API,
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=1,
        content={
            "rubric": "Reading Rubric",
            "rubric_version": "v1.0",
            "scale": ["Below Expectation", "Approaching Expectation", "Meeting Expectation"],
            "level": "Meeting Expectation",
            "rubric_level": "Meeting Expectation",  # Equal-alias control!
        },
        observed_at="2025-01-15T10:00:00+00:00",
    )
    assert ev.is_rubric is True


# =============================================================================
# 3. Explicit Null Checks: Valid Zero-Level Rubrics
# =============================================================================

def test_rubric_rank_with_valid_zero_level():
    """Explicit null checks ensure level=0 resolves to rank 0.0 on a scale containing 0."""
    content = {
        "rubric": "CBC Coding",
        "rubric_version": "v1.0",
        "scale": [0, 1, 2, 3],
        "level": 0,
    }
    rank, lvl_str = _get_rubric_rank(content)
    assert rank == 0.0
    assert lvl_str == "0"


@pytest.mark.asyncio
async def test_longitudinal_trend_with_zero_level_rubrics(tmp_path):
    """Analysis correctly detects advancing rubric progression starting from level 0."""
    db_file = tmp_path / "zero_rubric.db"
    store = SQLiteStore(str(db_file))
    await store.initialize()
    service = EvidenceService(store)
    analysis = AnalysisService(service)

    learner_id = "LRN-ZERO-RUBRIC"
    scale = [0, 1, 2, 3]

    for term, lvl in [(1, 0), (2, 1), (3, 2)]:
        await service.record_evidence(
            learner_id=learner_id,
            evidence_type="assessment",
            source_system="school_sis",
            ingestion_method="api",
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=term,
            subject="Computer Science",
            content={
                "grade": "Grade 4",
                "rubric": "Programming Concepts",
                "rubric_version": "v1.0",
                "scale": scale,
                "level": lvl,
                "form": "Project Rubric",
                "form_version": "v1.0",
                "language": "English",
                "measured_skill": "loops_and_conditionals",
                "comparison_authorized": True,
            },
            observed_at=f"2025-0{term*3}-15T10:00:00+00:00",
        )

    patterns = await analysis.analyse_longitudinal_pattern(learner_id)
    assert len(patterns) >= 1
    trend = [p for p in patterns if p["pattern_type"] == "trend"][0]
    assert "Advancing rubric progression" in trend["summary"]
    assert "0 -> 1 -> 2" in trend["summary"]

    await store.close()


# =============================================================================
# 4. Valid Trend Accompanied by Missing Result (Distinct from Contradiction)
# =============================================================================

@pytest.mark.asyncio
async def test_valid_trend_accompanied_by_missing_result(tmp_path):
    """Valid trend surfaces across 3 periods and reports missing outcome in limitations."""
    db_file = tmp_path / "trend_missing.db"
    store = SQLiteStore(str(db_file))
    await store.initialize()
    service = EvidenceService(store)
    analysis = AnalysisService(service)

    learner_id = "LRN-TREND-MISS"

    # Term 1: Valid 12/20
    await service.record_evidence(
        learner_id=learner_id,
        evidence_type="assessment",
        source_system="school_sis",
        ingestion_method="api",
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=1,
        subject="Mathematics",
        content={
            "score": 12,
            "max_score": 20,
            "grade": "Grade 2",
            "form": "Form A",
            "form_version": "v1.0",
            "language": "English",
            "measured_skill": "addition",
            "comparison_authorized": True,
        },
        observed_at="2025-01-15T10:00:00+00:00",
    )

    # Term 2: Missing outcome (absent with reason)
    await service.record_evidence(
        learner_id=learner_id,
        evidence_type="assessment",
        source_system="school_sis",
        ingestion_method="api",
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=2,
        subject="Mathematics",
        content={
            "status": "absent",
            "reason": "Illness with doctor note",
            "grade": "Grade 2",
        },
        observed_at="2025-04-15T10:00:00+00:00",
    )

    # Term 3: Valid 15/20
    await service.record_evidence(
        learner_id=learner_id,
        evidence_type="assessment",
        source_system="school_sis",
        ingestion_method="api",
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=3,
        subject="Mathematics",
        content={
            "score": 15,
            "max_score": 20,
            "grade": "Grade 2",
            "form": "Form A",
            "form_version": "v1.0",
            "language": "English",
            "measured_skill": "addition",
            "comparison_authorized": True,
        },
        observed_at="2025-07-15T10:00:00+00:00",
    )

    # Term 4: Valid 18/20
    await service.record_evidence(
        learner_id=learner_id,
        evidence_type="assessment",
        source_system="school_sis",
        ingestion_method="api",
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=4,
        subject="Mathematics",
        content={
            "score": 18,
            "max_score": 20,
            "grade": "Grade 2",
            "form": "Form A",
            "form_version": "v1.0",
            "language": "English",
            "measured_skill": "addition",
            "comparison_authorized": True,
        },
        observed_at="2025-10-15T10:00:00+00:00",
    )

    patterns = await analysis.analyse_longitudinal_pattern(learner_id)
    assert len(patterns) >= 1
    trend = [p for p in patterns if p["pattern_type"] == "trend"][0]
    assert "Improving across-term trend" in trend["summary"]
    assert "12/20 -> 15/20 -> 18/20" in trend["summary"]

    # Missing outcome must be in limitations, NOT conflicting_evidence
    assert any("missing outcomes" in lim and "preserved as null" in lim for lim in trend["limitations"])
    assert trend["conflicting_evidence"] == []  # Not treated as contradictory!

    await store.close()


# =============================================================================
# 5. Empty History Returns Explicit Insufficient Evidence
# =============================================================================

@pytest.mark.asyncio
async def test_empty_history_returns_explicit_insufficient_evidence(tmp_path):
    """Empty history returns an explicit INSUFFICIENT_EVIDENCE pattern, not empty list."""
    db_file = tmp_path / "empty_hist.db"
    store = SQLiteStore(str(db_file))
    await store.initialize()
    service = EvidenceService(store)
    analysis = AnalysisService(service)

    patterns = await analysis.analyse_longitudinal_pattern("NONEXISTENT_LEARNER")
    assert isinstance(patterns, list)
    assert len(patterns) == 1
    pattern = patterns[0]
    assert pattern["pattern_type"] == PatternType.INSUFFICIENT_EVIDENCE.value
    assert "No evidence records available" in pattern["summary"]
    assert pattern["supporting_evidence"] == []
    assert any("No recorded evidence history" in lim for lim in pattern["limitations"])

    await store.close()


# =============================================================================
# 6. Fluency Records Analysis Contract
# =============================================================================

@pytest.mark.asyncio
async def test_fluency_analysis_contract_three_periods(tmp_path):
    """Fluency records across 3 compatible periods surface trend without claiming insufficient periods."""
    db_file = tmp_path / "fluency_trend.db"
    store = SQLiteStore(str(db_file))
    await store.initialize()
    service = EvidenceService(store)
    analysis = AnalysisService(service)

    learner_id = "LRN-FLUENCY-01"

    # Ingest 3 compatible terms of oral reading fluency
    for term, val in [(1, 45.0), (2, 55.0), (3, 68.0)]:
        await service.record_evidence(
            learner_id=learner_id,
            evidence_type="assessment",
            source_system="school_sis",
            ingestion_method="api",
            source_type="teacher",
            source_reference="Mrs. Achebe",
            academic_year=2025,
            term=term,
            subject="English",
            content={
                "value": val,
                "unit": "cwpm",
                "grade": "Grade 2",
                "form": "Passage Form 1",
                "form_version": "v1.0",
                "language": "English",
                "measured_skill": "oral_reading_fluency",
                "comparison_authorized": True,
            },
            observed_at=f"2025-0{term*3}-15T10:00:00+00:00",
        )

    patterns = await analysis.analyse_longitudinal_pattern(learner_id)
    assert len(patterns) >= 1
    trend = [p for p in patterns if p["pattern_type"] == "trend"][0]
    assert "Improving across-term fluency trend" in trend["summary"]
    assert "45 cwpm -> 55 cwpm -> 68 cwpm" in trend["summary"]

    # Verify baseline change
    baseline = [p for p in patterns if p["pattern_type"] == "changed_from_baseline"][0]
    assert "Gain of 23 cwpm from baseline" in baseline["summary"]

    await store.close()


# =============================================================================
# 7. Two-Period Baseline Summary Format (Prints Term Number, Not Tuple)
# =============================================================================

@pytest.mark.asyncio
async def test_two_period_baseline_summary_prints_term_number(tmp_path):
    """Two-period baseline change summary prints 'Term 2', never a tuple like '(2025, 2)'."""
    db_file = tmp_path / "baseline_format.db"
    store = SQLiteStore(str(db_file))
    await store.initialize()
    service = EvidenceService(store)
    analysis = AnalysisService(service)

    learner_id = "LRN-BASE-FMT"

    # Term 1: 10/20
    await service.record_evidence(
        learner_id=learner_id,
        evidence_type="assessment",
        source_system="school_sis",
        ingestion_method="api",
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=1,
        subject="Mathematics",
        content={
            "score": 10,
            "max_score": 20,
            "grade": "Grade 2",
            "form": "Form A",
            "form_version": "v1.0",
            "language": "English",
            "measured_skill": "addition",
            "comparison_authorized": True,
        },
        observed_at="2025-01-15T10:00:00+00:00",
    )

    # Term 2: 16/20
    await service.record_evidence(
        learner_id=learner_id,
        evidence_type="assessment",
        source_system="school_sis",
        ingestion_method="api",
        source_type="teacher",
        source_reference="Teacher A",
        academic_year=2025,
        term=2,
        subject="Mathematics",
        content={
            "score": 16,
            "max_score": 20,
            "grade": "Grade 2",
            "form": "Form A",
            "form_version": "v1.0",
            "language": "English",
            "measured_skill": "addition",
            "comparison_authorized": True,
        },
        observed_at="2025-04-15T10:00:00+00:00",
    )

    patterns = await analysis.analyse_longitudinal_pattern(learner_id)
    assert len(patterns) == 1
    base_pat = patterns[0]
    assert base_pat["pattern_type"] == "changed_from_baseline"

    # Verify formatting: prints 'Term 2', no tuple like '(2025, 2)'
    summary = base_pat["summary"]
    assert "Term 2)" in summary
    assert "(2025, 2)" not in summary
    assert "Gain of 6 marks from baseline (10/20 in Year 2025 Term 1 to 16/20 in Year 2025 Term 2) in Grade 2 Mathematics." == summary

    await store.close()
