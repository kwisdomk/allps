"""Reproducible runner for ALLPS Model-Directed MCP Import Agent.

Demonstrates model-directed tool selection across TWO independent MCP servers:
1. @modelcontextprotocol/server-filesystem (Filesystem MCP server over stdio)
2. allps.mcp.server (ALLPS FastMCP server over stdio)

Uses local Qwen inference through LM Studio (http://127.0.0.1:1234/v1).

Usage:
    python examples/run_agentic_mcp_import.py [--learner LRN-001] [--db data/allps_dev.db]
"""

import asyncio
import os
from pathlib import Path
import sys

# Ensure repo root and src/ are on sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "src"))

from allps.agent.mcp_agent import AgentMCPConfig, run_agentic_workflow
from data.synthetic.seed_data import seed_database


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="ALLPS Two-Server Agentic MCP Import Runner")
    parser.add_argument("--learner", default="LRN-001", help="Target learner ID")
    parser.add_argument("--db", default="data/allps_mcp_live.db", help="Database path")
    parser.add_argument("--model", default="allps-qwen35-base-4b", help="LM Studio model ID")
    parser.add_argument("--url", default="http://127.0.0.1:1234/v1", help="LM Studio endpoint")
    parser.add_argument(
        "--trace-out",
        default="data/trace_agentic_mcp_run.json",
        help="Path for saving execution trace",
    )
    args = parser.parse_args()

    db_path = str(repo_root / args.db)
    imports_dir = str(repo_root / "data" / "mcp_imports")
    trace_path = str(repo_root / args.trace_out)

    print("=" * 75)
    print("ALLPS — FINAL AGENTIC MCP INTEGRATION RUNNER")
    print("=" * 75)
    print(f"Target Learner     : {args.learner}")
    print(f"Local Model ID     : {args.model}")
    print(f"LM Studio Endpoint : {args.url}")
    print(f"Database File      : {db_path}")
    print(f"MCP Imports Dir    : {imports_dir}")
    print(f"Trace Output File  : {trace_path}")
    print("-" * 75)

    # 1. Ensure database exists and is seeded with baseline learner data
    if not os.path.exists(db_path):
        print("[Setup] Seeding initial database with baseline learner data...")
        await seed_database(db_path)
    else:
        print("[Setup] Using existing database file.")

    # 2. Build configuration
    config = AgentMCPConfig(
        lm_studio_url=args.url,
        model_name=args.model,
        db_path=db_path,
        imports_dir=imports_dir,
        bound_learner_id=args.learner,
    )

    # 3. User task instruction
    user_task = (
        f"Execute the evidence import workflow for learner {config.bound_learner_id} in {config.imports_dir}: "
        "1. List the directory and read the export files once. "
        "2. Ingest the valid observation record into ALLPS while noting the validation error on the malformed record. "
        "3. Retrieve the learner's history and run longitudinal pattern analysis on Mathematics assessments (evidence_type='assessment'). "
        "4. Flag the resulting pattern for teacher review and summarize your findings."
    )

    print("\n[Executing] Launching Pydantic AI Agent with dual MCP servers...")
    print(f"[Task Prompt] {user_task}\n")

    # 4. Execute the agentic workflow
    trace = await run_agentic_workflow(config, user_prompt=user_task)

    # 5. Output results
    print("=" * 75)
    print(f"VERDICT: {trace.verdict}")
    print("=" * 75)
    print(f"Trace ID                      : {trace.trace_id}")
    print(f"Total Tool Calls Executed     : {len(trace.tool_calls)}")
    print(f"Persisted Evidence Count      : {len(trace.persisted_evidence)}")
    print(f"Candidate Reviews Flagged     : {len(trace.candidate_reviews)}")
    print(f"Failed Steps / Safe Recoveries: {len(trace.failed_steps)}")
    print(f"Governance Verified (Pending) : {trace.governance_verified}")
    print(f"Human Sovereign Acceptance    : {trace.human_acceptance_confirmed}")
    print("-" * 75)
    print("CHRONOLOGICAL TOOL EXECUTION LOG:")
    for idx, tc in enumerate(trace.tool_calls, 1):
        status_tag = f"[{tc.status.upper()}]"
        print(f"  {idx:02d}. [{tc.server_id.upper():10s}] {tc.tool_name:<28s} {status_tag:<12s} ({tc.duration_ms:6.1f}ms)")
        if tc.input_args:
            # show clean args summary
            clean_args = {k: v for k, v in tc.input_args.items() if k != "content"}
            if "content" in tc.input_args:
                clean_args["content"] = "{...}"
            print(f"       args: {clean_args}")
        if tc.error:
            print(f"       error/recovery: {tc.error}")
    print("-" * 75)
    print("AGENT FINAL SUMMARY:")
    print(trace.final_output)
    print("-" * 75)

    # 6. Save machine-readable trace
    trace.save_json(trace_path)
    print(f"\nTrace written to: {trace_path}")
    print("=" * 75)

    return 0 if "PASS" in trace.verdict else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
