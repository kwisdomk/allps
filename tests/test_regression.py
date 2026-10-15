import asyncio
import sqlite3
from datetime import datetime, timezone
import pytest

from allps.models import Evidence, EvidenceType, IngestionMethod, Learner
from allps.storage.sqlite_store import SQLiteStore
from allps.services.evidence_service import EvidenceService

from data.synthetic.seed_data import seed_database


@pytest.fixture
async def store(tmp_path):
    db_path = str(tmp_path / "test.db")
    s = SQLiteStore(db_path)
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
def service(store):
    return EvidenceService(store)


@pytest.mark.asyncio
async def test_migration_adds_source_event_id(tmp_path):
    # Create DB without source_event_id
    db_path = str(tmp_path / "old.db")
    import aiosqlite
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """CREATE TABLE evidence (
                evidence_id TEXT PRIMARY KEY,
                learner_id TEXT NOT NULL,
                evidence_type TEXT NOT NULL,
                source_system TEXT NOT NULL,
                ingestion_method TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_reference TEXT NOT NULL,
                academic_year INTEGER NOT NULL,
                term INTEGER NOT NULL,
                subject TEXT,
                content TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                FOREIGN KEY (learner_id) REFERENCES learners(learner_id)
            )"""
        )
        await db.commit()

    # Now initialize store, it should migrate
    s = SQLiteStore(db_path)
    await s.initialize()

    # Check if column was added
    async with s.db.execute("PRAGMA table_info(evidence)") as cursor:
        columns = [row["name"] for row in await cursor.fetchall()]
    assert "source_event_id" in columns
    await s.close()


@pytest.mark.asyncio
async def test_idempotent_ingestion_retry(service):
    # First ingest
    ev1 = await service.record_evidence(
        learner_id="LRN-001",
        evidence_type="assessment",
        source_system="test_sys",
        ingestion_method="api",
        source_type="teacher",
        source_reference="Ref",
        academic_year=2025,
        term=1,
        content={"score": 50, "max_score": 100},
        observed_at="2025-01-01T12:00:00+00:00",
        source_event_id="EV-123"
    )

    # Identical retry should return the same record (silent success)
    ev2 = await service.record_evidence(
        learner_id="LRN-001",
        evidence_type="assessment",
        source_system="test_sys",
        ingestion_method="api",
        source_type="teacher",
        source_reference="Ref",
        academic_year=2025,
        term=1,
        content={"score": 50, "max_score": 100},
        observed_at="2025-01-01T12:00:00+00:00",
        source_event_id="EV-123"
    )
    assert ev1.evidence_id == ev2.evidence_id

    # Modified content with same event_id should fail
    with pytest.raises(ValueError, match="Conflict: event EV-123 already exists with different content"):
        await service.record_evidence(
            learner_id="LRN-001",
            evidence_type="assessment",
            source_system="test_sys",
            ingestion_method="api",
            source_type="teacher",
            source_reference="Ref",
            academic_year=2025,
            term=1,
            content={"score": 90, "max_score": 100},
            observed_at="2025-01-01T12:00:00+00:00",
            source_event_id="EV-123"
        )


@pytest.mark.asyncio
async def test_concurrent_transactions(service):
    # Try multiple ingestions simultaneously
    tasks = []
    for i in range(5):
        tasks.append(
            service.record_evidence(
                learner_id="LRN-001",
                evidence_type="assessment",
                source_system="concurrent_sys",
                ingestion_method="api",
                source_type="teacher",
                source_reference="Ref",
                academic_year=2025,
                term=1,
                content={"score": 50 + i, "max_score": 100},
                observed_at="2025-01-01T12:00:00+00:00",
                source_event_id=f"EV-C-{i}"
            )
        )
    
    results = await asyncio.gather(*tasks)
    assert len(results) == 5


@pytest.mark.asyncio
async def test_rollback_on_validation_failure(service):
    # Provoke an error (missing status for attendance)
    with pytest.raises(ValueError):
        await service.record_evidence(
            learner_id="LRN-BAD",
            evidence_type="attendance",
            source_system="sys",
            ingestion_method="api",
            source_type="system",
            source_reference="Ref",
            academic_year=2025,
            term=1,
            content={"wrong_key": 1},
            observed_at="2025-01-01T12:00:00+00:00"
        )
    
    # Check learner was NOT created (rollback)
    assert not await service._store.learner_exists("LRN-BAD")


