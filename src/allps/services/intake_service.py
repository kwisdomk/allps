"""IntakeService — external system ingestion and file import manifest orchestration.

Provides batch JSON record ingestion and CSV/JSON file import with:
- File-level SHA-256 deduplication via ImportManifest
- Record-level Level 1 (source_event_id) and Level 2 (canonical_fingerprint) dedup
- Per-record validation isolation (bad rows are reported without crashing valid rows)
- Zero invented psychometric or comparability defaults
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
from typing import Any

from pydantic import BaseModel, Field

from allps.models.audit import AuditEntry
from allps.models.import_manifest import ImportManifest
from allps.services.evidence_service import EvidenceService
from allps.storage.sqlite_store import SQLiteStore


class DuplicateFileError(ValueError):
    """Raised when a file with the same SHA-256 and source_system was already imported."""

    def __init__(self, manifest: ImportManifest) -> None:
        self.manifest = manifest
        super().__init__(
            f"File '{manifest.file_name}' (SHA-256 {manifest.file_sha256[:12]}...) "
            f"from source '{manifest.source_system}' was already imported "
            f"as manifest '{manifest.manifest_id}'."
        )


class IntakeBatchSummary(BaseModel):
    """Structured result for batch/record ingestion."""

    source_system: str | None = None
    total: int
    accepted_count: int
    duplicate_count: int
    rejected_count: int
    results: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class FileImportSummary(BaseModel):
    """Structured result for file-level import with manifest metadata."""

    manifest: ImportManifest
    results: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


_NUMERIC_INT_OR_FLOAT_FIELDS = {
    "score",
    "max_score",
    "value",
    "days_present",
    "days_total",
    "max_level",
}

_BOOL_FIELDS = {
    "comparison_authorized",
    "comparable",
    "is_comparable",
}

_STRING_CONTENT_FIELDS = {
    "grade",
    "school_level",
    "assessment_stage",
    "stage",
    "assessment_event",
    "assessment_name",
    "form",
    "form_version",
    "version",
    "language",
    "measured_skill",
    "sampled_content",
    "skill",
    "kind",
    "purpose",
    "rubric",
    "rubric_name",
    "rubric_version",
    "level",
    "ordinal_level",
    "rubric_level",
    "unit",
    "status",
    "reason",
    "note",
    "observation",
    "reflection",
    "context",
    "project_title",
    "summary",
    "learning_area",
}


_WIDE_META_ALIASES: dict[str, str] = {
    "learner_id": "learner_id",
    "student_id": "learner_id",
    "admission_no": "learner_id",
    "adm_no": "learner_id",
    "reg_no": "learner_id",
    "pupil_id": "learner_id",
    "learner_display_name": "learner_display_name",
    "learner_name": "learner_display_name",
    "student_name": "learner_display_name",
    "pupil_name": "learner_display_name",
    "name": "learner_display_name",
    "full_name": "learner_display_name",
    "class_id": "class_id",
    "class": "class_id",
    "class_code": "class_id",
    "academic_year": "academic_year",
    "year": "academic_year",
    "term": "term",
    "academic_term": "term",
    "observed_at": "observed_at",
    "assessment_date": "observed_at",
    "exam_date": "observed_at",
    "date": "observed_at",
    "source_system": "source_system",
    "source_reference": "source_reference",
    "source_type": "source_type",
    "ingestion_method": "ingestion_method",
    "source_event_id": "source_event_id",
    "grade": "grade",
    "class_level": "grade",
    "assessment_stage": "assessment_stage",
    "stage": "assessment_stage",
    "form": "form",
    "assessment_name": "form",
    "assessment_event": "form",
    "exam_name": "form",
    "paper": "form",
    "form_version": "form_version",
    "version": "form_version",
    "language": "language",
    "measured_skill": "measured_skill",
    "skill": "measured_skill",
    "sampled_content": "measured_skill",
    "comparison_authorized": "comparison_authorized",
    "comparable": "comparison_authorized",
    "is_comparable": "comparison_authorized",
    "max_score": "max_score",
    "out_of": "max_score",
}

_WIDE_IGNORED_SUMMARY_COLS = {
    "total",
    "total_score",
    "total_marks",
    "sum",
    "average",
    "mean",
    "mean_score",
    "percentage",
    "overall_grade",
    "grade_overall",
    "rank",
    "position",
    "class_position",
    "remarks",
    "teacher_remarks",
    "comments",
    "comment",
}

_WIDE_MISSING_STATUS_MAP: dict[str, tuple[str, str]] = {
    "abs": ("absent", "Marked absent in native school mark sheet"),
    "absent": ("absent", "Marked absent in native school mark sheet"),
    "na": ("assessment_not_administered", "Marked not administered in native school mark sheet"),
    "n/a": ("assessment_not_administered", "Marked not administered in native school mark sheet"),
    "not_administered": ("assessment_not_administered", "Marked not administered in native school mark sheet"),
    "not_assessed": ("assessment_not_administered", "Marked not assessed in native school mark sheet"),
    "assessment_not_administered": ("assessment_not_administered", "Marked not administered in native school mark sheet"),
    "ns": ("not_submitted", "Marked not submitted in native school mark sheet"),
    "not_submitted": ("not_submitted", "Marked not submitted in native school mark sheet"),
    "unavail": ("result_unavailable", "Marked result unavailable in native school mark sheet"),
    "unavailable": ("result_unavailable", "Marked result unavailable in native school mark sheet"),
    "result_unavailable": ("result_unavailable", "Marked result unavailable in native school mark sheet"),
    "pending": ("result_unavailable", "Marked result pending/unavailable in native school mark sheet"),
}

_SUBJECT_MAX_HEADER_RE = re.compile(
    r"^(?P<subject>.+?)\s*(?:\(\s*(?:out\s+of\s+)?(?P<p_max>\d+(?:\.\d+)?)\s*\)|\[\s*(?P<b_max>\d+(?:\.\d+)?)\s*\]|/\s*(?P<s_max>\d+(?:\.\d+)?))\s*$",
    re.IGNORECASE,
)
_PAIRED_MAX_HEADER_RE = re.compile(
    r"^(?P<subject>.+?)(?:_max_score|_max|\s+max\s+score|\s+max|\s+out\s+of)$",
    re.IGNORECASE,
)
_FRACTION_SCORE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*$")
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TERM_RE = re.compile(r"^(?:term|t)?[\s_-]*(\d+)$", re.IGNORECASE)


def _normalize_header_key(col: str) -> str:
    return re.sub(r"[\s\-]+", "_", col.strip().lower()).strip("_")


def _parse_number(raw: str) -> int | float | str:
    """Parse integer or finite float from CSV cell; return original string on failure."""
    text = raw.strip()
    try:
        if "." not in text and "e" not in text.lower():
            return int(text)
        val = float(text)
        return val
    except ValueError:
        return text


def _parse_bool(raw: str) -> bool | str:
    """Parse explicit boolean string; return original string if unrecognized."""
    lowered = raw.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    return raw.strip()


def _parse_int_required(val: Any, field_name: str) -> int:
    if isinstance(val, bool):
        raise ValueError(f"Field '{field_name}' must be an integer, not boolean.")
    if isinstance(val, int):
        return val
    if isinstance(val, str) and val.strip():
        try:
            return int(val.strip())
        except ValueError as exc:
            raise ValueError(f"Field '{field_name}' must be an integer: '{val}'.") from exc
    raise ValueError(f"Missing required integer field '{field_name}'.")


def _parse_term_value(val: Any) -> int | str | None:
    """Parse term like 1, '2', 'Term 3', 'T1' into int when possible."""
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    text = str(val).strip()
    if not text:
        return None
    m = _TERM_RE.match(text)
    if m:
        return int(m.group(1))
    return text


def _normalize_observed_at(val: Any) -> str | None:
    """Normalize date-only (YYYY-MM-DD) or naive ISO strings to UTC ISO-8601."""
    if val is None:
        return None
    text = str(val).strip()
    if not text:
        return None
    if _DATE_ONLY_RE.match(text):
        return f"{text}T00:00:00Z"
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return text


def _parse_subject_header(raw_col: str) -> tuple[str, int | float | None, bool]:
    """Return (subject_name, inline_max_score, is_paired_max_column)."""
    cleaned = raw_col.strip()
    paired = _PAIRED_MAX_HEADER_RE.match(cleaned)
    if paired:
        return paired.group("subject").strip(), None, True
    matched = _SUBJECT_MAX_HEADER_RE.match(cleaned)
    if matched:
        raw_max = matched.group("p_max") or matched.group("b_max") or matched.group("s_max")
        parsed_max = _parse_number(raw_max)
        if isinstance(parsed_max, (int, float)):
            return matched.group("subject").strip(), parsed_max, False
    return cleaned, None, False


class IntakeService:
    """Coordinates external system record ingestion and file-level imports."""

    def __init__(self, evidence_service: EvidenceService, store: SQLiteStore) -> None:
        self._evidence_service = evidence_service
        self._store = store

    async def ingest_records(
        self,
        records: list[dict[str, Any]],
        *,
        default_source_system: str | None = None,
        default_ingestion_method: str = "api",
        default_source_type: str = "system",
        default_source_reference: str | None = None,
        default_class_id: str | None = None,
        enforce_class_id: str | None = None,
        allowed_subjects: set[str] | None = None,
        record_audit: bool = True,
    ) -> IntakeBatchSummary:
        """Ingest a batch of structured evidence records via EvidenceService."""
        accepted_count = 0
        duplicate_count = 0
        rejected_count = 0
        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        subject_lookup = {s.lower(): s for s in allowed_subjects} if allowed_subjects is not None else None

        for idx, raw_rec in enumerate(records):
            if not isinstance(raw_rec, dict):
                rejected_count += 1
                errors.append({"index": idx, "error": "Record must be a JSON object."})
                continue

            learner_id = raw_rec.get("learner_id")
            source_event_id = raw_rec.get("source_event_id")

            try:
                if raw_rec.get("__row_error__"):
                    raise ValueError(str(raw_rec["__row_error__"]))

                if not learner_id or not isinstance(learner_id, str) or not learner_id.strip():
                    raise ValueError("Missing required non-empty 'learner_id'.")

                raw_row_class = raw_rec.get("class_id")
                if enforce_class_id is not None and isinstance(raw_row_class, str) and raw_row_class.strip():
                    if raw_row_class.strip() != enforce_class_id:
                        raise ValueError(
                            f"Record class_id '{raw_row_class.strip()}' does not match target class '{enforce_class_id}'."
                        )

                raw_class_id = raw_row_class or default_class_id
                target_class_id = (
                    raw_class_id.strip()
                    if isinstance(raw_class_id, str) and raw_class_id.strip()
                    else None
                )
                if target_class_id is not None:
                    school_cls = await self._store.get_class(target_class_id)
                    if school_cls is None:
                        raise ValueError(f"Unknown class '{target_class_id}'.")

                evidence_type = raw_rec.get("evidence_type")
                if not evidence_type or not isinstance(evidence_type, str):
                    raise ValueError("Missing required 'evidence_type'.")

                source_system = raw_rec.get("source_system") or default_source_system
                if not source_system or not isinstance(source_system, str) or not source_system.strip():
                    raise ValueError("Missing required 'source_system'.")

                ingestion_method = raw_rec.get("ingestion_method") or default_ingestion_method
                source_type = raw_rec.get("source_type") or default_source_type
                source_reference = (
                    raw_rec.get("source_reference")
                    or default_source_reference
                    or source_system.strip()
                )

                academic_year = _parse_int_required(raw_rec.get("academic_year"), "academic_year")
                term = _parse_int_required(raw_rec.get("term"), "term")

                observed_at = raw_rec.get("observed_at")
                if not observed_at:
                    raise ValueError("Missing required 'observed_at' timestamp.")

                content = raw_rec.get("content")
                if not isinstance(content, dict):
                    raise ValueError("Field 'content' must be a JSON object.")

                subject = raw_rec.get("subject")
                if isinstance(subject, str):
                    subject = subject.strip() or None
                if subject_lookup is not None:
                    if not subject or subject.lower() not in subject_lookup:
                        allowed_list = ", ".join(sorted(subject_lookup.values())) or "none"
                        raise ValueError(
                            f"Subject '{subject or 'general'}' is outside your assigned subjects ({allowed_list})."
                        )
                    subject = subject_lookup[subject.lower()]

                learner_display_name = raw_rec.get("learner_display_name")

                ev, outcome = await self._evidence_service.record_evidence_with_status(
                    learner_id=learner_id.strip(),
                    evidence_type=evidence_type.strip(),
                    source_system=source_system.strip(),
                    ingestion_method=str(ingestion_method).strip(),
                    source_type=str(source_type).strip(),
                    source_reference=str(source_reference).strip(),
                    academic_year=academic_year,
                    term=term,
                    subject=subject,
                    content=content,
                    observed_at=observed_at,
                    source_event_id=(
                        str(source_event_id).strip()
                        if source_event_id is not None and str(source_event_id).strip()
                        else None
                    ),
                    learner_display_name=learner_display_name,
                )
                if target_class_id is not None:
                    await self._store.enroll_learner(target_class_id, ev.learner_id)

                if outcome == "created":
                    accepted_count += 1
                else:
                    duplicate_count += 1

                results.append({
                    "index": idx,
                    "status": outcome,
                    "evidence_id": ev.evidence_id,
                    "learner_id": ev.learner_id,
                    "subject": ev.subject,
                    "source_event_id": ev.source_event_id,
                })
            except Exception as exc:
                rejected_count += 1
                errors.append({
                    "index": idx,
                    "learner_id": learner_id,
                    "subject": raw_rec.get("subject"),
                    "source_event_id": source_event_id,
                    "error": str(exc),
                })

        if record_audit:
            audit = AuditEntry(
                tool_name="ingest_records",
                input_summary={
                    "source_system": default_source_system,
                    "total": len(records),
                    "accepted_count": accepted_count,
                    "duplicate_count": duplicate_count,
                    "rejected_count": rejected_count,
                },
                output_reference=f"accepted={accepted_count},duplicate={duplicate_count},rejected={rejected_count}",
            )
            await self._store.add_audit_entry(audit)

        return IntakeBatchSummary(
            source_system=default_source_system,
            total=len(records),
            accepted_count=accepted_count,
            duplicate_count=duplicate_count,
            rejected_count=rejected_count,
            results=results,
            errors=errors,
        )

    @staticmethod
    def _parse_json_export(text: str, source_system: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Parse JSON export payload (either {export_meta, records} or list of records)."""
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed JSON file: {exc}") from exc

        meta: dict[str, Any] = {}
        if isinstance(payload, list):
            raw_records = payload
        elif isinstance(payload, dict):
            if not isinstance(payload.get("records"), list):
                raise ValueError("JSON import object must contain a 'records' array.")
            raw_records = payload["records"]
            if isinstance(payload.get("export_meta"), dict):
                meta = payload["export_meta"]
        else:
            raise ValueError("JSON import must be a list of records or an object with 'records'.")

        if not raw_records:
            raise ValueError("Import file contains zero records.")

        normalized: list[dict[str, Any]] = []
        for rec in raw_records:
            if not isinstance(rec, dict):
                normalized.append(rec)
                continue
            merged = dict(rec)
            merged.setdefault("source_system", meta.get("source_system") or source_system)
            if "academic_year" not in merged and meta.get("academic_year") is not None:
                merged["academic_year"] = meta["academic_year"]
            if "term" not in merged and meta.get("term") is not None:
                merged["term"] = meta["term"]
            if "source_reference" not in merged and meta.get("originating_teacher"):
                merged["source_reference"] = meta["originating_teacher"]
            if "class_id" not in merged and meta.get("class_id"):
                merged["class_id"] = meta["class_id"]
            normalized.append(merged)

        return normalized, meta

    @staticmethod
    def _is_wide_marksheet_csv(fieldnames: list[str]) -> bool:
        """Detect wide school mark-sheet CSV (one row per learner, subjects as columns)."""
        normalized = {_normalize_header_key(col) for col in fieldnames if col and col.strip()}
        if "evidence_type" in normalized or "content" in normalized:
            return False
        learner_keys = {"learner_id", "student_id", "admission_no", "adm_no", "reg_no", "pupil_id"}
        return bool(normalized & learner_keys)

    @staticmethod
    def _parse_wide_marksheet_csv(
        text: str,
        source_system: str,
        import_method: str,
        *,
        default_academic_year: int | None = None,
        default_term: int | None = None,
        default_observed_at: str | None = None,
        default_max_score: int | float | None = None,
        default_grade: str | None = None,
        default_assessment_stage: str | None = None,
        default_form: str | None = None,
        default_form_version: str | None = None,
        default_language: str | None = None,
        default_comparison_authorized: bool | None = None,
        default_source_reference: str | None = None,
    ) -> list[dict[str, Any]]:
        """Unpivot wide school mark-sheet rows (one row per learner) into canonical assessment records."""
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError("CSV file is empty or missing a header row.")

        rows = list(reader)
        if not rows:
            raise ValueError("CSV file contains no data rows.")

        meta_columns: dict[str, str] = {}
        paired_max_columns: dict[str, str] = {}
        subject_columns: list[tuple[str, str, int | float | None]] = []

        for raw_col in reader.fieldnames:
            if not raw_col or not raw_col.strip():
                continue
            norm = _normalize_header_key(raw_col)
            if norm in _WIDE_META_ALIASES:
                meta_columns[raw_col] = _WIDE_META_ALIASES[norm]
                continue
            if norm in _WIDE_IGNORED_SUMMARY_COLS:
                continue
            subj_name, inline_max, is_paired_max = _parse_subject_header(raw_col)
            if is_paired_max:
                paired_max_columns[_normalize_header_key(subj_name)] = raw_col
            else:
                subject_columns.append((raw_col, subj_name, inline_max))

        if not subject_columns:
            raise ValueError(
                "Wide mark-sheet CSV contains no subject score columns. "
                "Add at least one subject column (e.g. 'Mathematics (100)' or 'English')."
            )

        norm_default_obs = _normalize_observed_at(default_observed_at)
        parsed_records: list[dict[str, Any]] = []

        for row_idx, row in enumerate(rows, start=2):
            meta_vals: dict[str, Any] = {}
            for raw_col, meta_key in meta_columns.items():
                raw_v = row.get(raw_col)
                if raw_v is None:
                    continue
                val = raw_v.strip() if isinstance(raw_v, str) else raw_v
                if val != "":
                    meta_vals.setdefault(meta_key, val)

            learner_id = meta_vals.get("learner_id")
            academic_year = meta_vals.get("academic_year") if "academic_year" in meta_vals else default_academic_year
            raw_term = meta_vals.get("term") if "term" in meta_vals else default_term
            term = _parse_term_value(raw_term)
            observed_at = _normalize_observed_at(meta_vals.get("observed_at")) or norm_default_obs

            row_max_score: int | float | None = default_max_score
            if "max_score" in meta_vals:
                parsed_row_max = _parse_number(str(meta_vals["max_score"]))
                if isinstance(parsed_row_max, (int, float)):
                    row_max_score = parsed_row_max

            comp_auth = default_comparison_authorized
            if "comparison_authorized" in meta_vals:
                parsed_bool = _parse_bool(str(meta_vals["comparison_authorized"]))
                if isinstance(parsed_bool, bool):
                    comp_auth = parsed_bool

            base_content: dict[str, Any] = {}
            for key, fallback in (
                ("grade", default_grade),
                ("assessment_stage", default_assessment_stage),
                ("form", default_form),
                ("form_version", default_form_version),
                ("language", default_language),
                ("measured_skill", None),
            ):
                chosen = meta_vals.get(key) or fallback
                if isinstance(chosen, str) and chosen.strip():
                    base_content[key] = chosen.strip()
            if comp_auth is not None:
                base_content["comparison_authorized"] = comp_auth

            row_source_system = meta_vals.get("source_system") or source_system
            row_source_ref = meta_vals.get("source_reference") or default_source_reference or row_source_system
            row_ingestion_method = meta_vals.get("ingestion_method") or import_method
            row_source_type = meta_vals.get("source_type") or "system"
            row_event_prefix = meta_vals.get("source_event_id")

            row_emitted = 0
            for raw_col, subj_name, inline_max in subject_columns:
                raw_cell = row.get(raw_col)
                if raw_cell is None:
                    continue
                cell = str(raw_cell).strip()
                if cell in ("", "-", "—"):
                    continue

                row_emitted += 1
                paired_col = paired_max_columns.get(_normalize_header_key(subj_name))
                col_max_score = inline_max
                if paired_col and row.get(paired_col):
                    paired_val = _parse_number(str(row[paired_col]))
                    if isinstance(paired_val, (int, float)):
                        col_max_score = paired_val

                content = dict(base_content)
                row_error: str | None = None

                frac_match = _FRACTION_SCORE_RE.match(cell)
                lowered_cell = cell.lower()
                if frac_match:
                    content["score"] = _parse_number(frac_match.group(1))
                    content["max_score"] = _parse_number(frac_match.group(2))
                elif lowered_cell in _WIDE_MISSING_STATUS_MAP:
                    status_code, reason_text = _WIDE_MISSING_STATUS_MAP[lowered_cell]
                    content["status"] = status_code
                    content["reason"] = reason_text
                else:
                    parsed_score = _parse_number(cell)
                    if isinstance(parsed_score, (int, float)):
                        resolved_max = col_max_score if col_max_score is not None else row_max_score
                        if resolved_max is None:
                            row_error = (
                                f"Row {row_idx}: missing max_score for subject '{subj_name}' "
                                "(specify in header e.g. 'Mathematics (100)', as '78/100', or in the Max Score field)."
                            )
                        else:
                            content["score"] = parsed_score
                            content["max_score"] = resolved_max
                    else:
                        row_error = (
                            f"Row {row_idx}: unrecognized mark or status '{cell}' for subject '{subj_name}'."
                        )

                record: dict[str, Any] = {
                    "learner_id": learner_id,
                    "learner_display_name": meta_vals.get("learner_display_name"),
                    "class_id": meta_vals.get("class_id"),
                    "evidence_type": "assessment",
                    "source_system": row_source_system,
                    "ingestion_method": row_ingestion_method,
                    "source_event_id": f"{row_event_prefix}:{subj_name}" if row_event_prefix else None,
                    "source_type": row_source_type,
                    "source_reference": row_source_ref,
                    "academic_year": academic_year,
                    "term": term,
                    "subject": subj_name,
                    "observed_at": observed_at,
                    "content": content,
                }
                if row_error:
                    record["__row_error__"] = row_error
                parsed_records.append(record)

            if row_emitted == 0:
                parsed_records.append({
                    "learner_id": learner_id,
                    "learner_display_name": meta_vals.get("learner_display_name"),
                    "class_id": meta_vals.get("class_id"),
                    "evidence_type": "assessment",
                    "academic_year": academic_year,
                    "term": term,
                    "observed_at": observed_at,
                    "content": {},
                    "__row_error__": f"Row {row_idx}: contains no subject scores or missing-outcome statuses.",
                })

        return parsed_records

    @staticmethod
    def _parse_csv_export(text: str, source_system: str, import_method: str) -> list[dict[str, Any]]:
        """Parse CSV rows into canonical record dicts without inventing defaults."""
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError("CSV file is empty or missing a header row.")

        rows = list(reader)
        if not rows:
            raise ValueError("CSV file contains no data rows.")

        parsed_records: list[dict[str, Any]] = []
        for row in rows:
            clean = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k is not None}

            if clean.get("content"):
                try:
                    content = json.loads(clean["content"])
                except json.JSONDecodeError as exc:
                    # Keep malformed indicator so per-row error reporting handles it cleanly
                    content = {"__parse_error__": str(exc)}
            else:
                content = {}
                for k, v in clean.items():
                    if v is None or v == "":
                        continue
                    if k in _NUMERIC_INT_OR_FLOAT_FIELDS:
                        content[k] = _parse_number(v)
                    elif k in _BOOL_FIELDS:
                        content[k] = _parse_bool(v)
                    elif k == "scale":
                        if v.startswith("["):
                            try:
                                content[k] = json.loads(v)
                            except json.JSONDecodeError:
                                content[k] = v
                        else:
                            content[k] = v
                    elif k in _STRING_CONTENT_FIELDS:
                        content[k] = v

            if isinstance(content, dict) and "__parse_error__" in content:
                rec_content: Any = f"Invalid JSON in content column: {content['__parse_error__']}"
            else:
                rec_content = content

            record: dict[str, Any] = {
                "learner_id": clean.get("learner_id"),
                "learner_display_name": clean.get("learner_display_name") or None,
                "class_id": clean.get("class_id") or None,
                "evidence_type": clean.get("evidence_type"),
                "source_system": clean.get("source_system") or source_system,
                "ingestion_method": clean.get("ingestion_method") or import_method,
                "source_event_id": clean.get("source_event_id") or None,
                "source_type": clean.get("source_type") or "system",
                "source_reference": clean.get("source_reference") or source_system,
                "academic_year": clean.get("academic_year"),
                "term": clean.get("term"),
                "subject": clean.get("subject") or None,
                "observed_at": clean.get("observed_at"),
                "content": rec_content,
            }
            parsed_records.append(record)

        return parsed_records

    async def ingest_file(
        self,
        *,
        file_bytes: bytes,
        file_name: str,
        source_system: str,
        import_method: str = "csv_import",
        imported_by: str | None = None,
        notes: str | None = None,
        default_class_id: str | None = None,
        enforce_class_id: str | None = None,
        allowed_subjects: set[str] | None = None,
        default_academic_year: int | None = None,
        default_term: int | None = None,
        default_observed_at: str | None = None,
        default_max_score: int | float | None = None,
        default_grade: str | None = None,
        default_assessment_stage: str | None = None,
        default_form: str | None = None,
        default_form_version: str | None = None,
        default_language: str | None = None,
        default_comparison_authorized: bool | None = None,
        default_source_reference: str | None = None,
    ) -> FileImportSummary:
        """Import a CSV (canonical or wide mark-sheet) or JSON school export file with SHA-256 manifest tracking."""
        if not file_bytes:
            raise ValueError("Uploaded file is empty.")

        clean_source = source_system.strip()
        if not clean_source:
            raise ValueError("source_system must be non-empty.")

        file_sha256 = hashlib.sha256(file_bytes).hexdigest()

        # File-level deduplication check before parsing/ingesting rows
        existing_manifest = await self._store.get_import_manifest_by_hash(file_sha256, clean_source)
        if existing_manifest is not None:
            raise DuplicateFileError(existing_manifest)

        try:
            text = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError(f"Import file must be UTF-8 encoded: {exc}") from exc

        ext = Path(file_name).suffix.lower()
        stripped = text.lstrip()
        if not stripped:
            raise ValueError("Uploaded file is empty.")

        if ext == ".json" or (not ext and stripped.startswith(("{", "["))):
            records, meta = self._parse_json_export(text, clean_source)
            default_ref = meta.get("originating_teacher") or default_source_reference or clean_source
            default_method = import_method or "api"
        elif ext == ".csv" or (not ext and "," in stripped.splitlines()[0]):
            header_reader = csv.DictReader(io.StringIO(text))
            fieldnames = list(header_reader.fieldnames or [])
            if self._is_wide_marksheet_csv(fieldnames):
                records = self._parse_wide_marksheet_csv(
                    text,
                    clean_source,
                    import_method,
                    default_academic_year=default_academic_year,
                    default_term=default_term,
                    default_observed_at=default_observed_at,
                    default_max_score=default_max_score,
                    default_grade=default_grade,
                    default_assessment_stage=default_assessment_stage,
                    default_form=default_form,
                    default_form_version=default_form_version,
                    default_language=default_language,
                    default_comparison_authorized=default_comparison_authorized,
                    default_source_reference=default_source_reference,
                )
            else:
                records = self._parse_csv_export(text, clean_source, import_method)
            default_ref = default_source_reference or clean_source
            default_method = import_method
        else:
            raise ValueError(
                f"Unsupported import file format for '{file_name}'. Expected .csv or .json."
            )

        batch = await self.ingest_records(
            records,
            default_source_system=clean_source,
            default_ingestion_method=default_method,
            default_source_type="system",
            default_source_reference=default_ref,
            default_class_id=default_class_id,
            enforce_class_id=enforce_class_id,
            allowed_subjects=allowed_subjects,
            record_audit=False,
        )

        manifest = ImportManifest(
            source_system=clean_source,
            file_name=Path(file_name).name or "upload",
            import_method=import_method,
            file_sha256=file_sha256,
            row_count=batch.total,
            accepted_count=batch.accepted_count,
            rejected_count=batch.rejected_count,
            duplicate_count=batch.duplicate_count,
            imported_by=imported_by,
            imported_at=datetime.now(timezone.utc),
            notes=notes,
        )

        manifest_persisted = False
        if batch.accepted_count > 0 or batch.duplicate_count > 0:
            try:
                await self._store.add_import_manifest(manifest)
                manifest_persisted = True
            except ValueError as exc:
                existing = await self._store.get_import_manifest_by_hash(file_sha256, clean_source)
                if existing is not None:
                    raise DuplicateFileError(existing) from exc
                raise

        audit = AuditEntry(
            tool_name="ingest_file",
            input_summary={
                "manifest_id": manifest.manifest_id if manifest_persisted else None,
                "source_system": manifest.source_system,
                "file_name": manifest.file_name,
                "file_sha256": manifest.file_sha256,
                "row_count": manifest.row_count,
                "accepted_count": manifest.accepted_count,
                "duplicate_count": manifest.duplicate_count,
                "rejected_count": manifest.rejected_count,
                "imported_by": imported_by,
            },
            output_reference=manifest.manifest_id if manifest_persisted else "rejected_all",
        )
        await self._store.add_audit_entry(audit)

        return FileImportSummary(
            manifest=manifest,
            results=batch.results,
            errors=batch.errors,
        )

