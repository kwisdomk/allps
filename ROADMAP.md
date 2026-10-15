# ALLPS — Project Roadmap & Completion Criteria

> **Document Status**: Living Roadmap  
> **Target Audience**: Challenge Evaluators, Contributors, Educators  
> **Scope**: Milestones, Implementation Status, and Acceptance Criteria

---

## 1. Status Overview

| Capability | Category | Status | Verification Evidence |
|---|---|---|---|
| **Immutable Evidence Ledger** | Storage / Models | **Implemented & Verified** | 19 tests in `test_storage.py`, frozen models |
| **System Origin & Provenance Tracking** | Data Integrity | **Implemented & Verified** | Preserves `source_system` and `ingestion_method` |
| **Idempotency & Conflict Replays** | Persistence | **Implemented & Verified** | Unique constraints and replay tests in `test_regression.py` |
| **Deterministic Longitudinal Comparability** | Analysis Engine | **Implemented & Verified** | 15 strict comparability tests in `test_analysis_service.py` |
| **MCP Tools (`ingest`, `history`, `analyse`)** | Protocol | **Implemented & Verified** | 12 tests in `test_mcp_tools.py`, stdio subprocess test |
| **Enforced Teacher Review Gate** | Human-in-the-Loop | **Implemented & Verified** | 44 tests in `test_phase2_governance.py` |
| **Reviewer Identity & Approved Snapshot Hashes** | Governance | **Implemented & Verified** | Reviewer identity tracking, non-agent approval guardrails, SHA-256 hash |
| **Prohibited Diagnostic Label Screening** | Safety Policies | **Implemented & Verified** | Screening rejecting stigmatizing labels (`"slow learner"`, `"ADHD"`) in `allps.policies` |
| **Bounded Agent Orchestration** | Agentic AI | **Implemented & Verified** | `src/allps/agent/`, 21 tests in `test_agent_orchestration.py` |
| **Multi-Outcome E2E Demo Script** | Demonstration | **Implemented & Verified** | `examples/demo_e2e.py`, automated tests in `tests/test_demo_e2e.py` |
| **Teacher Web Interface** | User Interface | **Upcoming (Milestone 04)** | Local FastAPI + HTML/CSS/JS dashboard for review inbox |

---

## 2. Completed & Upcoming Milestones

### Milestone 1: Safety & Review Gate Enforcement (Workstream 2) — Completed
* **Objective**: Turn "Human decides" into an unbypassable architectural filter.
* **Status**: Implemented & Verified with 44 tests in `tests/test_phase2_governance.py`.

### Milestone 2: Bounded AI Intelligence Layer (Workstream 3) — Completed
* **Objective**: Implement bounded AI synthesis respecting educational safety bounds.
* **Status**: Implemented & Verified with 21 tests in `tests/test_agent_orchestration.py` and live integration test `examples/test_live_lmstudio.py`.

### Milestone 3: End-to-End Multi-Outcome Demo & Policy Rejection (Workstream 3/4) — Completed
* **Objective**: Provide a runnable, under-60-second console proof of the complete ALLPS lifecycle.
* **Status**: Implemented & Verified in `examples/demo_e2e.py` (mock and live modes) and 29 automated tests across `tests/test_demo_e2e.py` and `tests/test_peer_comparison_gap.py`.
* **Demonstrated Outcomes**:
  1. **Accepted Trend**: Amara Kemboi declining maths trend -> verified handover brief -> Teacher Banda approves -> surfaced with SHA-256 snapshot.
  2. **Accepted Persistence**: Thabo Ndlovu science strength -> verified handover brief -> Dr. Mensah approves -> surfaced with SHA-256 snapshot.
  3. **Rejected Divergence**: Naledi Mwangi scores vs. observations -> teacher rejects with local bereavement context -> strictly hidden.
  4. **Safe Abstention**: Insufficient / damaged science assessment data -> deterministic engine -> clean AI abstention -> zero review items generated.
  5. **Policy Rejection**: Intentionally invalid draft containing indirect peer ranking (*"falling behind peers"*, *"below grade average"*), deficit labels, and causal links -> rejected by OutputValidator -> gated from database.

### Milestone 4: Teacher Web Interface (Workstream 4) — Upcoming
* **Objective**: Lightweight local educator review dashboard and longitudinal learner timeline viewer.