@pytest.mark.asyncio
async def test_seed_script(tmp_path):
    db_path = str(tmp_path / "seed.db")
    await seed_database(db_path)
    
    store = SQLiteStore(db_path)
    await store.initialize()
    
    # Check learner C exists
    l = await store.get_learner("LRN-003")
    assert l is not None
    
    # Check some evidence
    evs = await store.get_evidence_for_learner("LRN-003")
    assert len(evs) > 0
    await store.close()


@pytest.mark.asyncio
async def test_full_observation_idempotency_conflicts(service, store):
    """Reusing an event key with different learner, year, term, subject, timestamp, type, or provenance must produce a conflict."""
    base_params = {
        "learner_id": "LRN-IDEMP",
        "evidence_type": "assessment",
        "source_system": "school_sis",
        "ingestion_method": "api",
        "source_type": "teacher",
        "source_reference": "Mr. Test",
        "academic_year": 2025,
        "term": 1,
        "subject": "Mathematics",
        "content": {"score": 85, "max_score": 100},
        "observed_at": "2025-03-15T10:00:00+00:00",
        "source_event_id": "EV-FULL-01",
    }
    ev1 = await service.record_evidence(**base_params)

    # 1. Conflict on different learner
    with pytest.raises(ValueError, match="Conflict: event EV-FULL-01 already exists with different learner"):
        await service.record_evidence(**{**base_params, "learner_id": "LRN-OTHER"})

    # 2. Conflict on different year
    with pytest.raises(ValueError, match="Conflict: event EV-FULL-01 already exists with different year"):
        await service.record_evidence(**{**base_params, "academic_year": 2026})

    # 3. Conflict on different term
    with pytest.raises(ValueError, match="Conflict: event EV-FULL-01 already exists with different term"):
        await service.record_evidence(**{**base_params, "term": 2})

    # 4. Conflict on different subject
    with pytest.raises(ValueError, match="Conflict: event EV-FULL-01 already exists with different subject"):
        await service.record_evidence(**{**base_params, "subject": "Science"})

    # 5. Conflict on different timestamp
    with pytest.raises(ValueError, match="Conflict: event EV-FULL-01 already exists with different timestamp"):
        await service.record_evidence(**{**base_params, "observed_at": "2025-03-16T10:00:00+00:00"})

    # 6. Conflict on different type
    with pytest.raises(ValueError, match="Conflict: event EV-FULL-01 already exists with different type"):
        await service.record_evidence(**{**base_params, "evidence_type": "observation", "content": {"note": "participating"}})

    # 7. Conflict on different provenance (source_reference)
    with pytest.raises(ValueError, match="Conflict: event EV-FULL-01 already exists with different provenance"):
        await service.record_evidence(**{**base_params, "source_reference": "Mrs. Other"})

    # 8. Conflict on different provenance (ingestion_method)
    with pytest.raises(ValueError, match="Conflict: event EV-FULL-01 already exists with different provenance"):
        await service.record_evidence(**{**base_params, "ingestion_method": "webhook"})

    # 9. Conflict on different provenance (source_type)
    with pytest.raises(ValueError, match="Conflict: event EV-FULL-01 already exists with different provenance"):
        await service.record_evidence(**{**base_params, "source_type": "system"})

    # 10. Conflict on different content
    with pytest.raises(ValueError, match="Conflict: event EV-FULL-01 already exists with different content"):
        await service.record_evidence(**{**base_params, "content": {"score": 90, "max_score": 100}})

    # 11. Identical retry returns original evidence and creates an audit entry
    initial_audits = len(await store.get_audit_log(tool_name="ingest_evidence"))
    retry_ev = await service.record_evidence(**base_params)
    assert retry_ev.evidence_id == ev1.evidence_id

    after_audits = await store.get_audit_log(tool_name="ingest_evidence")
    assert len(after_audits) == initial_audits + 1
    assert after_audits[-1].input_summary.get("retry") is True
    assert after_audits[-1].output_reference == ev1.evidence_id


