"""Tests for ALLPS MCP tools.

Includes:
- Direct Python calls to tool functions (ingest_evidence, get_learner_history)
- Protocol-level smoke test against a real MCP server subprocess
- Verification that source_system and ingestion_method survive:
  MCP → service → SQLite → retrieval
"""

import json
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio

from allps.mcp.server import (
    analyse_longitudinal_pattern,
    get_learner_history,
    ingest_evidence,
    record_evidence,
    set_service,
)
from allps.models import IngestionMethod, Learner
from allps.services.evidence_service import EvidenceService
from allps.storage.sqlite_store import SQLiteStore
from data.synthetic.seed_data import seed_database


@pytest_asyncio.fixture
async def mcp_service(store):
    """Set up the MCP server with a test service."""
    service = EvidenceService(store)
    set_service(service)
    yield service
    set_service(None)


# ── Direct tool function tests ────────────────────────────────────


@pytest.mark.asyncio
class TestMCPToolsDirect:
    """Test MCP tool functions via direct Python calls."""

    async def test_ingest_evidence_tool(self, mcp_service):
        result = await ingest_evidence(
            learner_id="LRN-001",
            evidence_type="assessment",
            source_system="school_sis",
            ingestion_method="api",
            source_type="teacher",
            source_reference="Mr. Test",
            academic_year=2025,
            term=1,
            content={"score": 85, "max_score": 100},
            observed_at="2025-03-15T10:00:00+00:00",
            subject="Mathematics",
        )

        assert result["learner_id"] == "LRN-001"
        assert result["evidence_type"] == "assessment"
        assert result["source_system"] == "school_sis"
        assert result["ingestion_method"] == "api"
        assert result["source_type"] == "teacher"
        assert result["source_reference"] == "Mr. Test"
        assert result["content"]["score"] == 85

    async def test_record_evidence_backward_compatibility_alias(self, mcp_service):
        """record_evidence remains available as an alias to ingest_evidence."""
        assert record_evidence is ingest_evidence
        result = await record_evidence(
            learner_id="LRN-001",
            evidence_type="assessment",
            source_system="school_sis",
            ingestion_method="api",
            source_type="teacher",
            source_reference="Mr. Test",
            academic_year=2025,
            term=1,
            content={"score": 75, "max_score": 100},
            observed_at="2025-03-15T10:00:00+00:00",
        )
        assert result["learner_id"] == "LRN-001"
        assert result["content"]["score"] == 75

    async def test_source_system_and_ingestion_method_survive_pipeline(
        self, mcp_service, store
    ):
        """Proves source_system and ingestion_method survive:
        MCP tool -> service -> SQLite -> MCP retrieval.
        """
        # 1. Record via MCP tool
        record_res = await ingest_evidence(
            learner_id="LRN-SYS-01",
            evidence_type="assessment",
            source_system="moodle",
            ingestion_method="webhook",
            source_type="system",
            source_reference="quiz-engine-v3",
            academic_year=2025,
            term=2,
            content={"score": 92, "max_score": 100},
            observed_at="2025-06-12T14:30:00+00:00",
            subject="Physical Sciences",
        )
        assert record_res["source_system"] == "moodle"
        assert record_res["ingestion_method"] == "webhook"

        # 2. Check directly in SQLite store
        stored_records = await store.get_evidence_for_learner("LRN-SYS-01")
        assert len(stored_records) == 1
        assert stored_records[0].source_system == "moodle"
        assert stored_records[0].ingestion_method == IngestionMethod.WEBHOOK

        # 3. Retrieve via MCP tool
        history_res = await get_learner_history(learner_id="LRN-SYS-01")
        assert history_res["record_count"] == 1
        retrieved_ev = history_res["evidence"][0]
        assert retrieved_ev["source_system"] == "moodle"
        assert retrieved_ev["ingestion_method"] == "webhook"

    async def test_get_learner_history_tool(self, mcp_service):
        # Record evidence first
        await ingest_evidence(
            learner_id="LRN-001",
            evidence_type="assessment",
            source_system="school_sis",
            ingestion_method="api",
            source_type="teacher",
            source_reference="Mr. Test",
            academic_year=2025,
            term=1,
            content={"score": 80, "max_score": 100},
            observed_at="2025-03-15T10:00:00+00:00",
        )
        await ingest_evidence(
            learner_id="LRN-001",
            evidence_type="observation",
            source_system="allps",
            ingestion_method="manual_observation",
            source_type="teacher",
            source_reference="Mr. Test",
            academic_year=2025,
            term=1,
            content={"note": "Good participation"},
            observed_at="2025-03-20T10:00:00+00:00",
        )

        result = await get_learner_history(learner_id="LRN-001")

        assert result["learner_id"] == "LRN-001"
        assert result["record_count"] == 2
        assert len(result["evidence"]) == 2
        assert result["evidence"][0]["source_system"] == "school_sis"
        assert result["evidence"][1]["source_system"] == "allps"

    async def test_get_history_with_filters(self, mcp_service):
        await ingest_evidence(
            learner_id="LRN-001",
            evidence_type="assessment",
            source_system="school_sis",
            ingestion_method="api",
            source_type="teacher",
            source_reference="Mr. Test",
            academic_year=2025,
            term=1,
            content={"score": 80, "max_score": 100},
            observed_at="2025-03-15T10:00:00+00:00",
            subject="Mathematics",
        )
        await ingest_evidence(
            learner_id="LRN-001",
            evidence_type="attendance",
            source_system="attendance_system",
            ingestion_method="scheduled_sync",
            source_type="system",
            source_reference="system",
            academic_year=2025,
            term=1,
            content={"status": "present"},
            observed_at="2025-03-28T10:00:00+00:00",
        )

        result = await get_learner_history(
            learner_id="LRN-001",
            evidence_type="assessment",
        )

        assert result["record_count"] == 1
        assert result["evidence"][0]["evidence_type"] == "assessment"
        assert result["evidence"][0]["source_system"] == "school_sis"
        assert result["evidence"][0]["ingestion_method"] == "api"

    async def test_empty_history(self, mcp_service):
        result = await get_learner_history(learner_id="NONEXISTENT")
        assert result["record_count"] == 0
        assert result["evidence"] == []

    async def test_ingest_creates_audit_trail(self, mcp_service, store):
        await ingest_evidence(
            learner_id="LRN-AUDIT",
            evidence_type="assessment",
            source_system="csv_import",
            ingestion_method="csv_import",
            source_type="teacher",
            source_reference="Mrs. Audit",
            academic_year=2025,
            term=1,
            content={"score": 70, "max_score": 100},
            observed_at="2025-03-15T10:00:00+00:00",
        )

        logs = await store.get_audit_log(tool_name="ingest_evidence")
        assert len(logs) == 1
        assert logs[0].input_summary["learner_id"] == "LRN-AUDIT"
        assert logs[0].input_summary["source_system"] == "csv_import"
        assert logs[0].input_summary["ingestion_method"] == "csv_import"

    async def test_mcp_direct_rich_marks_rubric_and_missing(
        self, mcp_service, store
    ):
        """Verify rich marks, rubric, and missing outcomes through direct MCP calls."""
        learner_id = "LRN-MCP-RICH-01"

        # 1. Ingest rich marks across 3 terms
        scores = [10, 14, 18]
        for t_idx, s in enumerate(scores, start=1):
            await ingest_evidence(
                learner_id=learner_id,
                evidence_type="assessment",
                source_system="school_sis",
                ingestion_method="api",
                source_type="teacher",
                source_reference="Mr. Banda",
                academic_year=2025,
                term=t_idx,
                subject="Mathematics",
                content={
                    "grade": "Grade 2",
                    "score": s,
                    "max_score": 20,
                    "form": "Form A",
                    "form_version": "v1.0",
                    "language": "English",
                    "measured_skill": "addition",
                    "comparison_authorized": True,
                },
                observed_at=f"2025-{t_idx * 3:02d}-15T10:00:00+00:00",
                source_event_id=f"MCP-MARK-{t_idx}",
            )

        # 2. Ingest rubric assessment
        await ingest_evidence(
            learner_id=learner_id,
            evidence_type="assessment",
            source_system="school_sis",
            ingestion_method="api",
            source_type="teacher",
            source_reference="Mrs. Achebe",
            academic_year=2025,
            term=1,
            subject="English",
            content={
                "grade": "Grade 2",
                "rubric": "Reading Rubric",
                "rubric_version": "v1.0",
                "scale": ["Below Expectation", "Approaching Expectation", "Meeting Expectation", "Exceeding Expectation"],
                "level": "Meeting Expectation",
            },
            observed_at="2025-03-20T10:00:00+00:00",
            source_event_id="MCP-RUB-1",
        )

        # 3. Ingest missing outcome: result_unavailable
        await ingest_evidence(
            learner_id=learner_id,
            evidence_type="assessment",
            source_system="school_sis",
            ingestion_method="api",
            source_type="teacher",
            source_reference="Mrs. Achebe",
            academic_year=2025,
            term=2,
            subject="Science",
            content={
                "grade": "Grade 2",
                "status": "result_unavailable",
                "reason": "Damaged lab sheet",
                "max_score": 30,
            },
            observed_at="2025-06-20T10:00:00+00:00",
            source_event_id="MCP-UNAVAIL-1",
        )

        # 4. Ingest missing outcome: assessment_not_administered
        await ingest_evidence(
            learner_id=learner_id,
            evidence_type="assessment",
            source_system="school_sis",
            ingestion_method="api",
            source_type="teacher",
            source_reference="Mrs. Achebe",
            academic_year=2025,
            term=3,
            subject="Science",
            content={
                "grade": "Grade 2",
                "status": "assessment_not_administered",
                "reason": "School closure",
                "max_score": 30,
            },
            observed_at="2025-09-20T10:00:00+00:00",
            source_event_id="MCP-NOTADMIN-1",
        )

        # Retrieve history via MCP tool
        hist = await get_learner_history(learner_id=learner_id)
        assert hist["record_count"] == 6

        # Check distinct missing statuses survived
        unavail = [e for e in hist["evidence"] if e["source_event_id"] == "MCP-UNAVAIL-1"][0]
        notadmin = [e for e in hist["evidence"] if e["source_event_id"] == "MCP-NOTADMIN-1"][0]
        assert unavail["content"]["status"] == "result_unavailable"
        assert notadmin["content"]["status"] == "assessment_not_administered"

        # Check analysis tool
        analysis_patterns = await analyse_longitudinal_pattern(
            learner_id=learner_id,
            subject="Mathematics",
        )
        assert len(analysis_patterns) >= 1
        trend_p = [p for p in analysis_patterns if p["pattern_type"] == "trend"][0]
        assert "Improving across-term trend" in trend_p["summary"]
        assert "10/20 -> 14/20 -> 18/20" in trend_p["summary"]

    async def test_mcp_direct_workstream_1_defects(self, mcp_service):
        """Direct MCP tool calls verifying Workstream 1 contract defects."""
        learner_id = "LRN-MCP-DEFECTS"

        # 1. Reject conflicting comparison aliases via direct MCP call
        with pytest.raises(ValueError, match="Conflicting comparison-authorization aliases"):
            await ingest_evidence(
                learner_id=learner_id,
                evidence_type="assessment",
                source_system="school_sis",
                ingestion_method="api",
                source_type="teacher",
                source_reference="Teacher A",
                academic_year=2025,
                term=1,
                content={
                    "score": 15,
                    "max_score": 20,
                    "comparison_authorized": True,
                    "comparable": False,
                },
                observed_at="2025-03-20T10:00:00+00:00",
            )

        # 2. Reject boolean score via direct MCP call
        with pytest.raises(ValueError, match="'score' must be a numeric value, not boolean or non-numeric"):
            await ingest_evidence(
                learner_id=learner_id,
                evidence_type="assessment",
                source_system="school_sis",
                ingestion_method="api",
                source_type="teacher",
                source_reference="Teacher A",
                academic_year=2025,
                term=1,
                content={"score": True, "max_score": 20},
                observed_at="2025-03-20T10:00:00+00:00",
            )

        # 3. Accept fluency payload via direct MCP call
        ev_fl = await ingest_evidence(
            learner_id=learner_id,
            evidence_type="assessment",
            source_system="school_sis",
            ingestion_method="api",
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=1,
            content={"value": 45.0, "unit": "cwpm"},
            observed_at="2025-03-20T10:00:00+00:00",
            source_event_id="MCP-FL-01",
        )
        assert ev_fl["content"]["value"] == 45.0
        assert ev_fl["content"]["unit"] == "cwpm"

        # 4. Accept missing outcome with null outcome fields via direct MCP call
        ev_miss = await ingest_evidence(
            learner_id=learner_id,
            evidence_type="assessment",
            source_system="school_sis",
            ingestion_method="api",
            source_type="teacher",
            source_reference="Teacher A",
            academic_year=2025,
            term=1,
            content={"status": "absent", "reason": "Medical appointment", "score": None, "level": None},
            observed_at="2025-03-20T10:00:00+00:00",
            source_event_id="MCP-MISS-01",
        )
        assert ev_miss["content"]["status"] == "absent"

    async def test_analyse_pattern_on_seeded_learners(self, tmp_path):
        """Verify analyse_longitudinal_pattern directly against full seeded dataset."""
        db_path = str(tmp_path / "seeded_mcp_test.db")
        await seed_database(db_path)
        test_store = SQLiteStore(db_path)
        await test_store.initialize()
        srv = EvidenceService(test_store)
        set_service(srv)
        try:
            # 1. Learner 001 (LRN-001): Declining maths trend across 3 terms
            patterns_a = await analyse_longitudinal_pattern(
                learner_id="LRN-001",
                subject="Mathematics",
            )
            assert len(patterns_a) >= 1
            trend_a = [p for p in patterns_a if p["pattern_type"] == "trend"][0]
            assert "Declining across-term trend" in trend_a["summary"]
            assert "82/100 -> 68/100 -> 51/100" in trend_a["summary"]

            baseline_a = [p for p in patterns_a if p["pattern_type"] == "changed_from_baseline"][0]
            assert "Drop of 31 marks from baseline" in baseline_a["summary"]

            # 2. Learner 003 (LRN-003): Science subject stream has only 1 mark & 1 missing
            patterns_c_sci = await analyse_longitudinal_pattern(
                learner_id="LRN-003",
                subject="Science",
            )
            # Fails 3-period trend threshold, returns no trends (or insufficient evidence)
            trend_c = [p for p in patterns_c_sci if p["pattern_type"] == "trend"]
            assert len(trend_c) == 0

            # 3. Learner C: English subject stream has 3 terms (78 -> 81 -> 76, variable)
            patterns_c_eng = await analyse_longitudinal_pattern(
                learner_id="LRN-003",
                subject="English",
            )
            trend_c_eng = [p for p in patterns_c_eng if p["pattern_type"] == "trend"][0]
            assert "variable" in trend_c_eng["summary"]
        finally:
            set_service(None)
            await test_store.close()



