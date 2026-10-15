# ALLPS — Architecture & Technical Design

> **Document Status**: Canonical System Architecture  
> **Target Audience**: Challenge Evaluators, Systems Engineers, Educators  
> **Scope**: Component Architecture, Data Models, Comparability Engine, MCP Interface, Governance Guardrails

---

## 1. System Mission & Philosophy

ALLPS (**Agentic Longitudinal Learner Profile System**) is designed to solve a foundational friction in primary and secondary education across Africa: **the loss of learner context across terms, school years, and changing teachers**.

### Core Tenet: "Record evidence without reducing learners to labels."

Educational systems often condense learners into static labels (*"slow learner"*, *"at-risk"*, *"uncooperative"*). These labels introduce bias for subsequent teachers and erase developmental progress. 

Instead of summarizing learners with identity labels, ALLPS stores individual observations collected over time with source attribution:
1. **Atomic Evidence Ledger**: Stores dated learner evidence (test scores, attendance records, classroom observations, self-reflections) with full provenance.
2. **Deterministic Comparability Engine**: Evaluates longitudinal patterns only across strictly compatible assessment instruments, preventing false trajectories.
3. **Dual-View Approval Boundary**: AI recommends candidate insights and transition handover drafts; sovereign human teachers decide whether candidates are accepted into the learner's published profile.

---

## 2. Component Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                       MCP Interface                            │
│  [allps.mcp.server]                                            │
│    • ingest_evidence                                           │
│    • get_learner_history                                       │
│    • analyse_longitudinal_pattern                              │
│    • flag_pattern_for_review                                   │
│    • resolve_teacher_review                                    │
│    • get_pending_reviews                                       │
│    • get_surfaced_profile                                      │
└──────────────┬────────────────────────────────┬────────────────┘
               │                                │
┌──────────────▼─────────────────┐  ┌───────────▼────────────────┐
│       Evidence Service         │  │      Analysis Service      │
│ [allps.services.evidence_srv]  │  │ [allps.services.analysis]  │
│  • Pydantic validation         │  │  • Strict 9-key comparability│
│  • Provenance & idempotency    │  │  • Trend & baseline deltas │
│  • Audit logging integration   │  │  • Ordinal rubric rules    │
│                                │  │  • True zero / null safety │
└──────────────┬─────────────────┘  └───────────┬────────────────┘
               │                                │
┌──────────────▼────────────────────────────────▼────────────────┐
│                      Storage Layer                             │
│  [allps.storage.sqlite_store]                                  │
│    • Async SQLite via aiosqlite                                │
│    • Relational schema: learners, evidence, patterns,          │
│      review_items, audit_log                                   │
│    • Append-only storage via MCP (frozen models)               │
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

### 3.1. `Learner` — [IMPLEMENTED & VERIFIED]
Represents the student identity boundary.
- `learner_id: str` (UUID or school ID)
- `display_name: str` (Student display name, max 200 chars)
- `created_at: datetime` (Timezone-aware UTC)
- **Constraint**: `model_config = {"frozen": True}`

### 3.2. `Evidence` — [IMPLEMENTED & VERIFIED]
The foundational unit of observation in ALLPS.
- `evidence_id: str` (UUID)
- `learner_id: str` (Foreign key to Learner)
- `evidence_type: EvidenceType` (Enum: `assessment`, `attendance`, `observation`, `learner_reflection`, `project`)
- **System Origin & Ingestion Channel**:
  - `source_system: str`: Originating system (e.g., `"school_sis"`, `"moodle"`, `"attendance_system"`, `"synthetic_dataset"`). Captures that ALLPS is not the authoritative gradebook and preserves upstream origin.
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
- `subject: str | None`: Optional academic subject (e.g., `"Mathematics"`, `"Science"`, `"English"`)
- `content: MappingProxyType[str, Any]`: Structured, immutable payload per evidence type. Supports numeric marks, rubrics with versioned scales, fluency metrics (`value` and `unit`), and explicit missing outcomes with reasons.
- **Immutability**: Evidence models are frozen in Pydantic (`model_config = {"frozen": True}`), and the MCP server exposes no evidence editing or deletion tools. Direct database access can still modify records, as SQLite tables do not enforce database-level immutability triggers.

### 3.3. `Pattern` — [IMPLEMENTED & VERIFIED]
A candidate longitudinal pattern discovered across evidence records.
- `pattern_id: str` (UUID)
- `learner_id: str` (Foreign key to Learner)
- `pattern_type: PatternType` (Enum: `trend`, `persistence`, `convergence`, `divergence`, `changed_from_baseline`, `insufficient_evidence`)
- `summary: str`: Factual statement describing the pattern
- `supporting_evidence: list[str]`: List of `evidence_id` references
- `conflicting_evidence: list[str]`: List of `evidence_id` references that contradict or qualify the pattern
- `limitations: list[str]`: Known caveats (e.g., missing terms, small sample size, stage preservation, ordinal rank boundaries)
- `generated_at: datetime`: Timestamp
- **Architectural Decision**: `review_status` has been intentionally removed from `Pattern`. Human review states are separated into `ReviewItem` to maintain single-source-of-truth semantics.

