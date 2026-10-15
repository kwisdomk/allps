# ALLPS School Evidence Contract Specification (v1.0)

> **Document Status**: Active Specification  
> **Target Audience**: Challenge Evaluators, Systems Engineers, Educators  
> **Scope**: Primary & Secondary School Evidence Ingestion, Storage, and Longitudinal Comparability

---

## 1. Specification Overview

ALLPS (Agentic Longitudinal Learner Profile System) collects atomic, dated, attributed observations of student learning without assigning permanent diagnostic labels. This document defines the versioned **School Evidence Contract (v1.0)** governing how assessments, observations, attendance records, reflections, and projects are structured, validated, stored, and compared over time.

---

## 2. Core Evidence Schema

Every evidence record submitted to ALLPS adheres to the domain model [`Evidence`](file:///q:/ALLPS/src/allps/models/evidence.py#L116).

### 2.1. Top-Level Metadata Attributes

| Field | Type | Constraint | Description |
|---|---|---|---|
| `evidence_id` | `str` | UUID string | Globally unique identifier for this record. |
| `learner_id` | `str` | Non-empty string | Stable learner identity boundary. |
| `evidence_type` | `EvidenceType` | Enum (`assessment`, `attendance`, `observation`, `learner_reflection`, `project`) | High-level modality of the observation. |
| `source_system` | `str` | Non-empty string | Originating system (e.g. `"school_sis"`, `"moodle"`, `"paper_csv"`, `"allps"`). |
| `ingestion_method` | `IngestionMethod` | Enum (`api`, `webhook`, `scheduled_sync`, `csv_import`, `manual_observation`, `learner_pulse`, `synthetic`) | Ingestion channel. |
| `source_event_id` | `str \| None` | Optional string | Upstream event identifier used for idempotency and conflict detection. |
| `source_type` | `str` | Non-empty string | Category of author (`"teacher"`, `"system"`, `"learner"`). |
| `source_reference` | `str` | Non-empty string | Specific author or device identity (e.g. `"Mr. Banda"`, `"tablet-unit-04"`). |
| `academic_year` | `int` | $2000 \le year \le 2100$ | Academic year. |
| `term` | `int` | $1 \le term \le 4$ | Academic term number. |
| `subject` | `str \| None` | Optional string | Academic subject (e.g. `"Mathematics"`, `"English"`, `"Kiswahili"`). |
| `content` | `dict[str, Any]` | Frozen mapping | Flexible, validated payload according to `evidence_type`. |
| `observed_at` | `datetime` | Timezone-aware UTC | Exact timestamp when observation occurred in class. |
| `recorded_at` | `datetime` | Timezone-aware UTC | Timestamp when observation was ingested into ALLPS. |

---

## 3. Versioned Assessment Contract & Preview Field Reconciliation

Assessments represent structured evaluative observations. To ensure measurement integrity across terms and years, assessment payloads must supply contextual metadata and adhere to one of three distinct outcome schemas.

### 3.1. Field Reconciliation Mapping: Preview vs. Canonical Contract

The table below reconciles preview dataset fields with canonical contract fields, defining disambiguation rules and separation boundaries:

| Preview Field | Canonical Contract Field | Canonical Type / Enum | Reconciliation & Disambiguation Rules |
|---|---|---|---|
| `stage` | `assessment_stage` **OR** `school_level` | `AssessmentStage` / `SchoolLevel` | **Disambiguated into two orthogonal dimensions**: If `stage` in (`"opener"`, `"midterm"`, `"end_term"`), it maps to `assessment_stage`. If `stage` in (`"pre_primary"`, `"lower_primary"`, `"upper_primary"`, `"early_years"`, `"middle_school"`), it maps to `school_level`. |
| `assessment_stage` | `assessment_stage` | `AssessmentStage` (`opener`, `midterm`, `end_term`) | Timing milestone within an academic term. Kept strictly separate from `school_level`. |
| `school_level` | `school_level` | `SchoolLevel` (`pre_primary`, `lower_primary`, `upper_primary`, `early_years`, `middle_school`) | Institutional educational band. Kept strictly separate from `assessment_stage`. |
| `sampled_content` | `measured_skill` | `str` (non-empty) | Specific competency, sub-strand, or skill domain (e.g. `"letter_sound_fluency"`, `"single_digit_addition"`). `sampled_content` and `skill` alias directly into `measured_skill`. |
| `version` | `form_version` / `rubric_version` | `str` (non-empty) | Test instrument version (e.g. `"v1.0"`). Disambiguated: maps to `form_version` for marks, or `rubric_version` for rubrics. |
| `form` | `form` | `str` (non-empty) | Specific test form identity (e.g. `"Form A"`, `"CAT 1"`). **No invented "standard" fallback**. |
| `language` | `language` | `str` (non-empty) | Medium of administration (e.g. `"English"`, `"Kiswahili"`). **No invented "standard" fallback**. |
| `comparable` / `is_comparable` | `comparison_authorized` | `bool` | Explicit authorization barrier for longitudinal comparison (`comparison_authorized: True`). |
| `rubric_level` / `ordinal_level` | `level` | `str \| int` | Ordinal tier on a defined versioned scale. |
| `scale` / `rubric_scale` | `scale` | `list[str] \| str` | Explicit versioned scale (e.g. `["Below Expectation", "Approaching Expectation", "Meeting Expectation", "Exceeding Expectation"]` or registered identifier `"cbc_4_level_v1"`). |

### 3.2. Orthogonal Separation: Assessment Stage vs. School Level

* **Assessment Stage (`assessment_stage`)**:
  Represents the chronological timing milestone of an assessment event within a specific academic term:
  * `"opener"`: Baseline diagnostic assessment administered at the beginning of the term.
  * `"midterm"`: Formative continuous assessment test (CAT) administered mid-term.
  * `"end_term"`: Summative assessment administered at term conclusion.
* **School Level (`school_level`)**:
  Represents the institutional educational tier:
  * `"pre_primary"`: Pre-Primary 1 and 2 (PP1, PP2).
  * `"lower_primary"` / `"early_years"`: Grades 1, 2, and 3.
  * `"upper_primary"` / `"middle_school"`: Grades 4, 5, and 6.

An assessment at the `"end_term"` stage for a learner in the `"lower_primary"` band is completely valid. Conflating these two concepts or overriding one with the other is prohibited.

---

## 4. Three Distinct Assessment Outcomes

ALLPS strictly distinguishes between numerical marks, qualitative rubric tiers, and missing outcomes:

### Outcome 1: Recorded Marks
Captures numerical scores from standardized or classroom tests:
* `score` (`int | float`): Non-boolean, finite number ($0 \le score \le max\_score$). Non-finite values (`inf`, `-inf`, `nan`) are rejected.
* `max_score` (`int | float`): Non-boolean, finite number ($max\_score > 0$).
* **True Zero Preservation**: A score of $0$ ($score = 0.0$) is a valid recorded measurement (e.g., zero letters recognized). It must never be converted to `None`, omitted, or treated as missing.
* **Contradictory Rejection**: Records with numeric marks must NOT contain missing statuses or rubric levels.

### Outcome 2: Recorded Rubric
Captures qualitative competency-based evaluations without converting rubrics to numbers or percentages:
* `rubric` or `rubric_name` (`str`): Non-empty identifier of the rubric (e.g., `"CBC Early Grade Reading Rubric"`).
* `rubric_version` or `version` (`str`): Non-empty version tag (e.g., `"v1.0"`).
* `scale`: A defined, versioned scale (e.g., `["Below Expectation", "Approaching Expectation", "Meeting Expectation", "Exceeding Expectation"]`, registered scale `"cbc_4_level_v1"`, or positive `max_level`).
* `level` (`int | str`): Valid ordinal level belonging to the defined scale. Any level outside the scale is rejected.
* **Prohibition**: Rubrics must **never** be converted into percentages or treated as interchangeable with numerical test scores.

### Outcome 3: Missing Outcome
Represents unobserved or missing evaluations, preserving administrative and pedagogical distinctions:
* `status` (`str`): Must be one of five mutually exclusive states:
  * `"result_unavailable"` (alias `"unavailable"`): **The assessment was administered or scheduled, but the result/script is unavailable** (e.g., test paper lost in transit, corrupt digital submission, scoring pending, unreadable script).
  * `"assessment_not_administered"` (aliases `"not_administered"`, `"not_assessed"`): **The assessment event itself was never administered to the learner** (e.g., school closure, teacher strike, cancelled exam session, module omitted, learner waived).
  * `"absent"`: Learner was enrolled and expected, but absent from school on test day.
  * `"not_submitted"`: Learner attended the test session but failed to submit work.
  * `"not_enrolled"`: Learner was not enrolled at the school during the assessment period.
* `reason` (`str`): Non-empty explanation of missingness (e.g., `"Exam script lost in courier transit"`, `"School closed due to flood"`).
* `score`: Must be `None` (null result).
* **Null Invariance**: Missing results must stay `None`. They must never be imputed as zero ($0$) or averaged into performance metrics.

---

## 5. Longitudinal Comparison & Equating Rules

The analysis engine ([`AnalysisService`](file:///q:/ALLPS/src/allps/services/analysis_service.py)) enforces strict comparability guardrails:

1. **Explicit Compatibility Barrier (7-Fold Check)**:
   Longitudinal comparison across terms is permitted **only** between records matching across:
   * Identical `grade`
   * Identical `subject`
   * Identical `measured_skill`
   * Identical `form` (instrument identity; no invented `"standard"` fallback!)
   * Identical `form_version`
   * Identical `language` (no invented `"standard"` fallback!)
   * Explicit comparison authorization (`comparison_authorized: True`)
   * Identical `scoring scale` (exact same $max\_score$ for marks, or exact same rubric scale)
   Records missing comparison metadata or lacking comparison authorization are excluded from series groups and noted in transparent limitations.

2. **Trajectory Distinction for Marks**:
   Across $\ge 3$ distinct academic periods, marks trajectories are strictly distinguished:
   * **Unchanged**: All period scores are equal ($s_1 == s_2 == s_3$). Surfaced as `Unchanged across-term performance` (no phantom gain/drop reported).
   * **Improving**: Strictly increasing ($s_1 < s_2 < s_3$). Surfaced as `Improving across-term trend`.
   * **Declining**: Strictly decreasing ($s_1 > s_2 > s_3$). Surfaced as `Declining across-term trend`.
   * **Fluctuating / Variable**: Non-monotonic scores. Surfaced as `Performance ... remains variable ... without monotonic trajectory`.

3. **Rubric Progression Trajectory (No Blind Progression)**:
   Do NOT announce rubric progression merely because three periods exist. Rubrics are evaluated by ranking levels against the versioned scale ($r_1, r_2, r_3$):
   * **Advancing**: Strictly increasing ordinal ranks ($r_1 < r_2 < r_3$). Surfaced as `Advancing rubric progression`.
   * **Declining**: Strictly decreasing ordinal ranks ($r_1 > r_2 > r_3$). Surfaced as `Declining rubric trajectory`.
   * **Unchanged**: Identical ordinal ranks ($r_1 == r_2 == r_3$). Surfaced as `Unchanged rubric performance`.
   * **Fluctuating / Variable**: Non-monotonic ranks. Surfaced as `Performance ... remains variable ... without monotonic trajectory`.

4. **Three Distinct Academic Periods**:
   An across-term trend requires observations across at least **three distinct academic periods** (e.g. Term 1, Term 2, Term 3). Multiple tests within the same term do not establish an across-term trend.

5. **Non-Equivalence of Raw Percentages**:
   Expressing scores as percentages ($score / max\_score \times 100$) does **not** equate test forms. A score of $8/10$ (80%), $15/20$ (75%), and $60/100$ (60%) represent distinct scoring scales and instruments; combining them into a single trend or calculating cross-instrument point gains is prohibited.

6. **Cross-Grade Score Trend Prohibition**:
   Assessments administered across different grade levels represent different curriculum expectations and must not be chained into a single numeric score trend.