@pytest.mark.asyncio
async def test_nested_serialization_round_trip_and_retry(service, store):
    """Immutable nested objects round-trip correctly and remain equal after retrieval, including retries."""
    nested_payload = {
        "rubric": {
            "criteria": ["decoding", "fluency", "comprehension"],
            "thresholds": [40, 60, 80],
        },
        "flags": ["intervention_needed", "tusome_early_reader"],
    }

    ev = await service.record_evidence(
        learner_id="LRN-NESTED",
        evidence_type="observation",
        source_system="allps",
        ingestion_method="manual_observation",
        source_type="teacher",
        source_reference="Mrs. Teacher",
        academic_year=2025,
        term=1,
        content=nested_payload,
        observed_at="2025-04-10T09:00:00+00:00",
        source_event_id="EV-NESTED-01",
    )

    # 1. Retrieve from storage directly
    retrieved = await store.get_evidence_by_source_event("allps", "EV-NESTED-01")
    assert retrieved is not None
    # Frozen objects compare equal
    assert retrieved.content == ev.content
    # Dumped content matches original JSON payload exactly
    assert retrieved.model_dump()["content"] == nested_payload
    assert retrieved.model_dump(mode="json")["content"] == nested_payload

    # 2. History retrieval
    history = await service.get_learner_history("LRN-NESTED")
    assert len(history) == 1
    assert history[0].content == ev.content
    assert history[0].model_dump()["content"] == nested_payload

    # 3. Retry with exact same payload containing lists
    retry_ev = await service.record_evidence(
        learner_id="LRN-NESTED",
        evidence_type="observation",
        source_system="allps",
        ingestion_method="manual_observation",
        source_type="teacher",
        source_reference="Mrs. Teacher",
        academic_year=2025,
        term=1,
        content=nested_payload,
        observed_at="2025-04-10T09:00:00+00:00",
        source_event_id="EV-NESTED-01",
    )
    assert retry_ev.evidence_id == ev.evidence_id


@pytest.mark.asyncio
async def test_transaction_ownership_deterministic_overlap(service, store):
    """Deterministic test: pauses ingestion after insertion, overlaps history query, forces audit failure.
    Failed ingestion must leave neither evidence nor a newly provisioned learner, and history must not expose uncommitted evidence.
    """
    inserted_event = asyncio.Event()
    resume_event = asyncio.Event()

    async def pause_hook():
        inserted_event.set()
        await resume_event.wait()

    service._after_insert_hook = pause_hook

    ingest_task = asyncio.create_task(
        service.record_evidence(
            learner_id="LRN-TX-ISOLATED",
            evidence_type="assessment",
            source_system="school_sis",
            ingestion_method="api",
            source_type="teacher",
            source_reference="Mr. Isolation",
            academic_year=2025,
            term=2,
            content={"score": 92, "max_score": 100},
            observed_at="2025-05-15T10:00:00+00:00",
            source_event_id="EV-TX-01",
        )
    )

    # 1. Wait until learner and evidence are inserted into active transaction
    await inserted_event.wait()

    # 2. Overlap a history query while ingestion is paused
    history_task = asyncio.create_task(
        service.get_learner_history("LRN-TX-ISOLATED")
    )
    # Yield control so history query executes its read
    await asyncio.sleep(0.05)

    # 3. Force the ingestion audit to fail and resume ingestion
    service._force_audit_fail = True
    resume_event.set()

    # Ingestion must fail
    with pytest.raises(Exception, match="Forced audit failure"):
        await ingest_task

    # History query completes
    history = await history_task

    # 4. Assertions:
    # History must NOT expose uncommitted evidence
    assert len(history) == 0, f"History exposed uncommitted evidence: {history}"

    # Database must leave NEITHER evidence NOR a newly provisioned learner
    assert not await store.learner_exists("LRN-TX-ISOLATED")
    evs_in_db = await store.get_evidence_for_learner("LRN-TX-ISOLATED")
    assert len(evs_in_db) == 0


