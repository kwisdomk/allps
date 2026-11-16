# ALLPS — Workstream 5: Reproducibility & Test Execution Report

**Audited Snapshot**: Commit `b504e0c647f14718d062b186ab8613af189ea29f`  
**Execution Environment**: Python 3.14.7 (AMD64) / Windows 11 / Node.js  
**Date**: 15 October 2026  
**Auditor**: Independent Maintainer Review  

---

## 1. Executive Summary & Test Results

The full test suite was executed against the submitted codebase without introducing any new packages, modifying dependencies, or altering application code.

### Test Execution Summary
* **Total Tests Executed**: **252**
* **Passed**: **252**
* **Failures**: **0**
* **Errors**: **0**
* **Execution Duration**: **127.06s** (02:07)
* **Status**: **100% REPRODUCIBLE & VERIFIED**

```text
============================= test session starts =============================
platform win32 -- Python 3.14.7, pytest-8.3.4, pluggy-1.5.0
asyncio: mode=Mode.AUTO
rootdir: Q:\ALLPS
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.8.0, asyncio-0.25.2
collected 252 items

........................................................................ [ 28%]
........................................................................ [ 57%]
........................................................................ [ 85%]
....................................                                     [100%]

============================ 252 passed in 127.06s ============================
```

---

## 2. Test Suite Breakdown by Architectural Domain

| Test Module | Test Count | Focus Area & Verified Behaviors |
| :--- | :-: | :--- |
| [`tests/test_agent_orchestration.py`](../../tests/test_agent_orchestration.py) | **19** | Pydantic AI agent, prompt injection resilience, citation grounding validation, fallback routing. |
| [`tests/test_analysis_service.py`](../../tests/test_analysis_service.py) | **31** | 9-key longitudinal comparability, trend calculation, persistence calculation, divergence detection. |
| [`tests/test_audit_fixes.py`](../../tests/test_audit_fixes.py) | **11** | Edge cases in rubrics, missing data handling, and schema migrations. |
| [`tests/test_demo_e2e.py`](../../tests/test_demo_e2e.py) | **5** | End-to-end multi-term teacher workflow with mock LLM inference. |
| [`tests/test_evidence_service.py`](../../tests/test_evidence_service.py) | **11** | Evidence ingestion, validation, chronological sorting, and source tagging. |
| [`tests/test_mcp_tools.py`](../../tests/test_mcp_tools.py) | **22** | FastMCP server tool execution, JSON-RPC schemas, parameter validation. |
| [`tests/test_models.py`](../../tests/test_models.py) | **15** | Pydantic model serialization, UUID generation, enum constraints. |
| [`tests/test_peer_comparison_gap.py`](../../tests/test_peer_comparison_gap.py) | **27** | Strict detection and blocking of direct/indirect peer rankings. |
| [`tests/test_phase2_analysis_repairs.py`](../../tests/test_phase2_analysis_repairs.py) | **23** | Complex multi-scale rubric reconciliations and missing-term handling. |
| [`tests/test_phase2_governance.py`](../../tests/test_phase2_governance.py) | **44** | Teacher review gate, non-agent approval enforcement, SHA-256 snapshots, revision isolation. |
| [`tests/test_preview_flow.py`](../../tests/test_preview_flow.py) | **8** | Observation preview modal, draft validation, UI stage state transitions. |
| [`tests/test_regression.py`](../../tests/test_regression.py) | **16** | Cross-term data consistency and schema backward-compatibility. |
| [`tests/test_runtime_discovery.py`](../../tests/test_runtime_discovery.py) | **8** | LM Studio / Ollama provider discovery and model readiness probing. |
| [`tests/test_storage.py`](../../tests/test_storage.py) | **8** | SQLite WAL mode, async transactions, connection pooling, and rollback. |
| [`tests/test_web_api.py`](../../tests/test_web_api.py) | **4** | FastAPI REST endpoints, reload persistence, review submission. |
| **Total** | **252** | **100% Pass Rate Across All 15 Test Modules** |

---

## 3. Verification of Documented Startup Commands

Every command documented in [`README.md`](../../README.md) and [`ARCHITECTURE.md`](../architecture.md) (now `docs/architecture.md`) was executed and audited:

### 3.1 Synthetic Seed Ingestion
* **Command**: `python -m data.synthetic.seed_data allps_demo.db`
* **Exit Code**: `0` (Success)
* **Duration**: `2.75s`
* **Output Verified**: Created 3 CBC learners (`LRN-001`, `LRN-002`, `LRN-003`) and 27 multi-term evidence records.
* **Audit Finding**: Confirmed that the positional argument syntax works as implemented, whereas the documented `--target` flag was a documentation typo.

### 3.2 MCP Wire Protocol Demonstration
* **Command**: `python examples/demonstrate_mcp_wire_protocol.py`
* **Exit Code**: `0` (Success)
* **Duration**: `11.49s`
* **Output Verified**: 
  1. Initialized FastMCP stdio client.
  2. Executed standard MCP handshake: protocol version `2024-11-05`.
  3. Discovered 7 server tools.
  4. Executed `get_learner_history` for `LRN-001`.
  5. Attempted autonomous agent self-approval (`reviewer_id="autonomous-agent-007"`) $\to$ **Denied with `is_error=True` (`PermissionError`)**.
  6. Verified `get_surfaced_profile` remained strictly empty (0 findings leaked).

### 3.3 Teacher Workspace Web Server Smoke Test
* **Command**: `python -m allps.web.app --host 127.0.0.1 --port 8000 --db allps_demo.db`
* **HTTP Smoke Tests**:
  - `GET /` $\to$ `200 OK` (11,975 bytes)
  - `GET /api/config` $\to$ `200 OK` (`review_authority_available: true`, `server_reviewer_id: "TCH-BANDA"`)
  - `GET /api/learners` $\to$ `200 OK` (Returns all 3 learners)
  - `GET /api/learners/LRN-001/evidence` $\to$ `200 OK` (Returns 9 chronological evidence records)

### 3.4 Live Dual-Server MCP Import Runner
* **Command**: `python examples/run_agentic_mcp_import.py --db .audit-runtime/live-mcp.db --trace-out docs/closeout/evidence/live-mcp-rerun.json`
* **Exit Code**: `0` (Success)
* **Duration**: `99.0s`
* **Trace Produced**: Trace ID `938462af-28b0-4e94-893e-03c8ea4d8bb4`
* **Output Verified**: Autonomously connected to both `@modelcontextprotocol/server-filesystem` and `allps.mcp.server`, executed 7 tool calls, parsed multi-file inputs, ingested valid records, performed longitudinal analysis, and placed findings in `PENDING` review state.

---

## 4. Hardware Benchmarks & Runtime Resource Footprint

Measurements taken during active test execution and live local inference:

| Resource Metric | Measured Value | Operational Assessment |
| :--- | :--- | :--- |
| **Python Memory (RAM)** | ~145 MB | Very lightweight; runs comfortably on any standard laptop or desktop. |
| **Test Suite VRAM Usage** | 0 MB (CPU only) | Unit and integration test suites run entirely without requiring a GPU. |
| **LM Studio VRAM Footprint** | **3.2 GiB** | `qwen3.5-4b` (Q4_K_M GGUF, 8k context) fits easily within a 4GB or 6GB GPU. |
| **Inference Latency Range** | **535ms – 33.25s** | Simple tool probes return in <2s; full candidate brief syntheses require 15–33s on consumer CUDA hardware. |
| **CUDA OOM Boundary** | **> 7B Parameters** | Unquantized 7B models demand >14.2 GiB VRAM and fail on 8GB consumer GPUs. |
