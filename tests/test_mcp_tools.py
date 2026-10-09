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
    get_learner_history,
    ingest_evidence,
    record_evidence,
    set_service,
)
from allps.models import IngestionMethod, Learner
from allps.services.evidence_service import EvidenceService
from allps.storage.sqlite_store import SQLiteStore


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

                # ── 1. Verify exactly 2 tools registered ──
                tools_result = await session.list_tools()
                tool_names = sorted(
                    t.name for t in tools_result.tools
                )
                assert tool_names == [
                    "get_learner_history",
                    "ingest_evidence",
                ], f"Expected exactly ['get_learner_history', 'ingest_evidence'], got: {tool_names}"

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