@pytest.mark.asyncio
async def test_complete_outcome_logging(service, store):
    """Include timestamp parsing, timezone checks, enum validation, and retries in audited flow."""
    # 1. Invalid timestamp format
    with pytest.raises(ValueError):
        await service.record_evidence(
            learner_id="LRN-AUD-FAIL",
            evidence_type="assessment",
            source_system="sys",
            ingestion_method="api",
            source_type="teacher",
            source_reference="Ref",
            academic_year=2025,
            term=1,
            content={"score": 50, "max_score": 100},
            observed_at="not-a-valid-timestamp",
        )
    audits = await store.get_audit_log(tool_name="ingest_evidence")
    assert any("Failed:" in (a.output_reference or "") for a in audits)

    # 2. Timezone-free input
    with pytest.raises(ValueError, match="timezone-aware"):
        await service.record_evidence(
            learner_id="LRN-AUD-FAIL",
            evidence_type="assessment",
            source_system="sys",
            ingestion_method="api",
            source_type="teacher",
            source_reference="Ref",
            academic_year=2025,
            term=1,
            content={"score": 50, "max_score": 100},
            observed_at=datetime(2025, 1, 1, 10, 0, 0),  # naive
        )
    audits = await store.get_audit_log(tool_name="ingest_evidence")
    assert any("timezone-aware" in (a.output_reference or "") for a in audits)

    # 3. Invalid enum
    with pytest.raises(ValueError):
        await service.record_evidence(
            learner_id="LRN-AUD-FAIL",
            evidence_type="invalid_enum_type",
            source_system="sys",
            ingestion_method="api",
            source_type="teacher",
            source_reference="Ref",
            academic_year=2025,
            term=1,
            content={"score": 50, "max_score": 100},
            observed_at="2025-01-01T10:00:00+00:00",
        )
    audits = await store.get_audit_log(tool_name="ingest_evidence")
    assert any("invalid_enum_type" in (a.output_reference or "") for a in audits)


@pytest.mark.asyncio
async def test_audit_storage_failure_honest_rollback(service, store):
    """When audit storage fails within a transaction, preserve honest behavior: roll back evidence and learner, and raise failure."""
    service._force_audit_fail = True

    with pytest.raises(RuntimeError, match="Forced audit failure"):
        await service.record_evidence(
            learner_id="LRN-AUD-CRASH",
            evidence_type="assessment",
            source_system="sys",
            ingestion_method="api",
            source_type="teacher",
            source_reference="Ref",
            academic_year=2025,
            term=1,
            content={"score": 80, "max_score": 100},
            observed_at="2025-01-01T10:00:00+00:00",
            source_event_id="EV-CRASH-01",
        )

    # Assert honest rollback: neither learner nor evidence exist
    assert not await store.learner_exists("LRN-AUD-CRASH")
    assert len(await store.get_evidence_for_learner("LRN-AUD-CRASH")) == 0


