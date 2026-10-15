"""Deterministic analysis client for offline, verifiable evidence-based synthesis.

Executes genuine, deterministic longitudinal pattern analysis on real learner records
without relying on external language models or probabilistic inference.
Conforms strictly to docs/AI_CONTRACT.md and OutputValidator invariants.
"""

from __future__ import annotations

import html
import json
import logging
import re
from typing import Any, Sequence

from allps.agent.adapter import GenerationResult, InferenceClient
from allps.agent.contracts import CandidateHandoverBrief, HandoverStatus, SynthesizedFinding
from allps.models.evidence import Evidence
from allps.models.pattern import PatternType

logger = logging.getLogger(__name__)


class DeterministicAnalysisClient:
    """Inference client that performs genuine deterministic analysis from prompt context.

    Implements the InferenceClient protocol so it drops in seamlessly to AgentOrchestrator.
    Extracts verified patterns and evidence records from the prompt XML, ensuring
    100% grounded observations, zero fabricated metrics, and complete adherence
    to ALLPS pedagogical governance rules.
    """

    def __init__(self, method_tag: str = "deterministic") -> None:
        self.method_tag = method_tag

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """Parse prompt context and generate a contract-compliant candidate handover brief."""
        learner_id, target_subject, patterns, records_by_id = self._parse_prompt_context(prompt)

        # Check if patterns indicate insufficient evidence or empty
        insufficient = (
            not patterns
            or all(p.get("pattern_type") == PatternType.INSUFFICIENT_EVIDENCE.value for p in patterns)
        )

        if insufficient:
            abstention_limitations = []
            reason = "Insufficient compatible longitudinal records to establish a reliable trajectory."
            if patterns:
                for p in patterns:
                    abstention_limitations.extend(p.get("limitations", []))
                    if p.get("summary"):
                        reason = p["summary"]

            brief = CandidateHandoverBrief(
                learner_id=learner_id,
                status=HandoverStatus.ABSTAINED,
                summary=f"[{self.method_tag.capitalize()} Analysis] Insufficient longitudinal evidence available in {target_subject or 'evaluated subjects'}.",
                findings=[],
                contradictions=[],
                limitations=abstention_limitations or [
                    "Requires at least three distinct academic periods on compatible scales."
                ],
                abstention_reason=reason,
            )
            return GenerationResult(
                text=brief.model_dump_json(),
                used_fallback=False,
                fallback_error=None,
                runtime_method="deterministic",
            )

        # Build findings from verified patterns
        findings: list[SynthesizedFinding] = []
        contradictions: list[str] = []
        all_limitations: list[str] = [
            f"Generated via genuine {self.method_tag} rule engine without language model interpretation."
        ]

        # Scan for co-occurring attendance factors from cited terms
        attendance_by_term: dict[int, str] = {}
        for r in records_by_id.values():
            if r.get("type") == "attendance":
                t = r.get("term")
                dp = r.get("days_present")
                if t and dp is not None:
                    attendance_by_term[int(t)] = f"Attendance recorded at {dp} days present in Term {t}."

        has_trend = any(p.get("pattern_type") == PatternType.TREND.value for p in patterns)

        for p in patterns:
            ptype = p.get("pattern_type")
            if ptype == PatternType.INSUFFICIENT_EVIDENCE.value:
                continue

            # If an across-term trend is present, the trend pattern already covers the trajectory
            if ptype == PatternType.CHANGED_FROM_BASELINE.value and has_trend:
                continue

            summary = p.get("summary", "")
            # Ensure observation does not assert a derived subtraction delta that is absent from raw records
            if ptype == PatternType.CHANGED_FROM_BASELINE.value:
                summary = re.sub(r"^(?:Gain|Drop)\s+of\s+\d+(?:\.\d+)?\s*(?:marks|points)?\s+from\s+baseline\s*", "Baseline comparison shows shift ", summary, flags=re.IGNORECASE)

            supp_ids = p.get("supporting_evidence", [])
            conf_ids = p.get("conflicting_evidence", [])
            limitations = p.get("limitations", [])

            all_limitations.extend(limitations)

            # Check for conflicting observations or notes in records
            for eid in conf_ids:
                if eid in records_by_id:
                    contradictions.append(
                        f"Evidence record {eid} provides qualifying or divergent context."
                    )

            # Extract co-occurring factors from attendance in the same periods
            co_factors: list[str] = []
            for eid in supp_ids:
                rec = records_by_id.get(eid)
                if rec and rec.get("term"):
                    try:
                        term_num = int(rec["term"])
                        if term_num in attendance_by_term and attendance_by_term[term_num] not in co_factors:
                            co_factors.append(attendance_by_term[term_num])
                    except (ValueError, TypeError):
                        pass

            subj_label = target_subject or "this subject"
            inquiry = f"Review foundational scaffolding and term-by-term assessment rubric for {subj_label}."

            finding = SynthesizedFinding(
                observation=summary,
                supporting_evidence_ids=supp_ids,
                conflicting_evidence_ids=conf_ids,
                co_occurring_factors=co_factors,
                teacher_inquiries=[inquiry],
            )
            findings.append(finding)

        if not findings:
            brief = CandidateHandoverBrief(
                learner_id=learner_id,
                status=HandoverStatus.ABSTAINED,
                summary=f"[{self.method_tag.capitalize()} Analysis] No actionable patterns could be synthesized from evidence.",
                findings=[],
                contradictions=[],
                limitations=all_limitations,
                abstention_reason="No deterministic patterns met minimum threshold for handover synthesis.",
            )
            return GenerationResult(
                text=brief.model_dump_json(),
                used_fallback=False,
                fallback_error=None,
                runtime_method=self.method_tag,
            )

        primary_summary = findings[0].observation
        brief = CandidateHandoverBrief(
            learner_id=learner_id,
            status=HandoverStatus.COMPLETED,
            summary=f"[{self.method_tag.capitalize()} Analysis] {primary_summary}",
            findings=findings,
            contradictions=contradictions,
            limitations=list(dict.fromkeys(all_limitations)),
            abstention_reason=None,
        )
        return GenerationResult(
            text=brief.model_dump_json(),
            used_fallback=False,
            fallback_error=None,
            runtime_method=self.method_tag,
        )

    def _parse_prompt_context(
        self, prompt: str
    ) -> tuple[str, str | None, list[dict[str, Any]], dict[str, dict[str, Any]]]:
        """Extract learner_id, target_subject, patterns, and evidence records from prompt XML."""
        # 1. Learner context
        m_ctx = re.search(r'<learner_context\s+learner_id="([^"]+)"(?:\s+target_subject="([^"]+)")?', prompt)
        learner_id = m_ctx.group(1) if m_ctx else "unknown"
        target_subject = m_ctx.group(2) if m_ctx and m_ctx.group(2) != "all" else None

        # 2. Deterministic patterns
        patterns: list[dict[str, Any]] = []
        m_pat = re.search(r"<deterministic_patterns>\s*(.*?)\s*</deterministic_patterns>", prompt, re.DOTALL)
        if m_pat:
            try:
                patterns = json.loads(m_pat.group(1))
            except json.JSONDecodeError:
                logger.warning("Could not decode deterministic_patterns JSON from prompt")

        # 3. Evidence records
        records_by_id: dict[str, dict[str, Any]] = {}
        m_rec_block = re.search(r"<evidence_records>\s*(.*?)\s*</evidence_records>", prompt, re.DOTALL)
        if m_rec_block:
            block = m_rec_block.group(1)
            # Find <record id="..." ... />
            for m in re.finditer(r'<record\s+id="([^"]+)"([^>]*)/?>', block):
                eid = html.unescape(m.group(1))
                attrs = {k: html.unescape(v) for k, v in re.findall(r'(\w+)="([^"]*)"', m.group(2))}
                attrs["id"] = eid
                records_by_id[eid] = attrs

            # Find <untrusted_evidence_payload id="..." ...>
            for m in re.finditer(r'<untrusted_evidence_payload\s+id="([^"]+)"([^>]*)>(.*?)</untrusted_evidence_payload>', block, re.DOTALL):
                eid = html.unescape(m.group(1))
                attrs = {k: html.unescape(v) for k, v in re.findall(r'(\w+)="([^"]*)"', m.group(2))}
                attrs["id"] = eid
                attrs["content"] = html.unescape(m.group(3).strip())
                records_by_id[eid] = attrs

        return learner_id, target_subject, patterns, records_by_id
