"""ReviewService — teacher review gate and governance orchestration.

Enforces human sovereign review boundaries:
1. Review resolutions require an explicit human reviewer_id.
2. Autonomous agents / bots are strictly prohibited from approving patterns.
3. Content snapshot hash (SHA-256) is recorded at the moment of approval.
4. Surfaced learner profiles expose only human-accepted patterns.

Concurrency model (revision-based optimistic locking):
- Initial decisions target a PENDING review at the expected revision.
  Any two concurrent initial submissions on the same review produce
  exactly one success and one ConflictError — there is NO unconditional fallback.
- Corrections are an explicit operation distinct from initial decisions.
  They require is_correction=True, a verified teacher identity, appropriate
  review access, and the expected revision.  Caller authority is derived from
  the trusted transport/session context (authenticated_teacher_id), never from
  the supplied reviewer_id field alone.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from typing import Any

from allps.models.audit import AuditEntry
from allps.models.review import ReviewItem, ReviewStatus
from allps.storage.sqlite_store import SQLiteStore

# Prefix patterns identifying non-human autonomous systems
_BOT_AGENT_PATTERNS = re.compile(
    r"^(agent|bot|llm|system|ai|autonomous|worker|synthetic|pydantic_ai|langgraph)($|[:_\-\s])",
    re.IGNORECASE,
)


class ConflictError(Exception):
    """Raised when an optimistic-concurrency conditional update finds a stale revision.

    The caller should reload the review item (to obtain the current revision) and
    re-evaluate whether to retry.
    """


class ReviewService:
    """Service layer governing teacher adjudication and human-in-the-loop review gating."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    @staticmethod
    def is_autonomous_agent(reviewer_id: str) -> bool:
        """Check if an identifier indicates an autonomous system rather than a human educator."""
        if not reviewer_id or not isinstance(reviewer_id, str):
            return True
        clean_id = reviewer_id.strip().lower()
        if clean_id in ("agent", "bot", "system", "llm", "ai", "autonomous_agent", "background_worker"):
            return True
        return bool(_BOT_AGENT_PATTERNS.match(clean_id))

    async def flag_pattern_for_review(
        self,
        pattern_id: str,
        assigned_to: str | None = None,
    ) -> ReviewItem:
        """Flag a candidate pattern for human teacher review.

        De-duplicates candidate inbox items: if an active (pending or accepted)
        review item already exists for this pattern, returns the existing item.
        """
        pattern = await self._store.get_pattern(pattern_id)
        if not pattern:
            raise ValueError(f"Pattern with ID '{pattern_id}' does not exist.")

        existing_items = await self._store.get_review_items_for_pattern(pattern_id)
        for item in existing_items:
            if item.status == ReviewStatus.PENDING:
                return item

        review_item = ReviewItem(
            pattern_id=pattern_id,
            assigned_to=assigned_to,
            status=ReviewStatus.PENDING,
        )

        audit_entry = AuditEntry(
            tool_name="flag_pattern_for_review",
            input_summary={
                "pattern_id": pattern_id,
                "assigned_to": assigned_to,
            },
            output_reference=review_item.review_id,
            approval_state="pending",
        )

        async with self._store.transaction() as conn:
            await self._store.add_review_item(review_item, commit=False, conn=conn)
            await self._store.add_audit_entry(audit_entry, commit=False, conn=conn)

        return review_item

    async def resolve_teacher_review(
        self,
        review_id: str,
        status: str | ReviewStatus,
        reviewer_id: str,
        teacher_notes: str | None = None,
        expected_revision: int = 0,
        *,
        is_correction: bool = False,
        authenticated_teacher_id: str | None = None,
    ) -> ReviewItem:
        """Resolve a review item with human teacher adjudication.

        Parameters
        ----------
        review_id:
            The review to act on.
        status:
            Target status.  Must not be 'pending'.
        reviewer_id:
            Identity supplied by the caller (used as the on-record reviewer name).
            Authority is NOT derived from this field for corrections — use
            authenticated_teacher_id for that.
        teacher_notes:
            Optional teacher commentary.
        expected_revision:
            The revision the caller last observed.  The update is rejected
            (ConflictError) if the stored revision has advanced past this value.
            Initial decisions additionally require status == 'pending'.
        is_correction:
            When True, the caller is explicitly requesting a correction of an
            already-resolved review.  Requires authenticated_teacher_id to be
            set and verified as a registered teacher.  Initial decisions
            (is_correction=False) only succeed when status == 'pending'.
        authenticated_teacher_id:
            Teacher identity derived from the trusted transport/session context
            (e.g. a verified session cookie).  Must be set for corrections.
            Never accept this from an unauthenticated caller-supplied field.

        Raises
        ------
        ValueError
            Input validation failures (bad status, empty reviewer_id, bot identity
            on accepted, review or pattern not found).
        ConflictError
            Optimistic concurrency failure: expected_revision does not match
            the current stored revision.  Caller must reload the review and
            re-evaluate.
        PermissionError
            Correction attempted without a verified teacher identity.
        """
        if isinstance(status, str):
            try:
                status_enum = ReviewStatus(status.lower())
            except ValueError:
                raise ValueError(
                    f"Invalid review status: '{status}'. Must be one of: "
                    f"{', '.join(s.value for s in ReviewStatus if s != ReviewStatus.PENDING)}"
                )
        else:
            status_enum = status

        if status_enum == ReviewStatus.PENDING:
            raise ValueError("Cannot resolve review to 'pending' state.")

        if not reviewer_id or not isinstance(reviewer_id, str) or not reviewer_id.strip():
            raise ValueError("Resolution requires an explicit, non-empty human reviewer_id.")

        # Autonomous agents cannot approve patterns.
        if status_enum == ReviewStatus.ACCEPTED and self.is_autonomous_agent(reviewer_id):
            raise ValueError(
                f"Autonomous agent '{reviewer_id}' is prohibited from approving patterns. "
                "Only sovereign human educators may accept candidate patterns into the learner profile."
            )

        # ── Correction-specific authority checks ────────────────────────────────
        if is_correction:
            # Corrections MUST have an authenticated_teacher_id from the transport layer.
            if not authenticated_teacher_id:
                raise PermissionError(
                    "Corrections require a verified teacher identity from the trusted transport "
                    "context.  Supply authenticated_teacher_id from the session."
                )
            teacher_record = await self._store.get_teacher(authenticated_teacher_id)
            if not teacher_record:
                raise PermissionError(
                    f"Authenticated identity '{authenticated_teacher_id}' is not a registered teacher."
                )

        item = await self._store.get_review_item(review_id)
        if not item:
            raise ValueError(f"Review item with ID '{review_id}' does not exist.")

        # ── Initial-decision guard ───────────────────────────────────────────────
        # Non-correction calls must only succeed when the review is still pending
        # AND the caller's expected_revision matches the current stored revision.
        if not is_correction:
            if item.status != ReviewStatus.PENDING:
                raise ConflictError(
                    f"Review '{review_id}' is already resolved (status={item.status.value}). "
                    "To change a prior decision use is_correction=True with a verified teacher identity."
                )
            if item.revision != expected_revision:
                raise ConflictError(
                    f"Optimistic concurrency conflict on review '{review_id}': "
                    f"expected revision {expected_revision} but the stored revision is {item.revision}. "
                    "Reload the review item and retry."
                )

        pattern = await self._store.get_pattern(item.pattern_id)
        if not pattern:
            raise ValueError(f"Underlying pattern '{item.pattern_id}' does not exist.")

        content_hash: str | None = None
        if status_enum == ReviewStatus.ACCEPTED:
            content_hash = hashlib.sha256(pattern.summary.strip().encode("utf-8")).hexdigest()

        prior_status = item.status

        updated_item = ReviewItem(
            review_id=item.review_id,
            pattern_id=item.pattern_id,
            assigned_to=item.assigned_to,
            status=status_enum,
            teacher_notes=teacher_notes,
            created_at=item.created_at,
            resolved_at=datetime.now(timezone.utc),
            reviewer_id=reviewer_id.strip(),
            approved_content_hash=content_hash,
            revision=item.revision,  # read current — store will check and increment
        )

        audit_entry = AuditEntry(
            tool_name="resolve_teacher_review",
            input_summary={
                "review_id": review_id,
                "status": status_enum.value,
                "reviewer_id": reviewer_id.strip(),
                "has_notes": bool(teacher_notes),
                "is_correction": is_correction,
                "prior_status": prior_status.value,
                "authenticated_teacher_id": authenticated_teacher_id,
                "expected_revision": expected_revision,
            },
            output_reference=review_id,
            approval_state=status_enum.value,
        )

        async with self._store.transaction() as conn:
            if is_correction:
                # Corrections use revision-only conditional update (no pending check).
                updated = await self._store.update_review_at_revision(
                    updated_item, expected_revision=expected_revision, conn=conn
                )
            else:
                # Initial decisions use the combined pending + revision check.
                updated = await self._store.resolve_review_if_pending(
                    updated_item, conn=conn
                )

            if not updated:
                # Both paths return False on optimistic-lock failure only.
                # There is no unconditional fallback — a conflict is a conflict.
                raise ConflictError(
                    f"Optimistic concurrency conflict on review '{review_id}': "
                    f"expected revision {expected_revision} but the record has advanced. "
                    "Reload the review item and retry."
                )

            await self._store.add_audit_entry(audit_entry, commit=False, conn=conn)

        return updated_item

    async def get_pending_reviews(
        self,
        assigned_to: str | None = None,
    ) -> list[ReviewItem]:
        """Retrieve all review items pending teacher adjudication."""
        return await self._store.get_pending_reviews(assigned_to=assigned_to)

    async def get_surfaced_profile(
        self,
        learner_id: str,
    ) -> dict[str, Any]:
        """Retrieve published profile for a learner, strictly exposing accepted patterns."""
        if not learner_id or not isinstance(learner_id, str):
            raise ValueError("learner_id must be a non-empty string.")

        accepted_patterns = await self._store.get_surfaced_profile(learner_id)

        audit_entry = AuditEntry(
            tool_name="get_surfaced_profile",
            input_summary={"learner_id": learner_id},
            output_reference=learner_id,
            approval_state=f"surfaced_{len(accepted_patterns)}_patterns",
        )
        await self._store.add_audit_entry(audit_entry)

        return {
            "learner_id": learner_id,
            "accepted_pattern_count": len(accepted_patterns),
            "patterns": accepted_patterns,
        }
