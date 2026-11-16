# Phase 2: Safety, Teacher Review Gate & Governance — Implementation Plan

> **ALLPS — Workstream 2 Implementation Plan**  
> **Status**: Ready for Execution  
> **Objective**: Turn *"Human decides"* into an unbypassable architectural filter.

---

## 1. Executive Summary & Goals

Phase 1 established the immutable evidence ledger, deterministic 9-key comparability engine, and the core MCP server.

Phase 2 enforces the **Dual-View Approval Boundary** and **Pedagogical Safety Policies**:
1. **Unbypassable Review Gate**: Candidate patterns surfaced by analysis remain strictly invisible in published learner profiles until a sovereign human teacher reviews and accepts them.
2. **Human Authority Guardrail**: Review resolutions require an authenticated human `reviewer_id`. Autonomous AI agents and automated background tasks are hard-blocked from self-approving.
3. **Cryptographic Provenance**: Approved pattern summaries are snapshotted with an immutable $SHA\text{-}256$ content hash at the moment of approval to prevent silent drift or retroactive tampering.
4. **Prohibited Diagnostic Label Screening**: Active screening in `allps.policies` rejecting deficit and clinical terminology (`"slow learner"`, `"lazy"`, `"ADHD"`, `"uncooperative"`) at ingestion and synthesis boundaries.
5. **Full MCP Governance Tools**: Expose `flag_pattern_for_review`, `resolve_teacher_review`, `get_pending_reviews`, and `get_surfaced_profile` over the Model Context Protocol.

---

## 2. Architecture & Data Flow

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Analysis Service                                │
│                  [analyse_longitudinal_pattern]                        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Generates candidate patterns
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│               Atomic Ingestion & De-duplication                        │
│   • Persists Pattern to 'patterns' table                               │
│   • Generates ReviewItem (status: PENDING)                             │
│   • De-duplicates identical candidate streams (no inbox spam)         │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
                       ┌─────────────────────────┐
                       │  Teacher Review Inbox   │
                       │ (PENDING ReviewItems)   │
                       └────────────┬────────────┘
                                    │
                  Human Educator Adjudication Tool
                  [resolve_teacher_review(review_id, status, reviewer_id)]
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          │                         │                         │
          ▼                         ▼                         ▼
      ACCEPTED                  REJECTED               NEEDS_CONTEXT
   • Human ID recorded       • Human ID recorded     • Human ID recorded
   • SHA-256 hash snapshot   • Archived with notes   • Returned for further
   • Available in Profile    • NEVER in Profile        classroom inquiry
          │
          ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       get_surfaced_profile                             │
│     Strictly filters: Pattern MUST have ReviewItem.status == ACCEPTED   │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Work Breakdown & Implementation Steps

### Step 1: Prohibited Diagnostic Label Screening (`allps.policies`)
- [ ] Create `allps.policies.label_policy`:
  - Curated list of prohibited stigmatizing deficit and clinical diagnostic terms:
    - Deficit: `"slow learner"`, `"lazy"`, `"dumb"`, `"stupid"`, `"uncooperative"`, `"defiant"`, `"hopeless"`
    - Unauthorized diagnostic labels: `"adhd"`, `"autistic"`, `"add"`, `"bipolar"`, `"dyslexic"`, `"conduct disorder"`
  - `check_for_prohibited_labels(text: str) -> list[str]` (case-insensitive, whole-word matching via regex boundaries `\b`).
- [ ] Wire `check_for_prohibited_labels` into `EvidenceService.record_evidence` and `Evidence` validation:
  - Screen free-text fields in `content` (`note`, `reflection`, `reason`, `comment`).
  - Reject submissions containing prohibited labels with clear `ValueError`.

### Step 2: Domain Model & Schema Migration (`allps.models.review`, `allps.storage.sqlite_store`)
- [ ] Update `ReviewItem` in `src/allps/models/review.py`:
  - Add `reviewer_id: str | None = None`
  - Add `approved_content_hash: str | None = None`
  - Validation: when `status == ReviewStatus.ACCEPTED`, `reviewer_id` and `approved_content_hash` must be non-empty strings.
- [ ] Update SQLite Schema & Migrations in `src/allps/storage/sqlite_store.py`:
  - Add columns `reviewer_id TEXT` and `approved_content_hash TEXT` to `review_items`.
  - Non-destructive migration on `initialize()`: `ALTER TABLE review_items ADD COLUMN ...` if missing.
  - Implement storage methods:
    - `get_pattern(pattern_id) -> Pattern | None`
    - `get_patterns_for_learner(learner_id) -> list[Pattern]`
    - `get_review_item(review_id) -> ReviewItem | None`
    - `get_review_items_for_pattern(pattern_id) -> list[ReviewItem]`
    - `get_pending_reviews(assigned_to: str | None = None) -> list[ReviewItem]`
    - `update_review_item(item: ReviewItem, conn=None) -> ReviewItem`
    - `get_surfaced_profile(learner_id: str) -> list[dict]` (JOIN `patterns` and `review_items` where `status = 'accepted'`).

