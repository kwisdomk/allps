# Issue 001 — Concurrent review guard: race semantics vs human-correction path

**Branch:** `feature/teacher-review-authority`
**Status:** Closed — superseded by explicit correction path; `expected_revision` now enforced for initial decisions.
**Closed:** feature/teacher-review-authority closeout (2026-11-11)

---

## History

This issue was originally filed when the optimistic-lock guard (`WHERE status='pending'`)
broke legitimate human corrections: `test_gov02_mcp_client_cannot_self_approve` failed
because a teacher trying to accept a `needs_context` review was blocked by the same guard
as a race-condition loser.

An earlier draft fix used a conditional fallback — if the lock miss was by a non-agent
caller, proceed to `update_review_item` unconditionally. That draft was discarded before
shipping. **It does not reflect the current implementation.**

---

## Shipped implementation

The final design eliminates the fallback entirely and splits the two cases explicitly:

| Path | Flag | SQL constraint | Authority check |
|---|---|---|---|
| Initial decision | `is_correction=False` | `WHERE status='pending' AND revision=?` | None (any authenticated user) |
| Explicit correction | `is_correction=True` | `WHERE revision=?` (no pending check) | `authenticated_teacher_id` must be a registered teacher |

Key properties that are now verified by tests:

- **Concurrent initial decisions:** Two callers with the same `expected_revision=0` on a
  pending review → exactly one succeeds, one gets `ConflictError`.
  (`test_concurrent_decisions_exactly_one_wins`)
- **Stale initial decision:** A caller supplying an incorrect `expected_revision` on a
  still-pending review → `ConflictError` (409). `expected_revision` is enforced for both
  paths.  
  (`test_stale_initial_decision_returns_conflict`)
- **Stale correction:** A correction with the wrong `expected_revision` → 409.
  (`test_stale_correction_returns_conflict`)
- **MCP cannot correct:** MCP always passes `is_correction=False` and
  `authenticated_teacher_id=None`. Attempting to call MCP on an already-resolved review
  raises `ConflictError` (wrapped as `ValueError`).
  (`test_mcp_teacher_id_cannot_correct`)
- **Teacher correction requires authority:** `is_correction=True` with
  `authenticated_teacher_id` not in the teacher store → `PermissionError`.
- **Atomicity:** Review update and audit entry are written in the same
  `BEGIN IMMEDIATE` transaction.

---

## Resolved open design decisions

| # | Decision | Outcome |
|---|---|---|
| 1 | Correction requires same teacher or any teacher? | Any registered teacher (verified via session cookie at transport layer). `authenticated_teacher_id` must exist in `teachers` table. |
| 2 | Audit trail for corrections | `is_correction: bool` is recorded in `AuditEntry.input_summary`. |
| 3 | Pilot credentials in source | Plaintext PINs (`1234`, `5678`) in `_PILOT_TEACHERS` are hashed at startup via `bcrypt`; never stored plaintext. Known unsuitable for production — requires provisioning step. |
| 4 | Session secret boot randomness | Sessions don't survive restart if `ALLPS_SESSION_SECRET` is not set. Documented and acceptable for the synthetic pilot. |

---

## Affected files (final)

| File | Change |
|---|---|
| `src/allps/services/review_service.py` | Explicit `is_correction` path; `expected_revision` enforced for initial decisions |
| `src/allps/storage/sqlite_store.py` | `update_review_at_revision` (correction), `resolve_review_if_pending` (initial); both use `WHERE revision=?` |
| `src/allps/web/routes.py` | `reviewer_id` from session, not request body; `is_correction` forwarded |
| `src/allps/web/app.py` | Removed `trusted_reviewer_id`; pilot teachers seeded via `store.add_teacher` |
| `src/allps/mcp/server.py` | `is_correction=False`, `authenticated_teacher_id=None` hardcoded for all MCP calls |
| `src/allps/auth.py` | PIN login, HMAC-signed HttpOnly cookie, `/api/auth/login`, `/api/auth/me`, `/api/auth/logout` |
| `tests/test_teacher_review_authority.py` | 16 scenarios: A–K + J-2 (stale initial decision) |
| `tests/test_audit_fixes.py` | Updated GOV-02 test for new correction flow and message strings |
| `tests/test_web_api.py` | Updated for session-based auth, removed `trusted_reviewer_id` fixture param |
| `pyproject.toml` | Added `itsdangerous>=2.1`, `bcrypt>=4.0` |
