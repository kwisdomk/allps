"""Analysis service — deterministic longitudinal pattern detection."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional

from allps.models.pattern import Pattern, PatternType
from allps.models.evidence import Evidence, STANDARD_VERSIONED_SCALES
from allps.models.review import ReviewItem, ReviewStatus


@dataclass(frozen=True)
class SeriesKey:
    """Explicit compatibility key for longitudinal comparisons.

    Assessments are comparable only if they share the exact same grade,
    subject, measured_skill, form identity, form version, language,
    measurement kind, scoring scale, and assessment stage (timing milestone).
    Percentages alone do NOT make different assessments comparable.
    """

    grade: str
    subject: str
    measured_skill: str
    form: str
    form_version: str
    language: str
    measure: str  # "marks", "rubric", "fluency"
    scale: str  # "max_score:20.0", "rubric:name:ver:scale", "unit:cwpm"
    assessment_stage: Optional[str] = None  # "opener", "cat", "midterm", "end_term"


def _canonical_rubric_scale(content: Mapping[str, Any]) -> str:
    """Resolve complete, canonical rubric scale definition.

    Different scales must not produce a shared trend.
    Both registered names and explicit level lists resolve to canonical level sequences.
    """
    scale_def = content.get("scale") or content.get("rubric_scale") or content.get("levels")
    if isinstance(scale_def, str) and scale_def in STANDARD_VERSIONED_SCALES:
        return "levels:" + "|".join(STANDARD_VERSIONED_SCALES[scale_def])
    elif isinstance(scale_def, (list, tuple)) and scale_def:
        return "levels:" + "|".join(str(x) for x in scale_def)
    elif "max_level" in content and isinstance(content["max_level"], int) and not isinstance(content["max_level"], bool):
        return f"max_level:{content['max_level']}"
    return "unknown"


def _get_rubric_rank(content: Mapping[str, Any]) -> tuple[float | None, str]:
    """Return (rank, level_str) for a rubric content mapping against its scale.

    Returns None for rank if scale is not defined or level is not found in the scale.
    """
    level = None
    for k in ("level", "ordinal_level", "rubric_level"):
        if k in content and content[k] is not None:
            level = content[k]
            break

    scale = content.get("scale") or content.get("rubric_scale") or content.get("levels")

    if isinstance(scale, str) and scale in STANDARD_VERSIONED_SCALES:
        scale = STANDARD_VERSIONED_SCALES[scale]

    if isinstance(scale, (list, tuple)) and not isinstance(level, bool):
        if level in scale:
            return float(scale.index(level)), str(level)
        elif isinstance(level, (int, str)) and str(level) in [str(x) for x in scale]:
            str_scale = [str(x) for x in scale]
            return float(str_scale.index(str(level))), str(level)
    elif isinstance(level, int) and not isinstance(level, bool):
        return float(level), str(level)
    elif "ordinal_value" in content and isinstance(content["ordinal_value"], (int, float)) and not isinstance(content["ordinal_value"], bool):
        return float(content["ordinal_value"]), str(level)
    return None, str(level)


class AnalysisService:
    """Service layer for deterministic longitudinal analysis.

    Enforces strict measurement comparability rules:
    - Compares only explicitly compatible records within the same grade,
      subject, measured_skill, form, form_version, language, and scoring scale.
    - Requires explicit comparison authorization (comparison_authorized: True).
    - Excludes records with missing comparison metadata; does not invent defaults.
    - Requires at least three distinct academic periods for an across-term trend.
    - Distinguishes unchanged, improving, declining, and fluctuating marks and rubrics.
    - Does not announce rubric progression merely because three periods exist.
    - Never treats percentage conversion alone as proof of comparability.
    - Preserves true zero and keeps missing results null.
    - Returns evidence references and clear, transparent limitations.
    """

    def __init__(self, evidence_service: Any, store: Any = None) -> None:
        self._evidence_service = evidence_service
        self._store = (
            store
            or getattr(evidence_service, "store", None)
            or getattr(evidence_service, "_store", None)
        )

    async def analyse_longitudinal_pattern(
        self,
        learner_id: str,
        *,
        evidence_type: Optional[str] = None,
        subject: Optional[str] = None,
    ) -> List[Mapping[str, Any]]:
        """Determine longitudinal patterns for a learner.

        Returns a list of JSON-serializable dictionaries representing Pattern models.
        """
        # 1. Retrieve chronologically ordered evidence
        records: List[Evidence] = await self._evidence_service.get_learner_history(
            learner_id,
            evidence_type=evidence_type,
            subject=subject,
        )

        if not records:
            return [
                Pattern(
                    learner_id=learner_id,
                    pattern_type=PatternType.INSUFFICIENT_EVIDENCE,
                    summary="No evidence records available to evaluate longitudinal patterns.",
                    supporting_evidence=[],
                    limitations=["No recorded evidence history found for this learner."],
                ).model_dump(mode="json")
            ]

        # 2. Filter to assessment evidence
        assessment_records = [
            ev for ev in records if ev.evidence_type.value == "assessment"
        ]

        if not assessment_records:
            return [
                Pattern(
                    learner_id=learner_id,
                    pattern_type=PatternType.INSUFFICIENT_EVIDENCE,
                    summary="No assessment evidence available to evaluate longitudinal patterns.",
                    supporting_evidence=[e.evidence_id for e in records],
                    limitations=["Requires assessment records for longitudinal analysis."],
                ).model_dump(mode="json")
            ]

        # 3. Categorize assessments into compatible series, missing, or insufficiently described
        series_groups: dict[SeriesKey, list[Evidence]] = defaultdict(list)
        missing_records: list[Evidence] = []
        insufficient_records: list[Evidence] = []

        for ev in assessment_records:
            # Check for explicit missing outcome
            if ev.is_missing_outcome or (
                isinstance(ev.content, (dict, Mapping))
                and ev.content.get("score") is None
                and not ev.is_rubric
                and "value" not in ev.content
            ):
                missing_records.append(ev)
                continue

            content = ev.content if isinstance(ev.content, (dict, Mapping)) else {}
            subj = ev.subject or content.get("subject")
            grade = ev.grade
            skill = ev.measured_skill
            form_val = ev.form
            form_ver = ev.form_version
            lang_val = ev.language

            # Require comparison authorization and full comparison metadata
            # Exclude records with missing comparison metadata; no invented "standard" defaults!
            if not (
                subj
                and grade
                and skill
                and form_val
                and form_ver
                and lang_val
                and ev.comparison_authorized
            ):
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
                    max_s = float(max_score)
                    scale_key = f"max_score:{max_s:g}"
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
                unit_val = str(content.get("unit"))
                key = SeriesKey(
                    grade=str(grade),
                    subject=str(subj),
                    measured_skill=str(skill),
                    form=str(form_val),
                    form_version=str(form_ver),
                    language=str(lang_val),
                    measure="fluency",
                    scale=f"unit:{unit_val}",
                    assessment_stage=str(stage_val) if stage_val else None,
                )
                series_groups[key].append(ev)

            else:
                insufficient_records.append(ev)

        patterns: list[Pattern] = []

        # 4. Analyze each compatible series across distinct academic periods
        for key, series_evs in series_groups.items():
            # Group by distinct academic period (academic_year, term)
            period_map: dict[tuple[int, int], list[Evidence]] = defaultdict(list)
            for ev in series_evs:
                period_map[(ev.academic_year, ev.term)].append(ev)

            sorted_periods = sorted(period_map.keys(), key=lambda p: (p[0], p[1]))

            # Relevant missing and excluded evidence for this series
            relevant_missing = [
                e for e in missing_records
                if (e.subject is None or e.subject == key.subject)
                and (e.grade is None or e.grade == key.grade)
            ]
            relevant_insufficient = [
                e for e in insufficient_records
                if (e.subject is None or e.subject == key.subject)
                and (e.grade is None or e.grade == key.grade)
            ]

            extra_limitations: list[str] = []
            if relevant_missing:
                extra_limitations.append(
                    f"{len(relevant_missing)} assessment record(s) had missing outcomes (e.g., absent, unavailable, not submitted) and were preserved as null."
                )
            if relevant_insufficient:
                extra_limitations.append(
                    f"{len(relevant_insufficient)} assessment record(s) were excluded from numerical comparison "
                    "due to missing comparison metadata (grade, subject, form, form_version, language, measured_skill) "
                    "or lacking explicit comparison authorization."
                )

            # An across-term trend requires at least three distinct academic periods
            if len(sorted_periods) >= 3:
                if key.measure == "marks":
                    max_score_num = float(key.scale.replace("max_score:", ""))
                    period_scores: list[tuple[tuple[int, int], float, list[str]]] = []

                    for period in sorted_periods:
                        ev_list = period_map[period]
                        # Compute representative score for the period (average if multiple in same term)
                        avg_s = sum(float(e.content["score"]) for e in ev_list) / len(ev_list)
                        eids = [e.evidence_id for e in ev_list]
                        period_scores.append((period, avg_s, eids))

                    scores = [s for _, s, _ in period_scores]
                    all_eids = [eid for _, _, eids in period_scores for eid in eids]

                    is_unchanged = all(s == scores[0] for s in scores)
                    is_increasing = all(
                        s1 < s2 for s1, s2 in zip(scores, scores[1:])
                    )
                    is_decreasing = all(
                        s1 > s2 for s1, s2 in zip(scores, scores[1:])
                    )

                    score_str = " -> ".join(
                        f"{s:g}/{max_score_num:g}" for s in scores
                    )

                    limitations = [
                        f"Evaluated across {len(scores)} distinct academic periods within {key.grade}.",
                        f"Scoring scale is uniform ({max_score_num:g} marks); assessments have not been equated across different instruments or grades.",
                        "Percentage conversion alone was not used to establish comparability across differing scales.",
                    ]
                    if key.assessment_stage:
                        limitations.append(f"Assessment stage preserved: {key.assessment_stage}.")
                    if any(len(period_map[p]) > 1 for p in sorted_periods):
                        limitations.append(
                            "One or more terms included multiple assessments; period mean was utilized for trajectory evaluation."
                        )

                    all_limitations = limitations + extra_limitations

                    if is_unchanged:
                        patterns.append(
                            Pattern(
                                learner_id=learner_id,
                                pattern_type=PatternType.TREND,
                                summary=(
                                    f"Unchanged across-term performance in {key.grade} {key.subject} "
                                    f"(scale: {max_score_num:g} marks) across {len(scores)} distinct terms ({score_str})."
                                ),
                                supporting_evidence=all_eids,
                                limitations=all_limitations,
                            )
                        )
                    elif is_increasing:
                        patterns.append(
                            Pattern(
                                learner_id=learner_id,
                                pattern_type=PatternType.TREND,
                                summary=(
                                    f"Improving across-term trend in {key.grade} {key.subject} "
                                    f"(scale: {max_score_num:g} marks) across {len(scores)} distinct terms ({score_str})."
                                ),
                                supporting_evidence=all_eids,
                                limitations=all_limitations,
                            )
                        )
                    elif is_decreasing:
                        patterns.append(
                            Pattern(
                                learner_id=learner_id,
                                pattern_type=PatternType.TREND,
                                summary=(
                                    f"Declining across-term trend in {key.grade} {key.subject} "
                                    f"(scale: {max_score_num:g} marks) across {len(scores)} distinct terms ({score_str})."
                                ),
                                supporting_evidence=all_eids,
                                limitations=all_limitations,
                            )
                        )
                    else:
                        patterns.append(
                            Pattern(
                                learner_id=learner_id,
                                pattern_type=PatternType.TREND,
                                summary=(
                                    f"Performance in {key.grade} {key.subject} (scale: {max_score_num:g} marks) "
                                    f"remains variable across {len(scores)} distinct terms ({score_str}) without monotonic trajectory."
                                ),
                                supporting_evidence=all_eids,
                                limitations=all_limitations,
                            )
                        )

                    # Baseline change across distinct terms on the same scale (only when delta > 0)
                    if len(period_scores) >= 2 and not is_unchanged:
                        first_period, first_score, first_ids = period_scores[0]
                        last_period, last_score, last_ids = period_scores[-1]
                        delta = last_score - first_score
                        if abs(delta) > 0:
                            direction = "Gain" if delta > 0 else "Drop"
                            patterns.append(
                                Pattern(
                                    learner_id=learner_id,
                                    pattern_type=PatternType.CHANGED_FROM_BASELINE,
                                    summary=(
                                        f"{direction} of {abs(delta):g} marks from baseline "
                                        f"({first_score:g}/{max_score_num:g} in Year {first_period[0]} Term {first_period[1]} to "
                                        f"{last_score:g}/{max_score_num:g} in Year {last_period[0]} Term {last_period[1]}) "
                                        f"in {key.grade} {key.subject}."
                                    ),
                                    supporting_evidence=first_ids + last_ids,
                                    limitations=[
                                        f"Baseline comparison is restricted to compatible {key.grade} {key.subject} "
                                        f"assessments on the uniform {max_score_num:g}-mark scale.",
                                        "Does not assume cross-grade or cross-instrument equating.",
                                    ] + extra_limitations,
                                )
                            )

                elif key.measure == "rubric":
                    rubric_name = (
                        series_evs[0].content.get("rubric")
                        or series_evs[0].content.get("rubric_name")
                        or key.scale.split(":")[1]
                    )
                    period_rubrics: list[tuple[tuple[int, int], float | None, str, list[str]]] = []
                    has_conflicting_period_ranks = False
                    for period in sorted_periods:
                        ev_list = period_map[period]
                        ranks = [_get_rubric_rank(e.content)[0] for e in ev_list]
                        eids = [e.evidence_id for e in ev_list]
                        lvl_str = " / ".join(str(_get_rubric_rank(e.content)[1]) for e in ev_list)

                        if any(r is None for r in ranks):
                            period_rank = None
                            has_conflicting_period_ranks = True
                        elif len(set(ranks)) == 1:
                            period_rank = ranks[0]
                        else:
                            period_rank = None
                            has_conflicting_period_ranks = True
                        period_rubrics.append((period, period_rank, lvl_str, eids))

                    all_ranks_valid = not has_conflicting_period_ranks and all(
                        r is not None for _, r, _, _ in period_rubrics
                    )
                    ranks = [r for _, r, _, _ in period_rubrics if r is not None]
                    levels_str = " -> ".join(lvl for _, _, lvl, _ in period_rubrics)
                    all_eids = [eid for _, _, _, eids in period_rubrics for eid in eids]

                    rubric_limitations = [
                        "Rubric ratings are ordinal descriptors and have not been converted to percentage marks or averaged into fractional ranks.",
                        f"Restricted to compatible assessments within {key.grade}.",
                    ]
                    if key.assessment_stage:
                        rubric_limitations.append(f"Assessment stage preserved: {key.assessment_stage}.")

                    all_rubric_limitations = rubric_limitations + extra_limitations

                    if not all_ranks_valid:
                        patterns.append(
                            Pattern(
                                learner_id=learner_id,
                                pattern_type=PatternType.TREND,
                                summary=(
                                    f"Performance in {key.grade} {key.subject} for '{rubric_name}' "
                                    f"contains conflicting ordinal rubric ratings within the same period ({levels_str}) "
                                    f"which cannot be averaged into fractional ranks."
                                ),
                                supporting_evidence=all_eids,
                                limitations=all_rubric_limitations + [
                                    "Multiple conflicting ordinal ratings in the same period cannot be averaged."
                                ],
                            )
                        )
                    else:
                        is_unchanged = all(r == ranks[0] for r in ranks)
                        is_advancing = all(r1 < r2 for r1, r2 in zip(ranks, ranks[1:]))
                        is_declining = all(r1 > r2 for r1, r2 in zip(ranks, ranks[1:]))

                        if is_unchanged:
                            patterns.append(
                                Pattern(
                                    learner_id=learner_id,
                                    pattern_type=PatternType.TREND,
                                    summary=(
                                        f"Unchanged rubric performance in {key.grade} {key.subject} for '{rubric_name}' "
                                        f"across {len(sorted_periods)} distinct terms ({levels_str})."
                                    ),
                                    supporting_evidence=all_eids,
                                    limitations=all_rubric_limitations + [
                                        "Ordinal level remained constant across all evaluated terms."
                                    ],
                                )
                            )
                        elif is_advancing:
                            patterns.append(
                                Pattern(
                                    learner_id=learner_id,
                                    pattern_type=PatternType.TREND,
                                    summary=(
                                        f"Advancing rubric progression in {key.grade} {key.subject} for '{rubric_name}' "
                                        f"across {len(sorted_periods)} distinct terms ({levels_str})."
                                    ),
                                    supporting_evidence=all_eids,
                                    limitations=all_rubric_limitations,
                                )
                            )
                        elif is_declining:
                            patterns.append(
                                Pattern(
                                    learner_id=learner_id,
                                    pattern_type=PatternType.TREND,
                                    summary=(
                                        f"Declining rubric trajectory in {key.grade} {key.subject} for '{rubric_name}' "
                                        f"across {len(sorted_periods)} distinct terms ({levels_str})."
                                    ),
                                    supporting_evidence=all_eids,
                                    limitations=all_rubric_limitations,
                                )
                            )
                        else:
                            patterns.append(
                                Pattern(
                                    learner_id=learner_id,
                                    pattern_type=PatternType.TREND,
                                    summary=(
                                        f"Performance in {key.grade} {key.subject} for '{rubric_name}' "
                                        f"remains variable across {len(sorted_periods)} distinct terms ({levels_str}) without monotonic trajectory."
                                    ),
                                    supporting_evidence=all_eids,
                                    limitations=all_rubric_limitations,
                                )
                            )

                elif key.measure == "fluency":
                    unit_str = key.scale.replace("unit:", "")
                    period_values: list[tuple[tuple[int, int], float, list[str]]] = []

                    for period in sorted_periods:
                        ev_list = period_map[period]
                        avg_v = sum(float(e.content["value"]) for e in ev_list) / len(ev_list)
                        eids = [e.evidence_id for e in ev_list]
                        period_values.append((period, avg_v, eids))

                    values = [v for _, v, _ in period_values]
                    all_eids = [eid for _, _, eids in period_values for eid in eids]

                    is_unchanged = all(v == values[0] for v in values)
                    is_increasing = all(v1 < v2 for v1, v2 in zip(values, values[1:]))
                    is_decreasing = all(v1 > v2 for v1, v2 in zip(values, values[1:]))

                    val_str = " -> ".join(f"{v:g} {unit_str}" for v in values)

                    limitations = [
                        f"Evaluated across {len(values)} distinct academic periods within {key.grade}.",
                        f"Measurement unit is uniform ({unit_str}); fluency rates have not been equated across differing passage forms, languages, or grades.",
                    ]
                    if key.assessment_stage:
                        limitations.append(f"Assessment stage preserved: {key.assessment_stage}.")
                    if any(len(period_map[p]) > 1 for p in sorted_periods):
                        limitations.append(
                            "One or more terms included multiple assessments; period mean was utilized for trajectory evaluation."
                        )

                    all_fluency_limitations = limitations + extra_limitations

                    if is_unchanged:
                        patterns.append(
                            Pattern(
                                learner_id=learner_id,
                                pattern_type=PatternType.TREND,
                                summary=(
                                    f"Unchanged across-term fluency rate in {key.grade} {key.subject} "
                                    f"({unit_str}) across {len(values)} distinct terms ({val_str})."
                                ),
                                supporting_evidence=all_eids,
                                limitations=all_fluency_limitations,
                            )
                        )
                    elif is_increasing:
                        patterns.append(
                            Pattern(
                                learner_id=learner_id,
                                pattern_type=PatternType.TREND,
                                summary=(
                                    f"Improving across-term fluency trend in {key.grade} {key.subject} "
                                    f"({unit_str}) across {len(values)} distinct terms ({val_str})."
                                ),
                                supporting_evidence=all_eids,
                                limitations=all_fluency_limitations,
                            )
                        )
                    elif is_decreasing:
                        patterns.append(
                            Pattern(
                                learner_id=learner_id,
                                pattern_type=PatternType.TREND,
                                summary=(
                                    f"Declining across-term fluency trend in {key.grade} {key.subject} "
                                    f"({unit_str}) across {len(values)} distinct terms ({val_str})."
                                ),
                                supporting_evidence=all_eids,
                                limitations=all_fluency_limitations,
                            )
                        )
                    else:
                        patterns.append(
                            Pattern(
                                learner_id=learner_id,
                                pattern_type=PatternType.TREND,
                                summary=(
                                    f"Fluency rate in {key.grade} {key.subject} ({unit_str}) "
                                    f"remains variable across {len(values)} distinct terms ({val_str}) without monotonic trajectory."
                                ),
                                supporting_evidence=all_eids,
                                limitations=all_fluency_limitations,
                            )
                        )

                    # Baseline change across distinct terms on the same unit
                    if len(period_values) >= 2 and not is_unchanged:
                        first_period, first_val, first_ids = period_values[0]
                        last_period, last_val, last_ids = period_values[-1]
                        delta = last_val - first_val
                        if abs(delta) > 0:
                            direction = "Gain" if delta > 0 else "Drop"
                            patterns.append(
                                Pattern(
                                    learner_id=learner_id,
                                    pattern_type=PatternType.CHANGED_FROM_BASELINE,
                                    summary=(
                                        f"{direction} of {abs(delta):g} {unit_str} from baseline "
                                        f"({first_val:g} {unit_str} in Year {first_period[0]} Term {first_period[1]} to "
                                        f"{last_val:g} {unit_str} in Year {last_period[0]} Term {last_period[1]}) "
                                        f"in {key.grade} {key.subject}."
                                    ),
                                    supporting_evidence=first_ids + last_ids,
                                    limitations=[
                                        f"Baseline comparison is restricted to compatible {key.grade} {key.subject} "
                                        f"fluency assessments on the uniform {unit_str} unit.",
                                        "Does not assume cross-grade or cross-form equating.",
                                    ] + extra_limitations,
                                )
                            )

            elif len(sorted_periods) == 2 and key.measure == "marks":
                # Only 2 periods: calculate baseline change on compatible scale, but no across-term trend
                max_score_num = float(key.scale.replace("max_score:", ""))
                p1_evs = period_map[sorted_periods[0]]
                p2_evs = period_map[sorted_periods[1]]
                s1 = sum(float(e.content["score"]) for e in p1_evs) / len(p1_evs)
                s2 = sum(float(e.content["score"]) for e in p2_evs) / len(p2_evs)
                delta = s2 - s1
                if abs(delta) > 0:
                    direction = "Gain" if delta > 0 else "Drop"
                    patterns.append(
                        Pattern(
                            learner_id=learner_id,
                            pattern_type=PatternType.CHANGED_FROM_BASELINE,
                            summary=(
                                f"{direction} of {abs(delta):g} marks from baseline "
                                f"({s1:g}/{max_score_num:g} in Year {sorted_periods[0][0]} Term {sorted_periods[0][1]} to "
                                f"{s2:g}/{max_score_num:g} in Year {sorted_periods[1][0]} Term {sorted_periods[1][1]}) "
                                f"in {key.grade} {key.subject}."
                            ),
                            supporting_evidence=[e.evidence_id for e in p1_evs + p2_evs],
                            limitations=[
                                f"Baseline comparison is restricted to compatible {key.grade} {key.subject} "
                                f"assessments on the uniform {max_score_num:g}-mark scale.",
                                "Across-term trend requires at least three distinct academic periods; two periods available.",
                            ] + extra_limitations,
                        )
                    )

            elif len(sorted_periods) == 2 and key.measure == "fluency":
                unit_str = key.scale.replace("unit:", "")
                p1_evs = period_map[sorted_periods[0]]
                p2_evs = period_map[sorted_periods[1]]
                v1 = sum(float(e.content["value"]) for e in p1_evs) / len(p1_evs)
                v2 = sum(float(e.content["value"]) for e in p2_evs) / len(p2_evs)
                delta = v2 - v1
                if abs(delta) > 0:
                    direction = "Gain" if delta > 0 else "Drop"
                    patterns.append(
                        Pattern(
                            learner_id=learner_id,
                            pattern_type=PatternType.CHANGED_FROM_BASELINE,
                            summary=(
                                f"{direction} of {abs(delta):g} {unit_str} from baseline "
                                f"({v1:g} {unit_str} in Year {sorted_periods[0][0]} Term {sorted_periods[0][1]} to "
                                f"{v2:g} {unit_str} in Year {sorted_periods[1][0]} Term {sorted_periods[1][1]}) "
                                f"in {key.grade} {key.subject}."
                            ),
                            supporting_evidence=[e.evidence_id for e in p1_evs + p2_evs],
                            limitations=[
                                f"Baseline comparison is restricted to compatible {key.grade} {key.subject} "
                                f"fluency assessments on the uniform {unit_str} unit.",
                                "Across-term trend requires at least three distinct academic periods; two periods available.",
                            ] + extra_limitations,
                        )
                    )

        # 5. If no patterns were surfaced, return INSUFFICIENT_EVIDENCE with explicit limitations
        if not patterns:
            reasons = [
                "An across-term trend requires at least three distinct academic periods with compatible grade, subject, measure, form, language, and scoring scale."
            ]

            if insufficient_records:
                reasons.append(
                    f"{len(insufficient_records)} assessment record(s) were excluded from numerical comparison "
                    "due to missing comparison metadata (grade, subject, form, form_version, language, measured_skill) "
                    "or lacking explicit comparison authorization."
                )

            if missing_records:
                reasons.append(
                    f"{len(missing_records)} assessment record(s) had missing outcomes (e.g., absent, unavailable, not submitted) and were preserved as null."
                )

            # Check if all records were confined to the same term
            periods_present = set((ev.academic_year, ev.term) for ev in assessment_records)
            if len(periods_present) == 1:
                reasons.append(
                    "Multiple assessments within the same academic term do not establish an across-term trend."
                )

            # Check if scales differed across records
            scales_present = set(
                ev.content.get("max_score")
                for ev in assessment_records
                if isinstance(ev.content, (dict, Mapping)) and ev.content.get("max_score") is not None
            )
            if len(scales_present) > 1:
                reasons.append(
                    "Assessments on differing scoring scales cannot be converted to percentages or combined into a single trend without validated equating."
                )

            all_supp_ids = [e.evidence_id for e in assessment_records]
            patterns.append(
                Pattern(
                    learner_id=learner_id,
                    pattern_type=PatternType.INSUFFICIENT_EVIDENCE,
                    summary="Insufficient compatible longitudinal evidence across terms to establish an across-term pattern.",
                    supporting_evidence=all_supp_ids,
                    limitations=reasons,
                )
            )

        dumped_patterns: list[dict[str, Any]] = []
        for p in patterns:
            p_dict = p.model_dump(mode="json")
            if p.pattern_type != PatternType.INSUFFICIENT_EVIDENCE and self._store is not None:
                # Deduplicate existing pattern by signature
                existing = await self._store.get_pattern_by_signature(
                    p.learner_id, p.pattern_type.value, p.summary
                )
                if existing:
                    target_pattern_id = existing.pattern_id
                    p_dict["pattern_id"] = existing.pattern_id
                else:
                    await self._store.add_pattern(p)
                    target_pattern_id = p.pattern_id
                    p_dict["pattern_id"] = p.pattern_id

                # Auto-generate or link to active ReviewItem in PENDING state
                # (Previously accepted reviews cannot be silently reused for a new synthesis)
                existing_reviews = await self._store.get_review_items_for_pattern(target_pattern_id)
                pending_review = next(
                    (r for r in existing_reviews if r.status == ReviewStatus.PENDING),
                    None,
                )
                if not pending_review:
                    review_item = ReviewItem(
                        pattern_id=target_pattern_id,
                        status=ReviewStatus.PENDING,
                    )
                    await self._store.add_review_item(review_item)
                    p_dict["review_id"] = review_item.review_id
                    p_dict["review_status"] = ReviewStatus.PENDING.value
                else:
                    p_dict["review_id"] = pending_review.review_id
                    p_dict["review_status"] = ReviewStatus.PENDING.value

            dumped_patterns.append(p_dict)

        return dumped_patterns