### 3.4. `ReviewItem` — [MODEL IMPLEMENTED; ENFORCEMENT PROPOSED]
The human-in-the-loop review mechanism.
- `review_id: str` (UUID)
- `pattern_id: str` (Foreign key to Pattern)
- `assigned_to: str | None`: Teacher identifier
- `status: ReviewStatus` (Enum: `pending`, `accepted`, `rejected`, `needs_context`)
- `teacher_notes: str | None`: Professional notes by the educator
- `created_at: datetime`: Submission timestamp
- `resolved_at: datetime | None`: Resolution timestamp
- **Proposed for Workstream 2**:
  - `reviewer_id: str`: Authenticated teacher identity.
  - `approved_content_hash: str`: SHA-256 hash of the exact approved pattern summary snapshot.
  - Automated item generation on pattern detection.
  - Dual-view profile filter gating unapproved patterns.

### 3.5. `AuditEntry` — [IMPLEMENTED & VERIFIED]
Security and traceability ledger for MCP tool invocations and service operations.
- `audit_id: str` (UUID)
- `timestamp: datetime` (UTC)
- `tool_name: str` (e.g., `"ingest_evidence"`, `"get_learner_history"`, `"analyse_longitudinal_pattern"`)
- `input_summary: dict[str, Any]`: Sanitized input arguments
- `output_reference: str | None`: Affected entity reference (e.g., recorded `evidence_id`)
- `approval_state: str | None`: State flags or failure outcome status (e.g., `"success"`, `"failed: validation_error"`)

---

## 4. Storage Architecture (SQLite) — [IMPLEMENTED & VERIFIED]

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

### Transaction Isolation & Migrations
- **Non-destructive migration**: On initialization, existing databases lacking `source_event_id` are migrated automatically without data loss.
- **Dedicated transaction ownership**: Ingestion operations isolate their database write transaction so that concurrent read queries or audit actions do not commit uncommitted ingestion records.

---

## 5. Model Context Protocol (MCP) Interface — [IMPLEMENTED & VERIFIED]

The MCP server implements the official Model Context Protocol via standard stdio transport:

### Active MCP Tools
1. `ingest_evidence`:
   - Validates all fields against domain model constraints and payload rules.
   - Enforces UTC timezone-aware dates.
   - Handles idempotent retries when `source_event_id` is provided. Without it, repeated submissions create separate records.
   - Evidence and its success audit entry commit together in a single transaction. If validation fails, the transaction rolls back.
2. `get_learner_history`:
   - Retrieves all evidence matching learner ID in chronological order.
   - Supports optional SQL filtering by `evidence_type`, `academic_year`, `term`, and `subject`.
   - Logs an audit query entry.
3. `analyse_longitudinal_pattern`:
   - Runs deterministic longitudinal pattern detection across compatible evidence streams.
   - Enforces strict comparability across grade, subject, skill, form, form version, language, measure, scale, and assessment stage.
   - Requires explicit comparison authorization (`comparison_authorized: True`).
   - Requires at least 3 distinct academic periods for across-term trends.
   - Logs an audit query entry.

### Governance & Human Review Tools (Workstream 2)
- `flag_pattern_for_review`: Manually or automatically routes candidate patterns to teacher inbox in PENDING state.
- `resolve_teacher_review`: Teacher adjudication tool (`accepted`, `rejected`, `needs_context`) with human reviewer identity and approval hash.
- `get_pending_reviews`: Lists candidate patterns awaiting human educator review.
- `get_surfaced_profile`: Returns strictly accepted patterns, preventing unreviewed AI leakage.

---

## 6. Known Limitations & Concurrency Boundaries

- **Concurrent Write Access**: ALLPS uses embedded SQLite (`aiosqlite`). Sequential operations from MCP clients execute safely within transaction boundaries. Highly concurrent multi-process or multi-threaded bulk writers can encounter database-level locking (`sqlite3.OperationalError: database is locked`) unless serialized at the client.
- **Concurrent Submissions with the Same Source Event**: When two overlapping requests submit the same `(source_system, source_event_id)`, SQLite's unique index constraint ensures that only one record is stored. The second call encounters an `IntegrityError`, rolls back its write, and records a failure audit entry. Sequential retries of identical events succeed idempotently.
- **Teacher Review Authority Boundary**: While `ReviewService` screens known automated bot strings (`'agent'`, `'bot'`, `'llm'`) and the agent orchestrator is prohibited from resolving reviews, caller-supplied `reviewer_id` remains an unauthenticated prototype parameter without cryptographic proof or SSO session tokens. A production deployment requires cryptographic teacher authentication.
- **Direct Database Access**: Evidence immutability is enforced at the model and MCP protocol layer. Direct filesystem access to SQLite can still modify records.
- **Client Data Handling**: SQLite stores records locally. How connected open-source MCP harnesses or client agents handle or transmit returned data depends on those client configurations.