@pytest.mark.asyncio
async def test_sqlite_round_trip_and_replay_rich_marks_rubric_missing(service, store):
    """Verify rich marks, rubric, and missing outcomes through SQLite round-trip and replay/idempotency."""
    learner_id = "LRN-SQLITE-ROUNDTRIP"

    # 1. Rich marks record
    marks_content = {
        "grade": "Grade 2",
        "score": 15,
        "max_score": 20,
        "form": "Form A",
        "form_version": "v1.0",
        "language": "English",
        "measured_skill": "addition",
        "comparison_authorized": True,
        "assessment_stage": "end_term",
        "school_level": "lower_primary",
    }
    ev_marks = await service.record_evidence(
        learner_id=learner_id,
        evidence_type="assessment",
        source_system="school_sis",
        ingestion_method="api",
        source_type="teacher",
        source_reference="Mr. Banda",
        academic_year=2025,
        term=1,
        subject="Mathematics",
        content=marks_content,
        observed_at="2025-03-20T10:00:00+00:00",
        source_event_id="EV-RT-MARKS-01",
    )
    assert ev_marks.is_marks is True
    assert ev_marks.comparison_authorized is True

    # 2. Rubric record with versioned scale
    rubric_content = {
        "grade": "Grade 2",
        "rubric": "Reading Rubric",
        "rubric_version": "v1.0",
        "scale": ["Below Expectation", "Approaching Expectation", "Meeting Expectation", "Exceeding Expectation"],
        "level": "Meeting Expectation",
        "measured_skill": "reading_fluency",
        "comparison_authorized": True,
    }
    ev_rubric = await service.record_evidence(
        learner_id=learner_id,
        evidence_type="assessment",
        source_system="school_sis",
        ingestion_method="api",
        source_type="teacher",
        source_reference="Mrs. Achebe",
        academic_year=2025,
        term=1,
        subject="English",
        content=rubric_content,
        observed_at="2025-03-21T10:00:00+00:00",
        source_event_id="EV-RT-RUB-01",
    )
    assert ev_rubric.is_rubric is True

    # 3. Missing outcome: result_unavailable
    unavail_content = {
        "grade": "Grade 2",
        "status": "result_unavailable",
        "reason": "Courier lost script",
        "max_score": 50,
    }
    ev_unavail = await service.record_evidence(
        learner_id=learner_id,
        evidence_type="assessment",
        source_system="school_sis",
        ingestion_method="api",
        source_type="teacher",
        source_reference="Mr. Courier",
        academic_year=2025,
        term=1,
        subject="Science",
        content=unavail_content,
        observed_at="2025-03-22T10:00:00+00:00",
        source_event_id="EV-RT-UNAVAIL-01",
    )
    assert ev_unavail.is_missing_outcome is True
    assert ev_unavail.content["status"] == "result_unavailable"

    # 4. Missing outcome: assessment_not_administered
    notadmin_content = {
        "grade": "Grade 2",
        "status": "assessment_not_administered",
        "reason": "School flood cancellation",
        "max_score": 50,
    }
    ev_notadmin = await service.record_evidence(
        learner_id=learner_id,
        evidence_type="assessment",
        source_system="school_sis",
        ingestion_method="api",
        source_type="teacher",
        source_reference="Principal",
        academic_year=2025,
        term=1,
        subject="Social Studies",
        content=notadmin_content,
        observed_at="2025-03-23T10:00:00+00:00",
        source_event_id="EV-RT-NOTADMIN-01",
    )
    assert ev_notadmin.is_missing_outcome is True
    assert ev_notadmin.content["status"] == "assessment_not_administered"

    # 5. SQLite Store Round-Trip Verification
    all_stored = await store.get_evidence_for_learner(learner_id)
    assert len(all_stored) == 4

    stored_marks = [e for e in all_stored if e.source_event_id == "EV-RT-MARKS-01"][0]
    assert stored_marks.content == marks_content
    assert stored_marks.assessment_stage == "end_term"
    assert stored_marks.school_level == "lower_primary"
    assert stored_marks.comparison_authorized is True

    stored_rubric = [e for e in all_stored if e.source_event_id == "EV-RT-RUB-01"][0]
    assert list(stored_rubric.content["scale"]) == rubric_content["scale"]
    assert stored_rubric.model_dump()["content"]["scale"] == rubric_content["scale"]
    assert stored_rubric.content["level"] == "Meeting Expectation"

    stored_unavail = [e for e in all_stored if e.source_event_id == "EV-RT-UNAVAIL-01"][0]
    assert stored_unavail.content["status"] == "result_unavailable"
    assert stored_unavail.content["reason"] == "Courier lost script"

    stored_notadmin = [e for e in all_stored if e.source_event_id == "EV-RT-NOTADMIN-01"][0]
    assert stored_notadmin.content["status"] == "assessment_not_administered"
    assert stored_notadmin.content["reason"] == "School flood cancellation"

    # 6. Replay Idempotency Verification
    replay_marks = await service.record_evidence(
        learner_id=learner_id,
        evidence_type="assessment",
        source_system="school_sis",
        ingestion_method="api",
        source_type="teacher",
        source_reference="Mr. Banda",
        academic_year=2025,
        term=1,
        subject="Mathematics",
        content=marks_content,
        observed_at="2025-03-20T10:00:00+00:00",
        source_event_id="EV-RT-MARKS-01",
    )
    assert replay_marks.evidence_id == ev_marks.evidence_id

    # 7. Conflict Detection on Changed Content
    conflict_marks_content = dict(marks_content)
    conflict_marks_content["score"] = 18
    with pytest.raises(ValueError, match="Conflict: event EV-RT-MARKS-01 already exists with different content"):
        await service.record_evidence(
            learner_id=learner_id,
            evidence_type="assessment",
            source_system="school_sis",
            ingestion_method="api",
            source_type="teacher",
            source_reference="Mr. Banda",
            academic_year=2025,
            term=1,
            subject="Mathematics",
            content=conflict_marks_content,
            observed_at="2025-03-20T10:00:00+00:00",
            source_event_id="EV-RT-MARKS-01",
        )


