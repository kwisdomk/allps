# ALLPS — Evaluation Framework & Verification Checklist

> **Purpose**: Evaluation scorecard for ALLPS across challenge dimensions.

---

## 1. Challenge Evaluation Rubric Alignment

| Criterion | Evaluation Requirement | Phase 1 Implementation Status |
|---|---|---|
| **Mission Alignment** | Record evidence without reducing learners to labels; preserve learning continuity across terms/years/teachers. | **Implemented & Verified**: Stores and retrieves dated learner evidence with source information and strict comparability constraints. Deficit and clinical diagnostic label screening enforced in `allps.policies.label_policy`. |
| **System Architecture** | Modular, testable, and standards-compliant MCP integration. | **Implemented & Verified**: MCP server exposes validated tools over standard stdio transport; clean separation between models, storage, services, analysis engine, agent layer, and MCP server. |
| **Data Integrity & Provenance** | Evidence integrity, sortable academic time, upstream system origin, and explicit source attribution. | **Implemented & Verified**: Evidence models are frozen, and the MCP server exposes no editing or deletion tools. Tracks `source_system`, `ingestion_method`, `source_type`, `source_reference`, `academic_year` (int), `term` (int), and UTC timestamps. |
| **Safety Guardrails** | Enforce human-in-the-loop review, reject peer ranking, treat missing data safely. | **Implemented & Verified**: Human-in-the-loop teacher review gate, non-agent approval guardrails, SHA-256 snapshotting, epistemic non-causal schemas, and deterministic AI output validation. |
| **Test Verification** | Automated test coverage spanning unit, storage, service, analysis, governance, agent orchestration, peer comparison screening, runtime discovery, and MCP protocol integration. | **Implemented & Verified**: 234 automated tests passing across 12 distinct test suites with 100% pass rate. |

---

## 2. Test Suite Matrix

The ALLPS test suite covers 12 distinct layers (234 tests):

### 2.1. Domain Models (`tests/test_models.py` — 26 Tests)
- `test_create_valid_learner`: Validates learner model instantiation.
- `test_learner_requires_display_name`: Enforces minimum length validation.
- `test_learner_is_frozen`: Verifies immutability of learner records.
- `test_create_valid_evidence`: Validates standard evidence record creation with system origin.
- `test_evidence_requires_timezone_aware_observed_at`: Rejects naive timestamps.
- `test_evidence_invalid_type`: Rejects unknown evidence types.
- `test_evidence_term_range`: Validates term boundaries (1-4).
- `test_evidence_academic_year_range`: Validates academic year range (2000-2100).
- `test_evidence_is_frozen`: Enforces immutability of evidence records.
- `test_all_evidence_types_valid`: Asserts support for assessment, attendance, observation, reflection, and project types.
- `test_all_ingestion_methods_valid`: Asserts support for api, webhook, scheduled_sync, csv_import, manual_observation, learner_pulse, synthetic.
- `test_invalid_ingestion_method_rejected`: Rejects invalid ingestion method enums.
- `test_source_system_required`: Enforces non-empty string for source_system.
- `test_provenance_fields_required`: Validates requirement of `source_type` and `source_reference`.
- `test_academic_year_is_int`: Ensures academic year is stored as an integer for sortability.
- `test_term_is_int`: Ensures term is stored as an integer for sortability.
- `test_reject_conflicting_comparison_authorized_aliases`: Explicit false cannot be overridden by true; conflicting aliases rejected.
- `test_reject_booleans_and_non_numerics_in_marks_and_fluency`: Rejects `True`/`False` and non-numeric strings in `score`, `max_score`, and fluency `value`.
- `test_treat_null_outcome_fields_as_absent`: Treats null outcome fields as absent when evaluating contradictions on missing statuses.
- `test_rubric_scale_validation_targeted`: Enforces registered scale identifier or explicit level list; rejects invalid levels and unregistered IDs.
- `test_create_pattern`: Verifies Pattern model integrity.
- `test_pattern_has_no_review_status`: Asserts `review_status` has been removed from Pattern.
- `test_all_pattern_types_valid`: Asserts all 6 pattern types.
- `test_create_review_item` & `test_review_statuses`: Validates teacher review statuses (`pending`, `accepted`, `rejected`, `needs_context`).
- `test_create_audit_entry`: Validates MCP tool audit logging model.

