# ALLPS — Workstream 6: Retrospective & Deferred Work Backlog

**Project**: ALLPS (Agentic Longitudinal Learner Profile System)  
**Submission Track**: Education: The Long View — African Agentic AI Design Challenge  
**Frozen Baseline**: Commit `b504e0c647f14718d062b186ab8613af189ea29f`  
**Date**: 15 October 2026  

---

## 1. One-Page Project Retrospective

### 1.1 Architectural Successes & Strengths

1. **Constitutional Alignment ("Evidence, Not Labels")**:
   The core design principle — *"Record evidence without reducing learners to labels"* — was maintained without compromise throughout the entire development lifecycle. The deterministic policy engine strictly prevents both direct deficit categorizations (*"slow learner"*) and relative rankings (*"bottom 10%"*).
2. **Deterministic Pre-Validation Before AI Synthesis**:
   By enforcing a 9-key comparability series check (subject, grade, skill, form version, language, rubric scale, assessment stage) *before* any LLM inference occurs, ALLPS eliminates hallucinated longitudinal equating across disparate scales.
3. **Genuine Dual-Server MCP Composability**:
   ALLPS achieved authentic model-directed tool calling across two heterogeneous MCP servers: the official TypeScript Filesystem MCP server (`@modelcontextprotocol/server-filesystem`) and the custom Python FastMCP server (`allps.mcp.server`). The local Qwen 3.5 4B model successfully orchestrated multi-server tool use over stdio.
4. **Sovereign Human Oversight & Cryptographic Integrity**:
   AI is treated strictly as an unprivileged, advisory contributor. Autonomous self-approval is blocked at the protocol level (`PermissionError`). Teacher acceptance creates an immutable SHA-256 snapshot, guaranteeing complete auditability.
5. **Rock-Solid Test Reproducibility**:
   The test suite achieves a **100% pass rate** (252 passed, 0 failures across 15 test suites) in 127 seconds without requiring flaky external network dependencies.

### 1.2 Engineering Challenges & Bottlenecks

1. **Hardware & VRAM Allocation Boundaries**:
   Attempting to deploy unquantized 7B distilled reasoning models on consumer hardware hit severe CUDA Out-Of-Memory limits (>14.2 GiB VRAM required). This forced a pragmatic architectural pivot to 4-bit quantized `qwen3.5-4b` (~3.2 GiB VRAM), proving that realistic African school AI must target models $\le$ 4B parameters.
2. **Default Output Trace Contention**:
   The demonstration runner (`run_agentic_mcp_import.py`) defaulted its trace output to the tracked submission trace file (`data/trace_agentic_mcp_run.json`). This created risk of overwriting historical submission evidence during local verification, necessitating explicit path isolation during audits.
3. **Packaging vs. Web Workspace Scope**:
   `pyproject.toml` focused on core engine and agent dependencies (`pydantic-ai`, `mcp`, `aiosqlite`), leaving the FastAPI web dependencies (`fastapi`, `uvicorn`, `httpx`) undeclared in the base package manifest.

### 1.3 Key Takeaways for African Educational AI

* **Local-First is Non-Negotiable**: In rural or bandwidth-constrained African primary schools, cloud API dependencies guarantee system failure. True longitudinal continuity requires local edge inference.
* **Separation of Powers**: AI models must never possess write authority over official student transcripts or longitudinal handovers. Deterministic governance and human approval gates must remain sovereign.

---

## 2. Deferred Work Backlog (Post-Submission Roadmap)

The following high-value enhancements were identified during development but intentionally deferred to safeguard submission stability:

| Priority | Backlog Item | Architectural Domain | Description & Value |
| :-: | :--- | :--- | :--- |
| **P1** | **SSO & Role-Based Authentication** | Security & Identity | Replace the prototype `--reviewer` flag and demonstration header with a robust local educator authentication system (e.g. Ed-Fi SSO, local WebAuthn, or school-level PIN/keycard). |
| **P1** | **Trace Output Path Safety** | Developer Experience | Update `examples/run_agentic_mcp_import.py` to default `--trace-out` to a timestamped scratch directory (`.audit-runtime/traces/trace_<timestamp>.json`) to prevent accidental overwriting of preserved baseline traces. |
| **P2** | **CLI Packaging for Web Workspace** | Packaging & Distribution | Add `allps-web = "allps.web.app:main"` to `[project.scripts]` in `pyproject.toml`, with optional `[project.optional-dependencies]` for `web = ["fastapi", "uvicorn", "httpx"]`. |
| **P2** | **Relative Markdown Link Normalization** | Documentation | Refactor internal markdown documentation links from Windows absolute `file:///Q:/ALLPS/...` URIs to standard GitHub repository-relative paths (`[AnalysisService](src/allps/services/analysis_service.py)`). |
| **P3** | **Sub-3B CBC Distillation Benchmarking** | Model Research | Benchmark smaller parameter models (e.g. `Qwen2.5-1.5B-Instruct` and `SmolLM2-1.7B`) on CPU-only school workstations to evaluate whether 100% citation grounding can be preserved on hardware with 2GB–4GB RAM. |
| **P3** | **Multi-School Federated MCP Sync** | Networking & Protocols | Implement remote MCP transport (SSE / HTTP) to enable secure termly handover transfers between feeder primary schools and receiving secondary schools. |
| **P4** | **Offline Voice Memo Transcription** | Ingestion Multimodal | Integrate an offline, CPU-friendly speech-to-text pipeline (e.g. `whisper.cpp` quantized) allowing teachers to record spoken classroom observations between lessons. |

---

## 3. Proposed Minimal Post-Submission Commits

To incorporate the findings of this closure audit cleanly into version control without altering the submitted baseline on `master`, we propose the following sequential commits on a dedicated maintenance or documentation branch (`docs/post-submission-closeout`):

### Commit 1: Closeout Audit & Preservation Records
* **Branch**: `docs/post-submission-closeout`
* **Message**: `docs(closeout): integrate complete post-submission audit, preservation manifests, and operator guides`
* **Changes**:
  - Adds `docs/closeout/` directory with all 6 workstream reports (`01_git_audit_report.md` through `06_retrospective_and_backlog.md` and `README.md`).
  - Records cryptographic checksums and evidence logs.

### Commit 2: Correct Seed Invocation & Packaging Docs
* **Branch**: `docs/post-submission-closeout`
* **Message**: `docs: correct seed_data CLI syntax and document web server dependencies`
* **Changes**:
  - Updates `README.md` to remove unsupported `--target` flag from seed command.
  - Adds explicit `fastapi`, `uvicorn`, and `httpx` installation instructions.

### Commit 3: Safe MCP Runner Default Output
* **Branch**: `docs/post-submission-closeout`
* **Message**: `fix(examples): protect baseline MCP trace by timestamping default runner output`
* **Changes**:
  - Updates `examples/run_agentic_mcp_import.py` default `--trace-out` to write to a timestamped file rather than overwriting `data/trace_agentic_mcp_run.json`.

> [!NOTE]
> All commits remain staged on the isolated `docs/post-submission-closeout` worktree and will not be pushed or merged to `master` without explicit confirmation.
