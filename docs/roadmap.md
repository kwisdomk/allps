# ALLPS — Project Roadmap & Completion Criteria

> **Document Status**: Living Roadmap  
> **Target Audience**: Challenge Evaluators, Contributors, Educators  
> **Scope**: Milestones, Implementation Status, and Acceptance Criteria

---

## 1. Status Overview

| Capability | Category | Status | Verification Evidence |
|---|---|---|---|
| **Immutable Evidence Ledger** | Storage / Models | **Implemented & Verified** | Frozen models and persistence checks in `test_storage.py` |
| **System Origin & Provenance Tracking** | Data Integrity | **Implemented & Verified** | Preserves `source_system` and `ingestion_method` |
| **Idempotency & Conflict Replays** | Persistence | **Implemented & Verified** | Unique `(source_system, source_event_id)` constraints in `test_regression.py` |
| **Canonical Evidence Fingerprinting & Intake** | Ingestion | **Implemented & Verified** | `IntakeService`, `ImportManifest`, API/CSV/JSON ingestion in `test_evidence_identity.py` & `test_intake_and_export.py` |
| **Deterministic Longitudinal Comparability** | Analysis Engine | **Implemented & Verified** | Strict 9-key comparability tests in `test_analysis_service.py` |
| **MCP Tools (7-Tool FastMCP Server)** | Protocol | **Implemented & Verified** | `test_mcp_tools.py`, stdio subprocess verification |
| **Enforced Teacher Review Gate** | Human-in-the-Loop | **Implemented & Verified** | `test_phase2_governance.py` |
| **Teacher PIN Auth, Revision Locking & Corrections** | Governance / Auth | **Implemented & Verified** | Signed `HttpOnly` session cookies, `expected_revision` locking, explicit corrections in `test_teacher_review_authority.py` |
| **Reviewer Identity & Approved Snapshot Hashes** | Governance | **Implemented & Verified** | Reviewer identity tracking, non-agent approval guardrails, SHA-256 hash |
| **Prohibited Diagnostic Label Screening** | Safety Policies | **Implemented & Verified** | Screening rejecting stigmatizing labels (`"slow learner"`, `"ADHD"`) in `allps.policies` |
| **Bounded Agent Orchestration** | Agentic AI | **Implemented & Verified** | `src/allps/agent/`, verified in `test_agent_orchestration.py` |
| **Teacher Web Interface & Handover Export** | User Interface | **Implemented & Verified** | FastAPI + Vanilla JS SPA, DB status/reseed controls, PDF/HTML/MD/JSON handover export in `test_web_api.py`, `test_intake_and_export.py`, `test_workspace_seed_and_sync.py` |

---

## 2. Completed & Upcoming Milestones

### Milestone 1: Safety & Review Gate Enforcement (Workstream 2) — Completed

- **Objective**: Turn "Human decides" into an unbypassable architectural
  filter.
- **Status**: Implemented & Verified with 44 tests in
  `tests/test_phase2_governance.py`.

### Milestone 2: Bounded AI Intelligence Layer (Workstream 3) — Completed

- **Objective**: Implement bounded AI synthesis respecting educational safety
  bounds.
- **Status**: Implemented & Verified with 21 tests in
  `tests/test_agent_orchestration.py` and live integration test
  `examples/run_live_lmstudio.py`.

### Milestone 3: E2E Demo & Policy Rejection (Workstream 3/4) — Completed

- **Objective**: Provide a runnable, under-60-second console proof of the
  complete ALLPS lifecycle.
- **Status**: Implemented & Verified in `examples/demo_e2e.py` (mock and live
  modes) and 29 automated tests across `tests/test_demo_e2e.py` and
  `tests/test_peer_comparison_gap.py`.
- **Demonstrated Outcomes**:
  1. **Accepted Trend**: Amara Kemboi declining maths trend -> verified
     handover brief -> Teacher Banda approves -> surfaced with SHA-256
     snapshot.
  2. **Accepted Persistence**: Thabo Ndlovu science strength -> verified
     handover brief -> Dr. Mensah approves -> surfaced with SHA-256
     snapshot.
  3. **Rejected Divergence**: Naledi Mwangi scores vs. observations -> teacher
     rejects with local bereavement context -> strictly hidden.
  4. **Safe Abstention**: Insufficient / damaged science assessment data ->
     deterministic engine -> clean AI abstention -> zero review items
     generated.
  5. **Policy Rejection**: Intentionally invalid draft containing indirect
     peer ranking (*"falling behind peers"*, *"below grade average"*), deficit
     labels, and causal links -> rejected by OutputValidator -> gated from
     database.

### Milestone 4: Teacher Web Interface (Workstream 4) — Completed

- **Objective**: Lightweight local educator review dashboard and longitudinal
  learner timeline viewer.
- **Status**: Implemented & Verified in `tests/test_web_api.py` and browser
  verification scripts (`tests/exercise_browser_workflow.py`,
  `tests/verify_live_teacher_workflow.py`).
- **Deliverables**:
  - FastAPI web server (`src/allps/web/app.py`, `src/allps/web/routes.py`).
  - Zero-dependency Vanilla JS Single Page Application
    (`src/allps/web/static/index.html`).
  - Full candidate brief persistence across page reload (INT-01).
  - Sovereign human teacher review adjudication and SHA-256 snapshotting.

### Milestone 5: Teacher Review Authority, External Intake & Handover Export — Completed

- **Objective**: Harden educator identity, race-safe review decisions,
  external school data ingestion, sovereign handover export, and workspace
  database sync controls.
- **Status**: Implemented & Verified across `tests/test_teacher_review_authority.py`,
  `tests/test_evidence_identity.py`, `tests/test_intake_and_export.py`, and
  `tests/test_workspace_seed_and_sync.py`.
- **Deliverables**:
  - Local PIN login and HMAC-signed `HttpOnly` session cookies (`src/allps/auth.py`).
  - Optimistic concurrency (`expected_revision`) and explicit teacher correction path.
  - Canonical SHA-256 evidence fingerprinting, `ImportManifest` tracking, and `IntakeService` (`POST /api/ingest/records`, `POST /api/ingest/file`).
  - `ExportService` handover generation in PDF, HTML, Markdown, and JSON (`GET /api/learners/{id}/handover/export`).
  - Idempotent `seed_data.py` CLI (`--status`, `--reset`) and UI **Database & Sync** sidebar (`GET /api/db/status`, `POST /api/db/reseed`).