### 2.2. SQLite Persistence Layer (`tests/test_storage.py` — 19 Tests)
- `test_add_and_retrieve_learner`: CRUD verification for learner identity.
- `test_get_nonexistent_learner`: Safe null handling.
- `test_learner_exists`: Boolean query verification.
- `test_add_and_retrieve_evidence`: Ingestion and reading of evidence records.
- `test_evidence_chronological_order`: Strict verification of chronological ordering (`academic_year ASC, term ASC, observed_at ASC`).
- `test_filter_by_evidence_type`: Filter correctness for individual categories.
- `test_filter_by_academic_year`: Year-based isolation.
- `test_filter_by_term`: Term-based slice isolation.
- `test_filter_by_subject`: Subject-based filtering.
- `test_no_evidence_returns_empty`: Empty set handling.
- `test_evidence_preserves_provenance`: Roundtrip serialization check for provenance data.
- `test_evidence_preserves_timestamps`: UTC ISO 8601 precision preservation.
- `test_evidence_preserves_source_system_and_ingestion_method`: Proves SQLite schema and deserialization preserve `source_system` and `ingestion_method`.
- `test_rich_marks_comparability_roundtrip`: Verifies full comparability metadata (`grade`, `form`, `form_version`, `language`, `measured_skill`, `comparison_authorized`) survives SQLite serialization/deserialization.
- `test_rubric_scale_list_roundtrip`: Verifies rubric scale lists survive text storage and load back as structured data.
- `test_missing_outcome_status_roundtrip`: Verifies missing outcome statuses survive roundtrip distinct from zero scores.
- `test_retrieved_evidence_content_is_immutable`: Verifies that evidence content remains frozen (`MappingProxyType`) after retrieval from SQLite.
- `test_add_and_retrieve_audit`: Audit entry recording and retrieval.
- `test_filter_audit_by_tool`: Tool-specific audit log filtering.

### 2.3. Evidence Service Layer (`tests/test_evidence_service.py` — 10 Tests)
- `test_record_and_retrieve`: End-to-end service cycle preserving system origin and ingestion channel.
- `test_auto_creates_learner`: Safe auto-provisioning for unregistered learner IDs.
- `test_creates_audit_entry`: Audit log creation on record actions with `source_system` and `ingestion_method`.
- `test_invalid_evidence_type_rejected`: Rejection of invalid payload schemas.
- `test_invalid_ingestion_method_rejected`: Rejection of invalid ingestion channel string.
- `test_evidence_has_provenance`: Guaranteed provenance attachment.
- `test_returns_chronological_order`: Service-level ordering verification.
- `test_filters_work`: Combined filter execution.
- `test_empty_history`: Graceful empty response structure.
- `test_creates_audit_entry`: Audit log creation on read queries.

### 2.4. Longitudinal Analysis Service (`tests/test_analysis_service.py` — 19 Tests)
- Enforces strict comparability across grade, subject, measured skill, form identity & version, language, scoring scale, and assessment stage.
- Rejects monotonic gains on mixed assessment scales and same-term tests.
- Rejects invented defaults when comparison metadata is missing.
- Verifies ordinal rubric progression across versioned scales without false progression.
- Preserves true zero distinct from missing outcomes (`result_unavailable` vs `assessment_not_administered`).
- Detects improving, declining, unchanged, and fluctuating trajectories.
- `test_different_rubric_scales_do_not_produce_shared_trend`: Different rubric scales partition and do not produce a shared trend.
- `test_equivalent_scales_group_together`: Registered scale identifiers and explicit level lists resolve to canonical scale sequences.
- `test_preserve_assessment_stage_distinctions`: Timing milestones (`opener`, `cat`, `midterm`, `end_term`) are preserved and not combined.
- `test_ordinal_rubric_ranks_not_averaged_within_period`: Qualitative ordinal rubric ranks are never averaged into fractional numbers.

### 2.5. MCP Protocol & Tools (`tests/test_mcp_tools.py` — 13 Tests)
- `test_ingest_evidence_tool`: Direct Python invocation of `ingest_evidence`.
- `test_record_evidence_backward_compatibility_alias`: Verifies `record_evidence` is a Python-level alias for `ingest_evidence`.
- `test_source_system_and_ingestion_method_survive_pipeline`: Tests that `source_system` and `ingestion_method` survive MCP tool → service → SQLite → retrieval.
- `test_get_learner_history_tool`: Direct Python invocation of `get_learner_history`.
- `test_get_history_with_filters`: Direct filtered queries.
- `test_empty_history`: Direct query on non-existent learner.
- `test_ingest_creates_audit_trail`: Verifies tool execution leaves audit footprint in store including system origin.
- `test_mcp_direct_rich_marks_rubric_and_missing`: Verifies rich marks, rubrics, and missing outcomes through direct MCP calls.
- `test_mcp_direct_workstream_1_defects`: Rejection of conflicting aliases and booleans, acceptance of fluency and null outcomes.
- `test_analyse_pattern_on_seeded_learners`: Verifies `analyse_longitudinal_pattern` directly on contract-compliant seed data.
- `test_mcp_server_tools_and_calls`: Protocol-level integration smoke test over stdio JSON-RPC.
- `test_mcp_protocol_idempotency_retry_and_conflict`: Wire-protocol test verifying idempotent retries and error reporting on conflicts.
- `test_mcp_protocol_wire_rich_marks_rubric_and_missing_analysis`: End-to-end stdio wire test verifying marks, rubrics, missingness, and Workstream 1 contract validation.

