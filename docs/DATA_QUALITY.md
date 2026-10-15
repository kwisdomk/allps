# ALLPS — Data Quality & Ambiguity Management Specification (`DATA_QUALITY.md`)

> **Document Status**: Canonical Active Specification  
> **Target Audience**: Challenge Evaluators, Data Engineers, Educators  
> **Scope**: Handling Messy School Data, Missingness Semantics, Scale Canonicalization, Contradiction Preservation, and Normalization Invariants  

---

## 1. The Reality of Primary & Secondary School Data

School data in primary and secondary education across Africa (and globally) is fundamentally **messy, incomplete, and heterogeneous**:

1. **Missing Milestones**: A child misses a term due to school fees, illness, family relocation, or floods.
2. **Changing Assessment Scales**: Term 1 test is out of 20; Term 2 is out of 50; Term 3 shifts to CBC 4-level competency rubrics (*"Approaching Expectation"*).
3. **Subjective Disagreements**: Teacher A observes a child as *"vocal and eager"*; Teacher B reports the same child as *"disruptive and unfocused"*.
4. **Typo Variations & Inconsistent Naming**: Upstream spreadsheets contain `"Math"`, `"maths"`, `"Mathematics"`, `"Mid Term"`, `"midterm"`, `"CAT 1"`.
5. **Out-of-Order Backfills**: Paper markbooks are entered into digital systems weeks or months after the actual exams took place.
6. **Network Replays**: Unstable rural school connectivity results in webhooks and batch syncs retrying identical records multiple times.

---

## 2. Core Data Quality Principles in ALLPS

ALLPS was engineered from the ground up to **preserve raw truth and uncertainty**, rather than forcing noisy data into artificial neatness.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        DATA QUALITY PILLARS                            │
├────────────────────────────┬───────────────────────────────────────────┤
│ 1. Zero Is Not Missing     │ Never convert absence or missingness to 0.│
│ 2. Percentages ≠ Equivalence│ Never join different exam forms by math.  │
│ 3. Rubrics Are Not Floats  │ Never average ordinal levels into numbers.│
│ 4. Contradictions Stand    │ Preserve multi-teacher perspectives.      │
│ 5. Time Is Academic        │ Order by observed term, not upload clock. │
│ 6. Replays Are Idempotent  │ De-duplicate via (system, event_id).      │
└────────────────────────────┴───────────────────────────────────────────┘
```

---

## 3. Explicit Missingness Semantics: "Zero Is Not Missing"

The most destructive error in educational analytics is treating an absent exam as a score of `0%`. This manufactures artificial drop curves, distorts longitudinal baselines, and biases future teachers against the learner.

### 3.1. Standard Missing Statuses
ALLPS domain models explicitly recognize non-numeric missing states via [`AssessmentMissingStatus`](file:///q:/ALLPS/src/allps/models/evidence.py#L81):

| Status Enum | Real-World Context | System Handling |
|---|---|---|
| `absent` | Learner was enrolled but not present on assessment day. | Content stores `status: "absent"`. Value remains `None`. Never plotted as zero. |
| `result_unavailable` | Assessment was administered, but script was lost or unrecorded. | Treated as missing outcome; distinct from non-administration. |
| `not_administered` | School/teacher did not conduct the assessment for this class. | Excluded from learner baseline; recorded as institutional event. |
| `not_enrolled` | Learner had not yet joined the school/stream during that term. | Preserved as enrollment boundary; cannot form an absence penalty. |

### 3.2. Preservation of True Zero
If a student sat an exam, submitted their paper, and scored `0 / 50`, ALLPS records `score: 0, max_score: 50`. The analysis engine distinguishes a genuine score of zero from an absence:
- `score == 0`: Valid data point in the longitudinal series.
- `status in AssessmentMissingStatus`: Outcome is `None`; excluded from numerical trend slopes.

---

## 4. Strict Non-Equating & 9-Key Series Comparability

A common mistake in educational systems is converting scores to percentages and treating them as comparable (e.g. 15/20 = 75%, 75/100 = 75%). A 15/20 on an easy quiz does not measure the same difficulty or skill as a 75/100 on an end-term summative examination.

### 4.1. The 9-Key Series Key ([`SeriesKey`](file:///q:/ALLPS/src/allps/services/analysis_service.py#L14-L33))
Assessments are grouped into a longitudinal series **only if all 9 dimensions match identically**:

```python
@dataclass(frozen=True)
class SeriesKey:
    grade: str              # e.g., "Grade 3"
    subject: str            # e.g., "Mathematics"
    measured_skill: str     # e.g., "fractions_and_decimals"
    form: str               # e.g., "CAT 1"
    form_version: str       # e.g., "v1.2"
    language: str           # e.g., "English"
    measure: str            # "marks" | "rubric" | "fluency"
    scale: str              # "max_score:50.0" | "levels:Below|Approaching|Meeting|Exceeding"
    assessment_stage: str   # "opener" | "cat" | "midterm" | "end_term"