@pytest.mark.asyncio
async def test_sqlite_round_trip_and_conflict_handling_workstream_1_defects(service, store):
    """Targeted regression test verifying fluency round-trip, null outcome tolerance, and conflict detection."""
    learner_id = "LRN-TARGET-RT"

    # 1. Fluency assessment round-trip with stage
    fluency_content = {
        "grade": "Grade 2",
        "value": 45.0,
        "unit": "cwpm",
        "form": "Oral Fluency Form A",
        "form_version": "v1.0",
        "language": "English",
        "measured_skill": "oral_reading_fluency",
        "comparison_authorized": True,
        "assessment_stage": "opener",
    }
    ev_fl = await service.record_evidence(
        learner_id=learner_id,
        evidence_type="assessment",
        source_system="school_sis",
        ingestion_method="api",
        source_type="teacher",
        source_reference="Mrs. Achebe",
        academic_year=2025,
        term=1,
        subject="English",
        content=fluency_content,
        observed_at="2025-01-15T09:00:00+00:00",
        source_event_id="EV-FL-01",
    )
    assert ev_fl.is_fluency is True
    assert ev_fl.assessment_stage == "opener"

    # 2. Missing outcome with explicit null outcome fields tolerated
    missing_content = {
        "status": "absent",
        "reason": "Family bereavement",
        "score": None,
        "max_score": None,
        "level": None,
        "value": None,
    }
    ev_miss = await service.record_evidence(
        learner_id=learner_id,
        evidence_type="assessment",
        source_system="school_sis",
        ingestion_method="api",
        source_type="teacher",
        source_reference="Mr. Banda",
        academic_year=2025,
        term=1,
        subject="English",
        content=missing_content,
        observed_at="2025-01-20T09:00:00+00:00",
        source_event_id="EV-MISS-01",
    )
    assert ev_miss.is_missing_outcome is True

    # 3. SQLite Storage Roundtrip Verification
    stored = await store.get_evidence_for_learner(learner_id)
    assert len(stored) == 2
    stored_fl = [e for e in stored if e.source_event_id == "EV-FL-01"][0]
    assert stored_fl.is_fluency is True
    assert stored_fl.assessment_stage == "opener"
    assert stored_fl.content["value"] == 45.0
    assert stored_fl.content["unit"] == "cwpm"

    stored_miss = [e for e in stored if e.source_event_id == "EV-MISS-01"][0]
    assert stored_miss.is_missing_outcome is True
    assert stored_miss.content["status"] == "absent"

    # 4. Idempotent replay
    replay_fl = await service.record_evidence(
        learner_id=learner_id,
        evidence_type="assessment",
        source_system="school_sis",
        ingestion_method="api",
        source_type="teacher",
        source_reference="Mrs. Achebe",
        academic_year=2025,
        term=1,
        subject="English",
        content=fluency_content,
        observed_at="2025-01-15T09:00:00+00:00",
        source_event_id="EV-FL-01",
    )
    assert replay_fl.evidence_id == ev_fl.evidence_id

    # 5. Conflict rejection on changed fluency value
    conflict_fl_content = dict(fluency_content)
    conflict_fl_content["value"] = 52.0
    with pytest.raises(ValueError, match="Conflict: event EV-FL-01 already exists with different content"):
        await service.record_evidence(
            learner_id=learner_id,
            evidence_type="assessment",
            source_system="school_sis",
            ingestion_method="api",
            source_type="teacher",
            source_reference="Mrs. Achebe",
            academic_year=2025,
            term=1,
            subject="English",
            content=conflict_fl_content,
            observed_at="2025-01-15T09:00:00+00:00",
            source_event_id="EV-FL-01",
        )

    