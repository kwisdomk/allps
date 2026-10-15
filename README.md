# ALLPS — Agentic Longitudinal Learner Profile System

> Built for the African Agentic AI Design Challenge, education track.  
> *"Record evidence without reducing learners to labels."*

---

## Overview

Schools collect rich learner data — assessments, attendance, projects, teacher observations, participation metrics, and learner self-reflections. However, this information is almost always fragmented across terms, school years, and changing teachers. When a student transitions to a new grade or teacher, their longitudinal context is lost, forcing each educator to start from scratch or rely on informal impressions.

**ALLPS (Agentic Longitudinal Learner Profile System)** preserves learning continuity across terms, years, and teachers by connecting longitudinal evidence and surfacing sourced, verifiable patterns.

### Core Principles & Commitments

These core commitments guide the design of ALLPS:

**Implemented & Enforced:**
1. **Record evidence without reducing learners to labels**: ALLPS records factual, dated, attributed observations. Learner identity connects longitudinal records across years, but the system stores atomic evidence rather than permanent diagnostic labels.
2. **Evidence immutability**: Evidence domain models are frozen, and the MCP server exposes no editing or deletion tools. Upstream identifiers support idempotent re-ingestion.
3. **Explicit provenance & system origin**: Every piece of evidence captures `source_system`, `ingestion_method`, `source_type`, `source_reference`, `observed_at`, and `recorded_at`.
4. **Strict non-ranking**: History queries accept a single learner ID. Ranking or peer-sorting is prohibited and unexposed in the API.
5. **Deterministic comparability**: Longitudinal pattern detection strictly enforces measurement compatibility (same grade, subject, measured skill, form identity & version, language, rubric scale). No invented defaults; no false equating across differing instruments.
6. **Zero remains zero, missing remains null**: Explicit missing outcomes (`absent`, `result_unavailable`, `assessment_not_administered`) are preserved distinct from zero scores. Missing reflections are never penalized as negative evidence.

**Modeled & In Progress (Disclosed Status):**
7. **Sovereign Teacher Review Gate**: The `ReviewItem` data model exists and stores human adjudication states (`pending`, `accepted`, `rejected`, `needs_context`). Enforcement filtering—ensuring published profiles strictly expose accepted patterns—is currently being coupled to the analysis pipeline.
8. **Prohibited diagnostic label screening**: Policy rules rejecting deficit and clinical terminology (`"slow learner"`, `"lazy"`, `"ADHD"`) are being introduced into `allps.policies`.
9. **Bounded agent orchestration**: Gated pedagogical transition synthesis requiring explicit evidence citations, stated limitations, and explicit abstention when data is inconclusive.

---

## Phase 1 Scope & Architecture

Phase 1 establishes the data and tool foundation for longitudinal evidence collection:

```
┌────────────────────────────────────────────────────────┐
│                   MCP Client / Agent                   │
└───────────────────────────┬────────────────────────────┘
                            │ Model Context Protocol (stdio)
┌───────────────────────────▼────────────────────────────┐
│                  ALLPS MCP Server                      │
│   • ingest_evidence(learner_id, evidence_type, ...)    │
│   • get_learner_history(learner_id, [filters])         │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                 Evidence Service                       │
│   • Validates models (Pydantic v2)                     │
│   • Enforces UTC timezones & content rules             │
│   • Idempotency & retry handling (requires             │
│     source_event_id)                                   │
│   • Atomic evidence + audit commit                     │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│               Async SQLite Store                       │
│   • learners                                           │
│   • evidence (frozen models, append-only via MCP)      │
│   • patterns (Phase 2 analysis models ready)           │
│   • review_items (human-in-the-loop review state)      │
│   • audit_log (tool invocation audit trail)            │
└────────────────────────────────────────────────────────┘
```

### What Phase 1 Does

Phase 1 stores and retrieves dated learner evidence with source information. Pattern detection and baseline comparisons are planned:

- **Evidence Ingestion**: The `ingest_evidence` MCP tool accepts factual learner observations. A Python-level alias `record_evidence` exists in both the service layer and the MCP server module for backward compatibility, but only `ingest_evidence` is registered as an MCP tool. The tool captures:
  - **Source Provenance**: `source_system` (e.g. `school_sis`, `moodle`, `attendance_system`, `allps`, `csv_import`, `synthetic_dataset`) and `ingestion_method` (`api`, `webhook`, `scheduled_sync`, `csv_import`, `manual_observation`, `learner_pulse`, `synthetic`). ALLPS is not an authoritative gradebook; origin systems are explicitly preserved.
  - **Attribution**: `source_type` (`teacher`, `system`, `learner`) and `source_reference` (e.g. `"Mr. Banda"`).
  - **Academic Time**: `academic_year` (int), `term` (int), and UTC timezone-aware `observed_at`. Timezone-naive timestamps are rejected.
  - **Payload Validation**: Structured payloads are validated per evidence type. Assessment scores must be non-negative finite numbers with `score <= max_score`. Attendance requires either a daily status (`present`, `absent`, `late`) or term-level counts (`days_present` and `days_total` with `days_present <= days_total`). A supplied `rate` field is accepted in the content but is not currently validated against the counts.
- **Chronological History**: The `get_learner_history` tool returns records sorted chronologically (`academic_year ASC, term ASC, observed_at ASC`), supporting filtering by type, year, term, and subject. Pattern detection and baseline comparisons are planned for Phase 2.
- **Idempotency & Retry Handling**: Requires `source_event_id`. When a submission matches an existing `(source_system, source_event_id)` with identical observation fields, the original record is returned and the retry is logged in the audit trail. If the fields differ, a conflict error is raised. Without `source_event_id`, repeated submissions can create separate records.
- **Transactional Atomicity**: Evidence creation and its success audit entry commit together in a single transaction. If validation fails, the transaction rolls back. The service attempts to write a failure audit entry, but if audit storage is also unavailable, the error is logged and re-raised — no audit record is guaranteed in that scenario.
- **Storage and Safeguards**: Evidence models are frozen, and the MCP server exposes no evidence editing or deletion tools. Direct database access can still modify records. SQLite provides local storage. How connected MCP clients handle returned learner data depends on those clients.
- **Model Context Protocol (MCP)**: Runs as a standard stdio MCP server, compatible with FastMCP and standard MCP clients.

### What Remains Unfinished (Future Work)

- **Teacher Identity Authentication**: `ReviewService` prevents automated bots from approving patterns through identifier screening and decouples agent orchestration from adjudication. However, `reviewer_id` is currently an unauthenticated string parameter without cryptographic proof or SSO session tokens. A production deployment requires cryptographic teacher authentication.
- **Dedicated Educator UI**: Web dashboards, mobile teacher approval interfaces, and visual timeline exports are planned for future frontend milestones.
- **Live Open-Weight Model Verification**: Automated test suites verify AI orchestration via bounded mocks and deterministic fallback. Verification against live open-weight LLMs (e.g. Qwen 3.5 4B via LM Studio) requires a running local instance with loaded VRAM weights; when LM Studio times out during model loading, ALLPS engages deterministic fallback.

### Known Limitations

- **Concurrent submissions with the same source event**: When two overlapping requests submit the same `(source_system, source_event_id)`, both can pass the initial existence check before either transaction commits. SQLite's `UNIQUE(source_system, source_event_id)` index constraint ensures that only one evidence record is stored. The second call encounters an `IntegrityError`, rolls back its ingestion transaction, and attempts to log a failure audit entry. Sequential retries of identical events succeed normally and return the existing evidence record.
- **Teacher Review Authority Boundary**: While agent tools cannot self-approve and unreviewed/rejected patterns are never surfaced in the public profile, any caller with direct Python or MCP access can pass a human-like `reviewer_id`. Full cryptographic authentication remains an unresolved roadmap requirement.

---

## Getting Started

### Prerequisites

- Python 3.11+ (tested on Python 3.13 and 3.14)
- Virtual environment or system Python

### Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/kwisdomk/ALLPS.git
cd ALLPS

# Install package and dependencies
pip install -e .

