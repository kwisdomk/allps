"""Tests for two-level evidence identity and deduplication.

Level 1: logical idempotency via (source_system, source_event_id).
Level 2: canonical fingerprint deduplication — same observation,
         different file, different source_event_id.

Also covers import manifest file-level deduplication and the rule
that genuinely separate assessments are never silently discarded.
"""

import hashlib
import pytest
import pytest_asyncio

from allps.models.import_manifest import ImportManifest
from allps.services.evidence_service import EvidenceService
from allps.storage.sqlite_store import SQLiteStore

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def store():
    s = SQLiteStore(":memory:")
    await s.initialize()
    yield s
    await s.close()


@pytest_asyncio.fixture
async def svc(store):
    return EvidenceService(store)


# Minimal valid assessment payload used across multiple tests
_ASSESSMENT = {
    "score": 72,
    "max_score": 100,
    "measured_skill": "multiplication_and_division",
    "grade": "Grade 7",
    "assessment_stage": "end_term",
    "comparison_authorized": True,
}

_BASE_KWARGS = dict(
    learner_id="LRN-TEST",
    evidence_type="assessment",
    source_system="school_sis",
    ingestion_method="csv_import",
    source_type="system",
    source_reference="Term-3-Export-2025",
    academic_year=2025,
    term=3,
    subject="Mathematics",
    observed_at="2025-09-15T08:00:00+00:00",
    content=_ASSESSMENT,
)


# ── Level 1: source_event_id idempotency ──────────────────────────────────


@pytest.mark.asyncio
async def test_level1_same_event_id_returns_existing(svc):
    """Second call with the same source_event_id returns the first record unchanged."""
    ev1 = await svc.record_evidence(**_BASE_KWARGS, source_event_id="EVT-001")
    ev2 = await svc.record_evidence(**_BASE_KWARGS, source_event_id="EVT-001")
    assert ev1.evidence_id == ev2.evidence_id


@pytest.mark.asyncio
async def test_level1_conflict_on_same_event_id_different_content(svc):
    """Same source_event_id with different content raises ValueError (data conflict)."""
    await svc.record_evidence(**_BASE_KWARGS, source_event_id="EVT-002")
    different = dict(_BASE_KWARGS)
    different["content"] = {**_ASSESSMENT, "score": 55}
    with pytest.raises(ValueError, match="Conflict"):
        await svc.record_evidence(**different, source_event_id="EVT-002")


# ── Level 2: canonical fingerprint deduplication ──────────────────────────


@pytest.mark.asyncio
async def test_level2_same_observation_different_event_id_deduplicated(svc):
    """Same underlying observation arriving with a different source_event_id is deduplicated.

    This is the core 'different file, same row' scenario.
    """
    ev1 = await svc.record_evidence(**_BASE_KWARGS, source_event_id="FILE-A-ROW-1")
    # Same observation, arrives in a second export with a different generated ID
    ev2 = await svc.record_evidence(**_BASE_KWARGS, source_event_id="FILE-B-ROW-99")
    assert ev1.evidence_id == ev2.evidence_id, (
        "Duplicate observation from a different export file must not create a second record."
    )


@pytest.mark.asyncio
async def test_level2_same_observation_no_event_id_deduplicated(svc):
    """Fingerprint dedup works when neither record has a source_event_id."""
    ev1 = await svc.record_evidence(**_BASE_KWARGS, source_event_id=None)
    ev2 = await svc.record_evidence(**_BASE_KWARGS, source_event_id=None)
    assert ev1.evidence_id == ev2.evidence_id


@pytest.mark.asyncio
async def test_level2_dedup_audit_entry_recorded(svc, store):
    """A deduplication event must leave an audit trail."""
    await svc.record_evidence(**_BASE_KWARGS, source_event_id="FIRST")
    await svc.record_evidence(**_BASE_KWARGS, source_event_id="SECOND")
    audit_log = await store.get_audit_log(tool_name="ingest_evidence")
    dedup_entries = [e for e in audit_log if e.input_summary.get("deduplicated") is True]
    assert len(dedup_entries) == 1


# ── False-positive prevention: different assessments must NOT be merged ───


@pytest.mark.asyncio
async def test_different_score_produces_separate_records(svc, store):
    """Two assessments with different scores are NOT duplicates."""
    kwargs_a = dict(_BASE_KWARGS)
    kwargs_a["content"] = {**_ASSESSMENT, "score": 80}
    kwargs_b = dict(_BASE_KWARGS)
    kwargs_b["content"] = {**_ASSESSMENT, "score": 45}
    ev_a = await svc.record_evidence(**kwargs_a, source_event_id="A")
    ev_b = await svc.record_evidence(**kwargs_b, source_event_id="B")
    assert ev_a.evidence_id != ev_b.evidence_id


