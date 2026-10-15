# ALLPS — Data & Tool Contracts Specification

> **Document Status**: Canonical Active Specification  
> **Target Audience**: Challenge Evaluators, Systems Engineers, Educators  
> **Scope**: Ingestion Schemas, Strict Comparability, Missingness Semantics, Idempotency, and Teacher Review Governance

---

## 1. System Mission & Boundary

ALLPS (**Agentic Longitudinal Learner Profile System**) operates under the foundational commitment:  
**"Record evidence without reducing learners to labels."**

Educational systems often condense learners into static diagnoses (*"slow learner"*, *"at-risk"*), erasing developmental progress. ALLPS collects dated, attributed observations across terms and teachers while preserving strict human authority: **AI recommends candidate insights; sovereign human educators decide what enters the permanent profile.**

---

## 2. Core Domain Models & Schemas

### 2.1. Evidence Record ([`Evidence`](file:///q:/ALLPS/src/allps/models/evidence.py#L153)) — [IMPLEMENTED & VERIFIED]
All observations are immutable once recorded.

| Field | Type | Constraint | Description |
|---|---|---|---|
| `evidence_id` | `str` | UUID string | Unique identifier for this evidence record. |
| `learner_id` | `str` | Min length 1 | Stable learner identity boundary. |
| `evidence_type` | `EvidenceType` | Enum: `assessment`, `attendance`, `observation`, `learner_reflection`, `project` | Modality of the observation. |
| `source_system` | `str` | Min length 1 | Upstream origin (e.g. `"school_sis"`, `"moodle"`, `"synthetic_dataset"`). |
| `ingestion_method`| `IngestionMethod`| Enum: `api`, `webhook`, `scheduled_sync`, `csv_import`, `manual_observation`, `learner_pulse`, `synthetic` | Channel through which evidence arrived. |
| `source_event_id` | `str \| None` | Optional string | Upstream event ID for idempotent ingestion and conflict detection. |
| `source_type` | `str` | Min length 1 | Author classification (`"teacher"`, `"system"`, `"learner"`). |
| `source_reference`| `str` | Min length 1 | Specific author or system reference (e.g. `"Mr. Banda"`, `"attendance-v1"`). |
| `academic_year` | `int` | $2000 \le year \le 2100$ | Academic year for sortable chronological ordering. |
| `term` | `int` | $1 \le term \le 4$ | Academic term number. |
| `subject` | `str \| None` | Optional string | Academic subject (e.g. `"Mathematics"`, `"Science"`, `"English"`). |
| `content` | `MappingProxyType` | Frozen dictionary | Immutable, validated payload per evidence type. |
| `observed_at` | `datetime` | Timezone-aware UTC | When the observation occurred. |
| `recorded_at` | `datetime` | Timezone-aware UTC | When ALLPS recorded the entry. |

---

### 2.2. Assessment Content Payloads — [IMPLEMENTED & VERIFIED]

Assessments support four mutually exclusive outcome types. Any non-finite numbers (`inf`, `-inf`, `nan`) and boolean values (`True`, `False`) disguised in numeric fields are strictly rejected:

#### 1. Numeric Marks
```json
{
  "grade": "Grade 3",
  "score": 82,
  "max_score": 100,
  "form": "Term Test",
  "form_version": "v1.0",
  "language": "English",
  "measured_skill": "multiplication_and_division",
  "comparison_authorized": true,
  "assessment_stage": "end_term",
  "assessment_name": "Term 1 Test"
}
```
* **Validation**: `score` and `max_score` must be finite numbers and not booleans; $max\_score > 0$ and $0 \le score \le max\_score$.

#### 2. Rubric Descriptors
```json
{
  "grade": "Grade 3",
  "rubric": "Reading Competency",
  "rubric_version": "v1.0",
  "scale": [
    "Below Expectation",
    "Approaching Expectation",
    "Meeting Expectation",
    "Exceeding Expectation"
  ],
  "level": "Meeting Expectation",
  "form": "Oral Assessment",
  "form_version": "v1.0",
  "language": "English",
  "measured_skill": "oral_reading_fluency",
  "comparison_authorized": true,
  "assessment_stage": "midterm"
}
```
* **Validation**: `rubric` and `rubric_version` are required non-empty strings. `scale` must either be a registered identifier (e.g. `"cbc_4_level_v1"`, `"kenya_cbc_v1"`) or an explicit non-empty list of level descriptors, or an integer `max_level`. The recorded `level` must exist within the resolved scale. Rubrics without a valid, verifiable scale definition are rejected.