# Or install with dev/testing dependencies
pip install -e ".[dev]"
```

Dependencies include:
- `pydantic>=2.0,<3` — Type validation and serialization
- `aiosqlite>=0.19` — Async SQLite persistence
- `mcp>=1.0` — Model Context Protocol SDK (supports FastMCP and MCPServer)
- `pytest>=8.0`, `pytest-asyncio>=0.23` — Asynchronous testing

---

## Running Tests

The test suite includes **238 automated tests** across 13 test suites covering domain models, storage queries, service business logic, direct tool functions, pipeline roundtrips, regression edge cases, protocol-level MCP subprocess tests, bounded AI orchestration, epistemic output validation, indirect peer-comparison validator screening, runtime provider discovery with graceful degradation, and audit security/governance boundaries:

```bash
pytest -v
# or on Windows
python -m pytest -v
```

Output summary:
```text
tests/test_agent_orchestration.py ..................... [  8%]
tests/test_analysis_service.py ...................      [ 16%]
tests/test_audit_fixes.py ....                          [ 18%]
tests/test_demo_e2e.py .....                            [ 20%]
tests/test_evidence_service.py ..........               [ 24%]
tests/test_mcp_tools.py .............                   [ 30%]
tests/test_models.py ..........................         [ 41%]
tests/test_peer_comparison_gap.py ..................... [ 52%]
tests/test_phase2_analysis_repairs.py ................  [ 59%]
tests/test_phase2_governance.py ....................... [ 76%]
tests/test_regression.py ............                   [ 82%]
tests/test_runtime_discovery.py ......................  [ 92%]
tests/test_storage.py ...................               [100%]
===================== 238 passed in ~65s =====================
```

---

## Milestone 03 -- End-to-End Demonstration (`examples/demo_e2e.py`)

The reproducible demonstration executes the complete ALLPS workflow, verifying all 5 canonical outcomes against synthetic school data on an isolated disposable database:

### 1. Auto Mode (Adaptive Discovery & Fallback -- Recommended)
Probes local providers (LM Studio $\to$ Ollama) and automatically falls back to the deterministic analysis engine if no functional AI provider is ready:
```bash
python examples/demo_e2e.py --mode auto
```

### 2. Deterministic Mode (Pure Evidence-Based Analysis, Zero AI Dependency)
Runs genuine longitudinal evidence analysis using rule-based calculations without network or model dependencies:
```bash
python examples/demo_e2e.py --mode deterministic
```

### 3. Mock Mode (Instant Contract-Compliant Canned Responses)
Runs completely offline in under 2 seconds using canned mock fixtures for rapid regression verification:
```bash
python examples/demo_e2e.py --mode mock
```

### 4. Live Mode (Strict Local LLM Inference)
Connects directly to an open-weight model hosted locally (e.g. Qwen 3.5 4B via LM Studio) and strictly fails if the model is not ready:
```bash
python examples/demo_e2e.py --mode live --endpoint http://127.0.0.1:1234/v1
```

### CLI Arguments & Options:
- `--mode {auto,live,deterministic,mock}`: Execution mode (default: `auto`).
- `--endpoint URL`: OpenAI-compatible endpoint (default: `http://127.0.0.1:1234/v1`).
- `--model NAME`: Target model identifier.
- `--db-path PATH`: Custom SQLite database path (default: disposable temporary file).
- `--keep-db`: Retain disposable database file on exit instead of deleting.
- `--timeout SECONDS`: Inference timeout in seconds (default: 90.0).

### Demonstrated Outcomes:
| Outcome | Scenario | AI Pipeline | Simulated Teacher Review | Surfaced Profile |
|---|---|---|---|---|
| **1. Trend Detection** | `LRN-001` (Amara Kemboi, Math) | Validated handover brief (scores 82 -> 68 -> 51) | **ACCEPTED** by Mr. Banda | **Surfaced** with immutable SHA-256 snapshot |
| **2. Persistent Strength** | `LRN-002` (Thabo Ndlovu, Science) | Validated handover brief (scores 88, 91, 89 + project) | **ACCEPTED** by Dr. Mensah | **Surfaced** with immutable SHA-256 snapshot |
| **3. Divergent Evidence** | `LRN-003` (Naledi Mwangi, English) | Notes divergence between strong scores (78, 81, 76) and withdrawal | **REJECTED** by Ms. Achebe (temporary family bereavement note) | **Hidden** (Zero pattern leakage into profile) |
| **4. Safe Abstention** | `LRN-003` (Science, sparse/damaged data) | AI cleanly abstains (fewer than 3 comparable observation points) | N/A (No review item generated) | **Hidden** (Zero noise for educators) |
| **5. Policy Rejection** | Intentionally invalid draft | Blocks indirect peer ranking (*"falling behind peers"*, *"below grade average"*), labels, & causal links | Gated before DB insertion | **Blocked** (Audit trail records validation failure) |