```

If any dimension differs:
- The assessments are partitioned into distinct series.
- They are **never plotted on the same trend line**.
- The analysis engine emits [`PatternType.INSUFFICIENT_EVIDENCE`](file:///q:/ALLPS/src/allps/models/pattern.py#L19) if an isolated series contains fewer than 3 terms.

---

## 5. Ordinal Rubric Progression (CBC 4-Level Scales)

In competency-based curricula (e.g. Kenya CBC), learning is evaluated using qualitative rubrics rather than percentages:

```
Level 1: Below Expectation (BE)
Level 2: Approaching Expectation (AE)
Level 3: Meeting Expectation (ME)
Level 4: Exceeding Expectation (EE)
```

### 5.1. The "No Fractional Averages" Invariant
Qualitative descriptors are ordinal ranks, not continuous interval numbers:
- **Forbidden**: Averaging Level 2 (AE) and Level 3 (ME) into a mathematical `"2.5"`. A learner cannot be "2.5 Approaching Expectation."
- **Enforced**: Tracking step-wise ordinal progression across periods:
  $$\text{AE} \rightarrow \text{AE} \rightarrow \text{ME} \implies \text{Progression (Unchanged } \rightarrow \text{ Improving)}$$
- If rubric scales differ across terms (e.g. a 3-level scale vs. a 4-level scale), they are segregated into separate series and never equated.

---

## 6. Subject & Assessment Stage Alias Canonicalization

Dirty school spreadsheets use inconsistent terminology. ALLPS applies **conservative canonicalization** to bridge syntactic differences without corrupting underlying meaning:

### 6.1. Canonical Subject Aliases
```python
SUBJECT_CANONICAL_MAP = {
    "math": "Mathematics",
    "maths": "Mathematics",
    "mathematics": "Mathematics",
    "eng": "English",
    "english": "English",
    "kisw": "Kiswahili",
    "kiswahili": "Kiswahili",
    "sci": "Science",
    "science": "Science",
    "social": "Social Studies",
    "social studies": "Social Studies",
    "cre": "Religious Education",
    "ire": "Religious Education",
}
```

### 6.2. Canonical Assessment Stage Aliases
```python
STAGE_CANONICAL_MAP = {
    "opener": "opener",
    "opening": "opener",
    "beginning_of_term": "opener",
    "cat": "cat",
    "cat1": "cat",
    "cat 1": "cat",
    "cat2": "cat",
    "cat 2": "cat",
    "continuous_assessment": "cat",
    "midterm": "midterm",
    "mid-term": "midterm",
    "mid term": "midterm",
    "end_term": "end_term",
    "end-term": "end_term",
    "end of term": "end_term",
    "terminal": "end_term",
}
```

---

## 7. Conflict Resolution & Preserving Multi-Teacher Subjectivity

Teacher observations frequently conflict. For example:
- **Term 1 (Teacher Achebe)**: *"Student participates actively in class discussions."*
- **Term 2 (Teacher Okafor)**: *"Student is withdrawn and rarely speaks."*

### 7.1. Anti-Pattern: Forced Synthetic Consensus
A naive AI system would attempt to blend these into: *"Student displays moderate participation."* This erases the truth: participation changed, or the classroom environment affected behavior.

### 7.2. The ALLPS Solution: Multi-Perspective Attribution
1. **Preserve Both Records**: Both observations remain immutable with distinct `source_reference` identities (`"Teacher Achebe"`, `"Teacher Okafor"`).
2. **Surface as Divergence**: The analysis engine surfaces a candidate [`PatternType.DIVERGENCE`](file:///q:/ALLPS/src/allps/models/pattern.py#L17).
3. **Present to Teacher for Adjudication**: The candidate handover presents both quotes side-by-side:
   > *"Teacher Achebe noted high verbal engagement in Term 1, while Teacher Okafor observed withdrawal in Term 2. The receiving teacher may wish to evaluate whether group size or subject matter influences participation."*

---

## 8. Sortable Academic Time vs. Physical Ingestion Clock

In real schools, teachers frequently backfill grades weeks or months late.

ALLPS decouples physical ingestion from academic history:
- `recorded_at`: Timestamp when record was saved into SQLite (for audit integrity).
- `observed_at`: Exact timestamp when the observation or exam occurred.
- `academic_year` & `term`: Discrete integer values (e.g. `2026`, `Term 2`).

### Deterministic Timeline Ordering
All longitudinal queries sort strictly by academic time:
```sql
SELECT * FROM evidence 
WHERE learner_id = ? 
ORDER BY academic_year ASC, term ASC, observed_at ASC;
```
Even if Term 1 marks are backfilled during Term 3, they automatically slide into their correct chronological position in the longitudinal timeline.

---

## 9. Idempotency & Network Conflict Handling

Network interruptions in rural schools cause sync scripts to retry transactions.

### Unique Constraint on Upstream Events
```sql
CREATE UNIQUE INDEX idx_evidence_source_event 
    ON evidence(source_system, source_event_id) 
    WHERE source_event_id IS NOT NULL;
```
- **Identical Replay**: If an upstream sync resends `("kemis_sis", "ev-1082")` with identical fields, ALLPS recognizes the replay, returns the existing record, and logs an idempotent retry in `audit_log`.
- **Conflicting Replay**: If the same event ID arrives with altered scores, ALLPS rejects the conflicting submission, rolls back the write transaction, and raises an `IntegrityError` to prevent silent record corruption.
