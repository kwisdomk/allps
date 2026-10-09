# ALLPS — Architecture & Technical Design

> **Document Status**: Phase 1 Implementation Complete  
> **Target Audience**: Challenge Evaluators, Systems Engineers, Educators

---

## 1. System Mission & Philosophy

ALLPS (Agentic Longitudinal Learner Profile System) is designed to solve a foundational friction in primary and secondary education across Africa: **the loss of learner context across terms, school years, and changing teachers**.

### Core Tenet: "Collect observations, not identities."

Educational systems often inadvertently condense learners into static labels ("at-risk", "struggling", "gifted", "uncooperative"). These labels stigmatize students and introduce anchoring bias for subsequent teachers. 

ALLPS shifts the paradigm from **identity labels** to **longitudinally situated observations**:
1. Evidence consists of objective, timestamped records (test scores, attendance records, classroom observations, self-reflections).
2. The system surfaces observable relationships across time (trends, persistence, convergence, divergence).
3. The system enforces that AI interpretations have the **lowest authority** in the hierarchy, with teachers acting as essential human-in-the-loop reviewers before any interpretation is accepted into a student's profile.

---

## 2. Component Architecture (Phase 1)

```
┌────────────────────────────────────────────────────────────────┐
│                       MCP Interface                            │
│  [allps.mcp.server]                                            │
│    • ingest_evidence                                           │
│    • get_learner_history                                       │
└───────────────────────────────┬────────────────────────────────┘
                                │
┌───────────────────────────────▼────────────────────────────────┐
│                      Service Layer                             │
│  [allps.services.evidence_service]                             │
│    • Pydantic validation & normalization                       │
│    • Learner existence check / auto-registration               │
│    • Audit logging integration                                 │
└───────────────────────────────┬────────────────────────────────┘
                                │
┌───────────────────────────────▼────────────────────────────────┐
│                      Storage Layer                             │
│  [allps.storage.sqlite_store]                                  │
│    • Async SQLite via aiosqlite                                │
│    • Strict relational schema with indexed queries             │
│    • Immutable evidence append-only policy                     │
└───────────────────────────────┬────────────────────────────────┘
                                │
┌───────────────────────────────▼────────────────────────────────┐
│                     Domain Data Models                         │
│  [allps.models]                                                │
│    • Learner, Evidence, Pattern, ReviewItem, AuditEntry        │
└────────────────────────────────────────────────────────────────┘
```

---

## 3. Domain Model Specifications

### 3.1. `Learner`
Represents the student identity boundary.
- `learner_id: str` (UUID or school ID)
- `display_name: str` (Student display name, max 200 chars)
- `created_at: datetime` (Timezone-aware UTC)
- **Constraint**: `model_config = {"frozen": True}`

### 3.2. `Evidence`
The foundational unit of observation in ALLPS.
- `evidence_id: str` (UUID)
- `learner_id: str` (Foreign key to Learner)
- `evidence_type: EvidenceType` (Enum: `assessment`, `attendance`, `observation`, `learner_reflection`, `project`)
- **System Origin & Ingestion Channel**:
  - `source_system: str`: Originating system (e.g., `"school_sis"`, `"moodle"`, `"attendance_system"`, `"allps"`, `"csv_import"`, `"synthetic_dataset"`). Captures that ALLPS is not the authoritative gradebook and preserves upstream origin.
  - `ingestion_method: IngestionMethod` (Enum: `api`, `webhook`, `scheduled_sync`, `csv_import`, `manual_observation`, `learner_pulse`, `synthetic`)
- **Provenance Attributes**:
  - `source_type: str`: Category of author (`"teacher"`, `"system"`, `"learner"`)
  - `source_reference: str`: Concrete author or system identity (e.g., `"Mr. Banda"`, `"attendance-system-v2"`)
- **Sortable Academic Time**:
  - `academic_year: int`: Integer year (`2000 <= year <= 2100`)
  - `term: int`: Term number (`1 <= term <= 4`)
  - `observed_at: datetime`: Explicit timestamp when observation took place (UTC / timezone-aware required)
  - `recorded_at: datetime`: Timestamp when record was ingested into ALLPS
- `subject: str | None`: Optional academic subject (e.g., `"Mathematics"`, `"Science"`)
- `content: dict[str, Any]`: Structured, flexible payload according to evidence type (e.g., `{"score": 82, "max_score": 100}`)
- **Immutability**: `model_config = {"frozen": True}`. Evidence records cannot be modified once committed.