---

## Synthetic Data & Seeding

ALLPS includes 3 synthetic learners representing synthetic Kenyan school examples (used for testing longitudinal comparability; not official curriculum validation):

| Learner | ID | Scenario |
|---|---|---|
| **Learner 001** | `LRN-001` | Steady decline in maths over 3 terms; attendance drops; learner reflection notes difficulty |
| **Learner 002** | `LRN-002` | Consistent 85–91% science scores; high attendance; extracurricular mentoring; projects |
| **Learner 003** | `LRN-003` | Strong English test scores (76–81%), but teacher observations note withdrawn behavior and low participation. No self-reflection in terms 1–2. |

> **Note on Data Provenance**: These fixtures are synthetic Kenyan school examples created for system testing and comparability verification. They are not real student records from the Kenya Institute of Curriculum Development (KICD), the Tusome Early Grade Reading Activity, or any school system, and they do not imply official curriculum validation.

To seed a development database and run the MCP server against it:

```bash
# Seed the database
python data/synthetic/seed_data.py allps_dev.db

# Point the MCP server at the same database
# Linux/macOS
export ALLPS_DB_PATH="allps_dev.db"
# Windows PowerShell
$env:ALLPS_DB_PATH="allps_dev.db"

# Start the MCP server
allps-mcp
```

---

## Running the MCP Server

You can run the MCP server directly via stdio:

```bash
# Using CLI entrypoint
allps-mcp

# Or via python module
python -m allps.mcp.server
```

To configure the database path used by the MCP server, set `ALLPS_DB_PATH`:
```bash
# Linux/macOS
export ALLPS_DB_PATH="path/to/school.db"
# Windows PowerShell
$env:ALLPS_DB_PATH="path/to/school.db"
```

If `ALLPS_DB_PATH` is not set, the server defaults to `allps.db` in the current directory.

### Connecting via Model Context Protocol (stdio)

Any standard MCP-compliant client or harness connects via stdio JSON-RPC. Example standard configuration:

```json
{
  "mcpServers": {
    "allps": {
      "command": "python",
      "args": ["-m", "allps.mcp.server"],
      "cwd": "/path/to/ALLPS",
      "env": {
        "ALLPS_DB_PATH": "/path/to/ALLPS/allps_dev.db"
      }
    }
  }
}
```

---

## AI Runtime Discovery & Graceful Degradation (Workstream 3)

ALLPS includes a modular **Runtime Decision Layer** (`allps.runtime`) that dynamically discovers available inference providers, verifies model readiness, and selects an execution strategy without compromising governance rules or learner privacy.

### Supported Providers
1. **LM Studio** (`http://127.0.0.1:1234/v1`): OpenAI-compatible API with dynamic model discovery.
2. **Ollama** (`http://127.0.0.1:11434/v1`): OpenAI-compatible API with dynamic model discovery.
3. **Deterministic Engine**: Genuine evidence-based longitudinal analysis operating directly on real records without network or LLM dependencies.

### Supported Execution Modes

| Mode | Behavior |
|---|---|
| `auto` | Discovers providers in priority order (LM Studio $\to$ Ollama), verifies readiness via minimal zero-learner probe, or safely falls back to deterministic analysis. |
| `live` | Requires a verified, functional AI provider; fails explicitly if unavailable (refuses silent fallback). |
| `deterministic` | Executes genuine evidence-based non-AI analysis without model dependencies. |
| `mock` | Runs deterministic mock fixtures for offline CI/CD and verification. |

### Running the End-to-End Demonstration

```powershell
# Automatic discovery with graceful deterministic fallback
python examples/demo_e2e.py --mode auto

# Explicit live AI inference
python examples/demo_e2e.py --mode live

# Pure deterministic rule engine (analyzing real learner records)
python examples/demo_e2e.py --mode deterministic

# Offline reproducible mock execution
python examples/demo_e2e.py --mode mock
```

---

## Specifications & Roadmap

- **Data & Behavioral Contracts**: See [docs/contracts.md](docs/contracts.md) for payload schemas, strict comparability rules, missingness semantics, and review governance.
- **Verification Evidence**: See [EVALS.md](EVALS.md) for the 89-test verification matrix.
- **Proposed & Deferred Work**: See [ROADMAP.md](ROADMAP.md) for upcoming milestones and completion criteria.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