#### 3. Fluency Assessments
```json
{
  "grade": "Grade 2",
  "value": 45.0,
  "unit": "cwpm",
  "form": "Passage Form 1",
  "form_version": "v1.0",
  "language": "English",
  "measured_skill": "oral_reading_fluency",
  "comparison_authorized": true,
  "assessment_stage": "opener"
}
```
* **Validation**: `value` must be a non-negative finite number (not boolean); `unit` must be a non-empty string (e.g., `"cwpm"` for correct words per minute).

#### 4. Explicit Missing Outcomes
```json
{
  "grade": "Grade 3",
  "status": "result_unavailable",
  "reason": "Assessment paper water-damaged during transit",
  "max_score": 50
}
```
* **Validation**: `status` must be a recognized missing status enum (`"absent"`, `"result_unavailable"`, `"unavailable"`, `"not_submitted"`, `"assessment_not_administered"`, `"not_administered"`, `"not_assessed"`, `"not_enrolled"`); `reason` must be a non-empty string.
* **Contradiction Rules**: Contradictory payloads (e.g. non-null `score` or `level` with missing `status`) are strictly rejected. However, null outcome fields (`"score": null`, `"level": null`, `"value": null`) are treated as absent, not contradictions.

---

### 2.3. Attendance, Observations & Reflections — [IMPLEMENTED & VERIFIED]

* **Attendance**: Supports daily records (`{"status": "present" | "absent" | "late"}`) or term aggregations (`{"days_present": 48, "days_total": 50}`). Integer totals are enforced (booleans rejected).
* **Teacher Observations**: Contextual qualitative notes (`{"note": "Learner 001 participates actively..."}`).
* **Learner Reflections**: Self-assessments (`{"reflection": "I find the new topics harder..."}`).

---

## 3. Strict Longitudinal Comparability Rules — [IMPLEMENTED & VERIFIED]

Assessments are **only** longitudinally comparable when they match across all 9 dimensions of the explicit `SeriesKey`:

$$\text{SeriesKey} = (\text{grade}, \text{subject}, \text{measured\_skill}, \text{form}, \text{form\_version}, \text{language}, \text{measure}, \text{scale}, \text{assessment\_stage})$$

1. **Explicit Comparison Authorization**: The record must declare `comparison_authorized: True` (or aliases `comparable: True`, `is_comparable: True`). Conflicting aliases (`comparison_authorized: False` alongside `comparable: True`) are rejected; explicit `False` can never be overridden by a `True` alias.
2. **No Invented Defaults**: Records omitting `form`, `form_version`, `grade`, `language`, or `measured_skill` are excluded from comparisons; the system never invents fallback defaults.
3. **No Percentage Equating**: Converting marks on different tests to percentages (e.g. $8/10 \rightarrow 80\%$ vs $80/100 \rightarrow 80\%$) does **not** make assessments comparable.
4. **Assessment Stage Preservation**: Timing milestones (`opener`, `cat`, `midterm`, `end_term`) are preserved and partitioned in the `SeriesKey`. Results from different assessment stages are never combined into a single trajectory.
5. **Ordinal Rubric Non-Averaging**: Rubric ratings are qualitative ordinal descriptors. Rubric levels are **never** mathematically averaged into fractional numbers (`avg_rank = sum(ranks)/len(ranks)` is strictly prohibited). If multiple rubric ratings exist within the same academic period with identical ranks, that rank is used; if ratings conflict, the period rank is left indeterminate and noted in transparent limitations.
6. **Complete Rubric Scale Uniformity**: Both registered identifiers (`"cbc_4_level_v1"`) and explicit level lists resolve to a canonical level sequence. Assessments with differing rubric scales (e.g., 3-level vs 4-level) partition into separate series and never produce a shared trend.
7. **Across-Term Trend Threshold**: Evaluating an across-term trend requires at least **three distinct academic periods** on the same comparable series.

---

## 4. Missingness & Non-Penalty Semantics — [IMPLEMENTED & VERIFIED]