@pytest.mark.asyncio
async def test_different_term_produces_separate_records(svc, store):
    """Same learner, same subject, different terms produce separate records."""
    kwargs_t1 = dict(_BASE_KWARGS)
    kwargs_t1["term"] = 1
    kwargs_t1["observed_at"] = "2025-03-15T08:00:00+00:00"
    kwargs_t2 = dict(_BASE_KWARGS)
    kwargs_t2["term"] = 2
    kwargs_t2["observed_at"] = "2025-06-10T08:00:00+00:00"
    ev1 = await svc.record_evidence(**kwargs_t1, source_event_id="T1")
    ev2 = await svc.record_evidence(**kwargs_t2, source_event_id="T2")
    assert ev1.evidence_id != ev2.evidence_id


@pytest.mark.asyncio
async def test_different_learner_produces_separate_records(svc, store):
    """Same assessment from different learners must always produce separate records."""
    kwargs_a = dict(_BASE_KWARGS)
    kwargs_a["learner_id"] = "LRN-A"
    kwargs_b = dict(_BASE_KWARGS)
    kwargs_b["learner_id"] = "LRN-B"
    ev_a = await svc.record_evidence(**kwargs_a, source_event_id="X1")
    ev_b = await svc.record_evidence(**kwargs_b, source_event_id="X2")
    assert ev_a.evidence_id != ev_b.evidence_id


@pytest.mark.asyncio
async def test_different_subject_produces_separate_records(svc, store):
    """Same learner, same term, different subjects must not be merged."""
    kwargs_m = dict(_BASE_KWARGS)
    kwargs_m["subject"] = "Mathematics"
    kwargs_s = dict(_BASE_KWARGS)
    kwargs_s["subject"] = "Science"
    ev_m = await svc.record_evidence(**kwargs_m, source_event_id="M1")
    ev_s = await svc.record_evidence(**kwargs_s, source_event_id="S1")
    assert ev_m.evidence_id != ev_s.evidence_id


@pytest.mark.asyncio
async def test_different_timestamp_produces_separate_records(svc, store):
    """Two observations at different UTC second-precision timestamps are distinct."""
    kwargs_early = dict(_BASE_KWARGS)
    kwargs_early["observed_at"] = "2025-09-15T08:00:00+00:00"
    kwargs_early["evidence_type"] = "observation"
    kwargs_early["content"] = {"observation": "Engaged with group task.", "note": "Engaged."}
    kwargs_late = dict(_BASE_KWARGS)
    kwargs_late["observed_at"] = "2025-09-15T14:30:00+00:00"
    kwargs_late["evidence_type"] = "observation"
    kwargs_late["content"] = {"observation": "Engaged with group task.", "note": "Engaged."}
    ev_a = await svc.record_evidence(**kwargs_early, source_event_id="OBS-AM")
    ev_b = await svc.record_evidence(**kwargs_late, source_event_id="OBS-PM")
    assert ev_a.evidence_id != ev_b.evidence_id


@pytest.mark.asyncio
async def test_different_observation_content_same_timestamp_produces_separate_records(svc, store):
    """Two distinct teacher observations at the exact same timestamp must NOT collide."""
    kwargs_1 = dict(_BASE_KWARGS)
    kwargs_1["evidence_type"] = "observation"
    kwargs_1["content"] = {"observation": "Completed fraction strip model.", "note": "Completed fraction strip model."}
    kwargs_2 = dict(_BASE_KWARGS)
    kwargs_2["evidence_type"] = "observation"
    kwargs_2["content"] = {"observation": "Requested peer clarification on halves.", "note": "Requested peer clarification on halves."}
    ev_a = await svc.record_evidence(**kwargs_1, source_event_id="OBS-1")
    ev_b = await svc.record_evidence(**kwargs_2, source_event_id="OBS-2")
    assert ev_a.evidence_id != ev_b.evidence_id


# ── Fingerprint is stable across equivalent representations ───────────────


def test_canonical_fingerprint_stable_across_sub_second_jitter():
    """The fingerprint must be identical for the same observation with sub-second timestamp variation.

    Exports often produce slightly different millisecond values for the same event.
    The fingerprint must resolve them to the same second-precision bucket.
    """
    from allps.models.evidence import Evidence, EvidenceType, IngestionMethod
    from datetime import datetime, timezone

    def make_evidence(microsecond: int) -> Evidence:
        return Evidence(
            learner_id="LRN-X",
            evidence_type=EvidenceType.ASSESSMENT,
            source_system="sis",
            ingestion_method=IngestionMethod.CSV_IMPORT,
            source_type="system",
            source_reference="export",
            academic_year=2025,
            term=2,
            subject="English",
            content={
                "score": 60,
                "max_score": 80,
                "comparison_authorized": True,
            },
            observed_at=datetime(2025, 6, 10, 9, 0, 0, microsecond, tzinfo=timezone.utc),
        )

    ev1 = make_evidence(microsecond=0)
    ev2 = make_evidence(microsecond=999999)  # same second, max microsecond
    assert ev1.canonical_fingerprint == ev2.canonical_fingerprint