### 3.3. `Pattern`
A candidate longitudinal pattern discovered across evidence records (prepared for Phase 2).
- `pattern_id: str` (UUID)
- `learner_id: str` (Foreign key to Learner)
- `pattern_type: PatternType` (Enum: `trend`, `persistence`, `convergence`, `divergence`, `changed_from_baseline`, `insufficient_evidence`)
- `summary: str`: Factual statement describing the pattern
- `supporting_evidence: list[str]`: List of `evidence_id` references
- `conflicting_evidence: list[str]`: List of `evidence_id` references that contradict or qualify the pattern
- `limitations: list[str]`: Known caveats (e.g., missing terms, small sample size)
- `generated_at: datetime`: Timestamp
- **Architectural Decision**: `review_status` has been intentionally removed from `Pattern`. Human review states are separated into `ReviewItem` to maintain single-source-of-truth semantics.

### 3.4. `ReviewItem`
The human-in-the-loop review mechanism.
- `review_id: str` (UUID)
- `pattern_id: str` (Foreign key to Pattern)
- `assigned_to: str | None`: Teacher identifier
- `status: ReviewStatus` (Enum: `pending`, `accepted`, `rejected`, `needs_context`)
- `teacher_notes: str | None`: Professional notes by the educator
- `created_at: datetime`: Submission timestamp
- `resolved_at: datetime | None`: Resolution timestamp

### 3.5. `AuditEntry`
Security and traceability ledger for every MCP tool invocation.
- `audit_id: str` (UUID)
- `timestamp: datetime` (UTC)
- `tool_name: str` (e.g., `"ingest_evidence"`, `"get_learner_history"`)
- `input_summary: dict[str, Any]`: Sanitized input arguments
- `output_reference: str | None`: Affected entity reference (e.g., recorded `evidence_id`)
- `approval_state: str | None`: State flags

---

## 4. Storage Architecture (SQLite)

The persistence layer uses asynchronous SQLite via `aiosqlite`.

### Schema & Indexing Strategy

```sql
CREATE TABLE learners (
    learner_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE evidence (
    evidence_id TEXT PRIMARY KEY,
    learner_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    source_system TEXT NOT NULL,
    ingestion_method TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_reference TEXT NOT NULL,
    academic_year INTEGER NOT NULL,
    term INTEGER NOT NULL,
    subject TEXT,
    content TEXT NOT NULL,       -- JSON serialized
    observed_at TEXT NOT NULL,   -- ISO 8601 UTC
    recorded_at TEXT NOT NULL,   -- ISO 8601 UTC
    FOREIGN KEY (learner_id) REFERENCES learners(learner_id)
);

CREATE INDEX idx_evidence_learner ON evidence(learner_id);
CREATE INDEX idx_evidence_time ON evidence(academic_year, term, observed_at);
```

### Ordering Guarantees
Learner evidence is consistently returned in strict chronological order:
```sql
SELECT ... FROM evidence 
WHERE learner_id = ? 
ORDER BY academic_year ASC, term ASC, observed_at ASC;
```
This guarantees deterministic sequence reconstruction across academic transitions.

---

## 5. Model Context Protocol (MCP) Interface

The MCP server implements the official Model Context Protocol using FastMCP / MCPServer (compatible with both MCP 1.x and 2.x SDKs).

### Exposed Tools (Phase 1)

1. `ingest_evidence` (backwards-compatible alias: `record_evidence`):
   - Validates all fields against domain model constraints.
   - Enforces timezone-aware dates.
   - Writes immutable evidence to SQLite.
   - Generates an immutable audit trail entry in `audit_log`.
2. `get_learner_history`:
   - Retrieves all evidence matching learner ID.
   - Supports optional SQL filtering by `evidence_type`, `academic_year`, `term`, and `subject`.
   - Logs an audit query entry.

### Protocol Verification
The system includes automated tests that verify compliance with the wire protocol by running the server process via `stdio_client` and invoking tools using `ClientSession.call_tool()`.

---

## 6. Security, Safety, and Privacy Guardrails

1. **Observations vs. Diagnoses**: The system rejects diagnostic labels in evidence descriptions.
2. **Provenance Accountability**: Every record is tied to an explicit `source_type` and `source_reference`.
3. **No External Telemetry**: All data operations execute against a local SQLite database, avoiding data exfiltration of sensitive student data.
4. **Audit Trail**: Every query and insert is committed to the immutable audit log table.
