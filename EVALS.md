# ALLPS — Evaluation Framework & Verification Checklist

> **Purpose**: Evaluation scorecard for ALLPS across challenge dimensions.

---

## 1. Challenge Evaluation Rubric Alignment

| Criterion | Evaluation Requirement | Phase 1 Implementation Status |
|---|---|---|
| **Mission Alignment** | Preserve learning continuity across terms/years/teachers without labeling or diagnosing students. | **Implemented**: Domain models track timestamped observations with provenance, preventing identity labels. |
| **System Architecture** | Modular, testable, and standards-compliant MCP integration. | **Implemented**: MCP server exposes validated tools over standard stdio transport; clean separation between models, storage, services, and MCP server. |
| **Data Integrity & Provenance** | Immutable evidence, sortable academic time, upstream system origin, and explicit source attribution. | **Implemented**: `Evidence` frozen models with `source_system`, `ingestion_method`, `source_type`, `source_reference`, `academic_year` (int), `term` (int), and UTC timestamps. |
| **Safety Guardrails** | Enforce human-in-the-loop review, reject peer ranking, treat missing data safely. | **Partial**: Non-ranking data architecture is implemented. `ReviewItem` data model exists. Enforcement of teacher approval (blocking patterns from entering a learner's profile) is planned for Phase 2. |
| **Test Verification** | Automated test coverage spanning unit, storage, service, pipeline roundtrips, regression integrity, and MCP protocol integration. | **Implemented**: 66 automated tests passing, including real subprocess MCP wire protocol testing. |

---

## 2. Test Suite Matrix

The ALLPS test suite covers 5 distinct layers (66 tests):

### 2.1. Domain Models (`tests/test_models.py` — 22 Tests)
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
- `test_create_pattern`: Verifies Pattern model integrity.
- `test_pattern_has_no_review_status`: Asserts `review_status` has been removed from Pattern.
- `test_all_pattern_types_valid`: Asserts all 6 pattern types.
- `test_create_review_item` & `test_review_statuses`: Validates teacher review statuses (`pending`, `accepted`, `rejected`, `needs_context`).
- `test_create_audit_entry`: Validates MCP tool audit logging model.

### 2.2. SQLite Persistence Layer (`tests/test_storage.py` — 15 Tests)
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

### 2.4. MCP Protocol & Tools (`tests/test_mcp_tools.py` — 9 Tests)
- `test_ingest_evidence_tool`: Direct Python invocation of `ingest_evidence`.
- `test_record_evidence_backward_compatibility_alias`: Verifies `record_evidence` is a Python-level alias for `ingest_evidence`.
- `test_source_system_and_ingestion_method_survive_pipeline`: Tests that `source_system` and `ingestion_method` survive MCP tool → service → SQLite → retrieval.
- `test_get_learner_history_tool`: Direct Python invocation of `get_learner_history`.
- `test_get_history_with_filters`: Direct filtered queries.
- `test_empty_history`: Direct query on non-existent learner.
- `test_ingest_creates_audit_trail`: Verifies tool execution leaves audit footprint in store including system origin.
- `test_mcp_server_tools_and_calls`: Protocol-level integration smoke test over stdio JSON-RPC.
- `test_mcp_protocol_idempotency_retry_and_conflict`: Wire-protocol test verifying idempotent retries and error reporting on conflicts.

### 2.5. Regression & Integrity Layer (`tests/test_regression.py` — 10 Tests)
- `test_migration_adds_source_event_id`: Non-destructive schema migration.
- `test_idempotent_ingestion_retry`: Event key replay returns existing record.
- `test_concurrent_transactions`: Multiple concurrent ingestions succeed safely.
- `test_rollback_on_validation_failure`: Partial learner creations roll back atomically.
- `test_seed_script`: Validates real synthetic seed data execution.
- `test_full_observation_idempotency_conflicts`: Confirms conflicts on any difference in learner, year, term, subject, timestamp, type, provenance, or content.
- `test_nested_serialization_round_trip_and_retry`: Round-trip equality and retry support for nested dictionaries and lists.
- `test_transaction_ownership_deterministic_overlap`: Deterministic test verifying overlapping reads do not expose uncommitted evidence and failure rollbacks stay bounded.
- `test_complete_outcome_logging`: Timestamp, timezone, and enum validation error auditing.
- `test_audit_storage_failure_honest_rollback`: Verifies that when audit storage fails, the transaction rolls back and the error is logged and re-raised rather than silently swallowed.


---

## 3. Safety Verification Checklist

| Safety Rule | Verification Approach | Current Status |
|---|---|---|
| **Rule 1: One observation is not a pattern** | Multi-point scenarios exist in synthetic data. Enforcement requires the pattern detection engine. | Data fixtures prepared. Enforcement planned for Phase 2. |
| **Rule 2: Correlation is not causation** | Pattern summaries will describe co-occurrence, not causal claims. | Design principle. Enforcement depends on Phase 2 pattern engine. |
| **Rule 3: Missing responses ≠ negative evidence** | Learner C fixture omits self-reflection in Terms 1 & 2. No penalty is applied. | Validated in Learner C test data. |
| **Rule 4: Learner self-report is one source, not absolute** | Separate `LEARNER_REFLECTION` enum type; treated as one evidence source among others. | Architecture validated. |
| **Rule 5: Teacher observations are evidence, not truth** | Observation changes across teachers (e.g. Mr. Banda to Mrs. Ngcobo, Ms. Achebe to Mr. Okafor) tracked via `source_reference`. | Tested in Learner A & C fixtures. |
| **Rule 6: AI interpretations are lowest authority** | AI outputs will route to `ReviewItem` before entering a learner's profile. | `ReviewItem` data model exists. Routing logic planned for Phase 2. |
| **Rule 7: Never rank learners against peers** | Queries accept a single `learner_id`; no cross-learner ranking endpoints exist. | Implemented as an API constraint. |
| **Rule 8: Compare learners against own baseline** | Sortable chronological history (`academic_year, term, observed_at`) provides longitudinal baseline. | Tested in storage & MCP layers. |
| **Rule 9: Never generate harmful labels** | Domain models store structured evidence fields instead of freeform classification tags. | Schema-level constraint. No runtime label-blocking logic yet. |
| **Rule 10: Teacher review required** | `ReviewItem` model provides the review data structure. | Data model validated. Enforcement workflow planned for Phase 2. |

---

## 4. Known Technical Limitations & Scenarios

- **Concurrent Ingestion Conflict**: When two overlapping requests submit the same `(source_system, source_event_id)`, both can pass the existence check before either transaction commits. SQLite's unique constraint `UNIQUE(source_system, source_event_id)` ensures only one record is inserted. The second call fails with an `IntegrityError`, rolls back its transaction, and attempts to record a failure audit entry. Sequential retries of identical events succeed idempotently and return the existing evidence record.
- **Data Provenance**: The learner fixtures in `data/synthetic/seed_data.py` are fictional synthetic scenarios that prepare for future pattern-detection analysis (trend decline, persistent strength, divergence between grades and engagement, and missing data). They are not real student records from the Tusome Early Grade Reading Activity or any school system, and Tusome field definitions have not been verified against production educational datasets.
- **Future Work Boundaries**: Pattern detection (`analyse_longitudinal_pattern`) and enforced teacher review sign-off (`flag_pattern_for_review`) are Phase 2 deliverables. Agent orchestration and longitudinal transitions are Phase 3 deliverables.

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
