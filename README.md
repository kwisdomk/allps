# ALLPS — Agentic Longitudinal Learner Profile System

> **Challenge Track**: Education: The Long View — African Agentic AI Design Challenge  
> *"Record evidence without reducing learners to labels."*  
> **Repository**: [https://github.com/kwisdomk/ALLPS](https://github.com/kwisdomk/ALLPS)  
> **License**: [MIT License](LICENSE) (OSI-Approved)

---

## 1. Overview & Problem Statement

In African primary and secondary schools, learner data — test marks, attendance registers, project milestones, and classroom observations — is fragmented across terms, school years, and changing teachers. When a student transitions to upper primary or a new grade, their multi-year context is lost, leaving teachers with one-term snapshots or forcing them to rely on informal hearsay.

**ALLPS (Agentic Longitudinal Learner Profile System)** preserves learning continuity across terms, years, and teachers. It connects atomic learner evidence, deterministically evaluates longitudinal trajectories, and uses bounded local open-weight AI to synthesize verifiable transition handovers — with sovereign human teachers holding strict approval authority.

> [!IMPORTANT]
> **Public Portal Notice**:  
> The public website at **`https://allps.kwaix.dev`** is an **informational project documentation page**, not the local live application. It does not host the FastAPI backend, does not connect to LM Studio, and deliberately exposes zero learner records or unauthenticated approval endpoints to the open internet. The live AI application runs locally on `http://127.0.0.1:8000`.

---

## 2. Quick Start & Simple Runnable Commands

### ⚡ One-Line Verification (Fastest)

Run the automated test suite across all 14 test layers (252 passing tests):

```bash
python -m pytest
```

### ⚡ Run the End-to-End Multi-Outcome Demonstration (<60s)

Demonstrates five canonical outcomes: accepted trend, accepted persistence, rejected divergence, safe abstention, and policy violation rejection:

```bash
python examples/demo_e2e.py --mode auto
```

### ⚡ Run the Real MCP Wire Protocol Demonstration

Exercises our 7 FastMCP tools over real stdio transport using the official Python MCP SDK:

```bash
python examples/demonstrate_mcp_wire_protocol.py
```

### ⚡ Start the Local Teacher Workspace

Launches the FastAPI backend and serves the educator Single Page Application:

```bash
python -m allps.web.app --port 8000 --mode auto --reviewer TCH-BANDA
```

Open your browser to: **`http://127.0.0.1:8000`**

---

## 3. System Requirements & Environment

| Component | Requirement | Notes |
| :--- | :--- | :--- |
| **Python** | **Python 3.11+** (Tested on Python 3.13 and 3.14) | Core backend, Pydantic v2, FastMCP, SQLite store |
| **Node.js** | **Node.js 18+** *(Optional)* | **Zero Node dependency for core ALLPS or Web SPA.** Node is only required if running the borrowed `@modelcontextprotocol/server-filesystem` via `npx`. |
| **Local LLM Engine** | **LM Studio** (`v0.3.0+`) or **Ollama** | Running locally on `http://127.0.0.1:1234/v1` (LM Studio) or `http://127.0.0.1:11434/v1` (Ollama) |
| **Local Model** | **`allps-qwen35-base-4b`** (`Qwen2.5-3B` / `4B` 4-bit GGUF) | Fits in **<3.5 GB VRAM**; sub-5s inference latency. If unavailable, ALLPS safely engages deterministic fallback in `auto` mode. |
| **OS** | Linux, macOS, or Windows | Fully cross-platform; paths use standard library `pathlib.Path`. |

---

## 4. Synthetic Kenyan Demonstration Dataset

ALLPS ships with a realistic synthetic demonstration dataset modeled on the Kenyan Competency-Based Curriculum (CBC) and Tusome literacy benchmarks (`data/synthetic/seed_data.py`).

- **3 Demonstration Learners**:
  - `LRN-001` (Amara Kemboi): Grade 3, declining Mathematics trajectory across 3 terms (82 $\to$ 68 $\to$ 51), high attendance, strong spatial reasoning.
  - `LRN-002` (Thabo Ndlovu): Grade 3, persisting Science strength (consistent Level 4 rubric), peer study support.
  - `LRN-003` (Naledi Mwangi): Grade 3, high exam score (88/100) diverging from acute classroom disengagement due to local family bereavement.
- **27 Atomic Evidence Records**: Ingested with realistic messy properties (inconsistent scoring scales, missing outcomes with explicit reasons, and qualitative teacher notes).
- **Privacy Guarantee**: No real student records or personal identifying details are hosted or transmitted.

To re-seed a database manually:

```python
from data.synthetic.seed_data import seed_database
import asyncio

asyncio.run(seed_database("allps_demo.db"))
```

---

## 5. Architectural Highlights

1. **Our Seven-Tool FastMCP Server (`allps.mcp.server`)**:
   - Standard stdio JSON-RPC 2.0 interface.
   - 7 domain-bounded tools: `ingest_evidence`, `get_learner_history`, `analyse_longitudinal_pattern`, `flag_pattern_for_review`, `resolve_teacher_review`, `get_pending_reviews`, `get_surfaced_profile`.
2. **Borrowed Official MCP Server (`@modelcontextprotocol/server-filesystem`)**:
   - Reference filesystem server for reading raw local school files.
   - Status: **Fully Verified** via `src/allps/agent/mcp_agent.py` and `examples/run_agentic_mcp_import.py` (Trace ID `1cb86194-619c-43ce-a079-95f8cd791d60`, multi-server stdio JSON-RPC).
3. **Deterministic Comparability Engine (`AnalysisService`)**:
   - Strictly enforces 9-key comparability before pattern detection.
   - Rejects monotonic gains on mixed assessment scales; preserves true zero distinct from missing outcomes.
4. **Bounded Pydantic AI Orchestration (`AgentOrchestrator`)**:
   - Isolates qualitative free text in `<untrusted_evidence_payload>` XML tags.
   - `OutputValidator` screens raw LLM drafts: enforces 100% citation grounding, checks numerical claims against cited records, and rejects peer ranking (*"bottom 10%"*, *"below grade average"*) and deficit labels (*"slow learner"*).
5. **Human-in-the-Loop Sovereign Review Gate (`ReviewService`)**:
   - Autonomous agents are barred from approving candidate findings (`is_error=True`).
   - Human teacher approval generates an immutable SHA-256 snapshot. Unapproved patterns remain strictly invisible in published profiles.
6. **Teacher Web Interface (FastAPI + Vanilla JS SPA)**:
   - Apple HIG aesthetic; zero npm/webpack dependencies.
   - Full candidate brief persistence across page reloads (INT-01).

---

## 6. Known Failures & Limitations

- **Confirmed CUDA Allocation Failure (Unresolved)**:
  Attempting to load unquantized 7B distilled models (`DeepSeek-R1-Distill-Qwen-7B` / `Qwen2.5-7B`) on consumer 8GB GPUs produces a CUDA out-of-memory exception (`failed to allocate 14.2 GiB on CUDA:0`). Mitigated by utilizing the 4-bit quantized base model `allps-qwen35-base-4b` (<3.5GB VRAM). See [EVALS.md](EVALS.md) for full incident details and next untried experiments.
- **Prototype Reviewer Identity Boundary**:
  The prototype server injects a configured reviewer identifier (e.g. `--reviewer TCH-BANDA`) for human-in-the-loop demonstration. This is a demonstration setting, **not cryptographic authentication or SSO identity**. Production deployments require OpenID Connect / SAML integration.
- **Borrowed MCP Server Protocol Evidence**:
  While ALLPS supports upstream provenance tracking (`source_system`, `source_event_id`, `ingestion_method`), end-to-end multi-server execution with the external filesystem MCP server has not been independently verified.
- **Concurrent Ingestion Race**:
  Overlapping concurrent submissions with identical `(source_system, source_event_id)` fail with SQLite `IntegrityError` on the second transaction and roll back safely; sequential retries succeed idempotently.

---

## 7. Project Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — Concise one-page system architecture, component breakdown, and tool call boundaries.
- [EVALS.md](EVALS.md) — Nine real evaluation tasks, observed pass/fail outcomes, the unresolved CUDA allocation failure, and development repairs.
- [DEVELOPMENT_RESEARCH.md](DEVELOPMENT_RESEARCH.md) — Technical research record, African classroom constraints, architectural experiments, and limitations.
- [LICENSE](LICENSE) — OSI-Approved MIT License.
