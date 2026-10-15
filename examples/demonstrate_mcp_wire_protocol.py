"""ALLPS Real MCP Wire Protocol Demonstration.

Spawns the ALLPS MCP server (`allps.mcp.server`) via stdio transport, connects
the official Python MCP ClientSession, exercises full JSON-RPC protocol negotiation,
retrieves learner history, performs pattern analysis, verifies citation resolution
against SQLite, and proves rejection of unauthorized autonomous teacher approvals.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Ensure project root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "src"))

from data.synthetic.seed_data import seed_database


async def run_mcp_protocol_demonstration() -> dict[str, Any]:
    print("=" * 80)
    print("ALLPS -- REAL MCP WIRE PROTOCOL DEMONSTRATION")
    print("Transport: stdio (JSON-RPC 2.0)")
    print("=" * 80)

    # 1. Prepare isolated test database
    demo_db = root_dir / "allps_mcp_demo.db"
    if demo_db.exists():
        try:
            demo_db.unlink()
        except Exception:
            pass

    print(f"\n[1] Seeding clean demonstration database at {demo_db.name}...")
    await seed_database(str(demo_db))

    # Verify seed
    with sqlite3.connect(str(demo_db)) as conn:
        learner_count = conn.execute("SELECT COUNT(*) FROM learners").fetchone()[0]
        evidence_count = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    print(f"    -> Seeded {learner_count} learners, {evidence_count} evidence records.")

    # 2. Configure MCP server subprocess parameters
    env = os.environ.copy()
    env["ALLPS_DB_PATH"] = str(demo_db)
    env["PYTHONPATH"] = str(root_dir / "src") + os.pathsep + env.get("PYTHONPATH", "")

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "allps.mcp.server"],
        env=env,
    )

    protocol_transcript: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "protocol": "mcp/stdio",
        "transport": "stdio",
        "server_module": "allps.mcp.server",
        "database": str(demo_db),
        "steps": [],
    }

    print("\n[2] Spawning ALLPS MCP server subprocess & connecting via stdio...")
    t0 = time.perf_counter()

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            # Step A: Initialize Session Handshake
            init_result = await session.initialize()
            elapsed_init = (time.perf_counter() - t0) * 1000
            s_info = getattr(init_result, "server_info", getattr(init_result, "serverInfo", None))
            p_ver = getattr(init_result, "protocol_version", getattr(init_result, "protocolVersion", "unknown"))
            print(f"    -> MCP Handshake initialized in {elapsed_init:.1f}ms")
            print(f"    -> Server Info: {s_info}")
            print(f"    -> Protocol Version: {p_ver}")

            protocol_transcript["steps"].append({
                "step": "initialize",
                "latency_ms": elapsed_init,
                "server_info": {
                    "name": getattr(s_info, "name", "allps"),
                    "version": getattr(s_info, "version", "unknown"),
                },
                "protocol_version": str(p_ver),
            })

            # Step B: List Tools
            t_list = time.perf_counter()
            tools_response = await session.list_tools()
            elapsed_tools = (time.perf_counter() - t_list) * 1000
            tools_list = [
                {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": getattr(t, "input_schema", getattr(t, "inputSchema", {})),
                }
                for t in tools_response.tools
            ]
            print(f"\n[3] MCP tools/list ({len(tools_list)} tools discovered in {elapsed_tools:.1f}ms):")
            for t in tools_list:
                print(f"    - {t['name']}: {t['description'][:70]}...")

            protocol_transcript["steps"].append({
                "step": "tools/list",
                "latency_ms": elapsed_tools,
                "tool_count": len(tools_list),
                "tools": tools_list,
            })

            # Step C: Call permitted tool get_learner_history for LRN-001
            print("\n[4] Calling MCP tool: get_learner_history(learner_id='LRN-001')...")
            t_hist = time.perf_counter()
            hist_call = await session.call_tool(
                "get_learner_history",
                arguments={"learner_id": "LRN-001"},
            )
            elapsed_hist = (time.perf_counter() - t_hist) * 1000
            assert not hist_call.is_error, "get_learner_history should not fail"
            hist_payload = json.loads(hist_call.content[0].text)

            print(f"    -> Result: {hist_payload['record_count']} records retrieved in {elapsed_hist:.1f}ms")
            for ev in hist_payload["evidence"][:3]:
                print(f"       * [{ev['evidence_type']}] Year {ev['academic_year']} Term {ev['term']}: {ev['content']} (Source: {ev['source_system']}/{ev['source_reference']})")

            protocol_transcript["steps"].append({
                "step": "tools/call:get_learner_history",
                "arguments": {"learner_id": "LRN-001"},
                "latency_ms": elapsed_hist,
                "is_error": hist_call.is_error,
                "response_record_count": hist_payload["record_count"],
                "sample_records": hist_payload["evidence"][:3],
            })

            # Step D: Call permitted tool analyse_longitudinal_pattern for LRN-001 (Mathematics)
            print("\n[5] Calling MCP tool: analyse_longitudinal_pattern(learner_id='LRN-001', subject='Mathematics')...")
            t_an = time.perf_counter()
            an_call = await session.call_tool(
                "analyse_longitudinal_pattern",
                arguments={"learner_id": "LRN-001", "subject": "Mathematics"},
            )
            elapsed_an = (time.perf_counter() - t_an) * 1000
            assert not an_call.is_error, "analyse_longitudinal_pattern should not fail"
            patterns = [json.loads(c.text) for c in an_call.content]

            print(f"    -> Result: {len(patterns)} patterns discovered in {elapsed_an:.1f}ms")
            cited_evidence_ids: list[str] = []
            for pat in patterns:
                print(f"       * [{pat['pattern_type']}] {pat['summary']}")
                print(f"         Supporting Evidence ({len(pat['supporting_evidence'])} citations): {pat['supporting_evidence']}")
                cited_evidence_ids.extend(pat["supporting_evidence"])

            protocol_transcript["steps"].append({
                "step": "tools/call:analyse_longitudinal_pattern",
                "arguments": {"learner_id": "LRN-001", "subject": "Mathematics"},
                "latency_ms": elapsed_an,
                "is_error": an_call.is_error,
                "patterns_count": len(patterns),
                "patterns": patterns,
            })

            # Step E: Independently verify citation grounding in SQLite
            print(f"\n[6] Verifying Citation Grounding in SQLite Store ({len(cited_evidence_ids)} unique citations)...")
            citation_audit: list[dict[str, Any]] = []
            with sqlite3.connect(str(demo_db)) as conn:
                for eid in cited_evidence_ids:
                    row = conn.execute(
                        "SELECT evidence_id, learner_id, evidence_type, academic_year, term, content, source_system, observed_at "
                        "FROM evidence WHERE evidence_id = ?",
                        (eid,),
                    ).fetchone()
                    assert row is not None, f"Cited evidence ID {eid} NOT found in SQLite store!"
                    item = {
                        "evidence_id": row[0],
                        "learner_id": row[1],
                        "evidence_type": row[2],
                        "academic_year": row[3],
                        "term": row[4],
                        "content": json.loads(row[5]) if isinstance(row[5], str) else row[5],
                        "source_system": row[6],
                        "observed_at": row[7],
                    }
                    citation_audit.append(item)
                    print(f"    -> [VERIFIED CITATION] {item['evidence_id']} matches {item['evidence_type']} Y{item['academic_year']} T{item['term']} Score={item['content'].get('score')}/{item['content'].get('max_score')} (Observed: {item['observed_at']})")

            protocol_transcript["steps"].append({
                "step": "verify_citations_in_sqlite",
                "verified_count": len(citation_audit),
                "citations": citation_audit,
            })

            # Step F: Flag pattern for review (creates review item)
            trend_pattern_id = patterns[0]["pattern_id"]
            print(f"\n[7] Calling MCP tool: flag_pattern_for_review(pattern_id='{trend_pattern_id}')...")
            flag_call = await session.call_tool(
                "flag_pattern_for_review",
                arguments={"pattern_id": trend_pattern_id, "assigned_to": "TCH-BANDA"},
            )
            assert not flag_call.is_error
            flag_payload = json.loads(flag_call.content[0].text)
            review_id = flag_payload["review_id"]
            print(f"    -> Created Review Item {review_id} in state '{flag_payload['status']}'")

            protocol_transcript["steps"].append({
                "step": "tools/call:flag_pattern_for_review",
                "arguments": {"pattern_id": trend_pattern_id, "assigned_to": "TCH-BANDA"},
                "review_id": review_id,
                "status": flag_payload["status"],
            })

            # Step G: ATTEMPT UNAUTHORIZED AUTONOMOUS TEACHER APPROVAL
            print(f"\n[8] ATTEMPTING UNAUTHORIZED AUTONOMOUS TEACHER APPROVAL:")
            print(f"    Calling resolve_teacher_review(review_id='{review_id}', status='accepted', reviewer_id='autonomous-agent-007')...")
            unauth_call = await session.call_tool(
                "resolve_teacher_review",
                arguments={
                    "review_id": review_id,
                    "status": "accepted",
                    "reviewer_id": "autonomous-agent-007",
                    "teacher_notes": "Autonomous AI agent attempting self-approval",
                },
            )
            print(f"    -> Result is_error: {unauth_call.is_error}")
            error_message = unauth_call.content[0].text if unauth_call.content else "No message"
            print(f"    -> MCP Error Payload: {error_message}")
            assert unauth_call.is_error, "Autonomous agent approval MUST be rejected by MCP server!"
            assert "error executing tool resolve_teacher_review" in error_message.lower() or "cannot self-approve" in error_message.lower(), f"Unexpected error: {error_message}"
            print("    -> [SECURITY GATE CONFIRMED] Self-approval blocked over MCP protocol (is_error=True)!")

            protocol_transcript["steps"].append({
                "step": "tools/call:resolve_teacher_review (UNAUTHORIZED SELF-APPROVAL)",
                "arguments": {
                    "review_id": review_id,
                    "status": "accepted",
                    "reviewer_id": "autonomous-agent-007",
                },
                "is_error": unauth_call.is_error,
                "error_payload": error_message,
                "rejection_confirmed": True,
            })

            # Step H: CALL PERMITTED REVIEW RESOLUTION (needs_context)
            print(f"\n[9] Calling permitted review resolution: status='needs_context'...")
            context_call = await session.call_tool(
                "resolve_teacher_review",
                arguments={
                    "review_id": review_id,
                    "status": "needs_context",
                    "reviewer_id": "autonomous-audit-agent",
                    "teacher_notes": "Autonomous agent requested observational context for Term 2 decline.",
                },
            )
            assert not context_call.is_error, "needs_context should be permitted for non-approval interactions"
            context_payload = json.loads(context_call.content[0].text)
            print(f"    -> Permitted Status Update: {context_payload['status']} (Notes: '{context_payload['teacher_notes']}')")

            protocol_transcript["steps"].append({
                "step": "tools/call:resolve_teacher_review (PERMITTED NEEDS_CONTEXT)",
                "arguments": {
                    "review_id": review_id,
                    "status": "needs_context",
                    "reviewer_id": "autonomous-audit-agent",
                },
                "is_error": context_call.is_error,
                "status": context_payload["status"],
            })

            # Step I: Verify surfaced profile strictly excludes unapproved pattern
            print("\n[10] Calling MCP tool: get_surfaced_profile(learner_id='LRN-001')...")
            surf_call = await session.call_tool(
                "get_surfaced_profile",
                arguments={"learner_id": "LRN-001"},
            )
            assert not surf_call.is_error
            surf_payload = json.loads(surf_call.content[0].text)
            print(f"    -> Surfaced Profile Patterns Count: {len(surf_payload['patterns'])}")
            assert len(surf_payload["patterns"]) == 0, "Unapproved pattern MUST NOT appear in surfaced profile!"
            print("    -> [GOVERNANCE CONFIRMED] Learner profile remains strictly clean of unapproved findings.")

            protocol_transcript["steps"].append({
                "step": "tools/call:get_surfaced_profile",
                "arguments": {"learner_id": "LRN-001"},
                "is_error": surf_call.is_error,
                "surfaced_patterns_count": len(surf_payload["patterns"]),
            })

    # Save protocol transcript
    output_file = root_dir / "data" / "mcp_wire_protocol_demonstration.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(protocol_transcript, f, indent=2)
    print(f"\n[SUCCESS] Wire protocol demonstration completed! Full transcript saved to {output_file.name}")
    print("=" * 80)
    return protocol_transcript


if __name__ == "__main__":
    asyncio.run(run_mcp_protocol_demonstration())