1. **Missing Data is NOT Negative Evidence**: Missing self-reflections, absent survey responses, or unadministered assessments must never be penalized or factored as negative developmental evidence.
2. **Disambiguated Missing Statuses**:
   - `absent`: Student was enrolled and assessment was given, but student was not in attendance.
   - `result_unavailable`: Assessment was administered, but results could not be scored or retrieved.
   - `assessment_not_administered`: The school/teacher did not administer the test.
   - `not_enrolled`: Student was not enrolled during the assessment period.
3. **Zero Remains Zero**: True zero marks ($0/100$) are preserved as legitimate scores and never converted to null; missing outcomes remain null and are never converted to zero.

---

## 5. Idempotency & Conflict Replay Rules — [IMPLEMENTED & VERIFIED]

1. **Unique Key Constraint**: Ingestion enforces uniqueness on `(source_system, source_event_id)`.
2. **Idempotent Replay**: Resubmitting an identical observation with the same event ID returns the existing evidence record without creating duplicates or throwing errors.
3. **Conflict Rejection**: Resubmitting an existing event ID with differing payload attributes (e.g., modified score, different learner, or altered timestamps) triggers an explicit `IntegrityError` / `ValueError` conflict and audits the rejection.

---

## 6. Concurrent-Ingestion Limitations — [VERIFIED BEHAVIOR]

* **SQLite Storage Engine**: ALLPS uses a single embedded SQLite database (`aiosqlite`). SQLite enforces database-level write locks.
* **Concurrency Boundary**: Sequential write transactions from standard single-process MCP clients execute cleanly with transaction isolation and rollbacks. Highly concurrent write operations across multiple processes or multi-threaded bulk writers will encounter database locks (`sqlite3.OperationalError: database is locked`) unless serialized at the client or wrapped in application-level retry backoff. Concurrent multi-writer ingestion is outside the scope of the embedded SQLite storage layer.

---

## 7. Teacher Review Governance & Approval Boundary — [IMPLEMENTED & VERIFIED]

> [!NOTE]
> The governance model in this section is **fully implemented and verified** across Workstream 2 (Safety & Teacher Review Gate) and Workstream 3 (Bounded Agent Orchestration). `ReviewItem` exists in [`src/allps/models/review.py`](file:///q:/ALLPS/src/allps/models/review.py), with automatic item creation, profile gating, reviewer authentication, non-agent approval enforcement, and SHA-256 snapshot recording.

```
[Candidate Pattern Detected]
             │
             ▼
    [ReviewItem Created] ──► status: PENDING  (Verified in Workstream 2)
             │
             ├──► Teacher Inbox: Visible for human adjudication
             │
             └──► Published Profile: INVISIBLE (Gated)
                         │
                         ▼
             Teacher Adjudication (Human Sovereign)
             ├── ACCEPTED ──────► Surfaces in Published Learner Profile (SHA-256 Snapshot)
             ├── REJECTED ──────► Archived; never surfaces
             └── NEEDS_CONTEXT ─► Returned for further classroom inquiry
```

### 7.1. Review Lifecycle Model ([`ReviewItem`](file:///q:/ALLPS/src/allps/models/review.py))
* **Implemented & Verified**: `review_id`, `pattern_id`, `assigned_to`, `status` (`pending`, `accepted`, `rejected`, `needs_context`), `teacher_notes`, `created_at`, `resolved_at`.
* **Verified Governance Features**:
  - `reviewer_id`: Explicit authenticated teacher identity (e.g. `"teacher:mrs_ngcobo"`).
  - `approved_content_hash`: Cryptographic hash ($SHA\text{-}256$) of the exact approved pattern summary snapshot at time of approval.
  - Automatic creation of review items on candidate pattern detection.
  - Profile gating: published profiles expose only `status == ACCEPTED` patterns.

### 7.2. Approval Authority Guardrail — [IMPLEMENTED & VERIFIED]
* **Prohibition of Autonomous Self-Approval**: Autonomous agents, background jobs, or system workers are strictly forbidden from setting `status = ACCEPTED`. Only authenticated human reviewers may approve findings (`ReviewService.is_autonomous_agent()` raises `PermissionError`).
* **Gated Agent Orchestration — [IMPLEMENTED & VERIFIED]**: Handover briefs generated by LLM agents are treated as candidate drafts requiring teacher sign-off before entering the longitudinal record.