# ── Protocol-level MCP smoke test ─────────────────────────────────


@pytest.mark.asyncio
class TestMCPProtocol:
    """Protocol-level test: spawn MCP server subprocess, connect via stdio."""

    async def test_mcp_server_tools_and_calls(self, tmp_path):
        """Full protocol smoke: list tools, ingest evidence, retrieve history,
        proving source_system and ingestion_method survive across wire protocol.
        """
        # Pre-seed a temporary database with a learner
        db_file = tmp_path / "protocol_test.db"
        store = SQLiteStore(str(db_file))
        await store.initialize()
        await store.add_learner(
            Learner(
                learner_id="PROTO-001",
                display_name="Protocol Test Learner",
            )
        )
        await store.close()

        # Set up environment for the subprocess
        env = os.environ.copy()
        env["ALLPS_DB_PATH"] = str(db_file)
        src_dir = str(Path(__file__).parent.parent / "src")
        env["PYTHONPATH"] = (
            src_dir + os.pathsep + env.get("PYTHONPATH", "")
        )

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

                # ── 1. Verify tools registered ──
                tools_result = await session.list_tools()
                tool_names = sorted(
                    t.name for t in tools_result.tools
                )
                assert tool_names == [
                    "analyse_longitudinal_pattern",
                    "flag_pattern_for_review",
                    "get_learner_history",
                    "get_pending_reviews",
                    "get_surfaced_profile",
                    "ingest_evidence",
                    "resolve_teacher_review",
                ], f"Expected registered tools, got: {tool_names}"

                # ── 2. Call ingest_evidence via MCP protocol ──
                record_result = await session.call_tool(
                    "ingest_evidence",
                    arguments={
                        "learner_id": "PROTO-001",
                        "evidence_type": "assessment",
                        "source_system": "school_sis",
                        "ingestion_method": "api",
                        "source_type": "teacher",
                        "source_reference": "Protocol Test Teacher",
                        "academic_year": 2025,
                        "term": 1,
                        "content": {
                            "score": 90,
                            "max_score": 100,
                        },
                        "observed_at": "2025-03-15T10:00:00+00:00",
                        "subject": "Mathematics",
                    },
                )
                assert record_result.content
                result_data = json.loads(
                    record_result.content[0].text
                )
                assert result_data["learner_id"] == "PROTO-001"
                assert result_data["evidence_type"] == "assessment"
                assert result_data["source_system"] == "school_sis"
                assert result_data["ingestion_method"] == "api"
                assert (
                    result_data["source_reference"]
                    == "Protocol Test Teacher"
                )

                # ── 3. Call get_learner_history via MCP protocol ──
                history_result = await session.call_tool(
                    "get_learner_history",
                    arguments={"learner_id": "PROTO-001"},
                )
                history_data = json.loads(
                    history_result.content[0].text
                )
                assert history_data["learner_id"] == "PROTO-001"
                assert history_data["record_count"] >= 1
                ev_record = history_data["evidence"][0]
                assert ev_record["source_system"] == "school_sis"
                assert ev_record["ingestion_method"] == "api"
                assert (
                    ev_record["source_reference"]
                    == "Protocol Test Teacher"
                )

                # ── 4. Call analyse_longitudinal_pattern via MCP protocol ──
                analysis_result = await session.call_tool(
                    "analyse_longitudinal_pattern",
                    arguments={"learner_id": "PROTO-001"},
                )
                assert analysis_result.content
                patterns_data = [
                    json.loads(c.text) for c in analysis_result.content
                ]
                assert isinstance(patterns_data, list)
                assert len(patterns_data) >= 1
                assert patterns_data[0]["learner_id"] == "PROTO-001"

    async def test_mcp_protocol_idempotency_retry_and_conflict(self, tmp_path):
        """Test full-observation idempotency and conflict through real MCP wire protocol."""
        db_file = tmp_path / "protocol_idemp.db"
        store = SQLiteStore(str(db_file))
        await store.initialize()
        await store.add_learner(
            Learner(
                learner_id="PROTO-IDEMP-01",
                display_name="Protocol Idempotency Learner",
            )
        )
        await store.close()

        env = os.environ.copy()
        env["ALLPS_DB_PATH"] = str(db_file)
        src_dir = str(Path(__file__).parent.parent / "src")
        env["PYTHONPATH"] = (
            src_dir + os.pathsep + env.get("PYTHONPATH", "")
        )

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

                args = {
                    "learner_id": "PROTO-IDEMP-01",
                    "evidence_type": "assessment",
                    "source_system": "school_sis",
                    "ingestion_method": "api",
                    "source_type": "teacher",
                    "source_reference": "Protocol Teacher",
                    "academic_year": 2025,
                    "term": 1,
                    "content": {
                        "score": 90,
                        "max_score": 100,
                        "tags": ["reading", "fluency"],
                    },
                    "observed_at": "2025-03-15T10:00:00+00:00",
                    "source_event_id": "PROTO-EV-IDEMP-1",
                    "subject": "Reading",
                }

                # 1. First ingest over MCP protocol
                res1 = await session.call_tool("ingest_evidence", arguments=args)
                assert not res1.is_error
                data1 = json.loads(res1.content[0].text)
                ev1_id = data1["evidence_id"]

                # 2. Identical retry over MCP protocol
                res2 = await session.call_tool("ingest_evidence", arguments=args)
                assert not res2.is_error
                data2 = json.loads(res2.content[0].text)
                assert data2["evidence_id"] == ev1_id
                assert data2["content"]["tags"] == ["reading", "fluency"]

                # 3. Conflict over MCP protocol (different score)
                conflict_args = dict(args)
                conflict_args["content"] = {"score": 95, "max_score": 100, "tags": ["reading", "fluency"]}
                res_conflict = await session.call_tool("ingest_evidence", arguments=conflict_args)
                assert res_conflict.is_error
                assert res_conflict.content

    async def test_mcp_protocol_wire_rich_marks_rubric_and_missing_analysis(self, tmp_path):
        """Test full wire-protocol lifecycle for rich marks, rubrics, and distinct missing outcomes."""
        db_file = tmp_path / "protocol_rich.db"
        store = SQLiteStore(str(db_file))
        await store.initialize()
        await store.add_learner(
            Learner(
                learner_id="PROTO-RICH-01",
                display_name="Protocol Rich Learner",
            )
        )
        await store.close()

        env = os.environ.copy()
        env["ALLPS_DB_PATH"] = str(db_file)
        src_dir = str(Path(__file__).parent.parent / "src")
        env["PYTHONPATH"] = (
            src_dir + os.pathsep + env.get("PYTHONPATH", "")
        )

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

                # 1. Ingest rich marks across 3 distinct terms
                for t_idx, score in enumerate([10, 15, 20], start=1):
                    res = await session.call_tool(
                        "ingest_evidence",
                        arguments={
                            "learner_id": "PROTO-RICH-01",
                            "evidence_type": "assessment",
                            "source_system": "school_sis",
                            "ingestion_method": "api",
                            "source_type": "teacher",
                            "source_reference": "Mr. Banda",
                            "academic_year": 2025,
                            "term": t_idx,
                            "subject": "Mathematics",
                            "content": {
                                "grade": "Grade 2",
                                "score": score,
                                "max_score": 20,
                                "form": "Form A",
                                "form_version": "v1.0",
                                "language": "English",
                                "measured_skill": "addition",
                                "comparison_authorized": True,
                            },
                            "observed_at": f"2025-{t_idx * 3:02d}-15T10:00:00+00:00",
                            "source_event_id": f"PROTO-MARK-{t_idx}",
                        },
                    )
                    assert not res.is_error

                # 2. Ingest rubric assessment with defined scale
                res_rub = await session.call_tool(
                    "ingest_evidence",
                    arguments={
                        "learner_id": "PROTO-RICH-01",
                        "evidence_type": "assessment",
                        "source_system": "school_sis",
                        "ingestion_method": "api",
                        "source_type": "teacher",
                        "source_reference": "Mrs. Achebe",
                        "academic_year": 2025,
                        "term": 1,
                        "subject": "English",
                        "content": {
                            "grade": "Grade 2",
                            "rubric": "Reading Rubric",
                            "rubric_version": "v1.0",
                            "scale": ["Below Expectation", "Approaching Expectation", "Meeting Expectation", "Exceeding Expectation"],
                            "level": "Meeting Expectation",
                        },
                        "observed_at": "2025-03-20T10:00:00+00:00",
                        "source_event_id": "PROTO-RUB-1",
                    },
                )
                assert not res_rub.is_error

                # 3. Ingest missing outcome: result_unavailable
                res_unavail = await session.call_tool(
                    "ingest_evidence",
                    arguments={
                        "learner_id": "PROTO-RICH-01",
                        "evidence_type": "assessment",
                        "source_system": "school_sis",
                        "ingestion_method": "api",
                        "source_type": "teacher",
                        "source_reference": "Teacher A",
                        "academic_year": 2025,
                        "term": 2,
                        "subject": "Science",
                        "content": {
                            "grade": "Grade 2",
                            "status": "result_unavailable",
                            "reason": "Script damaged by water",
                            "max_score": 25,
                        },
                        "observed_at": "2025-06-20T10:00:00+00:00",
                        "source_event_id": "PROTO-UNAVAIL-1",
                    },
                )
                assert not res_unavail.is_error

                # 4. Ingest missing outcome: assessment_not_administered
                res_notadmin = await session.call_tool(
                    "ingest_evidence",
                    arguments={
                        "learner_id": "PROTO-RICH-01",
                        "evidence_type": "assessment",
                        "source_system": "school_sis",
                        "ingestion_method": "api",
                        "source_type": "teacher",
                        "source_reference": "Teacher A",
                        "academic_year": 2025,
                        "term": 3,
                        "subject": "Science",
                        "content": {
                            "grade": "Grade 2",
                            "status": "assessment_not_administered",
                            "reason": "School closure",
                            "max_score": 25,
                        },
                        "observed_at": "2025-09-20T10:00:00+00:00",
                        "source_event_id": "PROTO-NOTADMIN-1",
                    },
                )
                assert not res_notadmin.is_error

                # 5. Retrieve learner history via wire protocol
                hist_res = await session.call_tool(
                    "get_learner_history",
                    arguments={"learner_id": "PROTO-RICH-01"},
                )
                assert not hist_res.is_error
                hist_data = json.loads(hist_res.content[0].text)
                assert hist_data["record_count"] == 6

                # 6. Analyse longitudinal pattern over wire protocol
                analysis_res = await session.call_tool(
                    "analyse_longitudinal_pattern",
                    arguments={"learner_id": "PROTO-RICH-01", "subject": "Mathematics"},
                )
                assert not analysis_res.is_error
                patterns_data = [json.loads(c.text) for c in analysis_res.content]
                assert len(patterns_data) >= 1
                trend_pat = [p for p in patterns_data if p["pattern_type"] == "trend"][0]
                assert "Improving across-term trend" in trend_pat["summary"]
                assert "10/20 -> 15/20 -> 20/20" in trend_pat["summary"]
                assert len(trend_pat["supporting_evidence"]) == 3

                # 7. Wire protocol call with boolean score is rejected
                res_bool = await session.call_tool(
                    "ingest_evidence",
                    arguments={
                        "learner_id": "PROTO-RICH-01",
                        "evidence_type": "assessment",
                        "source_system": "school_sis",
                        "ingestion_method": "api",
                        "source_type": "teacher",
                        "source_reference": "Teacher A",
                        "academic_year": 2025,
                        "term": 1,
                        "content": {"score": True, "max_score": 20},
                        "observed_at": "2025-01-20T10:00:00+00:00",
                    },
                )
                assert res_bool.is_error

                # 8. Wire protocol call with conflicting comparison aliases is rejected
                res_alias = await session.call_tool(
                    "ingest_evidence",
                    arguments={
                        "learner_id": "PROTO-RICH-01",
                        "evidence_type": "assessment",
                        "source_system": "school_sis",
                        "ingestion_method": "api",
                        "source_type": "teacher",
                        "source_reference": "Teacher A",
                        "academic_year": 2025,
                        "term": 1,
                        "content": {
                            "score": 15,
                            "max_score": 20,
                            "comparison_authorized": True,
                            "comparable": False,
                        },
                        "observed_at": "2025-01-20T10:00:00+00:00",
                    },
                )
                assert res_alias.is_error

                # 9. Wire protocol call with valid fluency payload succeeds
                res_fl = await session.call_tool(
                    "ingest_evidence",
                    arguments={
                        "learner_id": "PROTO-RICH-01",
                        "evidence_type": "assessment",
                        "source_system": "school_sis",
                        "ingestion_method": "api",
                        "source_type": "teacher",
                        "source_reference": "Teacher A",
                        "academic_year": 2025,
                        "term": 1,
                        "content": {
                            "value": 45.0,
                            "unit": "cwpm",
                            "form": "Oral Form 1",
                            "form_version": "v1.0",
                            "language": "English",
                            "measured_skill": "fluency",
                            "comparison_authorized": True,
                        },
                        "observed_at": "2025-01-20T10:00:00+00:00",
                    },
                )
                assert not res_fl.is_error




