# ALLPS — Workstream 3: Documentation Quality Audit & Operator Guide

**Audited Snapshot**: Commit `b504e0c647f14718d062b186ab8613af189ea29f`  
**Closeout Branch**: `docs/post-submission-closeout`  
**Date**: 15 October 2026  
**Auditor**: Independent Maintainer Review  

---

## 1. Executive Summary

This document performs an exhaustive audit of all user-facing and technical documentation in the ALLPS repository ([`README.md`](../../README.md), [`ARCHITECTURE.md`](../../ARCHITECTURE.md), [`EVALS.md`](../../EVALS.md), [`docs/SUBMISSION.md`](../SUBMISSION.md), and [`docs/contracts.md`](../contracts.md)).

In strict compliance with the **Hard Constraints** ("*Separate any post-submission documentation corrections from the original submission snapshot*"), all corrections and operational guides are documented here on the closeout branch, preserving the submitted Git commit `b504e0c` as a frozen baseline.

---

## 2. Forensic Corrections & Factual Clarifications

| # | Item / Document | Documented / Submitted Wording | Verified Reality | Forensic Clarification & Correction |
| :-: | :--- | :--- | :--- | :--- |
| **1** | **Synthetic Seed Command**<br>`README.md:165` | `python -m data.synthetic.seed_data --target allps_demo.db` | `seed_data.py:630` parses positional `sys.argv[1]` | The script does not accept a `--target` flag. Running with `--target` creates a database file named literally `"--target"`.<br>**Correct command**: `python -m data.synthetic.seed_data allps_demo.db` |
| **2** | **MCP Runner Trace Overwrite**<br>`examples/run_agentic_mcp_import.py` | `python examples/run_agentic_mcp_import.py` | Line 37 defaults `--trace-out` to `data/trace_agentic_mcp_run.json` | Executing the script with default arguments overwrites the tracked, original submission trace.<br>**Correction**: Always pass an explicit output destination: `--trace-out docs/closeout/evidence/my_trace.json` |
| **3** | **Web Dependencies in Packaging**<br>`pyproject.toml` | Dependencies only list: `pydantic`, `aiosqlite`, `mcp`, `pydantic-ai` | `src/allps/web/app.py` imports `fastapi` and runs under `uvicorn`; tests require `httpx` | A clean `pip install -e .` will fail to run the web server without installing FastAPI dependencies.<br>**Correction**: Documented prerequisite: `pip install fastapi uvicorn httpx` |
| **4** | **Inference Latency Claims**<br>`README.md:120`, `ARCHITECTURE.md:55` | *"sub-5s local inference"*, *"<5s latency"*, *"<4.8s per cycle"* | Server logs show latencies from 535ms to 33,248ms (33.25s); 10 of 25 calls exceeded 5s | While simple tool probes and status responses run in ~500ms–2s, complex candidate generation and multi-file analysis require 15–33 seconds on local 4-bit GPU inference.<br>**Correction**: Latency is variable; SLA claims revised to reflect realistic consumer GPU bounds. |
| **5** | **Local Model Identification**<br>`README.md:120`, `ARCHITECTURE.md:108` | `allps-qwen35-base-4b (Qwen2.5-3B / Qwen2.5-4B 4-bit quantized GGUF)` | LM Studio runtime has `qwen3.5-4b` loaded under ID `allps-qwen35-base-4b` | References to Qwen 2.5 were legacy annotations from earlier exploratory testing. The active loaded model architecture is confirmed as **Qwen 3.5 4B** (`qwen35`). |
| **6** | **MCP Tool Failure vs. Input Isolation**<br>`EVALS.md:152`, `SUBMISSION.md:36` | Expected tool validation error and recovery inside tool execution | Preserved trace records 7 of 7 tool calls as `status="success"` with 0 tool errors | The model parsed `teacher_export_LRN001_malformed.json`, detected invalid schema fields in context, and avoided invoking `ingest_evidence` on it. Recovery occurred via LLM reasoning rather than a caught tool exception. |
| **7** | **Public Portal Scope**<br>`README.md:3`, `SUBMISSION.md:5` | `https://allps.kwaix.dev` | Static informational landing page | `allps.kwaix.dev` does **not** host a live AI model or execute MCP backends. It is an informational project summary. All AI inference and MCP operations are strictly local. |