### Step 3: Analysis Pipeline Integration & Review Item Auto-Generation
- [ ] Connect `AnalysisService` with `SQLiteStore`:
  - When candidate patterns are detected in `analyse_longitudinal_pattern`:
    - Check if pattern with identical `(learner_id, pattern_type, summary)` already exists in `patterns` / `review_items`.
    - If not, persist `Pattern` and insert `ReviewItem` in `PENDING` state within a single transaction.
    - Attach `review_id` and `review_status: "pending"` to returned pattern payloads.

### Step 4: Governance Service & Review Resolution Guardrails (`allps.services.review_service`)
- [ ] Create `ReviewService` in `src/allps/services/review_service.py`:
  - `resolve_review(review_id: str, status: ReviewStatus, reviewer_id: str, teacher_notes: str | None = None) -> ReviewItem`:
    - Enforce non-empty human `reviewer_id`.
    - Hard check: reject agent/bot IDs (e.g., prefix `agent:`, `bot:`, `llm:`, `system:` or `"autonomous_agent"`).
    - If `status == ACCEPTED`:
      - Fetch associated `Pattern`.
      - Compute SHA-256 hash of `pattern.summary`: `hashlib.sha256(summary.strip().encode("utf-8")).hexdigest()`.
      - Record `approved_content_hash`.
      - Set `resolved_at = datetime.now(timezone.utc)`.
    - Atomic commit with audit log entry (`tool_name="resolve_teacher_review"`).

### Step 5: MCP Server Tools
- [ ] In `src/allps/mcp/server.py`, expose tools:
  1. `flag_pattern_for_review(pattern_id: str, assigned_to: str | None = None) -> dict`:
     - Creates or re-assigns a `ReviewItem`.
  2. `resolve_teacher_review(review_id: str, status: str, reviewer_id: str, teacher_notes: str | None = None) -> dict`:
     - Resolves review with human authority validation and approved content hashing.
  3. `get_pending_reviews(assigned_to: str | None = None) -> list[dict]`:
     - Lists all actionable review items waiting for teacher review.
  4. `get_surfaced_profile(learner_id: str) -> dict`:
     - Returns learner profile strictly filtered to human-accepted patterns.

---

## 4. Potential Errors, Edge Cases & Countermeasures

| Potential Risk / Failure Mode | Root Cause | Preventive Countermeasure |
|---|---|---|
| **Autonomous Self-Approval Leak** | LLM agent calls `resolve_teacher_review` with `status="accepted"` | Check `reviewer_id` against bot/agent prefixes; require verifiable teacher role/identity format; test agent rejection explicitly. |
| **Review Inbox Duplication** | Repeated analysis runs generate identical candidate patterns | Implement pattern signature hashing / existence query before inserting new `ReviewItem`. |
| **Unapproved Pattern Leakage** | Profile query inadvertently falls back to raw `patterns` table | Implement dual-view architecture: `get_surfaced_profile` uses SQL `INNER JOIN review_items ON patterns.pattern_id = review_items.pattern_id WHERE review_items.status = 'accepted'`. |
| **Approved Text Tampering (Drift)** | Pattern summary altered in DB after approval | Verify SHA-256 `approved_content_hash` matches current pattern summary during `get_surfaced_profile`. Flag mismatch as corrupted. |
| **SQLite Schema Lock on Migration** | Adding columns to existing active DB | Use non-destructive `PRAGMA table_info` inspection before issuing `ALTER TABLE`. Wrap in transaction. |
| **Subtle Label Variations** | Teacher observations with punctuation/capitalization (`"Slow-learner"`, `"A.D.H.D."`) | Regex normalization in label screener stripping punctuation and handling hyphenated forms. |
| **Empty or Invalid Resolution State** | Teacher resolves with status not in Enum | Validate status against `ReviewStatus` enum (`accepted`, `rejected`, `needs_context`). Reject `pending` as resolution. |

---

## 5. Verification & Testing Matrix

- [ ] **Unit Tests (`test_policies.py`)**:
  - Detection of stigmatizing labels (`"slow learner"`, `"lazy"`).
  - Detection of clinical diagnostic labels (`"ADHD"`, `"autistic"`).
  - Tolerance of legitimate words (e.g. `"fast and slow rhythm"`, `"skills learned"`).
- [ ] **Storage & Migration Tests (`test_storage.py`)**:
  - Non-destructive migration adding `reviewer_id` and `approved_content_hash`.
  - Adding, retrieving, and updating `ReviewItem`.
  - Strict profile query filtering unaccepted patterns.
- [ ] **Review Service Tests (`test_review_service.py`)**:
  - Successful resolution with SHA-256 hash generation.
  - Rejection of autonomous agent approval attempts.
  - Rejection without valid `reviewer_id`.
- [ ] **MCP Protocol Subprocess Tests (`test_mcp_tools.py`)**:
  - Complete stdio roundtrip: `analyse_longitudinal_pattern` $\rightarrow$ `get_pending_reviews` $\rightarrow$ `resolve_teacher_review` $\rightarrow$ `get_surfaced_profile`.
  - Verification that rejected and pending patterns NEVER appear in `get_surfaced_profile`.
