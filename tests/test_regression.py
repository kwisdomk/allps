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
