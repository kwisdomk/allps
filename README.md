# ALLPS — Agentic Longitudinal Learner Profile System

> Built for the African Agentic AI Design Challenge, education track.  
> *"Collect observations, not identities."*

---

## Overview

Schools collect rich learner data — assessments, attendance, projects, teacher observations, participation metrics, and learner self-reflections. However, this information is almost always fragmented across terms, school years, and changing teachers. When a student transitions to a new grade or teacher, their longitudinal context is lost, forcing each educator to start from scratch or rely on informal impressions.

**ALLPS (Agentic Longitudinal Learner Profile System)** preserves learning continuity across terms, years, and teachers by connecting longitudinal evidence and surfacing sourced, verifiable patterns.

Planned pattern-detection capabilities (Phase 2) include:

- **Trends** (e.g., changes across terms)
- **Persistence** (e.g., sustained strengths or ongoing challenges)
- **Convergence** (e.g., multiple independent evidence sources aligning)
- **Divergence** (e.g., conflicting evidence, such as high assessment scores alongside disengagement observations)
- **Meaningful change from baseline** (evaluating learners against their own historical baseline, never ranking against peers)

### Design Principles

These ten rules guide the design of ALLPS. Some are enforced in the current implementation; others describe intended safeguards for future phases.

**Implemented in Phase 1:**

1. **Collect observations, not identities**: ALLPS records factual, dated, attributed observations. It does not assign static labels itself, but diagnostic-label detection and blocking are not implemented, and the schema does not prevent labels.
2. **Evidence immutability**: Evidence models are frozen, and the MCP server exposes no evidence editing or deletion tools. Direct database access can still modify records.
3. **Explicit provenance**: Every piece of evidence captures *who* observed it, *when* it was observed, and *when* it was recorded in ALLPS.
4. **Strict non-ranking**: History queries accept a single learner ID. Ranking or peer-sorting is not exposed in the API.
5. **Sortable chronological history**: History queries return records sorted chronologically by academic year, term, and observation time. Automated baseline comparisons and pattern detection are planned for Phase 2.

**Planned for Phase 2 and beyond:**

6. **One observation is not a pattern**: Multiple data points across time will be required before surfacing a pattern.
7. **Correlation is not causation**: Surfaced patterns will describe co-occurrence, not causal claims.
8. **Missing learner responses are not negative evidence**: Absence of evidence will not be treated as deficit.
9. **AI interpretations are the lowest-authority evidence layer**: AI assists; human professionals decide.
10. **Consequential outputs must go through teacher review**: The `ReviewItem` data model exists. Enforcement of teacher sign-off before patterns enter a learner's profile is a Phase 2 deliverable.

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

- **Pattern Detection & Baseline Comparisons**: The pattern detection engine (`analyse_longitudinal_pattern`) is planned for Phase 2. Trend, persistence, convergence, divergence, and baseline comparisons are not implemented.
- **Diagnostic-Label Detection**: Diagnostic-label detection and blocking are not implemented. The schema does not prevent labels from being included in submitted content.
- **AI Synthesis**: Generating sourced, verifiable summaries from longitudinal evidence is planned for a future phase.
- **Enforced Teacher Approval**: The `ReviewItem` and `Pattern` data models exist in the schema. Review gating workflows (`flag_pattern_for_review`) and enforced teacher sign-off are Phase 2 deliverables.
- **Agent Orchestration**: Multi-agent handoffs, automated synthesis for teacher transitions, and intervention drafting are planned for Phase 3.
- **User Interface**: Web interfaces, teacher review dashboards, and visual timeline exports are planned for Phase 4.

### Known Limitations

- **Concurrent submissions with the same source event**: When two overlapping requests submit the same `(source_system, source_event_id)`, both can pass the initial existence check before either transaction commits. SQLite's `UNIQUE(source_system, source_event_id)` index constraint ensures that only one evidence record is stored. The second call encounters an `IntegrityError`, rolls back its ingestion transaction, and attempts to log a failure audit entry. Sequential retries of identical events succeed normally and return the existing evidence record.

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

The test suite includes 66 automated tests covering domain models, storage queries, service business logic, direct tool functions, pipeline roundtrips, regression edge cases, and a real protocol-level MCP subprocess test that spawns the server and talks over stdio:

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

## Synthetic Data & Seeding

ALLPS includes 3 synthetic learners. These fixtures prepare scenarios for future pattern-detection analysis:

| Learner | ID | Scenario |
|---|---|---|
| **Amara Obi** | `LRN-001` | Steady decline in maths over 3 terms; attendance drops; learner reflection notes difficulty |
| **Thabo Mokoena** | `LRN-002` | Consistent 85–91% science scores; high attendance; extracurricular mentoring; projects |
| **Naledi Dlamini** | `LRN-003` | Strong English test scores (76–81%), but teacher observations note withdrawn behavior and low participation. No self-reflection in terms 1–2. |

> **Note on Data Provenance**: These fixtures are fictional synthetic scenarios created for system testing. They are not real student records from the Tusome Early Grade Reading Activity or any school system, and Tusome field definitions have not been verified against production educational datasets.

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
        "ALLPS_DB_PATH": "/path/to/ALLPS/allps_dev.db"
      }
    }
  }
}
```

---

## Roadmap

- **Phase 1 (Current)**: Data foundation, domain models, local SQLite storage, sortable academic time, provenance tracking, synthetic test dataset, runnable MCP server (`ingest_evidence`, `get_learner_history`), full test suite. Evidence models are frozen and MCP tools expose no edit or delete options, while direct database access can still modify records.
- **Phase 2**: Pattern detection engine (`analyse_longitudinal_pattern`), baseline comparisons, teacher review workflow (`flag_pattern_for_review`), diagnostic-label detection, and safety rule enforcement.
- **Phase 3**: Agent orchestration, context synthesis for teacher transitions, and review item management.
- **Phase 4**: Teacher UI / web application, exportable longitudinal summaries, and evaluation suite.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
