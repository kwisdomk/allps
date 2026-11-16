"""HandoverService — class-based permissions, evidence availability, readiness, releases, accountability, and diff tracking."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import re
from typing import Any
import uuid

from allps.models.evidence import Evidence
from allps.models.handover import (
    ChangeProgressStatus,
    ClassRelease,
    DiffSeverity,
    EvidenceAvailabilityStatus,
    PostReleaseChange,
    PublishedReportSection,
    ReceiptStatus,
    ReportReceipt,
    ReportViewEvent,
    SchoolClass,
    SectionReview,
    SectionReviewState,
    SubjectResponse,
    SubjectResponseType,
    TeacherAssignment,
    TeacherRole,
)
from allps.models.review import ReviewStatus
from allps.policies.label_policy import validate_text_for_prohibited_labels
from allps.services.analysis_service import (
    AnalysisService,
    SeriesKey,
    _canonical_rubric_scale,
    _get_rubric_rank,
)
from allps.services.evidence_service import EvidenceService
from allps.storage.sqlite_store import SQLiteStore

_NUM_WORDS = {
    0: "Zero",
    1: "One",
    2: "Two",
    3: "Three",
    4: "Four",
    5: "Five",
    6: "Six",
}

_NOT_CONDUCTED_STATUSES = {
    "assessment_not_administered",
    "not_administered",
    "not_assessed",
}

_MISSING_RESULT_STATUSES = {
    "absent",
    "result_unavailable",
    "unavailable",
    "not_submitted",
}

_UNTRACED_SOURCE_REFS = {
    "unknown",
    "untraced",
    "missing_trace",
    "source_not_found",
}

_SUBJECT_TRAJECTORY_RE = re.compile(
    r"(\b\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?\b|\d+\s*->\s*\d+)",
    re.IGNORECASE,
)


def _num_word(n: int, *, lower: bool = False) -> str:
    word = _NUM_WORDS.get(n, str(n))
    return word.lower() if lower else word


def _format_ts(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.astimezone(timezone.utc).strftime("%a %Y-%m-%d %H:%M UTC")


def _extract_direction(pattern_dict: dict[str, Any]) -> str:
    summary = str(pattern_dict.get("summary", "")).lower()
    ptype = str(pattern_dict.get("pattern_type", "")).lower()
    if ptype == "insufficient_evidence":
        return "insufficient"
    if "conflicting" in summary:
        return "conflicting"
    if "improving" in summary or summary.startswith("gain of") or "advancing" in summary:
        return "improving"
    if "declining" in summary or summary.startswith("drop of"):
        return "declining"
    if "unchanged" in summary or "constant" in summary:
        return "unchanged"
    if "variable" in summary or "without monotonic" in summary:
        return "variable"
    return "observed"


def _extract_pattern_subject(summary: str, subjects_known: list[str]) -> str | None:
    lowered = summary.lower()
    for subj in subjects_known:
        if subj.lower() in lowered:
            return subj
    return None


def _summarize_evidence_item(ev: Evidence) -> dict[str, Any]:
    content = dict(ev.content) if not isinstance(ev.content, dict) else ev.content
    summary: dict[str, Any] = {
        "evidence_id": ev.evidence_id,
        "evidence_type": ev.evidence_type.value,
        "subject": ev.subject,
        "academic_year": ev.academic_year,
        "term": ev.term,
        "observed_at": ev.observed_at.isoformat(),
        "source_system": ev.source_system,
        "source_reference": ev.source_reference,
    }
    if ev.is_missing_outcome:
        summary["missing_status"] = content.get("status")
        summary["missing_reason"] = content.get("reason")
    if "score" in content and content.get("score") is not None:
        summary["score"] = content.get("score")
        summary["max_score"] = content.get("max_score")
    if "level" in content or "ordinal_level" in content or "rubric_level" in content:
        summary["level"] = (
            content.get("level") or content.get("ordinal_level") or content.get("rubric_level")
        )
    if "value" in content:
        summary["value"] = content.get("value")
        summary["unit"] = content.get("unit")
    if "note" in content or "observation" in content or "reflection" in content:
        summary["text"] = content.get("note") or content.get("observation") or content.get("reflection")
    return summary


def _classify_missing_record(ev: Evidence) -> str:
    content = ev.content if isinstance(ev.content, dict) else dict(ev.content)
    status_val = str(content.get("status") or "").strip().lower()
    source_trace_flag = content.get("source_trace_found")
    src_ref = str(ev.source_reference or "").strip().lower()
    if source_trace_flag is False or src_ref in _UNTRACED_SOURCE_REFS or status_val == "source_not_found":
        return EvidenceAvailabilityStatus.SOURCE_TRACE_NOT_FOUND.value
    if status_val in _NOT_CONDUCTED_STATUSES:
        return EvidenceAvailabilityStatus.ASSESSMENT_NOT_CONDUCTED.value
    return EvidenceAvailabilityStatus.MISSING_RESULT.value


class HandoverService:
    """Coordinates class assignments, permissions, evidence availability, class releases, receipts, responses, and diffs."""

    def __init__(
        self,
        store: SQLiteStore,
        evidence_service: EvidenceService,
        analysis_service: AnalysisService,
    ) -> None:
        self._store = store
        self._evidence_service = evidence_service
        self._analysis_service = analysis_service

    # ── Permissions & Assignments ──────────────────────────────────

    async def get_teacher_learner_access(
        self,
        teacher_id: str,
        learner_id: str,
    ) -> dict[str, Any]:
        """Return teacher permissions for a learner, or raise PermissionError (403)."""
        learner_classes = await self._store.get_learner_classes(learner_id)
        if not learner_classes:
            raise PermissionError(
                f"Teacher '{teacher_id}' does not have class access to learner '{learner_id}'."
            )

        assignments = await self._store.get_teacher_assignments(teacher_id)
        learner_class_ids = {c.class_id for c in learner_classes}
        matching = [a for a in assignments if a.class_id in learner_class_ids]
        if not matching:
            raise PermissionError(
                f"Teacher '{teacher_id}' is not assigned to learner '{learner_id}'."
            )

        is_class_teacher = any(a.role == TeacherRole.CLASS_TEACHER for a in matching)
        allowed_subjects = sorted({a.subject for a in matching if a.subject})
        return {
            "is_class_teacher": is_class_teacher,
            "allowed_subjects": allowed_subjects,
            "class_ids": sorted({a.class_id for a in matching}),
        }

    async def assert_class_access(
        self,
        teacher_id: str,
        class_id: str,
        *,
        require_class_teacher: bool = False,
    ) -> list[TeacherAssignment]:
        """Ensure teacher is assigned to class_id (and optionally as class_teacher)."""
        assignments = [
            a for a in await self._store.get_teacher_assignments(teacher_id) if a.class_id == class_id
        ]
        if not assignments:
            raise PermissionError(
                f"Teacher '{teacher_id}' is not assigned to class '{class_id}'."
            )
        if require_class_teacher and not any(a.role == TeacherRole.CLASS_TEACHER for a in assignments):
            raise PermissionError(
                f"Only the class teacher of '{class_id}' can perform this action."
            )
        return assignments

    async def assert_evidence_access(self, teacher_id: str, ev: Evidence) -> dict[str, Any]:
        """Enforce both class membership and subject scope on a single evidence record."""
        access = await self.get_teacher_learner_access(teacher_id, ev.learner_id)
        if access["is_class_teacher"]:
            return access
        if ev.subject is not None and ev.subject not in access["allowed_subjects"]:
            raise PermissionError(
                f"Teacher '{teacher_id}' cannot access '{ev.subject}' evidence."
            )
        return access

    async def get_permitted_learner_ids(self, teacher_id: str) -> set[str]:
        """Return the set of learner IDs in classes assigned to teacher_id."""
        assignments = await self._store.get_teacher_assignments(teacher_id)
        class_ids = {a.class_id for a in assignments}
        permitted: set[str] = set()
        for cid in class_ids:
            for learner in await self._store.get_class_learners(cid):
                permitted.add(learner.learner_id)
        return permitted

    async def get_required_subjects_for_class(self, class_id: str) -> list[str]:
        """Return ordered required subjects for a class based on subject-teacher assignments."""
        assignments = await self._store.get_class_assignments(class_id)
        ordered_preferred = ["Mathematics", "English", "Science"]
        assigned = {
            a.subject
            for a in assignments
            if a.role == TeacherRole.SUBJECT_TEACHER and a.subject
        }
        result = [s for s in ordered_preferred if s in assigned]
        for s in sorted(assigned):
            if s not in result:
                result.append(s)
        return result

    async def get_required_scopes_for_class(self, class_id: str) -> list[str]:
        return ["student"] + await self.get_required_subjects_for_class(class_id)

    # ── Evidence Availability (Separate from Teacher Review Completion) ─────

    @staticmethod
    def _build_series_groups(
        assessment_records: list[Evidence],
    ) -> tuple[dict[SeriesKey, list[Evidence]], list[Evidence], list[Evidence]]:
        series_groups: dict[SeriesKey, list[Evidence]] = defaultdict(list)
        missing_records: list[Evidence] = []
        insufficient_records: list[Evidence] = []

        for ev in assessment_records:
            content = ev.content if isinstance(ev.content, dict) else dict(ev.content)
            if ev.is_missing_outcome or (
                content.get("score") is None
                and not ev.is_rubric
                and "value" not in content
            ):
                missing_records.append(ev)
                continue

            subj = ev.subject or content.get("subject")
            grade = ev.grade
            skill = ev.measured_skill
            form_val = ev.form
            form_ver = ev.form_version
            lang_val = ev.language

            if not (subj and grade and skill and form_val and form_ver and lang_val and ev.comparison_authorized):
                insufficient_records.append(ev)
                continue

            stage_val = ev.assessment_stage
            if ev.is_marks:
                max_score = content.get("max_score")
                score_val = content.get("score")
                if max_score is None or score_val is None:
                    insufficient_records.append(ev)
                    continue
                try:
                    scale_key = f"max_score:{float(max_score):g}"
                except (ValueError, TypeError):
                    insufficient_records.append(ev)
                    continue
                key = SeriesKey(
                    grade=str(grade),
                    subject=str(subj),
                    measured_skill=str(skill),
                    form=str(form_val),
                    form_version=str(form_ver),
                    language=str(lang_val),
                    measure="marks",
                    scale=scale_key,
                    assessment_stage=str(stage_val) if stage_val else None,
                )
                series_groups[key].append(ev)
            elif ev.is_rubric:
                rubric_name = str(content.get("rubric") or content.get("rubric_name") or "rubric")
                rubric_ver = str(content.get("rubric_version") or content.get("version") or "v1")
                canonical_scale = _canonical_rubric_scale(content)
                if canonical_scale == "unknown":
                    insufficient_records.append(ev)
                    continue
                key = SeriesKey(
                    grade=str(grade),
                    subject=str(subj),
                    measured_skill=str(skill),
                    form=str(form_val),
                    form_version=str(form_ver),
                    language=str(lang_val),
                    measure="rubric",
                    scale=f"rubric:{rubric_name}:{rubric_ver}:{canonical_scale}",
                    assessment_stage=str(stage_val) if stage_val else None,
                )
                series_groups[key].append(ev)
            elif "value" in content and "unit" in content:
                key = SeriesKey(
                    grade=str(grade),
                    subject=str(subj),
                    measured_skill=str(skill),
                    form=str(form_val),
                    form_version=str(form_ver),
                    language=str(lang_val),
                    measure="fluency",
                    scale=f"unit:{content.get('unit')}",
                    assessment_stage=str(stage_val) if stage_val else None,
                )
                series_groups[key].append(ev)
            else:
                insufficient_records.append(ev)

        return series_groups, missing_records, insufficient_records

    async def compute_evidence_availability(
        self,
        learner_id: str,
        scope: str,
    ) -> dict[str, Any]:
        """Determine data sufficiency or explicit gap status separately from review completion."""
        all_records = await self._evidence_service.get_learner_history(learner_id)
        if scope == "student":
            scope_records = [r for r in all_records if r.subject is None]
            available = [_summarize_evidence_item(r) for r in scope_records]
            if not scope_records:
                return {
                    "scope": "student",
                    "status": EvidenceAvailabilityStatus.NO_DATA_AVAILABLE.value,
                    "label": "No data available",
                    "human_message": "No data available. Do not infer why.",
                    "available_count": 0,
                    "required_count": 1,
                    "rule_name": "student_context_record",
                    "unmet_conclusion": "Whole-learner attendance, classroom observation, or self-reflection records are not yet recorded.",
                    "available_results": [],
                    "gap_disclosures": [
                        {
                            "status": EvidenceAvailabilityStatus.NO_DATA_AVAILABLE.value,
                            "description": "No data available for whole-learner context.",
                        }
                    ],
                }
            return {
                "scope": "student",
                "status": EvidenceAvailabilityStatus.SUFFICIENT.value,
                "label": f"Sufficient context — {len(scope_records)} learner-level record(s) available",
                "human_message": f"{len(scope_records)} learner-level record(s) available for Student Review.",
                "available_count": len(scope_records),
                "required_count": 1,
                "rule_name": "student_context_record",
                "unmet_conclusion": None,
                "available_results": available,
                "gap_disclosures": [],
            }

        subject = scope
        scope_records = [r for r in all_records if r.subject == subject]
        if not scope_records:
            return {
                "scope": subject,
                "status": EvidenceAvailabilityStatus.NO_DATA_AVAILABLE.value,
                "label": "No data available",
                "human_message": "No data available. ALLPS has no results and does not know why.",
                "available_count": 0,
                "required_count": 3,
                "rule_name": "across_term_trend",
                "unmet_conclusion": f"No {subject} records exist to support any longitudinal or baseline conclusion.",
                "available_results": [],
                "gap_disclosures": [
                    {
                        "status": EvidenceAvailabilityStatus.NO_DATA_AVAILABLE.value,
                        "description": f"No {subject} data available. Empty records do not establish whether assessments occurred.",
                    }
                ],
            }

        assessment_records = [r for r in scope_records if r.evidence_type.value == "assessment"]
        other_records = [r for r in scope_records if r.evidence_type.value != "assessment"]
        series_groups, missing_records, excluded_records = self._build_series_groups(assessment_records)

        gap_disclosures: list[dict[str, Any]] = []
        primary_missing_status: str | None = None
        for m_ev in missing_records:
            kind = _classify_missing_record(m_ev)
            content = m_ev.content if isinstance(m_ev.content, dict) else dict(m_ev.content)
            reason = content.get("reason")
            if kind == EvidenceAvailabilityStatus.ASSESSMENT_NOT_CONDUCTED.value:
                desc = f"Assessment not conducted (Year {m_ev.academic_year} Term {m_ev.term})"
            elif kind == EvidenceAvailabilityStatus.SOURCE_TRACE_NOT_FOUND.value:
                desc = f"Missing result — source trace not found (Year {m_ev.academic_year} Term {m_ev.term})"
            else:
                desc = f"Missing result (Year {m_ev.academic_year} Term {m_ev.term})"
            if reason:
                desc = f"{desc}: {reason}"
            gap_disclosures.append({
                "status": kind,
                "evidence_id": m_ev.evidence_id,
                "academic_year": m_ev.academic_year,
                "term": m_ev.term,
                "description": desc,
            })
            if primary_missing_status is None:
                primary_missing_status = kind

        if excluded_records:
            gap_disclosures.append({
                "status": EvidenceAvailabilityStatus.INSUFFICIENT_ASSESSMENT_HISTORY.value,
                "evidence_ids": [e.evidence_id for e in excluded_records],
                "description": (
                    f"{len(excluded_records)} assessment record(s) excluded from numerical comparison "
                    "due to incomplete comparison metadata or unauthorized equating."
                ),
            })

        best_series: tuple[SeriesKey, list[Evidence], list[tuple[int, int]], int, str] | None = None
        for key, evs in series_groups.items():
            periods = sorted({(e.academic_year, e.term) for e in evs})
            first_content = evs[0].content if isinstance(evs[0].content, dict) else dict(evs[0].content)
            comparison_rule = str(first_content.get("comparison_rule") or "").lower()
            purpose_val = str(first_content.get("purpose") or "").lower()
            explicit_req = first_content.get("required_assessments")
            if isinstance(explicit_req, int) and explicit_req >= 2:
                req_min = explicit_req
                rule_name = "baseline_change" if req_min == 2 else "across_term_trend"
            elif key.measure != "rubric" and (
                comparison_rule in ("baseline", "baseline_change") or purpose_val == "screening"
            ):
                req_min = 2
                rule_name = "baseline_change"
            else:
                req_min = 3
                rule_name = "across_term_trend"

            rank_tuple = (len(periods) >= req_min, len(periods), -req_min, len(evs))
            if best_series is None or rank_tuple > (
                len(best_series[2]) >= best_series[3],
                len(best_series[2]),
                -best_series[3],
                len(best_series[1]),
            ):
                best_series = (key, evs, periods, req_min, rule_name)

        available_summaries = [_summarize_evidence_item(e) for e in scope_records]

        if best_series is not None:
            key, evs, periods, req_min, rule_name = best_series
            avail_cnt = len(periods)
            preserved_series = [_summarize_evidence_item(e) for e in evs]
            if avail_cnt >= req_min:
                return {
                    "scope": subject,
                    "status": EvidenceAvailabilityStatus.SUFFICIENT.value,
                    "label": f"Sufficient — {avail_cnt} of {req_min} required assessments available",
                    "human_message": f"{avail_cnt} comparable {subject} period assessments available.",
                    "available_count": avail_cnt,
                    "required_count": req_min,
                    "rule_name": rule_name,
                    "unmet_conclusion": None,
                    "available_results": preserved_series + [
                        _summarize_evidence_item(o) for o in other_records
                    ],
                    "gap_disclosures": gap_disclosures,
                }

            unmet = (
                "Whether performance has changed from baseline cannot yet be concluded."
                if rule_name == "baseline_change"
                else "Whether performance is improving, declining, or unchanged over time across terms cannot yet be concluded."
            )
            return {
                "scope": subject,
                "status": EvidenceAvailabilityStatus.INSUFFICIENT_ASSESSMENT_HISTORY.value,
                "label": f"Insufficient assessment history — {avail_cnt} of {req_min} required assessments available",
                "human_message": (
                    f"Not enough results yet. {_num_word(avail_cnt)} of the {_num_word(req_min, lower=True)} "
                    "required assessments are available."
                ),
                "available_count": avail_cnt,
                "required_count": req_min,
                "rule_name": rule_name,
                "unmet_conclusion": unmet,
                "available_results": preserved_series,
                "gap_disclosures": gap_disclosures,
            }

        # Zero comparable assessment periods: surface exact missing status if recorded, else insufficient / no data
        if primary_missing_status == EvidenceAvailabilityStatus.ASSESSMENT_NOT_CONDUCTED.value:
            return {
                "scope": subject,
                "status": EvidenceAvailabilityStatus.ASSESSMENT_NOT_CONDUCTED.value,
                "label": "Assessment not conducted",
                "human_message": "Assessment not done: The records say it did not take place.",
                "available_count": 0,
                "required_count": 3,
                "rule_name": "across_term_trend",
                "unmet_conclusion": "The assessment was not conducted; teacher reviews this gap disclosure rather than inventing a score.",
                "available_results": available_summaries,
                "gap_disclosures": gap_disclosures,
            }
        if primary_missing_status == EvidenceAvailabilityStatus.SOURCE_TRACE_NOT_FOUND.value:
            return {
                "scope": subject,
                "status": EvidenceAvailabilityStatus.SOURCE_TRACE_NOT_FOUND.value,
                "label": "Missing result — source trace not found",
                "human_message": "Source not found: ALLPS cannot trace the expected result to a source record.",
                "available_count": 0,
                "required_count": 3,
                "rule_name": "across_term_trend",
                "unmet_conclusion": "Expected assessment result could not be traced to a verified source record.",
                "available_results": available_summaries,
                "gap_disclosures": gap_disclosures,
            }
        if primary_missing_status == EvidenceAvailabilityStatus.MISSING_RESULT.value:
            return {
                "scope": subject,
                "status": EvidenceAvailabilityStatus.MISSING_RESULT.value,
                "label": "Missing result",
                "human_message": "Missing result: A result is expected, but it cannot be found.",
                "available_count": 0,
                "required_count": 3,
                "rule_name": "across_term_trend",
                "unmet_conclusion": "Expected assessment result is missing; teacher checks whether the gap is accurately described.",
                "available_results": available_summaries,
                "gap_disclosures": gap_disclosures,
            }

        # Only non-assessment observations or excluded records exist
        return {
            "scope": subject,
            "status": EvidenceAvailabilityStatus.INSUFFICIENT_ASSESSMENT_HISTORY.value,
            "label": "Insufficient assessment history — 0 of 3 required assessments available",
            "human_message": "Not enough results yet. Zero of the three required assessments are available.",
            "available_count": 0,
            "required_count": 3,
            "rule_name": "across_term_trend",
            "unmet_conclusion": "Whether performance is improving, declining, or unchanged over time cannot be concluded without comparable assessments.",
            "available_results": available_summaries,
            "gap_disclosures": gap_disclosures,
        }

    # ── Pending Candidate Review Helpers & Signatures ───────────────

    async def _pending_review_count_for_scope(
        self,
        learner_id: str,
        scope: str,
        all_subjects: list[str],
    ) -> int:
        if scope == "student":
            return 0
        patterns = await self._store.get_patterns_for_learner(learner_id)
        pending_count = 0
        for p in patterns:
            subj = _extract_pattern_subject(p.summary, all_subjects)
            if subj == scope:
                revs = await self._store.get_review_items_for_pattern(p.pattern_id)
                pending_count += sum(1 for r in revs if r.status == ReviewStatus.PENDING)
        return pending_count

    async def _compute_scope_fingerprints_and_signature(
        self,
        learner_id: str,
        scope: str,
        availability: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, Any]]:
        all_records = await self._evidence_service.get_learner_history(learner_id)
        if scope == "student":
            scope_records = [r for r in all_records if r.subject is None]
        else:
            scope_records = [r for r in all_records if r.subject == scope]

        fingerprints = {r.evidence_id: r.canonical_fingerprint for r in scope_records}

        if scope == "student":
            return fingerprints, {
                "scope": "student",
                "availability_status": availability["status"],
                "record_count": len(scope_records),
                "primary_direction": "context",
                "primary_summary": availability["human_message"],
                "series": [],
                "missing_records": [],
                "latest_results": [_summarize_evidence_item(r) for r in scope_records],
            }

        patterns = await self._analysis_service.analyse_longitudinal_pattern(
            learner_id,
            subject=scope,
            persist_findings=False,
        )
        primary_pat = patterns[0] if patterns else {}
        primary_direction = _extract_direction(primary_pat) if primary_pat else "insufficient"

        assessment_records = [r for r in scope_records if r.evidence_type.value == "assessment"]
        series_groups, missing_records, excluded_records = self._build_series_groups(assessment_records)

        series_sigs: list[dict[str, Any]] = []
        series_directions: dict[str, str] = {}
        comparable_series_by_eid: dict[str, str] = {}
        for key, evs in sorted(series_groups.items(), key=lambda kv: (kv[0].subject, kv[0].measured_skill, kv[0].form)):
            period_points = []
            by_period: dict[tuple[int, int], list[Evidence]] = defaultdict(list)
            series_id = f"{key.measure}|{key.scale}|{key.measured_skill}|{key.form}|{key.form_version}|{key.language}"
            for ev in sorted(evs, key=lambda e: (e.academic_year, e.term, e.observed_at)):
                by_period[(ev.academic_year, ev.term)].append(ev)
                comparable_series_by_eid[ev.evidence_id] = series_id
                c = ev.content if isinstance(ev.content, dict) else dict(ev.content)
                period_points.append({
                    "evidence_id": ev.evidence_id,
                    "academic_year": ev.academic_year,
                    "term": ev.term,
                    "score": c.get("score"),
                    "max_score": c.get("max_score"),
                    "level": c.get("level") or c.get("ordinal_level") or c.get("rubric_level"),
                    "rubric_rank": _get_rubric_rank(c)[0] if ev.is_rubric else None,
                    "value": c.get("value"),
                    "unit": c.get("unit"),
                })

            sorted_p = sorted(by_period.keys())
            if len(sorted_p) < 3:
                s_dir = "insufficient"
            else:
                vals: list[float] = []
                invalid_p = False
                for p in sorted_p:
                    pevs = by_period[p]
                    if key.measure == "marks":
                        vals.append(sum(float(e.content["score"]) for e in pevs) / len(pevs))
                    elif key.measure == "fluency":
                        vals.append(sum(float(e.content["value"]) for e in pevs) / len(pevs))
                    else:
                        ranks = [_get_rubric_rank(e.content)[0] for e in pevs]
                        if any(r is None for r in ranks) or len(set(ranks)) != 1:
                            invalid_p = True
                            break
                        assert ranks[0] is not None
                        vals.append(ranks[0])
                if invalid_p:
                    s_dir = "conflicting"
                elif all(v == vals[0] for v in vals):
                    s_dir = "unchanged"
                elif all(a < b for a, b in zip(vals, vals[1:])):
                    s_dir = "improving"
                elif all(a > b for a, b in zip(vals, vals[1:])):
                    s_dir = "declining"
                else:
                    s_dir = "variable"

            series_directions[series_id] = s_dir
            series_sigs.append({
                "series_id": series_id,
                "direction": s_dir,
                "measure": key.measure,
                "scale": key.scale,
                "skill": key.measured_skill,
                "points": period_points,
            })

        return fingerprints, {
            "scope": scope,
            "availability_status": availability["status"],
            "record_count": len(scope_records),
            "assessment_count": len(assessment_records),
            "primary_pattern_type": primary_pat.get("pattern_type"),
            "primary_direction": primary_direction,
            "primary_summary": primary_pat.get("summary") or availability["human_message"],
            "series_directions": series_directions,
            "comparable_series_by_eid": comparable_series_by_eid,
            "excluded_evidence_ids": [e.evidence_id for e in excluded_records],
            "series": series_sigs,
            "missing_records": [
                {
                    "evidence_id": m.evidence_id,
                    "kind": _classify_missing_record(m),
                    "academic_year": m.academic_year,
                    "term": m.term,
                }
                for m in missing_records
            ],
            "latest_results": [_summarize_evidence_item(r) for r in scope_records],
        }

    # ── Class Readiness & Section Review Authoring ─────────────────

    async def get_class_readiness(self, class_id: str) -> dict[str, Any]:
        """Compute separated evidence availability and teacher review completion across the class."""
        school_class = await self._store.get_class(class_id)
        if school_class is None:
            raise KeyError(f"Class '{class_id}' does not exist.")

        learners = await self._store.get_class_learners(class_id)
        required_subjects = await self.get_required_subjects_for_class(class_id)
        required_scopes = ["student"] + required_subjects
        existing_sections = {
            (sr.learner_id, sr.scope): sr
            for sr in await self._store.get_section_reviews_for_class(class_id)
        }

        blocking_reasons: list[str] = []
        learner_rows: list[dict[str, Any]] = []
        if not learners:
            blocking_reasons.append("No learners enrolled in this class.")

        for learner in learners:
            slots: dict[str, Any] = {}
            learner_ready = True
            for scope in required_scopes:
                availability = await self.compute_evidence_availability(learner.learner_id, scope)
                section = existing_sections.get((learner.learner_id, scope))
                pending_findings = await self._pending_review_count_for_scope(
                    learner.learner_id, scope, required_subjects
                )
                review_state = (
                    section.review_state.value
                    if section is not None
                    else SectionReviewState.NOT_REVIEWED.value
                )
                label_title = "Student Review" if scope == "student" else f"{scope} Review"

                slot_blocked_reasons: list[str] = []
                if review_state not in (
                    SectionReviewState.READY_FOR_RELEASE.value,
                    SectionReviewState.REVIEWED_INCOMPLETE.value,
                ):
                    slot_blocked_reasons.append(f"{label_title} state is '{review_state}'.")
                if pending_findings > 0:
                    slot_blocked_reasons.append(
                        f"{pending_findings} pending candidate finding(s) in {scope}."
                    )
                if section is None or not (section.approved_summary or "").strip():
                    if review_state in (
                        SectionReviewState.READY_FOR_RELEASE.value,
                        SectionReviewState.REVIEWED_INCOMPLETE.value,
                    ):
                        slot_blocked_reasons.append(f"{label_title} needs an approved summary.")

                if slot_blocked_reasons:
                    learner_ready = False
                    blocking_reasons.extend(
                        f"{learner.display_name} ({learner.learner_id}): {msg}"
                        for msg in slot_blocked_reasons
                    )

                slots[scope] = {
                    "scope": scope,
                    "title": label_title,
                    "review_state": review_state,
                    "evidence_availability": availability,
                    "pending_findings_count": pending_findings,
                    "approved_summary": section.approved_summary if section else None,
                    "teacher_notes": section.teacher_notes if section else None,
                    "missing_evidence_disclosure": (
                        section.missing_evidence_disclosure if section else None
                    ),
                    "citations": list(section.citations) if section else [],
                    "reviewed_by": section.reviewed_by if section else None,
                    "reviewed_at": section.reviewed_at.isoformat() if section and section.reviewed_at else None,
                    "is_release_ready": len(slot_blocked_reasons) == 0,
                    "blocking_reasons": slot_blocked_reasons,
                }

            learner_rows.append({
                "learner_id": learner.learner_id,
                "display_name": learner.display_name,
                "is_release_ready": learner_ready,
                "slots": slots,
            })

        latest_release = await self._store.get_latest_class_release(class_id)
        return {
            "school_class": school_class.model_dump(mode="json"),
            "required_subjects": required_subjects,
            "required_scopes": required_scopes,
            "learners": learner_rows,
            "can_release": bool(learners) and len(blocking_reasons) == 0,
            "blocking_reasons": blocking_reasons,
            "latest_release": latest_release.model_dump(mode="json") if latest_release else None,
        }

    async def update_section_review(
        self,
        *,
        class_id: str,
        learner_id: str,
        scope: str,
        teacher_id: str,
        review_state: str,
        approved_summary: str | None = None,
        teacher_notes: str | None = None,
        missing_evidence_disclosure: str | None = None,
        citations: list[str] | None = None,
    ) -> dict[str, Any]:
        """Author or update a learner's Student Review or Subject Review readiness state."""
        await self.assert_class_access(teacher_id, class_id, require_class_teacher=True)

        class_learners = {l.learner_id for l in await self._store.get_class_learners(class_id)}
        if learner_id not in class_learners:
            raise ValueError(f"Learner '{learner_id}' is not enrolled in class '{class_id}'.")

        required_scopes = await self.get_required_scopes_for_class(class_id)
        if scope not in required_scopes:
            raise ValueError(
                f"Invalid scope '{scope}' for class '{class_id}'. Expected one of {required_scopes}."
            )

        state_enum = SectionReviewState(review_state)
        clean_summary = approved_summary.strip() if isinstance(approved_summary, str) and approved_summary.strip() else None
        clean_notes = teacher_notes.strip() if isinstance(teacher_notes, str) and teacher_notes.strip() else None
        clean_disclosure = (
            missing_evidence_disclosure.strip()
            if isinstance(missing_evidence_disclosure, str) and missing_evidence_disclosure.strip()
            else None
        )

        for field_name, val in (
            ("approved_summary", clean_summary),
            ("teacher_notes", clean_notes),
            ("missing_evidence_disclosure", clean_disclosure),
        ):
            if val:
                validate_text_for_prohibited_labels(val, field_name=field_name)

        clean_citations = [str(c).strip() for c in (citations or []) if str(c).strip()]
        if clean_citations:
            ev_map = await self._store.get_evidence_by_ids(clean_citations)
            for cid in clean_citations:
                cited_ev = ev_map.get(cid)
                if cited_ev is None:
                    raise ValueError(f"Cited evidence '{cid}' does not exist.")
                if cited_ev.learner_id != learner_id:
                    raise ValueError(
                        f"Cited evidence '{cid}' belongs to learner '{cited_ev.learner_id}', not '{learner_id}'."
                    )
                if scope == "student" and cited_ev.subject is not None:
                    raise ValueError(
                        f"Student Review cannot cite subject-specific evidence '{cid}' ({cited_ev.subject}); "
                        f"cite it in the {cited_ev.subject} Review."
                    )
                if scope != "student" and cited_ev.subject != scope:
                    raise ValueError(
                        f"{scope} Review cannot cite evidence '{cid}' belonging to subject '{cited_ev.subject}'."
                    )

        if scope == "student" and clean_summary:
            if _SUBJECT_TRAJECTORY_RE.search(clean_summary):
                raise ValueError(
                    "Student Review must summarize cross-learner context and must not contain subject score tables or mark trajectories."
                )
            subjects = await self.get_required_subjects_for_class(class_id)
            lowered = clean_summary.lower()
            for subj in subjects:
                if f"{subj.lower()}:" in lowered or f"{subj.lower()} marks" in lowered or f"{subj.lower()} score" in lowered:
                    raise ValueError(
                        f"Student Review cannot embed subject-specific score sections ('{subj}'). Put subject scores in the {subj} Review."
                    )

        availability = await self.compute_evidence_availability(learner_id, scope)
        pending_count = await self._pending_review_count_for_scope(
            learner_id, scope, await self.get_required_subjects_for_class(class_id)
        )
        if state_enum in (SectionReviewState.READY_FOR_RELEASE, SectionReviewState.REVIEWED_INCOMPLETE):
            if pending_count > 0:
                raise ValueError(
                    f"Cannot mark {scope} ready while {pending_count} pending candidate finding(s) remain unresolved."
                )
            if not clean_summary:
                raise ValueError("Marking a section ready or reviewed-incomplete requires an approved_summary.")
            if state_enum == SectionReviewState.REVIEWED_INCOMPLETE and not clean_disclosure:
                if availability["status"] != EvidenceAvailabilityStatus.SUFFICIENT.value:
                    clean_disclosure = availability["human_message"]
                else:
                    raise ValueError(
                        "Section marked 'reviewed_incomplete' requires a clear missing_evidence_disclosure."
                    )

        now = datetime.now(timezone.utc)
        section = SectionReview(
            class_id=class_id,
            learner_id=learner_id,
            scope=scope,
            review_state=state_enum,
            approved_summary=clean_summary,
            teacher_notes=clean_notes,
            missing_evidence_disclosure=clean_disclosure,
            citations=tuple(clean_citations),
            reviewed_by=teacher_id,
            reviewed_at=now if state_enum != SectionReviewState.NOT_REVIEWED else None,
            updated_at=now,
        )
        saved = await self._store.upsert_section_review(section)
        await self._store.add_audit_entry(
            entry=self._make_audit(
                tool_name="section_review_updated",
                input_summary={
                    "class_id": class_id,
                    "learner_id": learner_id,
                    "scope": scope,
                    "review_state": state_enum.value,
                    "reviewed_by": teacher_id,
                },
                output_reference=saved.section_review_id,
                approval_state=state_enum.value,
            )
        )
        return {
            **saved.model_dump(mode="json"),
            "evidence_availability": availability,
        }

    # ── Class Release (Immutable Snapshot) ─────────────────────────

    async def release_class(
        self,
        *,
        class_id: str,
        teacher_id: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Freeze and publish an immutable versioned handover for every learner and subject in class_id."""
        await self.assert_class_access(teacher_id, class_id, require_class_teacher=True)
        readiness = await self.get_class_readiness(class_id)
        if not readiness["can_release"]:
            raise ValueError(
                "Class is not ready for release: " + "; ".join(readiness["blocking_reasons"])
            )

        teacher = await self._store.get_teacher(teacher_id)
        teacher_name = teacher["display_name"] if teacher else teacher_id
        latest = await self._store.get_latest_class_release(class_id)
        version_number = (latest.version_number + 1) if latest else 1
        release_id = str(uuid.uuid4())
        released_at = datetime.now(timezone.utc)

        required_subjects = list(readiness["required_subjects"])
        required_scopes = list(readiness["required_scopes"])
        learner_ids = [row["learner_id"] for row in readiness["learners"]]

        assignments = await self._store.get_class_assignments(class_id)
        subject_teachers = [
            a for a in assignments if a.role == TeacherRole.SUBJECT_TEACHER and a.subject
        ]
        teacher_names: dict[str, str] = {}
        for a in assignments:
            t_row = await self._store.get_teacher(a.teacher_id)
            teacher_names[a.teacher_id] = t_row["display_name"] if t_row else a.teacher_id

        published_sections: list[PublishedReportSection] = []
        initial_receipts: list[ReportReceipt] = []

        for l_row in readiness["learners"]:
            lid = l_row["learner_id"]
            for scope in required_scopes:
                slot = l_row["slots"][scope]
                section = await self._store.get_section_review(class_id, lid, scope)
                assert section is not None
                fps, sig = await self._compute_scope_fingerprints_and_signature(
                    lid, scope, slot["evidence_availability"]
                )
                approver_id = section.reviewed_by or teacher_id
                approver_row = await self._store.get_teacher(approver_id)
                approver_name = approver_row["display_name"] if approver_row else approver_id
                published_sections.append(
                    PublishedReportSection(
                        release_id=release_id,
                        class_id=class_id,
                        learner_id=lid,
                        scope=scope,
                        section_title=slot["title"],
                        review_state=section.review_state,
                        evidence_availability=slot["evidence_availability"],
                        approved_summary=section.approved_summary or "",
                        teacher_notes=section.teacher_notes,
                        missing_evidence_disclosure=section.missing_evidence_disclosure,
                        citations=section.citations,
                        evidence_fingerprints=fps,
                        analysis_signature=sig,
                        approved_by=approver_id,
                        approved_by_name=approver_name,
                        approved_at=section.reviewed_at or released_at,
                        released_by=teacher_id,
                        released_at=released_at,
                    )
                )

            for st in subject_teachers:
                initial_receipts.append(
                    ReportReceipt(
                        release_id=release_id,
                        class_id=class_id,
                        learner_id=lid,
                        teacher_id=st.teacher_id,
                        teacher_name=teacher_names.get(st.teacher_id, st.teacher_id),
                        subject=st.subject,
                        status=ReceiptStatus.NOT_VIEWED,
                    )
                )

        release = ClassRelease(
            release_id=release_id,
            class_id=class_id,
            version_number=version_number,
            released_by=teacher_id,
            released_by_name=teacher_name,
            released_at=released_at,
            frozen_enrollment=tuple(learner_ids),
            frozen_subjects=tuple(required_subjects),
            notes=notes.strip() if notes and notes.strip() else None,
        )
        await self._store.create_class_release(release, published_sections, initial_receipts)
        await self._store.mark_changes_superseded(
            class_id=class_id,
            superseded_by_release_id=release_id,
            superseded_version_number=version_number,
        )
        await self._store.add_audit_entry(
            entry=self._make_audit(
                tool_name="class_release_published",
                input_summary={
                    "class_id": class_id,
                    "release_id": release_id,
                    "version_number": version_number,
                    "released_by": teacher_id,
                    "learner_count": len(learner_ids),
                },
                output_reference=release_id,
                approval_state="released",
            )
        )
        return {
            "release": release.model_dump(mode="json"),
            "published_sections_count": len(published_sections),
        }

    # ── Post-Release Diff Detection & 5-Step Progress Lifecycle ──────

    async def evaluate_post_release_changes_for_learner(
        self,
        learner_id: str,
    ) -> list[PostReleaseChange]:
        """Compare live evidence against latest published sections to record minor/major changes without altering the frozen release."""
        release, sections = await self._store.get_published_sections_for_learner(learner_id)
        if release is None or not sections:
            return []

        for sec in sections:
            availability = await self.compute_evidence_availability(learner_id, sec.scope)
            current_fps, current_sig = await self._compute_scope_fingerprints_and_signature(
                learner_id, sec.scope, availability
            )
            published_fps: dict[str, str] = sec.evidence_fingerprints or {}
            new_eids = [eid for eid in current_fps if eid not in published_fps]
            if not new_eids:
                continue

            all_scope_records = [
                e
                for e in await self._evidence_service.get_learner_history(learner_id)
                if (e.subject is None if sec.scope == "student" else e.subject == sec.scope)
            ]
            new_records = [e for e in all_scope_records if e.evidence_id in set(new_eids)]
            earlier_records = [e for e in all_scope_records if e.evidence_id in set(published_fps.keys())]

            pub_sig = sec.analysis_signature or {}
            pub_dir = str(pub_sig.get("primary_direction") or "insufficient")
            cur_dir = str(current_sig.get("primary_direction") or "insufficient")
            pub_avail = str(pub_sig.get("availability_status") or "")
            cur_avail = str(current_sig.get("availability_status") or "")

            has_new_missing_trace = any(
                e.is_missing_outcome
                and _classify_missing_record(e) == EvidenceAvailabilityStatus.SOURCE_TRACE_NOT_FOUND.value
                for e in new_records
            )
            excluded_eids = set(current_sig.get("excluded_evidence_ids") or [])
            comp_series_by_eid: dict[str, str] = current_sig.get("comparable_series_by_eid") or {}
            pub_series_dirs: dict[str, str] = pub_sig.get("series_directions") or {}
            cur_series_dirs: dict[str, str] = current_sig.get("series_directions") or {}

            has_uncertain_assessment = False
            for nr in new_records:
                if nr.evidence_type.value != "assessment":
                    continue
                if nr.is_missing_outcome or not nr.comparison_authorized or nr.evidence_id in excluded_eids:
                    has_uncertain_assessment = True
                    break
                nr_series = comp_series_by_eid.get(nr.evidence_id)
                if not nr_series or nr_series not in pub_series_dirs:
                    has_uncertain_assessment = True
                    break
                if cur_series_dirs.get(nr_series) in ("insufficient", "variable", "conflicting"):
                    has_uncertain_assessment = True
                    break

            has_new_contradiction = False
            for s_id, prev_sdir in pub_series_dirs.items():
                curr_sdir = cur_series_dirs.get(s_id)
                if curr_sdir and curr_sdir != prev_sdir:
                    if not (prev_sdir == "insufficient" and curr_sdir in ("improving", "unchanged")):
                        has_new_contradiction = True
                        pub_dir = prev_sdir
                        cur_dir = curr_sdir
                        break

            if not has_new_contradiction:
                if has_uncertain_assessment or has_new_missing_trace:
                    has_new_contradiction = True
                elif cur_dir in ("variable", "declining", "conflicting") and pub_dir in ("improving", "unchanged"):
                    has_new_contradiction = True
                elif pub_dir != cur_dir and not (
                    pub_avail == EvidenceAvailabilityStatus.INSUFFICIENT_ASSESSMENT_HISTORY.value
                    and cur_dir in ("improving", "unchanged")
                ):
                    if cur_dir != "observed" and pub_dir != "observed":
                        has_new_contradiction = True
                else:
                    # Also detect observational / reflection divergence if text explicitly contradicts strong published score trend
                    for nr in new_records:
                        if nr.evidence_type.value in ("observation", "reflection") and pub_dir in ("improving", "unchanged"):
                            c = nr.content if isinstance(nr.content, dict) else dict(nr.content)
                            text_val = str(c.get("note") or c.get("observation") or c.get("reflection") or "").lower()
                            if any(tok in text_val for tok in ("struggling", "withdrawn", "stopped", "unable", "disagree", "declined")):
                                has_new_contradiction = True
                                break

            if has_new_contradiction:
                severity = DiffSeverity.MAJOR
                if has_uncertain_assessment:
                    headline = "Important change: New uncalibrated or non-comparable evidence requires class-teacher review."
                    why_it_matters = (
                        "One or more new assessment records lack comparison authorization or do not match the published "
                        "assessment series; ALLPS cannot claim they confirm the published finding."
                    )
                    explanation = (
                        f"New evidence ({len(new_records)} record(s)) in {sec.section_title} cannot be automatically "
                        "equated with the published series and requires class-teacher review."
                    )
                else:
                    headline = "Important change: New results disagree with the published finding. Class-teacher review needed."
                    why_it_matters = (
                        f"Published conclusion indicated '{pub_dir}' ({pub_sig.get('primary_summary')}), "
                        f"whereas updated evidence shifts the finding to '{cur_dir}' ({current_sig.get('primary_summary')})."
                    )
                    explanation = (
                        f"New evidence ({len(new_records)} record(s)) changes the published conclusion in {sec.section_title}: "
                        f"earlier direction '{pub_dir}' now evaluates as '{cur_dir}'."
                    )
                why_small = None
            else:
                severity = DiffSeverity.MINOR
                headline = "Small update: One more comparable assessment is available. It supports the earlier finding."
                if len(new_records) != 1 or new_records[0].evidence_type.value != "assessment":
                    headline = "Small update: Additional comparable evidence is available. It supports the earlier finding."
                explanation = "One additional comparable result; direction unchanged."
                why_it_matters = "Longitudinal conclusion and direction remain consistent with the published review."
                why_small = f"Published finding direction ('{pub_dir}') matches updated evaluation ('{cur_dir}')."

            comparison = {
                "earlier_results": [_summarize_evidence_item(e) for e in earlier_records],
                "new_results": [_summarize_evidence_item(e) for e in new_records],
                "published_conclusion": sec.approved_summary,
                "published_analysis_summary": pub_sig.get("primary_summary"),
                "current_conclusion": current_sig.get("primary_summary"),
                "published_direction": pub_dir,
                "current_direction": cur_dir,
                "why_small": why_small,
                "why_it_matters": why_it_matters,
            }

            change = PostReleaseChange(
                release_id=release.release_id,
                class_id=release.class_id,
                learner_id=learner_id,
                scope=sec.scope,
                severity=severity,
                headline=headline,
                explanation=explanation,
                why_it_matters=why_it_matters,
                comparison=comparison,
                new_evidence_ids=tuple(e.evidence_id for e in new_records),
            )
            await self._store.upsert_post_release_change(change)

        return await self._store.get_post_release_changes(release_id=release.release_id, learner_id=learner_id)

    def _serialize_change(
        self,
        ch: PostReleaseChange,
        *,
        subject_teacher_name: str | None = None,
        class_teacher_name: str | None = None,
    ) -> dict[str, Any]:
        if ch.superseded_by_release_id is not None:
            progress_status = ChangeProgressStatus.NEW_VERSION_RELEASED.value
            progress_label = f"New version released (v{ch.superseded_version_number})"
        elif ch.reviewed_at is not None:
            progress_status = ChangeProgressStatus.REVIEWED_BY_CLASS_TEACHER.value
            progress_label = f"Reviewed by {ch.reviewed_by_name or class_teacher_name or 'Class teacher'}"
        elif ch.response_added_at is not None:
            progress_status = ChangeProgressStatus.RESPONSE_ADDED.value
            progress_label = "Response added"
        elif ch.opened_at is not None:
            progress_status = ChangeProgressStatus.OPENED.value
            progress_label = f"Opened by {ch.opened_by_name or subject_teacher_name or 'Subject teacher'}"
        else:
            progress_status = ChangeProgressStatus.NOT_OPENED.value
            progress_label = "Not opened"

        steps = [
            {
                "key": ChangeProgressStatus.NOT_OPENED.value,
                "label": "Not opened",
                "completed": True,
                "current": progress_status == ChangeProgressStatus.NOT_OPENED.value,
                "timestamp": ch.created_at.isoformat(),
            },
            {
                "key": ChangeProgressStatus.OPENED.value,
                "label": f"Opened by {ch.opened_by_name or subject_teacher_name or 'Subject teacher'}",
                "completed": ch.opened_at is not None,
                "current": progress_status == ChangeProgressStatus.OPENED.value,
                "timestamp": ch.opened_at.isoformat() if ch.opened_at else None,
            },
            {
                "key": ChangeProgressStatus.RESPONSE_ADDED.value,
                "label": "Response added",
                "completed": ch.response_added_at is not None,
                "current": progress_status == ChangeProgressStatus.RESPONSE_ADDED.value,
                "timestamp": ch.response_added_at.isoformat() if ch.response_added_at else None,
            },
            {
                "key": ChangeProgressStatus.REVIEWED_BY_CLASS_TEACHER.value,
                "label": f"Reviewed by {ch.reviewed_by_name or class_teacher_name or 'Class teacher'}",
                "completed": ch.reviewed_at is not None,
                "current": progress_status == ChangeProgressStatus.REVIEWED_BY_CLASS_TEACHER.value,
                "timestamp": ch.reviewed_at.isoformat() if ch.reviewed_at else None,
            },
            {
                "key": ChangeProgressStatus.NEW_VERSION_RELEASED.value,
                "label": "New version released",
                "completed": ch.superseded_by_release_id is not None,
                "current": progress_status == ChangeProgressStatus.NEW_VERSION_RELEASED.value,
                "timestamp": None,
            },
        ]

        return {
            **ch.model_dump(mode="json"),
            "progress_status": progress_status,
            "progress_label": progress_label,
            "progress_steps": steps,
        }

    # ── Accountability (Viewing History vs. Acknowledgment) & Responses ────

    async def record_report_view(
        self,
        *,
        release_id: str,
        learner_id: str,
        teacher_id: str,
        scope: str | None = None,
    ) -> dict[str, Any]:
        """Record access to a published learner report, preserving full viewing history without marking acknowledged."""
        release = await self._store.get_class_release(release_id)
        if release is None:
            raise KeyError(f"Release '{release_id}' not found.")
        access = await self.get_teacher_learner_access(teacher_id, learner_id)
        teacher = await self._store.get_teacher(teacher_id)
        teacher_name = teacher["display_name"] if teacher else teacher_id

        allowed_scopes = (
            await self.get_required_scopes_for_class(release.class_id)
            if access["is_class_teacher"]
            else ["student"] + access["allowed_subjects"]
        )
        target_scope = scope or (
            access["allowed_subjects"][0]
            if (not access["is_class_teacher"] and access["allowed_subjects"])
            else "student"
        )
        if target_scope not in allowed_scopes:
            raise PermissionError(f"Teacher '{teacher_id}' cannot view scope '{target_scope}'.")

        subject_for_receipt = (
            access["allowed_subjects"][0]
            if (not access["is_class_teacher"] and access["allowed_subjects"])
            else None
        )
        event, receipt = await self._store.record_report_view_event(
            ReportViewEvent(
                release_id=release_id,
                class_id=release.class_id,
                learner_id=learner_id,
                scope=target_scope,
                teacher_id=teacher_id,
                teacher_name=teacher_name,
            ),
            subject=subject_for_receipt,
        )

        # Advance active post-release change to Opened if subject teacher opened it
        if not access["is_class_teacher"]:
            for subj in access["allowed_subjects"]:
                await self._store.mark_change_opened(
                    release_id=release_id,
                    learner_id=learner_id,
                    scope=subj,
                    teacher_id=teacher_id,
                    teacher_name=teacher_name,
                    opened_at=event.viewed_at,
                )

        return {
            "view_event": event.model_dump(mode="json"),
            "receipt": receipt.model_dump(mode="json"),
        }

    async def acknowledge_report(
        self,
        *,
        release_id: str,
        learner_id: str,
        teacher_id: str,
    ) -> dict[str, Any]:
        """Explicitly acknowledge receipt of a released report separately from viewing."""
        release = await self._store.get_class_release(release_id)
        if release is None:
            raise KeyError(f"Release '{release_id}' not found.")
        access = await self.get_teacher_learner_access(teacher_id, learner_id)
        teacher = await self._store.get_teacher(teacher_id)
        teacher_name = teacher["display_name"] if teacher else teacher_id
        subject = access["allowed_subjects"][0] if access["allowed_subjects"] else None

        receipt = await self._store.acknowledge_report_receipt(
            release_id=release_id,
            class_id=release.class_id,
            learner_id=learner_id,
            teacher_id=teacher_id,
            teacher_name=teacher_name,
            subject=subject,
        )
        await self._store.add_audit_entry(
            self._make_audit(
                tool_name="report_acknowledged",
                input_summary={
                    "release_id": release_id,
                    "learner_id": learner_id,
                    "teacher_id": teacher_id,
                    "subject": subject,
                },
                output_reference=receipt.receipt_id,
                approval_state="acknowledged",
            )
        )
        return receipt.model_dump(mode="json")

    async def add_subject_response(
        self,
        *,
        release_id: str,
        learner_id: str,
        subject: str,
        teacher_id: str,
        response_type: str,
        content: str,
        related_change_id: str | None = None,
    ) -> dict[str, Any]:
        """Attach an attributed SubjectResponse child card beneath a frozen Subject Review."""
        release = await self._store.get_class_release(release_id)
        if release is None:
            raise KeyError(f"Release '{release_id}' not found.")
        access = await self.get_teacher_learner_access(teacher_id, learner_id)
        if subject not in access["allowed_subjects"]:
            raise PermissionError(
                f"Teacher '{teacher_id}' is not assigned as the '{subject}' subject teacher for learner '{learner_id}'."
            )

        clean_content = content.strip()
        validate_text_for_prohibited_labels(clean_content, field_name="content")

        sections = await self._store.get_published_sections_for_release(release_id, learner_id=learner_id)
        target_section = next((s for s in sections if s.scope == subject), None)
        if target_section is None:
            raise ValueError(f"Published '{subject}' review section not found in release '{release_id}'.")

        teacher = await self._store.get_teacher(teacher_id)
        teacher_name = teacher["display_name"] if teacher else teacher_id

        response = SubjectResponse(
            release_id=release_id,
            published_section_id=target_section.published_section_id,
            class_id=release.class_id,
            learner_id=learner_id,
            subject=subject,
            teacher_id=teacher_id,
            teacher_name=teacher_name,
            response_type=SubjectResponseType(response_type),
            content=clean_content,
            related_change_id=related_change_id,
        )
        saved = await self._store.add_subject_response(response)
        await self._store.mark_change_response_added(
            release_id=release_id,
            learner_id=learner_id,
            scope=subject,
            response_id=saved.response_id,
            teacher_name=teacher_name,
            added_at=saved.created_at,
        )
        await self._store.add_audit_entry(
            self._make_audit(
                tool_name="subject_response_added",
                input_summary={
                    "release_id": release_id,
                    "learner_id": learner_id,
                    "subject": subject,
                    "teacher_id": teacher_id,
                    "response_type": response.response_type.value,
                },
                output_reference=saved.response_id,
                approval_state="response_added",
            )
        )
        return saved.model_dump(mode="json")

    async def mark_change_reviewed(
        self,
        *,
        class_id: str,
        change_id: str,
        teacher_id: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Allow the class teacher to record that they reviewed a post-release change item."""
        await self.assert_class_access(teacher_id, class_id, require_class_teacher=True)
        existing = await self._store.get_post_release_change_by_id(change_id)
        if existing is None or existing.class_id != class_id:
            raise KeyError(f"Change '{change_id}' not found in class '{class_id}'.")

        clean_notes = notes.strip() if notes and notes.strip() else None
        if clean_notes:
            validate_text_for_prohibited_labels(clean_notes, field_name="notes")

        teacher = await self._store.get_teacher(teacher_id)
        teacher_name = teacher["display_name"] if teacher else teacher_id
        updated = await self._store.mark_change_reviewed(
            change_id=change_id,
            teacher_id=teacher_id,
            teacher_name=teacher_name,
            notes=clean_notes,
        )
        assert updated is not None
        return self._serialize_change(updated, class_teacher_name=teacher_name)

    # ── Scoped Published Report Assembly ───────────────────────────

    async def get_learner_published_handover_view(
        self,
        learner_id: str,
        teacher_id: str,
    ) -> dict[str, Any]:
        """Return role-scoped frozen Student/Subject Reviews, accountability receipts, child responses, and post-release updates."""
        access = await self.get_teacher_learner_access(teacher_id, learner_id)
        release, all_sections = await self._store.get_published_sections_for_learner(learner_id)
        if release is None or not all_sections:
            return {
                "learner_id": learner_id,
                "release": None,
                "sections": [],
                "receipts": [],
                "viewing_history": [],
                "changes": [],
            }

        changes = await self.evaluate_post_release_changes_for_learner(learner_id)
        assignments = await self._store.get_class_assignments(release.class_id)
        teacher_names: dict[str, str] = {}
        subject_teacher_by_subject: dict[str, str] = {}
        class_teacher_name = release.released_by_name
        for a in assignments:
            t_row = await self._store.get_teacher(a.teacher_id)
            name = t_row["display_name"] if t_row else a.teacher_id
            teacher_names[a.teacher_id] = name
            if a.role == TeacherRole.SUBJECT_TEACHER and a.subject:
                subject_teacher_by_subject[a.subject] = name
            elif a.role == TeacherRole.CLASS_TEACHER:
                class_teacher_name = name

        allowed_scopes = (
            {s.scope for s in all_sections}
            if access["is_class_teacher"]
            else ({"student"} | set(access["allowed_subjects"]))
        )

        visible_sections = [s for s in all_sections if s.scope in allowed_scopes]
        all_receipts = await self._store.get_report_receipts_for_release(
            release.release_id, learner_id=learner_id
        )
        all_views = await self._store.get_report_view_events(
            release.release_id, learner_id=learner_id
        )
        all_responses = await self._store.get_subject_responses_for_release(
            release.release_id, learner_id=learner_id
        )

        receipts_out = [
            rc.model_dump(mode="json")
            for rc in all_receipts
            if access["is_class_teacher"] or rc.teacher_id == teacher_id or rc.subject in access["allowed_subjects"]
        ]

        sections_out: list[dict[str, Any]] = []
        for sec in visible_sections:
            sec_responses = [
                resp.model_dump(mode="json")
                for resp in all_responses
                if resp.published_section_id == sec.published_section_id
                and (access["is_class_teacher"] or resp.subject in access["allowed_subjects"])
            ]

            if sec.scope == "student":
                relevant_receipts = [rc for rc in all_receipts if access["is_class_teacher"] or rc.teacher_id == teacher_id]
                relevant_views = [
                    v for v in all_views
                    if access["is_class_teacher"] or v.teacher_id == teacher_id
                ]
            else:
                relevant_receipts = [
                    rc for rc in all_receipts
                    if rc.subject == sec.scope and (access["is_class_teacher"] or rc.teacher_id == teacher_id)
                ]
                relevant_views = [
                    v for v in all_views
                    if (v.scope == sec.scope or any(rc.teacher_id == v.teacher_id and rc.subject == sec.scope for rc in all_receipts))
                    and (access["is_class_teacher"] or v.teacher_id == teacher_id)
                ]

            # Latest open accountability line & acknowledgment line
            latest_view = relevant_views[-1] if relevant_views else None
            ack_receipt = next((rc for rc in relevant_receipts if rc.acknowledged_at is not None), None)
            if latest_view is not None:
                last_opened = {
                    "teacher_id": latest_view.teacher_id,
                    "teacher_name": latest_view.teacher_name,
                    "viewed_at": latest_view.viewed_at.isoformat(),
                    "display": f"Last opened by {latest_view.teacher_name} — {_format_ts(latest_view.viewed_at)}",
                }
            else:
                last_opened = None

            if ack_receipt is not None and ack_receipt.acknowledged_at is not None:
                acknowledgment = {
                    "acknowledged": True,
                    "teacher_id": ack_receipt.teacher_id,
                    "teacher_name": ack_receipt.teacher_name,
                    "acknowledged_at": ack_receipt.acknowledged_at.isoformat(),
                    "display": f"Acknowledged by {ack_receipt.teacher_name} — {_format_ts(ack_receipt.acknowledged_at)}",
                }
            else:
                acknowledgment = {
                    "acknowledged": False,
                    "teacher_id": teacher_id if not access["is_class_teacher"] else None,
                    "teacher_name": teacher_names.get(teacher_id) if not access["is_class_teacher"] else None,
                    "acknowledged_at": None,
                    "display": "Not acknowledged",
                }

            sec_changes = [
                self._serialize_change(
                    ch,
                    subject_teacher_name=subject_teacher_by_subject.get(sec.scope),
                    class_teacher_name=class_teacher_name,
                )
                for ch in changes
                if ch.scope == sec.scope
            ]

            sections_out.append({
                **sec.model_dump(mode="json"),
                "hash_verified": sec.verify_content_hash(),
                "responses": sec_responses,
                "last_opened": last_opened,
                "acknowledgment": acknowledgment,
                "viewing_history": [v.model_dump(mode="json") for v in relevant_views],
                "changes": sec_changes,
            })

        visible_changes = [
            self._serialize_change(
                ch,
                subject_teacher_name=subject_teacher_by_subject.get(ch.scope),
                class_teacher_name=class_teacher_name,
            )
            for ch in changes
            if ch.scope in allowed_scopes
        ]

        return {
            "learner_id": learner_id,
            "release": release.model_dump(mode="json"),
            "sections": sections_out,
            "receipts": receipts_out,
            "viewing_history": [
                v.model_dump(mode="json")
                for v in all_views
                if access["is_class_teacher"] or v.teacher_id == teacher_id
            ],
            "changes": visible_changes,
        }

    async def get_teacher_workspace(self, teacher_id: str) -> dict[str, Any]:
        """Build signed-in teacher home context: responsibilities, classes, and attention items."""
        teacher = await self._store.get_teacher(teacher_id)
        if teacher is None:
            raise KeyError(f"Teacher '{teacher_id}' does not exist.")

        assignments = await self._store.get_teacher_assignments(teacher_id)
        classes_out: list[dict[str, Any]] = []
        attention_items: list[dict[str, Any]] = []

        for asn in assignments:
            school_class = await self._store.get_class(asn.class_id)
            if school_class is None:
                continue
            learners = await self._store.get_class_learners(school_class.class_id)
            latest_release = await self._store.get_latest_class_release(school_class.class_id)

            role_label = (
                "Class teacher"
                if asn.role == TeacherRole.CLASS_TEACHER
                else f"{asn.subject} teacher"
            )
            classes_out.append({
                "class_id": school_class.class_id,
                "display_name": school_class.display_name,
                "grade": school_class.grade,
                "academic_year": school_class.academic_year,
                "term": school_class.term,
                "role": asn.role.value,
                "subject": asn.subject,
                "role_label": role_label,
                "learner_count": len(learners),
                "latest_release": latest_release.model_dump(mode="json") if latest_release else None,
            })

            # Evaluate updates & attention queue
            if latest_release is not None:
                for learner in learners:
                    changes = await self.evaluate_post_release_changes_for_learner(learner.learner_id)
                    if asn.role == TeacherRole.CLASS_TEACHER:
                        for ch in changes:
                            if ch.severity == DiffSeverity.MAJOR and ch.superseded_by_release_id is None:
                                attention_items.append({
                                    "kind": "major_change",
                                    "class_id": school_class.class_id,
                                    "class_name": school_class.display_name,
                                    "learner_id": learner.learner_id,
                                    "learner_name": learner.display_name,
                                    "scope": ch.scope,
                                    "headline": ch.headline,
                                    "why_it_matters": ch.why_it_matters,
                                    "change": self._serialize_change(ch, class_teacher_name=teacher["display_name"]),
                                })
                    else:
                        receipt = await self._store.get_report_receipt(
                            latest_release.release_id, learner.learner_id, teacher_id
                        )
                        if receipt is None or receipt.status != ReceiptStatus.ACKNOWLEDGED:
                            attention_items.append({
                                "kind": "pending_acknowledgment",
                                "class_id": school_class.class_id,
                                "class_name": school_class.display_name,
                                "learner_id": learner.learner_id,
                                "learner_name": learner.display_name,
                                "release_id": latest_release.release_id,
                                "version_number": latest_release.version_number,
                                "subject": asn.subject,
                                "headline": f"{learner.display_name} — Grade report v{latest_release.version_number} ready for your acknowledgment",
                            })
                        for ch in changes:
                            if ch.scope == asn.subject and ch.superseded_by_release_id is None:
                                attention_items.append({
                                    "kind": "major_change" if ch.severity == DiffSeverity.MAJOR else "minor_change",
                                    "class_id": school_class.class_id,
                                    "class_name": school_class.display_name,
                                    "learner_id": learner.learner_id,
                                    "learner_name": learner.display_name,
                                    "scope": ch.scope,
                                    "headline": ch.headline,
                                    "why_it_matters": ch.why_it_matters,
                                    "change": self._serialize_change(ch, subject_teacher_name=teacher["display_name"]),
                                })
            elif asn.role == TeacherRole.CLASS_TEACHER:
                readiness = await self.get_class_readiness(school_class.class_id)
                if not readiness["can_release"]:
                    attention_items.append({
                        "kind": "class_readiness",
                        "class_id": school_class.class_id,
                        "class_name": school_class.display_name,
                        "headline": f"{school_class.display_name} handover sections need review before class release",
                        "blocking_count": len(readiness["blocking_reasons"]),
                    })

        return {
            "teacher_id": teacher["teacher_id"],
            "display_name": teacher["display_name"],
            "classes": classes_out,
            "needs_attention": attention_items,
        }

    @staticmethod
    def _make_audit(*, tool_name: str, input_summary: dict[str, Any], output_reference: str | None, approval_state: str | None) -> Any:
        from allps.models.audit import AuditEntry

        return AuditEntry(
            tool_name=tool_name,
            input_summary=input_summary,
            output_reference=output_reference,
            approval_state=approval_state,
        )
