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
2. The system is designed to surface observable relationships across time (trends, persistence, convergence, divergence). Pattern detection is planned for Phase 2.
3. AI interpretations are intended to have the **lowest authority** in the hierarchy, with teachers acting as essential human-in-the-loop reviewers. The `ReviewItem` data model exists; enforcement of teacher approval is a Phase 2 deliverable.

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
  - `source_event_id: str | None`: Optional upstream event identifier used for idempotency and duplicate prevention.
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
- `content: dict[str, Any]`: Structured, flexible payload according to evidence type (e.g., `{"score": 82, "max_score": 100}`). There is no required instrument or assessment-tool field; the content schema depends on the evidence type.
- **Immutability**: `model_config = {"frozen": True}`. Evidence records cannot be modified once committed.

### 3.3. `Pattern`
A candidate longitudinal pattern discovered across evidence records (data model defined; detection engine planned for Phase 2).
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
The human-in-the-loop review mechanism (data model and schema defined; enforced teacher approval workflow planned for Phase 2).
- `review_id: str` (UUID)
- `pattern_id: str` (Foreign key to Pattern)
- `assigned_to: str | None`: Teacher identifier
- `status: ReviewStatus` (Enum: `pending`, `accepted`, `rejected`, `needs_context`)
- `teacher_notes: str | None`: Professional notes by the educator
- `created_at: datetime`: Submission timestamp
- `resolved_at: datetime | None`: Resolution timestamp

### 3.5. `AuditEntry`
Security and traceability ledger for MCP tool invocations and service operations.
- `audit_id: str` (UUID)
- `timestamp: datetime` (UTC)
- `tool_name: str` (e.g., `"ingest_evidence"`, `"get_learner_history"`)
- `input_summary: dict[str, Any]`: Sanitized input arguments
- `output_reference: str | None`: Affected entity reference (e.g., recorded `evidence_id`)
- `approval_state: str | None`: State flags or failure outcome status (e.g., `"success"`, `"failed: validation_error"`)

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
    source_event_id TEXT,
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
CREATE UNIQUE INDEX idx_evidence_source_event 
    ON evidence(source_system, source_event_id) 
    WHERE source_event_id IS NOT NULL;
```

### Ordering Guarantees
Learner evidence is consistently returned in strict chronological order:
```sql
SELECT ... FROM evidence 
WHERE learner_id = ? 
ORDER BY academic_year ASC, term ASC, observed_at ASC;
```
This guarantees deterministic sequence reconstruction across academic transitions.

### Transaction Isolation & Migrations
- **Non-destructive migration**: On initialization, existing databases lacking `source_event_id` are migrated automatically without data loss.
- **Dedicated transaction ownership**: Ingestion operations isolate their database write transaction so that concurrent read queries or audit actions on a shared connection do not commit uncommitted ingestion records.

---

## 5. Model Context Protocol (MCP) Interface

The MCP server implements the official Model Context Protocol using FastMCP / MCPServer (compatible with MCP 1.x and 2.x SDKs).

### Registered MCP Tools (Phase 1)

1. `ingest_evidence`:
   - Validates all fields against domain model constraints and payload rules.
   - Enforces UTC timezone-aware dates.
   - Handles idempotent retries when `source_event_id` is provided. Without it, repeated submissions can create separate records.
   - Evidence and its success audit entry commit together in a single transaction. If validation fails, the transaction rolls back. The service attempts to write a failure audit entry, but if audit storage is also unavailable, the error is logged and re-raised.
2. `get_learner_history`:
   - Retrieves all evidence matching learner ID.
   - Supports optional SQL filtering by `evidence_type`, `academic_year`, `term`, and `subject`.
   - Logs an audit query entry.

**Backward-compatibility alias**: `record_evidence` is a Python-level alias for `ingest_evidence` in both the service layer and the MCP server module. It is not separately registered as an MCP tool.

### Future Tools (Phase 2 & Beyond)
- `analyse_longitudinal_pattern`: Pattern detection engine (Phase 2).
- `flag_pattern_for_review`: Teacher review routing and sign-off workflow (Phase 2).

---

## 6. Known Limitations

- **Concurrent submissions with the same source event**: When two overlapping requests submit the same `(source_system, source_event_id)`, both can pass the initial existence check before either transaction commits. SQLite's `UNIQUE(source_system, source_event_id)` index constraint ensures that only one record is stored. The second call encounters an `IntegrityError`, rolls back its write, and attempts to record a failure audit entry. Sequential retries of identical events succeed idempotently and return the existing evidence record.

---

## 7. Synthetic Data Disclaimer

The learner records in `data/synthetic/seed_data.py` are fictional synthetic scenarios constructed to prepare for future pattern-detection analysis (trend decline, persistent strength, score-engagement divergence, and missing reflections). They are not real student records from the Tusome Early Grade Reading Activity or any school system, and Tusome field definitions have not been verified against production educational datasets.

---

## 8. Security, Safety, and Privacy Guardrails

1. **Observations vs. Diagnoses**: The system rejects diagnostic labels in evidence descriptions.
2. **Provenance Accountability**: Every record is tied to an explicit `source_type` and `source_reference`.
3. **No External Telemetry**: All data operations execute against a local SQLite database, avoiding exfiltration of sensitive student data.
4. **Audit Trail**: Successful ingestion and its audit entry commit together. Query audit entries are written after retrieval. The service attempts to record failures, but if audit storage is unavailable during a failure, the error is logged rather than silently dropped.
5. **Human-in-the-Loop Safeguard**: The `ReviewItem` data model exists to gate pattern outputs through teacher review. Enforcement of this workflow is planned for Phase 2.