---

## 3. What ALLPS Actually Implements

ALLPS implements a production-grade, local-first learner profile architecture comprising:

1. **Atomic Evidence Ledger**: An append-only SQLite store ([`src/allps/storage/sqlite_store.py`](../../src/allps/storage/sqlite_store.py)) recording classroom assessments, attendance logs, and qualitative teacher observations with source attribution (`source_system`, `recorded_by_id`, `recorded_at`).
2. **9-Key Longitudinal Comparability Engine**: A deterministic analysis service ([`src/allps/services/analysis_service.py`](../../src/allps/services/analysis_service.py)) enforcing strict series alignment across subject, grade, skill, form version, language, rubric scale, and assessment stage before computing trends or persistence.
3. **Prohibited Deficit Screening**: A non-negotiable policy module ([`src/allps/policies/label_policy.py`](../../src/allps/policies/label_policy.py)) that deterministically blocks deficit labels (*"slow learner"*, *"dull"*, *"hopeless"*) and direct or indirect peer rankings (*"bottom 10%"*, *"below average"*).
4. **FastMCP Server**: Standardized MCP stdio server ([`src/allps/mcp/server.py`](../../src/allps/mcp/server.py)) exposing 7 tools for evidence ingestion, history retrieval, pattern analysis, and human review gating.
5. **Dual-Server Agentic Orchestration**: A Pydantic AI agent ([`src/allps/agent/mcp_agent.py`](../../src/allps/agent/mcp_agent.py)) connecting simultaneously to the official Filesystem MCP server and ALLPS FastMCP server over stdio.
6. **Sovereign Teacher Review Gate**: A human-in-the-loop workflow ([`src/allps/services/review_service.py`](../../src/allps/services/review_service.py)) ensuring AI candidate briefs remain strictly in `PENDING` state until an authorized educator reviews, provides contextual notes, and accepts the finding. Acceptance generates an immutable SHA-256 cryptographic snapshot.
7. **Single-Page Teacher Workspace**: A responsive web interface ([`src/allps/web/`](../../src/allps/web)) providing evidence stream visualization, observation entry with dual timestamps, side-panel citation drawers, candidate brief review, and approved handover profile viewing.

---

## 4. Operator Guide: Step-by-Step Instructions

### 4.1 How to Configure LM Studio and Qwen 3.5

1. **Download & Install LM Studio**: Ensure version $\ge$ 0.3.0 is installed.
2. **Download Model**:
   - In LM Studio Search, download `qwen3.5-4b` (recommended quantization: `Q4_K_M` GGUF by lmstudio-community).
3. **Load Model**:
   - Go to the **Local Server** tab in LM Studio.
   - Select `qwen3.5-4b` from the model dropdown.
   - Set **Context Length** to `8192` tokens.
   - Verify GPU acceleration is enabled (e.g. CUDA layer offloading).
4. **Set Model Identifier**:
   - In the Server settings, assign the model ID: `allps-qwen35-base-4b`.
5. **Start Server**:
   - Click **Start Server** on port `1234` (`http://127.0.0.1:1234`).
   - Verify readiness:
     ```powershell
     curl http://127.0.0.1:1234/api/v0/models
     ```
     Ensure `"id": "allps-qwen35-base-4b"` is present and `"state": "loaded"`.

### 4.2 How to Start the Application Locally

```bash
# 1. Activate virtual environment
.venv\Scripts\activate

# 2. Seed database with synthetic Kenyan demonstration cohort
python -m data.synthetic.seed_data allps_dev.db

# 3. Start Teacher Workspace Server
python -m allps.web.app --host 127.0.0.1 --port 8000 --db allps_dev.db --mode auto --reviewer TCH-BANDA
```
* Open your browser to `http://127.0.0.1:8000`.

### 4.3 How to Execute the MCP Workflow

