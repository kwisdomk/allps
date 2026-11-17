# ALLPS — Workstream 2: Release Preservation Manifest

**Target Release**: v0.1.0 — African Agentic AI Design Challenge  
**Frozen Submission Commit**: `b504e0c647f14718d062b186ab8613af189ea29f`  
**Tag on Origin**: `v1.0.0-challenge-submission` (Tag Object: `c13db9772dbe09f16bb824d32c440ce09f8b0855`)  
**Repository**: [https://github.com/kwisdomk/ALLPS](https://github.com/kwisdomk/ALLPS)  
**Preservation Date**: 15 October 2026  

---

## 1. Preservation Archives & Cryptographic Hashes

To guarantee that the submitted release can be reconstructed bit-for-bit without relying on undocumented local state or internet availability, two standalone preservation artifacts have been produced and verified:

| Artifact | File Name | Size (Bytes) | SHA-256 Checksum | Contents & Verification |
| :--- | :--- | :--- | :--- | :--- |
| **Git Bundle** | `allps-all-refs.bundle` | 6,275,531 | `3c63b43a2825c09d4d1e5b0e994dc7d232fc8af1f6f47594f7a7c6f35d875222` | Complete uncompressed Git history across all 12 refs (branches, tags, remotes, worktrees). Verified via `git bundle verify`. |
| **Clean Source Zip** | `allps-submission-b504e0c.zip` | 6,677,603 | `ebe2e185d0084ff5114c6be51ad2c1a9189dc24329cdea56586d00db9b43cea9` | Clean export of commit `b504e0c` tracked files. Excludes untracked databases, node_modules, and cache files. |

Both preservation archives are stored locally at:
`.audit-runtime/preservation/`

---

## 2. Inventory of Submitted Deliverables

Every submission deliverable defined by the challenge rubric was inspected, verified, and mapped to its exact repository path and Git blob hash:

### 2.1 Core Source Code & Packaging
* **Package Definition**: [`pyproject.toml`](../../pyproject.toml) (Blob: `6c478a5...`, Version `0.1.0`)
* **Node MCP Dependencies**: [`package.json`](../../package.json), [`package-lock.json`](../../package-lock.json) (`@modelcontextprotocol/server-filesystem` v1.0.0)
* **Application Package**: [`src/allps/`](../../src/allps)
  - `agent/`: Orchestrator, Pydantic AI MCP agent, OutputValidator, contracts
  - `mcp/`: FastMCP server exposing evidence storage and longitudinal analysis tools
  - `models/`: Pydantic domain models (`Learner`, `Evidence`, `Pattern`, `ReviewItem`, `AuditEntry`)
  - `policies/`: Non-negotiable label screening policy (`label_policy.py`)
  - `runtime/`: Model discovery, readiness probing, execution mode selection (`RuntimeRegistry`)
  - `services/`: Longitudinal analysis engine (`AnalysisService`), Evidence ledger (`EvidenceService`), Human review gate (`ReviewService`)
  - `storage/`: Async SQLite ledger with atomic write transactions (`SQLiteStore`)
  - `web/`: FastAPI backend routes (`routes.py`) and single-page teacher workspace (`static/`)

### 2.2 Primary Documentation & Governance Contracts
* [`README.md`](../../README.md) (24,740 bytes) — Project overview, CBC educational context, 13 checklist items, architecture, and quickstart.
* [`ARCHITECTURE.md`](../architecture.md) (14,327 bytes; moved to `docs/architecture.md`) — System boundaries, protocol layers, dual MCP architecture, and governance flow.
* [`EVALS.md`](../evals.md) (21,103 bytes; moved to `docs/evals.md`) — 9 verified evaluation tasks, real hardware benchmarks, and failure investigations.
* [`docs/submission.md`](../submission.md) (5,956 bytes) — Official 300-word submission statement and 3-minute video storyboard.
* [`LICENSE`](../../LICENSE) (1,075 bytes) — OSI-Approved MIT License.
* [`docs/contracts.md`](../contracts.md) (12,673 bytes) — Technical data schemas and governance state transition contracts.
* [`docs/ai_contract.md`](../ai_contract.md) (10,709 bytes) — Citation grounding and prohibited label safety contracts.
* [`docs/data_quality.md`](../data_quality.md) (10,663 bytes) — 9-key longitudinal comparability rules and missing data handling.

### 2.3 MCP Server & Agentic Orchestration
* **Custom MCP Server**: [`src/allps/mcp/server.py`](../../src/allps/mcp/server.py)
  - Exposes 4 core tools: `get_learner_history`, `ingest_evidence`, `analyse_longitudinal_pattern`, `flag_pattern_for_review`.
  - Exposes 3 wire demonstration tools: `get_surfaced_profile`, `record_teacher_observation`, `submit_review_decision`.
  - Transport: `stdio` (FastMCP).
* **Official Filesystem MCP Server**: `@modelcontextprotocol/server-filesystem` over stdio via `npx` / `node`.
* **Agentic Orchestration**: [`src/allps/agent/mcp_agent.py`](../../src/allps/agent/mcp_agent.py)
  - Uses Pydantic AI (`Agent`) with stdio client connections to both MCP servers simultaneously.
  - Model autonomously selects tools, reads external teacher exports, filters malformed records, ingests valid evidence, retrieves learner history, performs longitudinal trend analysis, and queues candidate findings for teacher review.

### 2.4 Genuine Execution Evidence
* **Submitted Live Trace**: [`data/trace_agentic_mcp_run.json`](../../data/trace_agentic_mcp_run.json)
  - Trace ID: `1cb86194-619c-43ce-a079-95f8cd791d60`
  - Timestamp: `2026-10-15T03:08:54.581695+00:00`
  - Model: `allps-qwen35-base-4b` via LM Studio (`http://127.0.0.1:1234/v1`)
  - Tool Calls: 7 successful calls across `filesystem` (3) and `allps` (4).
* **Audit Re-run Trace**: [`docs/closeout/evidence/live-mcp-rerun.json`](evidence/live-mcp-rerun.json)
  - Trace ID: `938462af-28b0-4e94-893e-03c8ea4d8bb4`
  - Timestamp: `2026-10-15T04:58:02.318553+00:00`
  - Proves 100% end-to-end reproducibility of model-directed tool calling on the submitted codebase.

### 2.5 Synthetic Sample Data & Test Fixtures
* [`data/synthetic/seed_data.py`](../../data/synthetic/seed_data.py) — 3 CBC demonstration learners (`LRN-001`, `LRN-002`, `LRN-003`) with 27 multi-term evidence records designed to test trend, persistence, and divergence patterns.
* [`data/mcp_imports/teacher_export_LRN001_valid.json`](../../data/mcp_imports/teacher_export_LRN001_valid.json) — Valid CBC teacher observation fixture.
* [`data/mcp_imports/teacher_export_LRN001_malformed.json`](../../data/mcp_imports/teacher_export_LRN001_malformed.json) — Deliberately malformed fixture for testing input isolation.

### 2.6 External References & Public Demonstration
* **Video Demonstration**: [https://youtu.be/MXhL38vzq-s](https://youtu.be/MXhL38vzq-s)
  - Verified title: *"ALLPS — Agentic AI & MCP for African Education | Demo."*
  - Channel: kwaixFIT (Duration: 2m 45s).
  - Demonstrates: MCP wire protocol, teacher observation entry, live Qwen AI synthesis, teacher review gate, cryptographic SHA-256 snapshot, and reload persistence.
* **Public Information Page**: [https://allps.kwaix.dev](https://allps.kwaix.dev)
  - Hosted static page describing the project mission and architecture.
  - Includes explicit disclaimer: *"This is a project information page, not a live AI demonstration or an active API endpoint."*

---

## 3. Canonical Execution Commands for Clean Reconstruction

To reconstruct and run the submitted release on a clean workstation without relying on any undocumented environment state:

### 3.1 Environment Prerequisites
* Python $\ge$ 3.11 (tested on Python 3.14.7 64-bit on Windows 11)
* Node.js $\ge$ 18.0 (for `@modelcontextprotocol/server-filesystem`)
* LM Studio $\ge$ 0.3.0 (with `qwen3.5-4b` 4-bit GGUF loaded under identifier `allps-qwen35-base-4b` on port 1234)

### 3.2 Step-by-Step Reconstruction

```bash
# 1. Clone repository
git clone https://github.com/kwisdomk/ALLPS.git
cd ALLPS
git checkout b504e0c647f14718d062b186ab8613af189ea29f

# 2. Install Node MCP dependencies
npm install

# 3. Create and activate Python virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 4. Install Python dependencies
pip install -e .
pip install pytest pytest-asyncio fastapi uvicorn httpx

# 5. Run test suite (verifies all 252 tests pass)
python -m pytest -v

# 6. Seed synthetic demonstration database (positional argument)
python -m data.synthetic.seed_data allps_demo.db

# 7. Run MCP Wire Protocol Demonstration
python examples/demonstrate_mcp_wire_protocol.py

# 8. Start Teacher Web Interface
python -m allps.web.app --port 8000 --db allps_demo.db

# 9. (Optional) Run Live Dual-Server MCP Import Agent (requires LM Studio)
python examples/run_agentic_mcp_import.py --db data/allps_mcp_live.db --trace-out docs/closeout/evidence/new_trace.json
```
