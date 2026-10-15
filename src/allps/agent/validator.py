"""Deterministic output validator for the ALLPS AI Intelligence Layer.

Enforces strict, mathematical validation boundaries on LLM-generated output:
1. Pydantic schema conformance.
2. 100% citation existence against records retrieved for the specific learner.
3. Numerical claim verification against the specific cited records.
4. Screening for prohibited deficit and clinical diagnostic labels.
5. Screening for unsupported causal attribution.
6. Screening for peer-ranking and comparative language.
7. Screening for unauthorized/clinical actions in recommendations.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Sequence

from allps.agent.contracts import CandidateHandoverBrief, HandoverStatus, SynthesizedFinding
from allps.models.evidence import Evidence
from allps.policies.label_policy import check_for_prohibited_labels

logger = logging.getLogger(__name__)

# Banned causal attribution patterns linking phenomena without clinical/diagnostic authorization
_CAUSAL_PATTERNS = [
    re.compile(r"\bcaused\s+by\b", re.IGNORECASE),
    re.compile(r"\bbecause\s+of\s+(?:the\s+)?(?:learner['’]?s\s+)?(?:lack|poor|bad|absence|failure|truancy|behavior|attitude)\b", re.IGNORECASE),
    re.compile(r"\bdue\s+to\s+(?:the\s+)?(?:learner['’]?s\s+)?(?:lack|poor|bad|laziness|absence|truancy|attitude)\b", re.IGNORECASE),
    re.compile(r"\bas\s+a\s+result\s+of\s+(?:the\s+)?(?:learner['’]?s\s+)?(?:laziness|disinterest|truancy)\b", re.IGNORECASE),
    re.compile(r"\bfailed\s+because\b", re.IGNORECASE),
    re.compile(r"\bleads\s+to\s+(?:failure|poor\s+grades)\b", re.IGNORECASE),
]

# Banned peer ranking & comparative norm-referencing patterns (direct & indirect)
_PEER_RANKING_PATTERNS = [
    re.compile(r"\branked\s+(?:bottom|top|last|first|\d+(?:st|nd|rd|th))\b", re.IGNORECASE),
    re.compile(r"\bbottom\s+\d+\s*(?:%|percent(?!\w))", re.IGNORECASE),
    re.compile(r"\btop\s+\d+\s*(?:%|percent(?!\w))", re.IGNORECASE),
    re.compile(r"\b(?:at\s+the\s+|in\s+the\s+)?(?:bottom|top)\s+of\s+(?:the\s+)?(?:class|grade|cohort)\b", re.IGNORECASE),
    re.compile(r"\b(?:bottom|top)\s+(?:decile|quartile)\b", re.IGNORECASE),
    re.compile(r"\bweaker\s+than\s+(?:peers|classmates|others)\b", re.IGNORECASE),
    re.compile(r"\bstronger\s+than\s+(?:peers|classmates)\b", re.IGNORECASE),
    re.compile(r"\b(?:lower|higher|slower|faster)\s+than\s+(?:their\s+)?(?:peers|classmates)\b", re.IGNORECASE),
    re.compile(r"\b(?:class|grade|cohort|school|national|peer)\s+average\b", re.IGNORECASE),
    re.compile(r"\b(?:below|above)\s+(?:the\s+)?(?:class|grade|cohort|school|national|peer)\s+average\b", re.IGNORECASE),
    re.compile(r"\bpeer\s+(?:ranking|comparison)\b", re.IGNORECASE),
    re.compile(r"\bnorm-referenced\b", re.IGNORECASE),
    re.compile(r"\bcompared\s+to\s+(?:other\s+students|classmates|peers|the\s+class)\b", re.IGNORECASE),
    re.compile(r"\bin\s+comparison\s+(?:to|with)\s+(?:their\s+)?(?:peers|classmates|other\s+students|the\s+class)\b", re.IGNORECASE),
    re.compile(r"\brelative\s+to\s+(?:their\s+)?(?:peers|classmates|other\s+students|the\s+class)\b", re.IGNORECASE),
    re.compile(r"\b(?:lags|lagging|falling|trailing|dropping)\s+behind\s+(?:their\s+)?(?:peers|classmates|the\s+class|others)\b", re.IGNORECASE),
    re.compile(r"\b(?:ahead\s+of|behind)\s+(?:their\s+)?(?:peers|classmates)\b", re.IGNORECASE),
    re.compile(r"\b(?:outperformed|outperforming|underperforming)\s+(?:by\s+)?(?:their\s+)?(?:peers|classmates)\b", re.IGNORECASE),
]

# Banned non-pedagogical / clinical actions
_UNAUTHORIZED_ACTION_PATTERNS = [
    re.compile(r"\b(psychiatric|medication|clinical\s+evaluation|expel|suspend|punish|detention)\b", re.IGNORECASE),
]

# Numeric extraction pattern (extracts numbers that appear to be scores, percentages, or metrics)
_NUMERIC_CLAIM_PATTERN = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:%|percent|marks|points)?\b", re.IGNORECASE)


class ValidationResult:
    """Result of deterministic output validation."""

    def __init__(
        self,
        is_valid: bool,
        brief: CandidateHandoverBrief | None = None,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        self.is_valid = is_valid
        self.brief = brief
        self.errors = errors or []
        self.warnings = warnings or []

    def __repr__(self) -> str:
        return f"<ValidationResult is_valid={self.is_valid} errors={len(self.errors)} warnings={len(self.warnings)}>"


class OutputValidator:
    """Deterministic validator enforcing AI contract invariants on generated text."""

    def __init__(self) -> None:
        pass

    def validate(
        self,
        raw_llm_output: str,
        retrieved_evidence: Sequence[Evidence],
        expected_learner_id: str,
    ) -> ValidationResult:
        """Validate raw LLM output against retrieved evidence and safety rules."""
        errors: list[str] = []
        warnings: list[str] = []

        # 1. Parse JSON with markdown fence stripping
        clean_text = raw_llm_output.strip()
        if clean_text.startswith("```"):
            lines = clean_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            clean_text = "\n".join(lines).strip()

        first_brace = clean_text.find("{")
        last_brace = clean_text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            clean_text = clean_text[first_brace:last_brace + 1]

        try:
            data = json.loads(clean_text)
            if not isinstance(data, dict):
                return ValidationResult(
                    is_valid=False,
                    errors=["LLM output is not a JSON dictionary."],
                )
        except json.JSONDecodeError as exc:
            return ValidationResult(
                is_valid=False,
                errors=[f"Malformed JSON in LLM response: {exc}"],
            )

        # 2. Schema instantiation & validation
        try:
            # If model didn't set learner_id, enforce expected_learner_id
            if "learner_id" not in data or not data["learner_id"]:
                data["learner_id"] = expected_learner_id

            brief = CandidateHandoverBrief(**data)
        except Exception as exc:
            return ValidationResult(
                is_valid=False,
                errors=[f"Pydantic schema validation failure: {exc}"],
            )

        # 3. Learner identity containment
        if brief.learner_id != expected_learner_id:
            errors.append(
                f"Handover learner_id '{brief.learner_id}' does not match expected '{expected_learner_id}'."
            )

        # Build index of valid evidence for this learner
        evidence_by_id = {ev.evidence_id: ev for ev in retrieved_evidence}
        valid_ids = set(evidence_by_id.keys())

        # If abstained, verify abstention invariants
        if brief.status == HandoverStatus.ABSTAINED:
            if not brief.abstention_reason:
                errors.append("Status is 'abstained' but no abstention_reason was provided.")
            # If abstained and clean, return early with result
            if errors:
                return ValidationResult(is_valid=False, brief=None, errors=errors)
            return ValidationResult(is_valid=True, brief=brief, errors=[], warnings=warnings)

        # 4. Evidence Citation Existence & Grounding
        for idx, finding in enumerate(brief.findings):
            if not finding.supporting_evidence_ids:
                errors.append(
                    f"Finding {idx + 1} has no supporting_evidence_ids. All claims must be grounded."
                )

            for eid in finding.supporting_evidence_ids:
                if eid not in valid_ids:
                    errors.append(
                        f"Finding {idx + 1} cites non-existent or unauthorized evidence_id: '{eid}'."
                    )

            for eid in finding.conflicting_evidence_ids:
                if eid not in valid_ids:
                    errors.append(
                        f"Finding {idx + 1} cites non-existent conflicting evidence_id: '{eid}'."
                    )

            # 5. Numerical Claim Verification against Cited Records
            finding_numbers = self._extract_numbers(finding.observation)
            if finding_numbers:
                cited_evidence = [
                    evidence_by_id[eid]
                    for eid in finding.supporting_evidence_ids
                    if eid in evidence_by_id
                ]
                cited_metrics = self._extract_metrics_from_records(cited_evidence)

                for num in finding_numbers:
                    # Check if the claimed number exists in the records cited for THIS finding
                    if num not in cited_metrics:
                        errors.append(
                            f"Finding {idx + 1} makes numerical claim '{num}' not found in its cited evidence records "
                            f"({[e.evidence_id for e in cited_evidence]})."
                        )

        # 6. Prohibited Deficit and Clinical Diagnostic Labels
        all_texts = [brief.summary]
        for f in brief.findings:
            all_texts.append(f.observation)
            all_texts.extend(f.co_occurring_factors)
            all_texts.extend(f.teacher_inquiries)
        all_texts.extend(brief.contradictions)
        all_texts.extend(brief.limitations)

        for text in all_texts:
            bad_labels = check_for_prohibited_labels(text)
            if bad_labels:
                errors.append(
                    f"Prohibited deficit or clinical label detected in generated text: {bad_labels}"
                )

        # 7. Unsupported Causal Statements
        for text in all_texts:
            for pattern in _CAUSAL_PATTERNS:
                match = pattern.search(text)
                if match:
                    errors.append(
                        f"Unsupported causal attribution detected: '{match.group(0)}' in text '{text}'. "
                        "Policy mandates descriptive and co-occurrence framing rather than causal assertion."
                    )

        # 8. Peer-Ranking / Norm-Referencing Language
        for text in all_texts:
            for pattern in _PEER_RANKING_PATTERNS:
                match = pattern.search(text)
                if match:
                    errors.append(
                        f"Peer-ranking language detected: '{match.group(0)}' in text '{text}'. "
                        "Policy strictly prohibits comparative norm-referencing against peers."
                    )

        # 9. Unauthorized / Clinical Inquiries
        for f in brief.findings:
            for inq in f.teacher_inquiries:
                for pattern in _UNAUTHORIZED_ACTION_PATTERNS:
                    match = pattern.search(inq)
                    if match:
                        errors.append(
                            f"Unauthorized non-pedagogical action detected in inquiry: '{match.group(0)}'."
                        )

        is_valid = len(errors) == 0
        return ValidationResult(
            is_valid=is_valid,
            brief=brief if is_valid else None,
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def _extract_numbers(text: str) -> set[float]:
        """Extract explicit numeric values mentioned in text."""
        numbers: set[float] = set()
        for match in _NUMERIC_CLAIM_PATTERN.finditer(text):
            val_str = match.group(1)
            try:
                numbers.add(float(val_str))
            except ValueError:
                pass
        return numbers

    @staticmethod
    def _extract_metrics_from_records(records: Sequence[Evidence]) -> set[float]:
        """Extract verified numeric metrics from evidence records."""
        metrics: set[float] = set()
        if records:
            metrics.add(float(len(records)))  # e.g. "across 3 terms"

        for ev in records:
            metrics.add(float(ev.term))
            metrics.add(float(ev.academic_year))
            if ev.grade:
                m = re.search(r"\b(\d+)\b", ev.grade)
                if m:
                    metrics.add(float(m.group(1)))

            content = ev.content
            if not isinstance(content, dict):
                try:
                    content = dict(content)
                except Exception:
                    continue

            # Direct numeric fields in content
            for k, v in content.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    metrics.add(float(v))
                    # If score and max_score exist, also include percentage
                    if k == "score" and "max_score" in content and isinstance(content["max_score"], (int, float)):
                        if content["max_score"] > 0:
                            pct = round((content["score"] / content["max_score"]) * 100, 1)
                            metrics.add(float(pct))
                            metrics.add(float(round(pct)))  # integer rounded version

            # Attendance metrics
            if "days_present" in content and isinstance(content["days_present"], (int, float)):
                metrics.add(float(content["days_present"]))
            if "days_total" in content and isinstance(content["days_total"], (int, float)):
                metrics.add(float(content["days_total"]))

        return metrics