def test_canonical_fingerprint_differs_for_different_outcomes():
    """Two assessments with different scores must produce different fingerprints."""
    from allps.models.evidence import Evidence, EvidenceType, IngestionMethod
    from datetime import datetime, timezone

    base_kwargs = dict(
        learner_id="LRN-FP",
        evidence_type=EvidenceType.ASSESSMENT,
        source_system="sis",
        ingestion_method=IngestionMethod.CSV_IMPORT,
        source_type="system",
        source_reference="export",
        academic_year=2025,
        term=1,
        subject="Mathematics",
        observed_at=datetime(2025, 3, 15, 10, 0, 0, tzinfo=timezone.utc),
    )
    ev_high = Evidence(**base_kwargs, content={"score": 90, "max_score": 100, "comparison_authorized": True})
    ev_low = Evidence(**base_kwargs, content={"score": 40, "max_score": 100, "comparison_authorized": True})
    assert ev_high.canonical_fingerprint != ev_low.canonical_fingerprint


# ── Import manifest: file-level deduplication ─────────────────────────────


@pytest.mark.asyncio
async def test_import_manifest_stored_and_retrieved(store):
    """An import manifest is persisted and retrievable by file hash."""
    file_bytes = b"learner_id,score\nLRN-001,72\n"
    sha256 = hashlib.sha256(file_bytes).hexdigest()
    manifest = ImportManifest(
        source_system="school_sis",
        file_name="term3_maths.csv",
        import_method="csv_import",
        file_sha256=sha256,
        row_count=1,
        accepted_count=1,
        rejected_count=0,
    )
    await store.add_import_manifest(manifest)
    retrieved = await store.get_import_manifest_by_hash(sha256, "school_sis")
    assert retrieved is not None
    assert retrieved.manifest_id == manifest.manifest_id
    assert retrieved.accepted_count == 1


@pytest.mark.asyncio
async def test_import_manifest_duplicate_file_rejected(store):
    """Re-importing the same file (same SHA-256, same source) raises ValueError."""
    file_bytes = b"learner_id,score\nLRN-001,72\n"
    sha256 = hashlib.sha256(file_bytes).hexdigest()
    manifest = ImportManifest(
        source_system="school_sis",
        file_name="term3_maths.csv",
        import_method="csv_import",
        file_sha256=sha256,
        row_count=1,
        accepted_count=1,
        rejected_count=0,
    )
    await store.add_import_manifest(manifest)
    import uuid as _uuid
    duplicate = ImportManifest(
        manifest_id=str(_uuid.uuid4()),
        source_system="school_sis",
        file_name="term3_maths_copy.csv",  # different name, same content
        import_method="csv_import",
        file_sha256=sha256,
        row_count=1,
        accepted_count=1,
        rejected_count=0,
    )
    with pytest.raises(ValueError, match="already been imported"):
        await store.add_import_manifest(duplicate)


@pytest.mark.asyncio
async def test_import_manifest_same_hash_different_source_allowed(store):
    """The same file content imported from a different source system is NOT a duplicate."""
    file_bytes = b"learner_id,score\nLRN-001,72\n"
    sha256 = hashlib.sha256(file_bytes).hexdigest()

    m1 = ImportManifest(
        source_system="school_sis_a",
        file_name="export.csv",
        import_method="csv_import",
        file_sha256=sha256,
        row_count=1,
        accepted_count=1,
        rejected_count=0,
    )
    m2 = ImportManifest(
        source_system="school_sis_b",
        file_name="export.csv",
        import_method="csv_import",
        file_sha256=sha256,
        row_count=1,
        accepted_count=1,
        rejected_count=0,
    )
    await store.add_import_manifest(m1)
    await store.add_import_manifest(m2)  # must not raise
    # Both exist
    r1 = await store.get_import_manifest_by_hash(sha256, "school_sis_a")
    r2 = await store.get_import_manifest_by_hash(sha256, "school_sis_b")
    assert r1 is not None
    assert r2 is not None
    assert r1.manifest_id != r2.manifest_id


@pytest.mark.asyncio
async def test_import_manifest_absent_returns_none(store):
    """Querying for an unrecorded file hash returns None."""
    result = await store.get_import_manifest_by_hash("a" * 64, "school_sis")
    assert result is None


@pytest.mark.asyncio
async def test_list_import_manifests(store):
    """list_import_manifests returns all records in reverse chronological order."""
    for i in range(3):
        sha = hashlib.sha256(f"file-{i}".encode()).hexdigest()
        m = ImportManifest(
            source_system="sis",
            file_name=f"file-{i}.csv",
            import_method="csv_import",
            file_sha256=sha,
            row_count=10,
            accepted_count=10,
            rejected_count=0,
        )
        await store.add_import_manifest(m)
    manifests = await store.list_import_manifests()
    assert len(manifests) == 3


# ── get_evidence_by_fingerprint ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_evidence_by_fingerprint_returns_stored(svc, store):
    """After ingestion, get_evidence_by_fingerprint returns the stored record."""
    ev = await svc.record_evidence(**_BASE_KWARGS, source_event_id="FP-LOOKUP")
    found = await store.get_evidence_by_fingerprint(ev.canonical_fingerprint)
    assert found is not None
    assert found.evidence_id == ev.evidence_id


@pytest.mark.asyncio
async def test_get_evidence_by_fingerprint_absent_returns_none(store):
    """Querying for an unrecorded fingerprint returns None."""
    result = await store.get_evidence_by_fingerprint("x" * 64)
    assert result is None
