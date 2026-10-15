# ALLPS — Agentic Longitudinal Learner Profile System

> **Challenge Track**: Education: The Long View — African Agentic AI Design Challenge  
> *"Record evidence without reducing learners to labels."*  
> **Repository**: [https://github.com/kwisdomk/ALLPS](https://github.com/kwisdomk/ALLPS)  
> **License**: [MIT License](LICENSE) (OSI-Approved)

---

## 1. Problem Statement

In African primary and secondary schools, learner data — test marks, attendance registers, project milestones, and classroom observations — is fragmented across terms, school years, and changing teachers. With pupil-to-teacher ratios frequently reaching 50–80:1 and high teacher turnover, educators are left with isolated termly mark sheets.

When a student transitions to upper primary or enters a new grade (e.g., Grade 3 to Grade 4), their multi-year context is lost. Incoming educators are forced to rely on informal hearsay or reductive one-off test scores, flattening rich developmental trajectories into simplistic diagnostic labels.

---

## 2. Solution Overview

**ALLPS (Agentic Longitudinal Learner Profile System)** preserves learning continuity across terms, years, and teachers. It couples an atomic, immutable evidence ledger with a deterministic longitudinal comparability engine and bounded local open-weight AI orchestration to synthesize verifiable transition handovers — with sovereign human educators holding strict approval authority.

Core pillars of ALLPS:
1. **Atomic Evidence Ledger**: Append-only storage recording assessments, attendance, and qualitative observations with explicit origin (`source_system`, `ingestion_method`).
2. **Deterministic Comparability Engine**: Strictly validates 9-key comparability before pattern detection, preventing false equating across incompatible scales.
3. **Bounded Local Open-Weight AI**: Synthesizes plain-language candidate transition briefs citing exact record UUIDs with zero cloud data egress.
4. **Sovereign Human-in-the-Loop Gate**: Autonomous agents are barred from approving candidate findings (`is_error=True`). Human teacher approval generates an immutable SHA-256 snapshot.

> [!IMPORTANT]
> **Public Portal Notice**:  
> The public website at **`https://allps.kwaix.dev`** is an **informational project documentation page**, not the local live application. It does not host the FastAPI backend, does not connect to LM Studio, and deliberately exposes zero learner records or unauthenticated approval endpoints to the open internet. The live AI application runs locally on `http://127.0.0.1:8000`.

---

## 3. Target Users

ALLPS is designed specifically for public and community school ecosystems across Africa:

1. **Primary & Secondary School Teachers**:
   - Class teachers conducting end-of-year or term-to-term transition handovers.
   - Teachers recording factual classroom observations and reviewing AI-generated candidate profiles.
2. **Headteachers & Academic Deans**:
   - School leadership tracking longitudinal learning trends across grades and monitoring curriculum execution without reducing students to rankings.
3. **Curriculum Support Officers (CSOs) & Sub-County Quality Assurance**:
   - Educational officers overseeing Competency-Based Curriculum (CBC) implementation and verifying that student progress is assessed holistically against competencies.
4. **Special Needs & Remedial Support Coordinators**:
   - Educators requiring longitudinal evidence to distinguish between temporary situational divergence (e.g., family bereavement) and persistent developmental needs.

---

## 4. Architecture

ALLPS uses a strictly bounded multi-tiered architecture that separates untrusted inputs, deterministic analysis, bounded AI generation, and sovereign human review:

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
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ Verified Handover Brief
┌───────────────────────────────────────────▼────────────────────────────────────────────┐
│                       SOVEREIGN TEACHER REVIEW GATE & AUDIT LEDGER                     │
│  • Candidate Findings enter review inbox in PENDING state (strictly un-surfaced)       │
│  • Teacher approves finding -> Immutable Cryptographic SHA-256 Snapshot generated     │
│  • Published profile surfaces ONLY verified human-approved findings                    │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

For full details, see [ARCHITECTURE.md](ARCHITECTURE.md) and [`allps_architecture_map.md`](allps_architecture_map.md).

---

## 5. Technology Stack

| Layer | Component / Technology | Justification & Role |
| :--- | :--- | :--- |
| **Backend Core** | **Python 3.11+** (Tested on 3.13 & 3.14) | Core domain logic, async runtime, type safety |
| **Data Contracts** | **Pydantic v2** | Strict schema validation, immutability, frozen models |
| **Persistence** | **SQLite (WAL Mode)** | Local, zero-configuration, ACID transactions, robust foreign keys |
| **Agent & Protocol** | **Model Context Protocol (FastMCP + MCP Python SDK)** | Standard JSON-RPC 2.0 stdio protocol for tool-using agents |
| **Agent Framework** | **Pydantic AI** | Model-directed multi-server orchestration with structured output |
| **Local LLM Engine** | **LM Studio (`v0.3.0+`)** or **Ollama** | Local OpenAI-compatible API on `127.0.0.1:1234` / `11434` |
| **Local Model** | **`allps-qwen35-base-4b`** (`Qwen2.5-3B` / `4B` 4-bit GGUF) | Fits in **<3.5 GB VRAM**, sub-5s local inference, offline privacy |
| **Frontend UI** | **Vanilla HTML5 / Modern CSS3 (Apple HIG)** | Zero npm/node/webpack build dependencies, instant loading, mobile responsive |
| **Web Server** | **FastAPI + Uvicorn** | High-performance asynchronous REST API for local teacher workspace |
| **Testing** | **Pytest + pytest-asyncio + AnyIO** | 14 test layers, 252 automated tests covering all critical invariants |

---

## 6. Setup & Installation Instructions

### Prerequisites
- Python 3.11 or higher
- Git
- *(Optional)* LM Studio or Ollama with `Qwen2.5-3B` or `Qwen2.5-Coder-3B` / `Qwen3.5` 4-bit GGUF
- *(Optional)* Node.js 18+ (only needed if running the external filesystem MCP server)

### Step 1: Clone Repository
```bash
git clone https://github.com/kwisdomk/ALLPS.git
cd ALLPS
```

### Step 2: Set Up Virtual Environment
```bash
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate

# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
```

### Step 3: Install ALLPS & Dependencies
```bash
pip install -e ".[dev]"
```

### Step 4: Configure Local AI Engine (Optional for Live Mode)
1. Launch **LM Studio** (or Ollama).
2. Download `Qwen2.5-3B-Instruct` (or 4B 4-bit GGUF).
3. Start the local server on `http://127.0.0.1:1234/v1` with identifier `allps-qwen35-base-4b`.
> *Note: If LM Studio is not running, ALLPS automatically and safely engages deterministic fallback in `auto` mode.*

### Step 5: Seed Synthetic Demonstration Cohort
```bash
python -m data.synthetic.seed_data --target allps_demo.db
```

---

## 7. Usage Instructions

### ⚡ Automated Test Suite Execution (Fastest Verification)
Run all 252 automated unit, service, MCP, and integration tests across 14 test layers:
```bash
python -m pytest
```

### ⚡ End-to-End Multi-Outcome Demonstration (<60s)
Executes all five canonical outcomes (accepted trend, accepted persistence, rejected divergence, safe abstention, policy violation rejection):
```bash
python examples/demo_e2e.py --mode auto
```

### ⚡ Real MCP Wire Protocol Demonstration
Exercises our 7 FastMCP tools over real stdio transport using the official Python MCP SDK, including non-agent permission gate verification:
```bash
python examples/demonstrate_mcp_wire_protocol.py
```

### ⚡ Dual-Server Pydantic AI MCP Agent Run
Demonstrates a model-directed agent reading raw school records via the Filesystem MCP server and ingesting them into ALLPS:
```bash
python examples/run_agentic_mcp_import.py
```

### ⚡ Start the Local Teacher Workspace (Web UI)
Launches the FastAPI backend and serves the educator workspace Single Page Application:
```bash
python -m allps.web.app --port 8000 --mode auto --reviewer TCH-BANDA
```
Open your browser to: **`http://127.0.0.1:8000`**

---

## 8. Agent Architecture

ALLPS employs a **bounded, deterministic-first agent architecture**:

```
Raw Learner Records
       │
       ▼
┌─────────────────────────────────┐
│   Deterministic AnalysisService │  Enforces 9-key comparability:
│   (Strict Mathematical Logic)   │  subject, grade, skill, form, scale, etc.
└──────────────┬──────────────────┘
               │ Pre-computed patterns & verified facts
               ▼
┌─────────────────────────────────┐
│       AgentOrchestrator         │  • XML Envelopment: Untrusted notes isolated
│         (Pydantic AI)           │    in <untrusted_evidence_payload> tags
│    Local Open-Weight Model      │  • Grounded Synthesis: LLM generates brief
└──────────────┬──────────────────┘
               │ Raw LLM Output Draft
               ▼
┌─────────────────────────────────┐
│         OutputValidator         │  Deterministic Gate:
│    (Deterministic Post-Check)   │  1. 100% citation grounding (valid UUIDs)
└──────────────┬──────────────────┘  2. Numerical claims match cited records
               │                     3. Rejects peer ranking & deficit labels
               ▼
Candidate Handover Brief (PENDING state in Teacher Review Inbox)
```

1. **Prompt Injection Defense**: Qualitative teacher notes and untrusted classroom text are strictly isolated inside `<untrusted_evidence_payload>` XML tags.
2. **Deterministic OutputValidator**: Raw LLM drafts are screened before reaching human teachers. The validator enforces 100% citation grounding, checks numerical claims against cited records, and deterministically blocks deficit labels (*"slow learner"*, *"feeble"*) and peer ranking (*"bottom 10%"*, *"below grade average"*).
3. **Graceful Fallback**: If LLM output fails validation, the orchestrator triggers an automatic repair pass; if unrecoverable or if the local model is offline, ALLPS falls back to structured deterministic synthesis.

---

## 9. MCP Implementation

ALLPS implements the official **Model Context Protocol (MCP)** using standard JSON-RPC 2.0 stdio wire transport:

- **Official Python MCP SDK & FastMCP**: Native integration ensuring compatibility with MCP clients (Claude Desktop, Cursor, Goose, custom scripts).
- **Multi-Server Coordination**: Verified end-to-end multi-server execution coordinating our domain server (`allps.mcp.server`) with the reference `@modelcontextprotocol/server-filesystem` server.
- **Client Session Management**: Real stdio client connections (`stdio_client`) managing subprocess lifecycle, tool discovery, and schema-validated tool invocation.
- **Verified Protocol Trace**: Execution trace `1cb86194-619c-43ce-a079-95f8cd791d60` confirms real multi-server tool discovery and execution.

---

## 10. MCP Tools & Servers

### 1. ALLPS Domain Server (`allps.mcp.server`)
Our custom FastMCP server exposes 7 domain-bounded tools:

| Tool Name | Parameters | Purpose & Enforced Rules |
| :--- | :--- | :--- |
| `ingest_evidence` | `learner_id`, `category`, `source_system`, `payload` | Ingests atomic evidence record with provenance and timezone validation |
| `get_learner_history` | `learner_id` | Retrieves complete chronological evidence stream for a learner |
| `analyse_longitudinal_pattern`| `learner_id`, `analysis_type`, `params` | Deterministic pattern detector enforcing 9-key comparability |
| `flag_pattern_for_review` | `learner_id`, `pattern_id`, `summary` | Flags candidate finding into teacher review inbox in `PENDING` state |
| `resolve_teacher_review` | `review_id`, `reviewer_id`, `decision`, `notes` | **Human Teacher Adjudication Gate**. Autonomous agents blocked (`is_error=True`) |
| `get_pending_reviews` | `learner_id` | Lists all pending candidate findings awaiting teacher review |
| `get_surfaced_profile` | `learner_id` | Returns official longitudinal profile containing **only human-approved findings** |

### 2. Borrowed Reference Server (`@modelcontextprotocol/server-filesystem`)
- **Source**: Official `@modelcontextprotocol/server-filesystem` (Anthropic reference MCP server).
- **Purpose**: Reads raw school export files (CSV, JSON, and text) from local school directories.
- **Integration**: Coordinated by `src/allps/agent/mcp_agent.py` to ingest external school records into the ALLPS ledger.

---

## 11. Human-in-the-Loop Workflow

In ALLPS, AI is treated as the lowest-authority contributor with **strictly zero autonomous approval capability**:

1. **Non-Agent Approval Gate**:
   - If an automated agent attempts to approve a candidate finding via `resolve_teacher_review(reviewer_id="autonomous-agent")`, the server raises `PermissionError` and halts with `is_error=True`.
2. **Review Inbox Isolation**:
   - Candidate briefs enter the teacher workspace in a `PENDING` state and remain completely invisible in published profiles (`get_surfaced_profile`).
3. **Teacher Adjudication Choices**:
   - **Accept**: The educator approves the finding and adds pedagogical handover notes. An immutable cryptographic **SHA-256 snapshot** is computed from the exact finding payload and reviewer ID.
   - **Reject**: The educator rejects the candidate brief with documented pedagogical rationale. The finding is marked `REJECTED` and permanently excluded from the surfaced profile.
   - **Needs Context**: The educator requests supplementary evidence before a decision can be made.
4. **Revision State Isolation**:
   - Generating a new AI synthesis creates `REV 2` in `PENDING` status. It **never inherits approval** from previous revisions, preventing silent drift.

---

## 12. Limitations

- **Confirmed CUDA Allocation Failure (Unresolved for 7B Models)**:  
  Attempting to load unquantized 7B distilled models (`DeepSeek-R1-Distill-Qwen-7B` / `Qwen2.5-7B`) on consumer 8GB GPUs produces a CUDA out-of-memory exception (`failed to allocate 14.2 GiB on CUDA:0`). Mitigated by utilizing the 4-bit quantized base model `allps-qwen35-base-4b` (<3.5GB VRAM). See [EVALS.md](EVALS.md) for full incident details.
- **Prototype Reviewer Identity Boundary**:  
  The prototype server injects a configured reviewer identifier (e.g. `--reviewer TCH-BANDA`) for human-in-the-loop demonstration. This is a demonstration setting, **not cryptographic authentication or SSO identity**. Production deployments require OpenID Connect / SAML integration.
- **Concurrent Ingestion Race**:  
  Overlapping concurrent submissions with identical `(source_system, source_event_id)` fail with SQLite `IntegrityError` on the second transaction and roll back safely; sequential retries succeed idempotently.
- **Local Network Boundary**:  
  ALLPS runs on localhost/LAN to ensure complete student data privacy and zero cloud egress. Remote access requires a secure VPN or reverse proxy with authentication.

---

## 13. Future Improvements

1. **Full CBC Phase 2 Competency Alignment**:
   - Expand taxonomy to cover all 7 core competencies of Kenya's Competency-Based Curriculum across Grades 1–6.
2. **Enterprise Authentication & Single Sign-On**:
   - Replace prototype reviewer injection with OpenID Connect (OIDC) / SAML 2.0 integration for official school management systems (e.g., NEMIS).
3. **Multimodal Evidence Ingestion**:
   - Support spoken teacher voice notes in Swahili and English via local Whisper models.
   - Ingest handwritten student workbook and rubric photos using local vision models.
4. **Offline Distributed Synchronization**:
   - Support peer-to-peer or mesh synchronization (sneakernet / periodic sync) for rural schools without continuous grid power or internet.
5. **Edge Single-Board Hardware Deployment**:
   - Optimize runtime for low-cost hardware (Raspberry Pi 5 / Orange Pi with NPU) to enable sub-\$100 school server appliances.

---

## 14. Synthetic Kenyan Demonstration Dataset

ALLPS ships with a realistic synthetic demonstration dataset modeled on the Kenyan Competency-Based Curriculum (CBC) and Tusome literacy benchmarks (`data/synthetic/seed_data.py`).

- **3 Demonstration Learners**:
  - `LRN-001` (Amara Kemboi): Grade 3, declining Mathematics trajectory across 3 terms (82 $\to$ 68 $\to$ 51), high attendance, strong spatial reasoning.
  - `LRN-002` (Thabo Ndlovu): Grade 3, persisting Science strength (consistent Level 4 rubric), peer study support.
  - `LRN-003` (Naledi Mwangi): Grade 3, high exam score (88/100) diverging from acute classroom disengagement due to local family bereavement.
- **27 Atomic Evidence Records**: Ingested with realistic messy properties (inconsistent scoring scales, missing outcomes with explicit reasons, and qualitative teacher notes).
- **Privacy Guarantee**: No real student records or personal identifying details are hosted or transmitted.

---

## 15. Project Documentation & Verification Links

- [ARCHITECTURE.md](ARCHITECTURE.md) — Comprehensive system architecture, component breakdown, and tool call boundaries.
- [EVALS.md](EVALS.md) — Nine real evaluation tasks, observed pass/fail outcomes, the unresolved CUDA allocation failure, and development repairs.
- [DEVELOPMENT_RESEARCH.md](DEVELOPMENT_RESEARCH.md) — Technical research record, African classroom constraints, architectural experiments, and limitations.
- [ROADMAP.md](ROADMAP.md) — Implementation roadmap, milestone tracking, and completed deliverables.
- [docs/SUBMISSION.md](docs/SUBMISSION.md) — Official challenge submission materials and video demonstration outline.
- [LICENSE](LICENSE) — OSI-Approved MIT License.
