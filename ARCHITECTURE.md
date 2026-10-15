# ALLPS — System Architecture & Technical Design

> **Challenge Track**: Education: The Long View — African Agentic AI Design Challenge  
> **Repository**: `Q:\ALLPS`  
> **Core Tenet**: *"Record evidence without reducing learners to labels."*

---

## 1. One-Page Architecture Map

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                               EXTERNAL AGENTS & MCP CLIENTS                            │
│                  (Claude Desktop, Cursor, Goose, Custom Agent Scripts)                 │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ Standard Stdio Transport (JSON-RPC 2.0)
┌───────────────────────────────────────────▼────────────────────────────────────────────┐
│                    OUR SEVEN-TOOL FASTMCP SERVER [allps.mcp.server]                    │
│   • ingest_evidence             • get_learner_history    • analyse_longitudinal_pattern│
│   • flag_pattern_for_review     • resolve_teacher_review • get_pending_reviews         │
│   • get_surfaced_profile        (Enforces schema, frozen models, and non-agent gates)  │
└─────────────────────┬─────────────────────────────────────────────────────┬────────────┘
                      │                                                     │
┌─────────────────────▼───────────────────────┐   ┌─────────────────────────▼────────────┐
│ BORROWED MCP SERVER: Filesystem MCP Server │   │       EDUCATOR WORKSPACE (SPA)       │
│  [@modelcontextprotocol/server-filesystem]  │   │ Pure Vanilla JS (ES2022) + Apple HIG │
│  • Reads raw local CSV / JSON school records│   │ • Evidence Timeline & Citation Drawer│
│  • Status: Verified via dual-server agent   │   │ • Idempotent Observation Form        │
└─────────────────────┬───────────────────────┘   └─────────────────────────┬────────────┘
                      │ Raw records                                         │ HTTP REST API
                      ▼                                                     ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        PREDEFINED PYTHON SERVICE PIPELINE                              │
│                                                                                        │
│  ┌───────────────────────┐  ┌─────────────────────────┐  ┌──────────────────────────┐  │
│  │   EvidenceService     │  │     AnalysisService     │  │      ReviewService       │  │
│  │ • Pydantic validation │  │ • Strict 9-key grouping │  │ • Non-agent auth check   │  │
│  │ • Timezone enforcement│  │ • Across-term trends    │  │ • SHA-256 snapshotting   │  │
│  │ • Idempotent retries  │  │ • Ordinal rubric scales │  │ • Dual-view filtering    │  │
│  └──────────┬────────────┘  └───────────┬─────────────┘  └────────────┬─────────────┘  │
└─────────────┼───────────────────────────┼─────────────────────────────┼────────────────┘
              │                           │                             │
┌─────────────▼───────────────────────────▼─────────────────────────────▼────────────────┐
│                         BOUNDED PYDANTIC AI ORCHESTRATION                              │
│                                [allps.agent.orchestrator]                              │
│  • XML Envelopment: Untrusted text isolated in <untrusted_evidence_payload> tags       │
│  • Context Bounding: Passes pre-computed deterministic patterns to the model           │
│  • Strict Pydantic Contracts: CandidateHandoverBrief, SynthesizedFinding, HandoverStat │
│  • OutputValidator: Enforces 100% citation grounding, checks numerical claims, rejects │
│    peer ranking ("bottom 10%", "trailing classmates") and deficit labels ("slow")      │
└─────────────────────────────────────────┬──────────────────────────────────────────────┘
                                          │ Bounded Chat Completions API
┌─────────────────────────────────────────▼──────────────────────────────────────────────┐
│                    LOCAL OPEN-WEIGHT INFERENCE: LM STUDIO                              │
│  • Model: allps-qwen35-base-4b (4-bit quantized GGUF; 3.2 GB VRAM; <5s latency)        │
│  • Zero Data Egress: All minor records stay strictly on-premises on the local machine   │
│  • Resilient Fallback: Auto mode safely falls back to deterministic analysis on timeout │
└─────────────────────────────────────────┬──────────────────────────────────────────────┘
                                          │
┌─────────────────────────────────────────▼──────────────────────────────────────────────┐
│                        IMMUTABLE SQLITE STORAGE & AUDIT LEDGER                         │
│                               [allps.storage.sqlite_store]                             │
│  • learners (frozen)               • patterns (candidate & verified)                   │
│  • evidence (frozen, append-only)  • review_items (adjudication state & SHA-256 hash)  │
│  • audit_log (every tool call)     • candidate_briefs (INT-01 reload persistence)      │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Core Architectural Components

### 2.1. Our Seven-Tool FastMCP Server (`allps.mcp.server`)
Built with FastMCP over standard stdio JSON-RPC 2.0. Exposes seven domain-bounded tools:
1. `ingest_evidence`: Atomic ingestion of dated observations with origin metadata (`source_system`, `ingestion_method`).
2. `get_learner_history`: Chronological evidence retrieval (`academic_year ASC, term ASC, observed_at ASC`).
3. `analyse_longitudinal_pattern`: Deterministic pattern discovery enforcing 9-key comparability.
4. `flag_pattern_for_review`: Flags candidate patterns for sovereign teacher adjudication.
5. `resolve_teacher_review`: Teacher adjudication gate. Strictly blocks autonomous agents (`is_error=True`).
6. `get_pending_reviews`: Lists unreviewed items awaiting teacher action.
7. `get_surfaced_profile`: Retrieves the public profile, strictly filtering for approved patterns.

