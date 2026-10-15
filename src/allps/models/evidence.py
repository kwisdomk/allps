"""Evidence domain model — the core data unit in ALLPS."""

from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Annotated
import math

from pydantic import BaseModel, Field, field_validator, model_validator, PlainValidator, PlainSerializer

import uuid
from allps.policies.label_policy import scan_content_for_prohibited_labels

def _deep_freeze(v: Any) -> Any:
    if isinstance(v, MappingProxyType):
        return v
    if isinstance(v, dict):
        return MappingProxyType({k: _deep_freeze(val) for k, val in v.items()})
    if isinstance(v, list):
        return tuple(_deep_freeze(val) for val in v)
    if isinstance(v, set):
        return frozenset(_deep_freeze(val) for val in v)
    return v

def _deep_unfreeze(v: Any) -> Any:
    if isinstance(v, (MappingProxyType, dict)):
        return {k: _deep_unfreeze(val) for k, val in v.items()}
    if isinstance(v, (tuple, list)):
        return [_deep_unfreeze(val) for val in v]
    if isinstance(v, (frozenset, set)):
        return [_deep_unfreeze(val) for val in v]
    return v

def _validate_mapping_proxy(v: Any) -> MappingProxyType:
    return _deep_freeze(v)

FrozenDictType = Annotated[
    MappingProxyType[str, Any],
    PlainValidator(_validate_mapping_proxy),
    PlainSerializer(_deep_unfreeze, return_type=dict)
]

STANDARD_VERSIONED_SCALES: dict[str, list[str]] = {
    "cbc_4_level": [
        "Below Expectation",
        "Approaching Expectation",
        "Meeting Expectation",
        "Exceeding Expectation",
    ],
    "cbc_4_level_v1": [
        "Below Expectation",
        "Approaching Expectation",
        "Meeting Expectation",
        "Exceeding Expectation",
    ],
    "kenya_cbc_v1": [
        "Below Expectation",
        "Approaching Expectation",
        "Meeting Expectation",
        "Exceeding Expectation",
    ],
}


def _check_finite_recursive(val: Any, path: str = "content") -> None:
    """Recursively ensure no non-finite numeric values exist."""
    if isinstance(val, bool):
        return
    if isinstance(val, (int, float)):
        if not math.isfinite(val):
            raise ValueError(f"Non-finite numeric value in '{path}': {val} is not permitted")
    elif isinstance(val, (dict, MappingProxyType)):
        for k, v in val.items():
            _check_finite_recursive(v, f"{path}.{k}")
    elif isinstance(val, (list, tuple, set, frozenset)):
        for idx, item in enumerate(val):
            _check_finite_recursive(item, f"{path}[{idx}]")



class AssessmentMissingStatus(str, Enum):
    """Explicit statuses for missing assessment outcomes."""

    ABSENT = "absent"
    RESULT_UNAVAILABLE = "result_unavailable"
    UNAVAILABLE = "unavailable"  # canonical alias for result_unavailable
    NOT_SUBMITTED = "not_submitted"
    ASSESSMENT_NOT_ADMINISTERED = "assessment_not_administered"
    NOT_ADMINISTERED = "not_administered"  # canonical alias
    NOT_ASSESSED = "not_assessed"  # canonical alias
    NOT_ENROLLED = "not_enrolled"


class AssessmentKind(str, Enum):
    """Kind of assessment instrument."""

    EXAM = "exam"
    CAT = "cat"
    QUIZ = "quiz"
    ORAL = "oral"
    PRACTICAL = "practical"


class AssessmentPurpose(str, Enum):
    """Pedagogical purpose of the assessment."""

    FORMATIVE = "formative"
    SUMMATIVE = "summative"
    DIAGNOSTIC = "diagnostic"
    SCREENING = "screening"
    PROGRESS_MONITORING = "progress_monitoring"


class AssessmentStage(str, Enum):
    """Timing milestone within the academic term (kept distinct from school level)."""

    OPENER = "opener"
    CAT = "cat"
    MIDTERM = "midterm"
    END_TERM = "end_term"


