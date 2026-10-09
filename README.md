# ALLPS — Agentic Longitudinal Learner Profile System

> **Official African Agentic AI Design Challenge Implementation**  
> *"Collect observations, not identities."*

---

## 🌍 Overview

Schools collect rich learner data — assessments, attendance, projects, teacher observations, participation metrics, and learner self-reflections. However, this information is almost always fragmented across terms, school years, and changing teachers. When a student transitions to a new grade or teacher, their longitudinal context is lost, forcing each educator to start from scratch or rely on informal impressions.

**ALLPS (Agentic Longitudinal Learner Profile System)** preserves learning continuity across terms, years, and teachers by connecting longitudinal evidence and surfacing sourced, verifiable patterns:

- 📈 **Trends** (e.g., changes across terms)
- 🔒 **Persistence** (e.g., sustained strengths or ongoing challenges)
- 🎯 **Convergence** (e.g., multiple independent evidence sources aligning)
- ⚠️ **Divergence** (e.g., conflicting evidence, such as high assessment scores alongside disengagement observations)
- 📊 **Meaningful change from baseline** (evaluating learners against their own historical baseline, never ranking against peers)

### Core Principles & Safety Stance

- **Collect observations, not identities**: ALLPS records factual, dated, attributed observations. It never assigns static labels (e.g., "slow learner", "disruptive", "gifted").
- **AI assists, humans decide**: AI surfaces and synthesizes evidence with explicit citations; teachers and educators retain sole authority for educational interventions.
- **Evidence immutability**: Once recorded, evidence cannot be altered, preserving the historical record.
- **Explicit provenance**: Every piece of evidence captures *who* observed it, *what* instrument was used, *when* it was observed, and *when* it was recorded in ALLPS.
- **Strict non-ranking**: Learners are compared solely against their own longitudinal baseline. Ranking or peer-sorting is strictly prohibited.

---

