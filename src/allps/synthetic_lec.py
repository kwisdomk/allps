"""Add the frozen fictional LEC pilot through the normal deduplicating importer."""
from pathlib import Path
import hashlib
import json

from allps.models.handover import SchoolClass, TeacherAssignment
from allps.services.evidence_service import EvidenceService
from allps.services.intake_service import IntakeService
from allps.storage.sqlite_store import SQLiteStore


async def seed_lec_demo(store: SQLiteStore) -> None:
    root = Path(__file__).with_name("data") / "lec"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["sha256"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Frozen LEC dataset checksum mismatch: {name}")
    reference = json.loads((root / "reference.json").read_text(encoding="utf-8"))
    # Reuse provisioned demo logins; never create the smoke-test PIN accounts.
    teachers = {"SMOKE-TCH-01": "TCH-OCHIENG", "SMOKE-TCH-02": "TCH-KAMAU"}
    for teacher_id in (*teachers.values(), "TCH-BANDA"):
        if await store.get_teacher(teacher_id) is None:
            raise ValueError(f"LEC demo requires provisioned educator {teacher_id}")
    for row in reference["classes"]:
        await store.add_class(SchoolClass(**row))
    for row in reference["assignments"]:
        await store.add_teacher_assignment(TeacherAssignment(**{
            **row, "teacher_id": teachers[row["teacher_id"]],
        }))
        await store.add_teacher_assignment(TeacherAssignment(
            assignment_id=f"LEC-MATH-{row['class_id']}",
            class_id=row["class_id"], teacher_id="TCH-BANDA",
            role="subject_teacher", subject="Mathematics",
        ))
    records = json.loads((root / "allps_evidence.json").read_text(encoding="utf-8"))["records"]
    result = await IntakeService(EvidenceService(store), store).ingest_records(records)
    if result.rejected_count:
        raise ValueError(f"LEC demo intake rejected records: {result.errors}")
