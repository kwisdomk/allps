"""ReviewService — teacher review gate and governance orchestration.

Enforces human sovereign review boundaries:
1. Review resolutions require an explicit human reviewer_id.
2. Autonomous agents / bots are strictly prohibited from approving patterns.
3. Content snapshot hash (SHA-256) is recorded at the moment of approval.
4. Surfaced learner profiles expose only human-accepted patterns.
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
    ) -> ReviewItem:
        """Resolve a review item with human teacher adjudication.

        Guardrails enforced:
        - reviewer_id must be a valid, non-empty human teacher identifier.
        - Autonomous agents cannot resolve status to 'accepted'.
        - On 'accepted', an immutable SHA-256 snapshot of pattern summary is recorded.
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

        # Human authority guardrail: reject autonomous agent approval attempts.
        # Note on Authority Boundary:
        # Bot screening catches explicit agent/bot identifiers. However, caller-supplied
        # reviewer_id is an unauthenticated prototype parameter without cryptographic human proof.
        # Full cryptographic identity and out-of-band human authentication remain an unresolved requirement.
        if status_enum == ReviewStatus.ACCEPTED and self.is_autonomous_agent(reviewer_id):
            raise ValueError(
                f"Autonomous agent '{reviewer_id}' is prohibited from approving patterns. "
                "Only sovereign human educators may accept candidate patterns into the learner profile."
            )

        item = await self._store.get_review_item(review_id)
        if not item:
            raise ValueError(f"Review item with ID '{review_id}' does not exist.")

        pattern = await self._store.get_pattern(item.pattern_id)
        if not pattern:
            raise ValueError(f"Underlying pattern '{item.pattern_id}' does not exist.")

        content_hash: str | None = None
        if status_enum == ReviewStatus.ACCEPTED:
            content_hash = hashlib.sha256(pattern.summary.strip().encode("utf-8")).hexdigest()

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
        )

        audit_entry = AuditEntry(
            tool_name="resolve_teacher_review",
            input_summary={
                "review_id": review_id,
                "status": status_enum.value,
                "reviewer_id": reviewer_id.strip(),
                "has_notes": bool(teacher_notes),
            },
            output_reference=review_id,
            approval_state=status_enum.value,
        )

        async with self._store.transaction() as conn:
            await self._store.update_review_item(updated_item, commit=False, conn=conn)
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