## 🛠️ Phase 1 Scope & Architecture

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
│   • Full-observation idempotency & retry handling      │
│   • Atomic transactions & execution audit logging      │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│               Async SQLite Store                       │
│   • learners                                           │
│   • evidence (immutable, append-only, indexed)         │
│   • patterns (Phase 2 analysis models ready)           │
│   • review_items (human-in-the-loop review state)      │
│   • audit_log (full tool invocation audit trail)       │
└────────────────────────────────────────────────────────┘
```

### What Phase 1 Actually Does

- **Evidence Ingestion**: The `ingest_evidence` tool (with backward-compatible alias `record_evidence`) accepts factual learner observations. It captures:
  - **Source Provenance**: `source_system` (e.g. `school_sis`, `moodle`, `attendance_system`, `allps`, `csv_import`, `synthetic_dataset`) and `ingestion_method` (`api`, `webhook`, `scheduled_sync`, `csv_import`, `manual_observation`, `learner_pulse`, `synthetic`). ALLPS is not an authoritative gradebook; origin systems are explicitly preserved.
  - **Attribution**: `source_type` (`teacher`, `system`, `learner`) and `source_reference` (e.g. `"Mr. Banda"`).
  - **Academic Time**: `academic_year` (int), `term` (int), and UTC timezone-aware `observed_at`. Timezone-free timestamps are rejected.
  - **Payload Validation**: Structured payloads are checked (e.g. assessment scores must have non-negative finite numbers with `score <= max_score`; attendance requires valid days and rates).
- **Chronological History**: The `get_learner_history` tool returns records sorted chronologically (`academic_year ASC, term ASC, observed_at ASC`), supporting filtering by type, year, term, and subject.
- **Idempotency & Retry Handling**: Submitting the same `(source_system, source_event_id)` with identical observation fields returns the original record and logs the retry in the audit trail. Submitting a matching event ID with modified fields raises a clear conflict error.
- **Transactional Atomicity**: Evidence creation and audit logging commit together. If validation or audit storage fails, changes roll back and an audit failure record is preserved.
- **Model Context Protocol (MCP)**: Runs as a standard stdio MCP server, compatible with FastMCP and standard MCP clients.

### What Remains Unfinished (Future Work)

- **Pattern Analysis Engine**: The `analyse_longitudinal_pattern` tool is not implemented in Phase 1. Trend, persistence, convergence, divergence, and baseline-shift analysis are scheduled for Phase 2.
- **Enforced Teacher Approval**: The `ReviewItem` and `Pattern` data models exist in the schema, but review gating workflows (`flag_pattern_for_review`) and enforced teacher sign-off are Phase 2 deliverables.
- **Agent Orchestration**: Multi-agent handoffs, automated synthesis for teacher transitions, and intervention drafting are planned for Phase 3.
- **User Interface**: Web interfaces, teacher review dashboards, and visual timeline exports are scheduled for Phase 4.

### Known Limitations

- **Simultaneous submissions of the same source event**: When two concurrent ingestion calls submit the exact same `(source_system, source_event_id)` at the exact same millisecond, both can pass the initial pre-transaction check before either has committed. SQLite's `UNIQUE(source_system, source_event_id)` index constraint ensures that only one evidence record is stored. The second call encounters an `IntegrityError`, rolls back its ingestion transaction, and logs a failure audit entry. Sequential retries of identical events succeed normally and return the existing evidence record.

---

## 🚀 Getting Started

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

## 🧪 Running Tests

The test suite includes 66 automated tests covering domain models, storage queries, service business logic, direct tool functions, pipeline roundtrips, regression edge cases, and a **real protocol-level MCP subprocess test** that spawns the server and talks over stdio:

```bash
pytest -v
```

Output summary:
```text
tests/test_evidence_service.py .......... [ 15%]
tests/test_mcp_tools.py .........         [ 28%]
tests/test_models.py .................... [ 62%]
tests/test_regression.py ..........       [ 77%]
tests/test_storage.py ...............     [100%]
====================== 66 passed in ~8.2s ======================
```

---

## 📊 Synthetic Data & Seeding

ALLPS includes 3 synthetic learners designed to test future pattern detection algorithms:

| Learner | ID | Scenario | Patterns Tested |
|---|---|---|---|
| **Amara Obi** | `LRN-001` | Steady decline in maths over 3 terms; attendance drops; learner reflection notes difficulty | **Trend** (decline) |
| **Thabo Mokoena** | `LRN-002` | Consistent 85–91% science scores; high attendance; extracurricular mentoring; projects | **Persistence** (strength) |
| **Naledi Dlamini** | `LRN-003` | Strong English test scores (76–81%), but teacher observations note withdrawn behavior and low participation | **Divergence** (grades vs. engagement) & **Missing Data** (no reflection in terms 1-2) |

> **Note on Data Provenance**: These fixtures are fictional synthetic scenarios created for system testing and validation. They are not real student records from the Tusome Early Grade Reading Activity or any school system, and Tusome field definitions have not been verified against production educational datasets.

To seed a development database:

```bash
python data/synthetic/seed_data.py allps_dev.db
```

---

## 🔌 Running the MCP Server

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

### Connecting to Claude Desktop / Antigravity / Cursor

Add the server to your MCP configuration file (`mcp_config.json`):

```json
{
  "mcpServers": {
    "allps": {
      "command": "python",
      "args": ["-m", "allps.mcp.server"],
      "cwd": "/path/to/ALLPS",
      "env": {
        "ALLPS_DB_PATH": "/path/to/ALLPS/allps.db"
      }
    }
  }
}
```

---

## 🛡️ The 10 Safety Rules

ALLPS enforces 10 non-negotiable safety guardrails across all layers:

1. **One observation is not a pattern** — Multiple data points across time are strictly required.
2. **Correlation is not causation** — Surfaced patterns describe co-occurrence, never causal claims.
3. **Missing learner responses are not negative evidence** — Absence of evidence is never treated as deficit.
4. **Learner self-report is one evidence source, not absolute truth** — Valued equally with other observations.
5. **Teacher observations are evidence, not unquestionable truth** — Subject to contextual interpretation and teacher turnover.
6. **AI interpretations are the lowest-authority evidence layer** — AI assists; human professionals decide.
7. **Never rank learners against classmates** — Comparisons are only made against the learner's own baseline.
8. **Primarily compare a learner against their own historical evidence** — Focus on personal growth and trajectories.
9. **Never autonomously generate harmful labels** — Prohibited terminology (e.g., diagnostic or stigmatizing tags).
10. **Consequential outputs must go through teacher review** — All patterns create a `ReviewItem` requiring human sign-off (Data model implemented; strict enforcement planned for Phase 2).

---

## 🗺️ Roadmap

- **Phase 1 (Current)**: Data foundation, domain models, immutable SQLite persistence, sortable academic time, provenance tracking, synthetic test dataset, runnable MCP server (`ingest_evidence`, `get_learner_history`), full test suite.
- **Phase 2**: Deterministic pattern detection engine (`analyse_longitudinal_pattern`), teacher review workflow (`flag_pattern_for_review`), safety validation policies, and rule-based checks.
- **Phase 3**: Agent orchestration, context synthesis for teacher transitions, and review item management.
- **Phase 4**: Teacher UI / web application, exportable longitudinal summaries, and full evaluation suite.

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