### 2.6. Regression & Integrity Layer (`tests/test_regression.py` — 12 Tests)
- `test_migration_adds_source_event_id`: Non-destructive schema migration.
- `test_idempotent_ingestion_retry`: Event key replay returns existing record.
- `test_concurrent_transactions`: Multiple concurrent ingestions succeed safely.
- `test_rollback_on_validation_failure`: Partial learner creations roll back atomically.
- `test_seed_script`: Validates real synthetic seed data execution.
- `test_full_observation_idempotency_conflicts`: Confirms conflicts on any difference in learner, year, term, subject, timestamp, type, provenance, or content.
- `test_nested_serialization_round_trip_and_retry`: Round-trip equality and retry support for nested dictionaries and lists.
- `test_transaction_ownership_deterministic_overlap`: Deterministic test verifying overlapping reads do not expose uncommitted evidence and failure rollbacks stay bounded.
- `test_complete_outcome_logging`: Timestamp, timezone, and enum validation error auditing.
- `test_audit_storage_failure_honest_rollback`: Verifies that when audit storage fails, the transaction rolls back and the error is logged and re-raised.
- `test_sqlite_round_trip_and_replay_rich_marks_rubric_missing`: Full round-trip verification across rich marks, rubrics, and missingness.
- `test_sqlite_round_trip_and_conflict_handling_workstream_1_defects`: Targeted regression test verifying fluency roundtrip, null outcome tolerance, and conflict detection.



### 2.7. Phase 2 Governance & Safety Policies (`tests/test_phase2_governance.py` — 44 Tests)
- Label policy & prohibited diagnostic/deficit terminology screening (`check_for_prohibited_labels`, `scan_content_for_prohibited_labels`).
- `ReviewItem` domain validation: human `reviewer_id` and `approved_content_hash` enforced upon acceptance.
- `ReviewService` adjudication and strict blocking of autonomous agents (`is_autonomous_agent`).
- Auto-generation and deduplication of review items in `AnalysisService`.
- Dual-view learner profile filtering: unapproved patterns strictly excluded from `get_surfaced_profile`.
- Cryptographic SHA-256 content snapshot integrity verification.
- Phase 2 MCP server tools integration (`flag_pattern_for_review`, `resolve_teacher_review`, `get_pending_reviews`, `get_surfaced_profile`).

### 2.8. Phase 2 Analysis Engine Repairs (`tests/test_phase2_analysis_repairs.py` — 16 Tests)
- Verification of ordinal rubric ranks and progression across scale revisions.
- Scale sequence canonicalization without fractional rank averaging.
- Preservation of true zero vs. missing outcome statuses across edge cases.

### 2.9. Bounded AI Agent Orchestration (`tests/test_agent_orchestration.py` — 21 Tests)
- Pydantic schema conformance (`CandidateHandoverBrief`, `SynthesizedFinding`, `HandoverStatus`).
- Deterministic output validator: 100% citation existence against records retrieved for the learner.
- Numerical claim verification against the specific cited records.
- Defense against prompt injection in learner reflections and observations.
- Rejection of unsupported causal language, direct peer-ranking language, and unauthorized actions.
- Safe failure on inference timeout without state or evidence corruption.
- Invariant verification: AI cannot self-approve; unapproved drafts never enter surfaced profile.

### 2.10. Peer-Comparison Validator Gap Closure (`tests/test_peer_comparison_gap.py` — 27 Tests)
- Rejection of direct peer ranking: `ranked bottom 10%`, `ranked top 5%`, `ranked 1st`, `ranked last`.
- Detection and rejection of indirect comparative phrasing: `falling behind peers`, `trailing behind classmates`, `below grade average`, `above class average`, `at the bottom of the class`, `relative to classmates`, `in comparison with other students`, `ahead of peers`, `underperforming classmates`, `bottom quartile`, `norm-referenced`.
- Prevention of false positives on legitimate pedagogical context: `peer collaboration during science inquiry`, `peer study support`, `peer tutoring`, `relative to Term 1 baseline`, `Grade 3 mathematics standards`.

### 2.11. End-to-End Demonstration (`tests/test_demo_e2e.py` — 5 Tests)
- Automated programmatic execution of `demo_e2e.py` covering all 5 canonical outcomes.
- Verification of CLI execution modes (`auto`, `live`, `deterministic`, `mock`).
- CLI subprocess invocation and temporary database cleanup verification.