### 2.2. Borrowed Official MCP Server (`@modelcontextprotocol/server-filesystem`)
- **Role**: Standard reference MCP server executed via Node.js stdio transport to read local flat files (e.g. legacy school CSVs or exported register JSONs) without custom file-handling code.
- **Why it beats writing it ourselves**: Implements standard, battle-tested path-traversal sandboxing, OS permission checks, and standard streaming file access supported across the open MCP ecosystem.
- **Verification Status**: **Fully Verified** via `src/allps/agent/mcp_agent.py` and `examples/run_agentic_mcp_import.py` (Trace ID `1cb86194-619c-43ce-a079-95f8cd791d60`).

### 2.3. Dual-Server Agentic Orchestration (`src/allps/agent/mcp_agent.py`)
- Constructed with `pydantic-ai==2.56.0` connecting simultaneously to two independent MCP servers via `StdioTransport`:
  1. Borrowed official Filesystem MCP server (`list_directory`, `read_text_file`).
  2. Custom ALLPS FastMCP server (`ingest_evidence`, `get_learner_history`, `analyse_longitudinal_pattern`, `flag_pattern_for_review`).
- Uses local open-weights `allps-qwen35-base-4b` via LM Studio. The model autonomously selects tools, reads external school files, catches validation errors, ingests valid records, retrieves learner history, runs longitudinal analysis, and enters findings into teacher review.

### 2.4. Bounded Pydantic AI Orchestration (`src/allps/agent/orchestrator.py`)
- Implements strict Pydantic v2 schemas: `CandidateHandoverBrief`, `SynthesizedFinding`, and `HandoverStatus`.
- Unlike unconstrained autonomous agents that generate unverified text or execute arbitrary tool loops, ALLPS uses a **bounded orchestration pattern**:
  - Pre-computes deterministic patterns using `AnalysisService`.
  - Wraps student artifacts in `<untrusted_evidence_payload>` XML tags to eliminate prompt injection attacks.
  - Submits bounded context to the local LLM.
  - Passes raw output through `OutputValidator` before any review item or brief is written to SQLite.

### 2.5. Existing Deterministic Backend Pipeline (`src/allps/services/`)
- **`EvidenceService`**: Enforces timezone awareness, payload integrity, and idempotent replay on `(source_system, source_event_id)`.
- **`AnalysisService`**: Evaluates 9-key comparability (grade, subject, measured skill, form identity & version, language, rubric scale, assessment stage). Distinguishes true zero from missing outcomes (`absent`, `not_administered`).
- **`ReviewService`**: Enforces the human-in-the-loop review boundary, computes SHA-256 snapshots, and prevents autonomous bot approvals.

### 2.6. Local Open-Weight Qwen Inference
- **Target Model**: `allps-qwen35-base-4b` (`qwen2.5-3b` / `qwen2.5-4b` 4-bit quantized GGUF) served locally via LM Studio on `http://127.0.0.1:1234/v1`.
- **Privacy & Sovereignty**: Student records for minors never leave the local machine or host institution.
- **Performance**: 3.2 GiB VRAM footprint, <5s per synthesis cycle. Refuses silent fallback when explicitly run in `live` mode.

### 2.7. SQLite Provenance & Immutability (`src/allps/storage/sqlite_store.py`)
- Async SQLite storage using `aiosqlite`.
- Relational schema: `learners`, `evidence`, `patterns`, `review_items`, `audit_log`, `candidate_briefs`.
- Domain models are frozen (`model_config = {"frozen": True}`). Evidence is append-only via MCP.
- The `candidate_briefs` table provides INT-01 reload persistence, ensuring full candidate brief restoration upon browser refresh.

### 2.8. Teacher Review and Publication Authority
- **Dual-View Separation**: Unreviewed (`pending`), rejected, and `needs_context` patterns remain strictly isolated in the teacher review inbox.
- **Cryptographic Snapshotting**: Upon teacher acceptance, `ReviewService` generates an immutable SHA-256 hash of the pattern text and cited evidence IDs.
- **Published Profile**: Only patterns with verified teacher acceptance and valid hash snapshots are exposed in `get_surfaced_profile` and the web handover view.

---

## 3. Tool Calls vs. Predefined Service Calls

A foundational principle of ALLPS is the clear architectural boundary between **model-directed tool calls** and **predefined Python service calls**:

| Execution Mechanism | Where It Occurs | Purpose & Scope | Governance Guarantee |
| :--- | :--- | :--- | :--- |
| **Model-Directed Tool Calls** *(Dual-MCP Agent)* | Over stdio JSON-RPC transport via `pydantic-ai` | Agent connects to both Filesystem MCP and ALLPS FastMCP servers to import files, analyze patterns, and flag candidate findings. | Strictly limited to exposed MCP tools. Interceptors enforce path containment; `resolve_teacher_review(status="accepted")` is blocked with `PermissionError`. |
| **Predefined Python Service Calls** *(Internal Backend)* | Inside `AgentOrchestrator` and `allps.web.routes` | The web backend directly executes `AnalysisService.compute_longitudinal_patterns()`, `OutputValidator.validate()`, and `store.add_candidate_brief()`. | The LLM **never** directly calls internal SQLite methods or mutates state. All LLM output must survive deterministic validation before any database write occurs. |
