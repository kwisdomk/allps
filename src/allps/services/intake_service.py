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
        record_audit: bool = True,
    ) -> IntakeBatchSummary:
        """Ingest a batch of structured evidence records via EvidenceService."""
        accepted_count = 0
        duplicate_count = 0
        rejected_count = 0
        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for idx, raw_rec in enumerate(records):
            if not isinstance(raw_rec, dict):
                rejected_count += 1
                errors.append({"index": idx, "error": "Record must be a JSON object."})
                continue

            learner_id = raw_rec.get("learner_id")
            source_event_id = raw_rec.get("source_event_id")

            try:
                if not learner_id or not isinstance(learner_id, str) or not learner_id.strip():
                    raise ValueError("Missing required non-empty 'learner_id'.")

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

                if outcome == "created":
                    accepted_count += 1
                else:
                    duplicate_count += 1

                results.append({
                    "index": idx,
                    "status": outcome,
                    "evidence_id": ev.evidence_id,
                    "learner_id": ev.learner_id,
                    "source_event_id": ev.source_event_id,
                })
            except Exception as exc:
                rejected_count += 1
                errors.append({
                    "index": idx,
                    "learner_id": learner_id,
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
            normalized.append(merged)

        return normalized, meta

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
    ) -> FileImportSummary:
        """Import a CSV or JSON school export file with file-level SHA-256 manifest tracking."""
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

        if ext == ".json" or (not ext and stripped.startswith(("{", "["))):
            records, meta = self._parse_json_export(text, clean_source)
            default_ref = meta.get("originating_teacher") or clean_source
            default_method = import_method or "api"
        elif ext == ".csv" or (not ext and "," in stripped.splitlines()[0]):
            records = self._parse_csv_export(text, clean_source, import_method)
            default_ref = clean_source
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

        try:
            await self._store.add_import_manifest(manifest)
        except ValueError as exc:
            existing = await self._store.get_import_manifest_by_hash(file_sha256, clean_source)
            if existing is not None:
                raise DuplicateFileError(existing) from exc
            raise

        audit = AuditEntry(
            tool_name="ingest_file",
            input_summary={
                "manifest_id": manifest.manifest_id,
                "source_system": manifest.source_system,
                "file_name": manifest.file_name,
                "file_sha256": manifest.file_sha256,
                "row_count": manifest.row_count,
                "accepted_count": manifest.accepted_count,
                "duplicate_count": manifest.duplicate_count,
                "rejected_count": manifest.rejected_count,
                "imported_by": imported_by,
            },
            output_reference=manifest.manifest_id,
        )
        await self._store.add_audit_entry(audit)

        return FileImportSummary(
            manifest=manifest,
            results=batch.results,
            errors=batch.errors,
        )