### 2.12. Runtime Discovery & Degradation Layer (`tests/test_runtime_discovery.py` — 22 Tests)
- Dynamic model discovery with bounded timeouts across LM Studio and Ollama.
- Minimal inference probe (`ping`) containing zero learner data.
- Strict model selection hierarchy (exact match, case-insensitive, normalized separator/basename match, configured aliases).
- Unrestricted substring containment rejection (e.g. `unintended-...-different-finetune`).
- Silent fallback refusal in `live` mode; graceful disclosed deterministic fallback in `auto` mode.
- Per-request provenance accuracy across failure and recovery sequences (`used_fallback` reset).
- Refusal of fallback on OutputValidator governance rejections.
- Teacher review authority boundary and dual-view accepted-only profile filtering.
- Explicit model selection namespace isolation (rejects cross-namespace matching unless explicitly aliased).
- Request-scoped provenance isolation under overlapping concurrent asynchronous requests.

---

## 3. Safety Verification Checklist

| Safety Rule | Verification Approach | Current Status |
|---|---|---|
| **Rule 1: One observation is not a pattern** | Longitudinal engine requires minimum 3 periods for across-term trends. | **Implemented & Verified** |
| **Rule 2: Correlation is not causation** | Output validator rejects causal connective verbs; enforces co-occurrence framing. | **Implemented & Verified** |
| **Rule 3: Missing responses ≠ negative evidence** | Explicit missing statuses (`absent`, `not_administered`) preserved as None, never 0. | **Implemented & Verified** |
| **Rule 4: Learner self-report is one source, not absolute** | Separate `LEARNER_REFLECTION` enum; wrapped in `<untrusted_evidence_payload>`. | **Implemented & Verified** |
| **Rule 5: Teacher observations are evidence, not truth** | Multi-teacher observations preserved with author attribution; divergent notes flagged. | **Implemented & Verified** |
| **Rule 6: AI interpretations are lowest authority** | AI drafts enter `ReviewItem(status="pending")`; cannot enter surfaced profile. | **Implemented & Verified** |
| **Rule 7: Never rank learners against peers** | Validator rejects direct and indirect peer ranking (`bottom 10%`, `weaker than peers`, `falling behind peers`, `below grade average`, `bottom of class`, `relative to classmates`); history queries take 1 ID. | **Implemented & Verified** |
| **Rule 8: Compare learners against own baseline** | Trends calculated relative to learner's own historical baseline. | **Implemented & Verified** |
| **Rule 9: Never generate harmful labels** | Ingestion & output validator scan regex rejecting deficit/clinical labels (`slow learner`). | **Implemented & Verified** |
| **Rule 10: Teacher review required** | `ReviewService.is_autonomous_agent()` blocks bots; requires human reviewer + SHA-256. Dual-view profile surfacing strictly excludes unreviewed/pending patterns. Note: Full cryptographic human authentication is an unresolved prototype boundary. | **Implemented & Verified** |

---

## 4. Known Technical Limitations & Scenarios

- **Concurrent Ingestion Conflict**: When two overlapping requests submit the same `(source_system, source_event_id)`, both can pass the existence check before either transaction commits. SQLite's unique constraint `UNIQUE(source_system, source_event_id)` ensures only one record is inserted. The second call fails with an `IntegrityError`, rolls back its transaction, and attempts to record a failure audit entry. Sequential retries of identical events succeed idempotently and return the existing evidence record.
- **Teacher Review Authority Boundary**: `ReviewService` prevents automated bots from approving patterns through identifier screening and decouples agent orchestration from adjudication. However, `reviewer_id` is currently an unauthenticated string parameter without cryptographic proof or SSO session tokens. A production deployment requires cryptographic teacher authentication.
- **Evidence Immutability Scope**: Evidence models are frozen, and the MCP server exposes no editing or deletion tools. Direct database access can still modify records.
- **Client Data Handling**: SQLite provides local storage. How connected MCP clients handle, store, or transmit returned learner data depends on those clients.
- **Local Inference Host Read Timeouts**: When local inference engines (e.g. LM Studio) fail to respond within configured probe or generation timeout windows, ALLPS engages deterministic fallback. Live AI generation with local open-weight models requires an active, responsive inference server.
- **Data Provenance**: The learner fixtures in `data/synthetic/seed_data.py` are fictional synthetic scenarios created for system testing and comparability verification. They are not real student records from the Tusome Early Grade Reading Activity or any school system.

---

## 5. How to Execute the Evaluations

To run the full evaluation suite:

```bash
# Run all test suites
pytest -v

# Run with stdout output
pytest -v -s

# Run only MCP protocol test
pytest -v tests/test_mcp_tools.py -k test_mcp_server_tools_and_calls
```