class SchoolLevel(str, Enum):
    """School tier / educational band (kept distinct from assessment stage)."""

    PRE_PRIMARY = "pre_primary"
    LOWER_PRIMARY = "lower_primary"
    UPPER_PRIMARY = "upper_primary"
    EARLY_YEARS = "early_years"
    MIDDLE_SCHOOL = "middle_school"


class EvidenceType(str, Enum):
    """Types of learner evidence that ALLPS can record."""

    ASSESSMENT = "assessment"
    ATTENDANCE = "attendance"
    OBSERVATION = "observation"
    LEARNER_REFLECTION = "learner_reflection"
    PROJECT = "project"


class IngestionMethod(str, Enum):
    """Mechanisms by which evidence is ingested into ALLPS."""

    API = "api"
    WEBHOOK = "webhook"
    SCHEDULED_SYNC = "scheduled_sync"
    CSV_IMPORT = "csv_import"
    MANUAL_OBSERVATION = "manual_observation"
    LEARNER_PULSE = "learner_pulse"
    SYNTHETIC = "synthetic"


class Evidence(BaseModel):
    """A single piece of learner evidence with full provenance.

    Evidence is immutable once recorded. Each record captures what was
    observed, who observed it, when it was observed, and when it was
    recorded in ALLPS.

    ALLPS is not the authoritative gradebook — evidence may originate
    from an external SIS, LMS, attendance system, CSV import, learner
    pulse, or direct teacher observations. Both the originating
    source_system and ingestion_method are explicitly preserved.

    The content field is a flexible dict for evidence-type-specific
    payloads (e.g., {"score": 72, "max_score": 100} for assessments).
    """

    evidence_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    learner_id: str = Field(..., min_length=1)
    evidence_type: EvidenceType

    # System origin and ingestion channel
    source_system: str = Field(
        ...,
        min_length=1,
        description=(
            "Originating system, e.g. 'school_sis', 'moodle', "
            "'attendance_system', 'allps', 'csv_import', 'synthetic_dataset'"
        ),
    )
    ingestion_method: IngestionMethod = Field(
        ...,
        description="Ingestion mechanism/channel, e.g. 'manual_observation', 'api'",
    )

    source_event_id: str | None = Field(
        default=None,
        description="Stable unique identifier from the source system for idempotent ingestion.",
    )

    # Provenance
    source_type: str = Field(
        ...,
        min_length=1,
        description=(
            "Who/what provided this evidence, "
            "e.g. 'teacher', 'system', 'learner'"
        ),
    )
    source_reference: str = Field(
        ...,
        min_length=1,
        description=(
            "Specific source identifier, "
            "e.g. 'Mrs. Nkosi', 'attendance-system-v2'"
        ),
    )

    # Academic time (sortable)
    academic_year: int = Field(..., ge=2000, le=2100)
    term: int = Field(..., ge=1, le=4)

    # Optional subject
    subject: str | None = Field(default=None)

    # Flexible payload (Immutable)
    content: FrozenDictType = Field(
        ..., description="Evidence-type-specific payload"
    )

    # Timestamps
    observed_at: datetime = Field(
        ...,
        description="When the observation/event occurred (timezone-aware)",
    )
    recorded_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this was recorded in ALLPS",
    )

    @property
    def grade(self) -> str | None:
        """Academic grade level (e.g. 'Grade 2', 'PP1') from content if present."""
        if isinstance(self.content, (dict, MappingProxyType)):
            return self.content.get("grade")
        return None

    @property
    def school_level(self) -> str | None:
        """Educational tier (e.g. 'pre_primary', 'lower_primary', 'upper_primary') from content if present."""
        if isinstance(self.content, (dict, MappingProxyType)):
            sl = self.content.get("school_level")
            if sl is None and self.content.get("stage") in (
                "pre_primary",
                "lower_primary",
                "upper_primary",
                "early_years",
                "middle_school",
            ):
                sl = self.content.get("stage")
            return sl
        return None

    @property
    def assessment_stage(self) -> str | None:
        """Assessment timing within term (e.g. 'opener', 'cat', 'midterm', 'end_term') from content if present."""
        if isinstance(self.content, (dict, MappingProxyType)):
            stage = self.content.get("assessment_stage")
            if stage is None and self.content.get("stage") in (
                "opener",
                "cat",
                "midterm",
                "end_term",
            ):
                stage = self.content.get("stage")
            if stage is None and self.content.get("kind") in ("cat",):
                stage = "cat"
            return stage
        return None

    @property
    def assessment_event(self) -> str | None:
        """Assessment event title (e.g. 'Term 1 CAT 1') from content if present."""
        if isinstance(self.content, (dict, MappingProxyType)):
            return self.content.get("assessment_event")
        return None

    @property
    def form(self) -> str | None:
        """Form identity (e.g. 'Form A', 'CAT 1') from content if present."""
        if isinstance(self.content, (dict, MappingProxyType)):
            return self.content.get("form")
        return None

    @property
    def form_version(self) -> str | None:
        """Form version identifier (e.g. 'v1.0') from content if present."""
        if isinstance(self.content, (dict, MappingProxyType)):
            return self.content.get("form_version") or self.content.get("version")
        return None

    @property
    def language(self) -> str | None:
        """Assessment language from content if present."""
        if isinstance(self.content, (dict, MappingProxyType)):
            return self.content.get("language")
        return None

    @property
    def measured_skill(self) -> str | None:
        """Specific measured competency or skill domain from content if present."""
        if isinstance(self.content, (dict, MappingProxyType)):
            for k in ("measured_skill", "sampled_content", "skill"):
                if k in self.content and self.content[k] is not None:
                    return str(self.content[k])
        return None

    @property
    def comparison_authorized(self) -> bool:
        """Return True if explicit authorization for longitudinal comparison is granted.
        
        Explicit false must never be overridden by a true alias.
        """
        if not isinstance(self.content, (dict, MappingProxyType)):
            return False
        aliases = ("comparison_authorized", "comparable", "is_comparable")
        vals = [
            self.content[k]
            for k in aliases
            if k in self.content and isinstance(self.content[k], bool)
        ]
        if not vals:
            return False
        # Explicit false must never be overridden by a true alias
        if any(v is False for v in vals):
            return False
        return any(v is True for v in vals)

    @property
    def is_missing_outcome(self) -> bool:
        """Return True if this assessment has an explicit missing outcome."""
        if self.evidence_type != EvidenceType.ASSESSMENT:
            return False
        if not isinstance(self.content, (dict, MappingProxyType)):
            return False
        return self.content.get("status") in (
            "absent",
            "result_unavailable",
            "unavailable",
            "not_submitted",
            "assessment_not_administered",
            "not_administered",
            "not_assessed",
            "not_enrolled",
        )

    @property
    def is_rubric(self) -> bool:
        """Return True if this assessment has a recorded rubric outcome."""
        if self.evidence_type != EvidenceType.ASSESSMENT:
            return False
        if not isinstance(self.content, (dict, MappingProxyType)):
            return False
        has_name = self.content.get("rubric") is not None or self.content.get("rubric_name") is not None
        has_ver = self.content.get("rubric_version") is not None or self.content.get("version") is not None
        has_lvl = (
            self.content.get("level") is not None
            or self.content.get("ordinal_level") is not None
            or self.content.get("rubric_level") is not None
        )
        return bool(has_name and has_ver and has_lvl)

    @property
    def is_marks(self) -> bool:
        """Return True if this assessment has recorded marks (score and max_score)."""
        if self.evidence_type != EvidenceType.ASSESSMENT:
            return False
        if not isinstance(self.content, (dict, MappingProxyType)):
            return False
        s = self.content.get("score")
        ms = self.content.get("max_score")
        return (
            s is not None
            and ms is not None
            and not isinstance(s, bool)
            and not isinstance(ms, bool)
            and isinstance(s, (int, float))
            and isinstance(ms, (int, float))
        )

    @property
    def is_fluency(self) -> bool:
        """Return True if this assessment has recorded fluency ('value' and 'unit')."""
        if self.evidence_type != EvidenceType.ASSESSMENT:
            return False
        if not isinstance(self.content, (dict, MappingProxyType)):
            return False
        v = self.content.get("value")
        u = self.content.get("unit")
        return (
            v is not None
            and u is not None
            and not isinstance(v, bool)
            and isinstance(v, (int, float))
            and isinstance(u, str)
            and bool(u.strip())
        )

    @field_validator("observed_at", "recorded_at")
    @classmethod
    def must_be_timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("Datetime must be timezone-aware")
        return v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_content_payloads(self) -> "Evidence":
        """Validate known evidence types (Assessment, Attendance) and enforce safety policies."""
        # Enforce safety policy: reject deficit and clinical diagnostic labels
        scan_content_for_prohibited_labels(self.content, "content")

        if self.evidence_type == EvidenceType.ASSESSMENT:
            # Check for non-finite numeric values anywhere in content recursively
            _check_finite_recursive(self.content, "content")

            # Treat null outcome fields as absent when evaluating components
            status_val = self.content.get("status")
            has_missing_status = status_val in (
                "absent",
                "result_unavailable",
                "unavailable",
                "not_submitted",
                "assessment_not_administered",
                "not_administered",
                "not_assessed",
                "not_enrolled",
            )
            has_score_key = "score" in self.content and self.content["score"] is not None
            has_max_score_key = "max_score" in self.content and self.content["max_score"] is not None
            has_score_val = has_score_key and has_max_score_key

            rubric_level_vals = {}
            for k in ("level", "ordinal_level", "rubric_level"):
                if k in self.content and self.content[k] is not None:
                    v = self.content[k]
                    if isinstance(v, bool):
                        raise ValueError(f"Rubric '{k}' cannot be a boolean")
                    rubric_level_vals[k] = v

            if len(rubric_level_vals) > 1:
                first_k, first_v = next(iter(rubric_level_vals.items()))
                for k, v in rubric_level_vals.items():
                    if v != first_v or type(v) is not type(first_v):
                        raise ValueError(
                            f"Conflicting rubric-level aliases: {rubric_level_vals}"
                        )

            level_val = next(iter(rubric_level_vals.values())) if rubric_level_vals else None
            has_rubric_level = level_val is not None
            has_rubric_name = (
                self.content.get("rubric") is not None
                or self.content.get("rubric_name") is not None
            )
            has_rubric_ver = (
                self.content.get("rubric_version") is not None
                or self.content.get("version") is not None
            )
            has_rubric = has_rubric_name and has_rubric_ver and has_rubric_level

            has_fluency_val = "value" in self.content and self.content["value"] is not None
            has_fluency_unit = "unit" in self.content and self.content["unit"] is not None
            has_fluency_pair = has_fluency_val and has_fluency_unit

            # Reject contradictory outcomes (only when non-null values conflict)
            if has_missing_status:
                if has_score_key:
                    raise ValueError(
                        "Contradictory outcome: missing assessment status cannot have a numeric score"
                    )
                if has_rubric_level:
                    raise ValueError(
                        "Contradictory outcome: missing assessment status cannot have a rubric level"
                    )
                if has_fluency_val:
                    raise ValueError(
                        "Contradictory outcome: missing assessment status cannot have a fluency value"
                    )

            if has_score_key and has_rubric_level:
                raise ValueError(
                    "Contradictory outcome: cannot contain both numeric marks and rubric level"
                )
            if has_score_key and has_fluency_val:
                raise ValueError(
                    "Contradictory outcome: cannot contain both numeric marks and fluency value"
                )
            if has_rubric_level and has_fluency_val:
                raise ValueError(
                    "Contradictory outcome: cannot contain both rubric level and fluency value"
                )

            # Check for at least one valid outcome type
            if (
                not has_missing_status
                and not has_rubric
                and not has_score_val
                and not has_fluency_pair
            ):
                raise ValueError(
                    "Assessment evidence must contain valid recorded marks ('score' and 'max_score'), "
                    "recorded rubric ('rubric'/'version'/'level'), "
                    "missing outcome ('status' in {'absent', 'result_unavailable', 'not_submitted', "
                    "'assessment_not_administered', 'not_enrolled'} and 'reason'), "
                    "or fluency ('value' and 'unit')"
                )

            # Validate marks
            if has_score_key:
                score = self.content["score"]
                if isinstance(score, bool) or not isinstance(score, (int, float)):
                    raise ValueError("'score' must be a numeric value, not boolean or non-numeric")
                if not math.isfinite(score):
                    raise ValueError("'score' must be a finite number")

            if has_max_score_key:
                max_score = self.content["max_score"]
                if isinstance(max_score, bool) or not isinstance(max_score, (int, float)):
                    raise ValueError("'max_score' must be a numeric value, not boolean or non-numeric")
                if not math.isfinite(max_score):
                    raise ValueError("'max_score' must be a finite number")
                if max_score <= 0:
                    raise ValueError("'max_score' must be greater than 0")

            if has_score_key and has_max_score_key:
                score = self.content["score"]
                max_score = self.content["max_score"]
                if score < 0 or score > max_score:
                    raise ValueError("'score' must be between 0 and 'max_score'")

            # Validate fluency
            if has_fluency_val:
                f_val = self.content["value"]
                if isinstance(f_val, bool) or not isinstance(f_val, (int, float)):
                    raise ValueError("Fluency 'value' must be a numeric value, not boolean or non-numeric")
                if not math.isfinite(f_val):
                    raise ValueError("Fluency 'value' must be a finite number")
                if f_val < 0:
                    raise ValueError("Fluency 'value' cannot be negative")

            if has_fluency_unit:
                unit = self.content["unit"]
                if not isinstance(unit, str) or not unit.strip():
                    raise ValueError("Fluency 'unit' must be a non-empty string")

            if has_missing_status:
                reason = self.content.get("reason")
                if not isinstance(reason, str) or not reason.strip():
                    raise ValueError(
                        "Missing assessment outcome must include a non-empty 'reason'"
                    )

            elif has_rubric:
                rubric_name = self.content.get("rubric") or self.content.get("rubric_name")
                rubric_ver = self.content.get("rubric_version") or self.content.get("version")
                if not isinstance(rubric_name, str) or not rubric_name.strip():
                    raise ValueError("Rubric name must be a non-empty string")
                if not isinstance(rubric_ver, str) or not rubric_ver.strip():
                    raise ValueError("Rubric version must be a non-empty string")

                # Validate rubric level against defined, versioned scale
                scale_defined = (
                    self.content.get("scale")
                    or self.content.get("rubric_scale")
                    or self.content.get("levels")
                )
                max_level = self.content.get("max_level")

                if isinstance(scale_defined, str):
                    if scale_defined not in STANDARD_VERSIONED_SCALES:
                        raise ValueError(f"Unrecognized rubric scale identifier: '{scale_defined}'")
                    scale_defined = STANDARD_VERSIONED_SCALES[scale_defined]

                if scale_defined is not None:
                    if not isinstance(scale_defined, (list, tuple)) or not scale_defined:
                        raise ValueError("Rubric 'scale' must be a non-empty list of valid levels")
                    if level_val not in scale_defined:
                        raise ValueError(
                            f"Rubric level '{level_val}' is invalid against defined scale: {list(scale_defined)}"
                        )
                elif max_level is not None:
                    if isinstance(max_level, bool) or not isinstance(max_level, int) or max_level <= 0:
                        raise ValueError("Rubric 'max_level' must be a positive integer")
                    if isinstance(level_val, bool) or not isinstance(level_val, int) or level_val < 1 or level_val > max_level:
                        raise ValueError(
                            f"Rubric level {level_val} must be an integer between 1 and {max_level}"
                        )
                else:
                    raise ValueError(
                        f"Rubric level '{level_val}' cannot be validated against a defined, versioned scale without an explicit 'scale' "
                        f"(list of levels or registered scale identifier) or 'max_level'"
                    )

            # Validate optional context fields if provided
            if "grade" in self.content and self.content["grade"] is not None:
                g = self.content["grade"]
                if not isinstance(g, str) or not g.strip():
                    raise ValueError("'grade' must be a non-empty string if provided")
            if "form" in self.content and self.content["form"] is not None:
                f = self.content["form"]
                if not isinstance(f, str) or not f.strip():
                    raise ValueError("'form' must be a non-empty string if provided")
            if "form_version" in self.content and self.content["form_version"] is not None:
                fv = self.content["form_version"]
                if not isinstance(fv, str) or not fv.strip():
                    raise ValueError("'form_version' must be a non-empty string if provided")
            if "language" in self.content and self.content["language"] is not None:
                lang = self.content["language"]
                if not isinstance(lang, str) or not lang.strip():
                    raise ValueError("'language' must be a non-empty string if provided")
            # Validate and check measured_skill aliases consistency
            skill_alias_vals = {}
            for k in ("measured_skill", "sampled_content", "skill"):
                if k in self.content and self.content[k] is not None:
                    ms_val = self.content[k]
                    if not isinstance(ms_val, str) or not ms_val.strip():
                        raise ValueError(f"'{k}' must be a non-empty string if provided")
                    skill_alias_vals[k] = ms_val
            if len(set(skill_alias_vals.values())) > 1:
                raise ValueError(
                    f"Conflicting measured-skill aliases: {skill_alias_vals}"
                )

            if "assessment_stage" in self.content and self.content["assessment_stage"] is not None:
                st = self.content["assessment_stage"]
                if st not in ("opener", "cat", "midterm", "end_term"):
                    raise ValueError("'assessment_stage' must be 'opener', 'cat', 'midterm', or 'end_term'")
            if "school_level" in self.content and self.content["school_level"] is not None:
                sl = self.content["school_level"]
                if not isinstance(sl, str) or not sl.strip():
                    raise ValueError("'school_level' must be a non-empty string if provided")
            if "stage" in self.content and self.content["stage"] is not None:
                stg = self.content["stage"]
                if stg in ("opener", "cat", "midterm", "end_term"):
                    pass
                elif stg in ("pre_primary", "lower_primary", "upper_primary", "early_years", "middle_school"):
                    pass
                else:
                    raise ValueError(
                        f"Unrecognized 'stage' value '{stg}'. Must be 'opener', 'cat', 'midterm', 'end_term' (assessment_stage) "
                        f"or school level ('pre_primary', 'lower_primary', 'upper_primary', 'early_years', 'middle_school')."
                    )

            # Check assessment_stage vs school_level vs stage aliases consistency
            as_val = self.content.get("assessment_stage")
            sl_val = self.content.get("school_level")
            stage_val = self.content.get("stage")

            if stage_val is not None:
                if stage_val in ("opener", "cat", "midterm", "end_term"):
                    if as_val is not None and as_val != stage_val:
                        raise ValueError(
                            f"Conflicting assessment-stage aliases: 'assessment_stage' is '{as_val}' but 'stage' is '{stage_val}'"
                        )
                elif stage_val in ("pre_primary", "lower_primary", "upper_primary", "early_years", "middle_school"):
                    if sl_val is not None and sl_val != stage_val:
                        raise ValueError(
                            f"Conflicting school-level aliases: 'school_level' is '{sl_val}' but 'stage' is '{stage_val}'"
                        )

            # Check comparison_authorized aliases consistency
            alias_vals = {}
            for k in ("comparison_authorized", "comparable", "is_comparable"):
                if k in self.content and self.content[k] is not None:
                    v = self.content[k]
                    if not isinstance(v, bool):
                        raise ValueError(f"'{k}' must be a boolean (True or False)")
                    alias_vals[k] = v
            if True in alias_vals.values() and False in alias_vals.values():
                raise ValueError(
                    "Conflicting comparison-authorization aliases: explicit false cannot be overridden by true"
                )

        elif self.evidence_type == EvidenceType.ATTENDANCE:
            has_daily = "status" in self.content
            has_term = "days_present" in self.content and "days_total" in self.content

            if not has_daily and not has_term:
                raise ValueError("Attendance evidence must contain either 'status' or ('days_present' and 'days_total')")

            if has_daily:
                if self.content["status"] not in ("present", "absent", "late"):
                    raise ValueError("Attendance status must be 'present', 'absent', or 'late'")

            if has_term:
                dp = self.content["days_present"]
                dt = self.content["days_total"]
                if isinstance(dp, bool) or isinstance(dt, bool) or not isinstance(dp, int) or not isinstance(dt, int):
                    raise ValueError("'days_present' and 'days_total' must be integers (not boolean)")
                if dt <= 0:
                    raise ValueError("'days_total' must be greater than 0")
                if dp < 0 or dp > dt:
                    raise ValueError("'days_present' must be between 0 and 'days_total'")

        return self

    model_config = {"frozen": True}