#### A. Wire Protocol Demonstration (No LLM required)
```bash
python examples/demonstrate_mcp_wire_protocol.py
```
* Demonstrates standard JSON-RPC 2.0 handshake over stdio, tool discovery, history querying, and autonomous self-approval denial.

#### B. Live Dual-Server Agentic MCP Import (Requires LM Studio)
```bash
# Ensure LM Studio is running on 127.0.0.1:1234
python examples/run_agentic_mcp_import.py --learner LRN-001 --db data/allps_mcp_live.db --trace-out docs/closeout/evidence/my_trace.json
```
* The agent connects to Node.js Filesystem MCP and Python ALLPS FastMCP, reads files from `data/mcp_imports/`, ingests valid records, runs longitudinal pattern analysis, and flags findings for teacher review.

### 4.4 How to Run Tests

```bash
# Run complete test suite (252 tests)
python -m pytest -v

# Run targeted test suites
python -m pytest tests/test_agent_orchestration.py -v
python -m pytest tests/test_analysis_service.py -v
python -m pytest tests/test_mcp_tools.py -v
python -m pytest tests/test_phase2_governance.py -v
```

### 4.5 How to Review Learner Evidence in Teacher Workspace

1. **Select Learner**: In the header dropdown, choose `Learner 001 (LRN-001)`.
2. **Examine Evidence Stream**: Review the chronological assessment and observation cards.
3. **Inspect Citations**: Click any evidence citation pill to open the right side-panel drawer showing exact source attribution, rubric criteria, and ingestion method.
4. **Generate AI Handover**:
   - Navigate to the **Candidate Review** tab.
   - Click `⚡ Generate AI Candidate Handover`.
   - The system executes local inference via LM Studio (or deterministic fallback if LM Studio is offline).
   - Generated findings appear with `PENDING` review status.
5. **Adjudicate Finding**:
   - Enter qualitative pedagogical notes in the teacher context box.
   - Click `✓ Accept Finding` (or `✕ Reject` / `? Needs Context`).
   - Acceptance computes and displays the SHA-256 cryptographic snapshot badge.
6. **Verify Published Handover**:
   - Switch to the **Approved Handover** tab.
   - Confirm only accepted findings appear; unreviewed candidate material is strictly excluded.

---

## 5. Experimental Features & Unresolved Engineering Problems

1. **Unquantized 7B Model VRAM Exhaustion**:
   - Attempting to run unquantized 7B models (`DeepSeek-R1-Distill-Qwen-7B` or `Qwen2.5-7B-Instruct`) on consumer GPUs with 8GB VRAM triggers CUDA Out-Of-Memory exceptions (`failed to allocate 14.2 GiB on CUDA:0`).
   - Mitigated by adopting 4-bit quantized `allps-qwen35-base-4b` (~3.2 GiB VRAM footprint).
2. **Multi-Turn LLM Recovery vs. Single-Turn Tool Use**:
   - Single-turn model-directed tool selection reliably chooses correct tools. However, multi-turn conversational error recovery under complex multi-server state remains an experimental research area.
3. **Automated Cross-School Federated Synchronization**:
   - The current MCP implementation operates over local stdio. Cross-school network federation over HTTP/SSE transports is planned for future phases.

---

## 6. Known Security & Architecture Limitations

1. **Demonstration Authentication Boundary**:
   - In the submission prototype, the teacher identity (`TCH-BANDA`) is configured server-side via command-line flag `--reviewer` or API header. It is a prototype demonstration setting, not a cryptographically verified SSO or OAuth2 token.
2. **Single-Node SQLite Concurrency**:
   - The SQLite storage backend uses WAL mode and atomic write transactions. While highly efficient for single-school deployments, it does not support high-concurrency multi-master distributed clustering.
3. **Adversarial Prompt Injection via Unstructured Observations**:
   - Deficit label policy screening deterministically detects prohibited keywords and ranking patterns. However, sophisticated adversarial prompt injection embedded inside qualitative observation free-text remains a known research limitation. The strict human review gate ensures malicious text cannot enter the published profile without explicit teacher approval.