---

## 7. Synthetic Data Disclaimer

The learner records in `data/synthetic/seed_data.py` are synthetic Kenyan school examples constructed for testing longitudinal comparability and provenance integrity. They are not real student records from the Kenya Institute of Curriculum Development (KICD), the Tusome Early Grade Reading Activity, or any school system, and they do not imply official curriculum validation.

---

## 8. Runtime Decision Layer & Graceful Degradation (Workstream 3)

Workstream 3 introduces a modular **Runtime Decision Layer** (`allps.runtime`) that decouples model inference from educational orchestration and deterministic analysis.

```
┌────────────────────────────────────────────────────────┐
│                   AgentOrchestrator                    │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                    RuntimeRegistry                     │
│  • Manages prioritized provider configs                │
│  • Coordinates discovery and health probes             │
└──────────────┬────────────────────────────┬────────────┘
               │ (AI Available)             │ (AI Offline / Fallback)
┌──────────────▼────────────────┐ ┌─────────▼────────────────────┐
│     LocalOpenAIClient         │ │  DeterministicAnalysisClient │
│   (LM Studio / Ollama)        │ │  • Zero network dependency   │
│   • Bounded probe timeout     │ │  • Analyzes real records     │
│   • Model discovery (/models) │ │  • 100% cited evidence       │
│   • Zero-learner test probe   │ │  • Contract-compliant brief  │
└───────────────────────────────┘ └──────────────────────────────┘
```

### 8.1. Discovery & Zero-Learner Readiness Probing
- **Dynamic Model Discovery**: Queries `/v1/models` with bounded timeouts (default: 2.0s).
- **Preference Matching**:
  - **Explicit Model Selection**: When a specific model is explicitly requested, requires the exact provider model ID, case-insensitive exact match, or an explicitly configured alias. Automatically stripping namespaces (e.g. `approved-publisher/<model>`) or quantization suffixes is forbidden on this path.
  - **General Discovery Preferences**: Matches configured default models using exact, case-insensitive, normalized basename, or configured alias. Unrestricted substring or containment matching is strictly rejected to prevent hijacking by third-party fine-tunes.
- **Readiness Verification**: Probes model readiness using a minimal prompt (`{"role": "user", "content": "ping"}`) with zero learner information. Models that time out or return HTTP errors during the probe are rejected. (No speculative hardware or VRAM assertions are made; failure is logged as an HTTP/inference timeout).
- **Endpoint Trust**: Probes are restricted to explicitly configured and trusted endpoints. Learner context is never sent to unverified or untrusted endpoints.

### 8.2. Execution Modes
- **`auto`**: Probes LM Studio $\to$ Ollama in priority order. If a verified model is ready, selects `LIVE_AI` wrapped in a `ResilientInferenceClient`. If all AI providers are unavailable, safely falls back to `DETERMINISTIC`. If an AI runtime fails mid-execution, safely falls back to `DETERMINISTIC` with the original error logged in the audit trail.
- **`live`**: Requires a ready, verified AI provider. Refuses silent fallback; raises `RuntimeSelectionError` immediately if unavailable.
- **`deterministic`**: Bypasses network and model discovery entirely; performs genuine rule-based longitudinal synthesis using `AnalysisService` on real learner evidence.
- **`mock`**: Preserves deterministic offline mock fixtures for reproducible testing and CI/CD.

### 8.3. Governance Invariants
1. **No Silent Fallback in Live Mode**: Live mode strictly fails when AI inference cannot be guaranteed.
2. **No Fallback on Governance Violations**: If an AI model produces output rejected by `OutputValidator` (e.g. peer ranking, causal claims, deficit labels), fallback is prohibited. The validation error stands.
3. **Disclosed Runtime Execution**: Terminal output, return payloads, and database audit entries explicitly record `runtime_method` (`live_ai`, `deterministic`, `deterministic_fallback`, or `mock`).

### 8.4. Request-Scoped Provenance & Website Integration Handoff
- **Provenance Isolation**: `GenerationResult` subclasses `str` to carry immutable per-generation metadata (`used_fallback`, `fallback_error`, `runtime_method`). Overlapping or concurrent asynchronous requests on a shared client do not overwrite each other's audit records or return metadata. `AgentOrchestrator.orchestrate_handover` also supports request-scoped client injection via the optional `inference_client` parameter.
- **Teacher Review Authority Boundary**: `ReviewService.resolve_teacher_review` currently screens caller identifiers against known autonomous bot patterns (`is_autonomous_agent`), but does not perform cryptographic human authentication. It is exposed over MCP without session tokens. The website application must implement server-side authenticated teacher sessions (JWT/session cookie) and invoke `ReviewService.resolve_teacher_review` directly from trusted backend routes, preventing autonomous agents from accessing the approval endpoint.
