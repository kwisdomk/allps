"""Generate synthetic learner data for ALLPS development and testing.

Creates 3 learners with intentionally varied evidence patterns:

- Learner A (LRN-001 / Amara Obi):
    Steady decline in maths over 3 terms.
    Attendance also drops. Learner reflection mentions difficulty.
    → Designed to test TREND detection.

- Learner B (LRN-002 / Thabo Mokoena):
    Consistently strong in science across all 3 terms.
    High attendance, positive observations, strong projects.
    → Designed to test PERSISTENCE detection.

- Learner C (LRN-003 / Naledi Dlamini):
    Good assessment scores in English BUT teacher observations
    consistently note low engagement / withdrawn behaviour.
    Learner self-reflection says "I'm doing okay."
    → Designed to test DIVERGENCE detection.
    → Also tests: missing data (no reflection in terms 1 & 2 for
      comparison), teacher change between terms.

Each learner has 8-9 evidence records spanning assessments, attendance,
observations, and reflections.
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure src is in sys.path when running as a standalone script
_src_dir = str(Path(__file__).resolve().parent.parent.parent / "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from allps.models import Evidence, EvidenceType, IngestionMethod, Learner
from allps.storage.sqlite_store import SQLiteStore


# ── Learners ──────────────────────────────────────────────────────

LEARNERS = [
    Learner(learner_id="LRN-001", display_name="Amara Obi"),
    Learner(learner_id="LRN-002", display_name="Thabo Mokoena"),
    Learner(learner_id="LRN-003", display_name="Naledi Dlamini"),
]


# ── Helper ────────────────────────────────────────────────────────


def _dt(year: int, month: int, day: int) -> datetime:
    """Create a timezone-aware UTC datetime."""
    return datetime(year, month, day, tzinfo=timezone.utc)


# ── Learner A — Declining maths trend ────────────────────────────

LEARNER_A_EVIDENCE = [
    # Term 1: Strong start
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-001",
        evidence_type=EvidenceType.ASSESSMENT,
        source_type="teacher",
        source_reference="Mr. Banda",
        academic_year=2025,
        term=1,
        subject="Mathematics",
        content={
            "score": 82,
            "max_score": 100,
            "assessment_name": "Term 1 Test",
        },
        observed_at=_dt(2025, 3, 15),
    ),
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-001",
        evidence_type=EvidenceType.ATTENDANCE,
        source_type="system",
        source_reference="attendance-system",
        academic_year=2025,
        term=1,
        subject=None,
        content={"days_present": 48, "days_total": 50, "rate": 0.96},
        observed_at=_dt(2025, 3, 28),
    ),
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-001",
        evidence_type=EvidenceType.OBSERVATION,
        source_type="teacher",
        source_reference="Mr. Banda",
        academic_year=2025,
        term=1,
        subject="Mathematics",
        content={
            "note": (
                "Amara participates actively and helps classmates "
                "with problem-solving."
            )
        },
        observed_at=_dt(2025, 3, 20),
    ),
    # Term 2: Slight decline
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-001",
        evidence_type=EvidenceType.ASSESSMENT,
        source_type="teacher",
        source_reference="Mr. Banda",
        academic_year=2025,
        term=2,
        subject="Mathematics",
        content={
            "score": 68,
            "max_score": 100,
            "assessment_name": "Term 2 Test",
        },
        observed_at=_dt(2025, 6, 10),
    ),
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-001",
        evidence_type=EvidenceType.ATTENDANCE,
        source_type="system",
        source_reference="attendance-system",
        academic_year=2025,
        term=2,
        subject=None,
        content={"days_present": 42, "days_total": 50, "rate": 0.84},
        observed_at=_dt(2025, 6, 25),
    ),
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-001",
        evidence_type=EvidenceType.LEARNER_REFLECTION,
        source_type="learner",
        source_reference="LRN-001",
        academic_year=2025,
        term=2,
        subject="Mathematics",
        content={
            "reflection": (
                "I find the new topics harder. "
                "I don't always understand in class."
            )
        },
        observed_at=_dt(2025, 6, 20),
    ),
    # Term 3: Further decline
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-001",
        evidence_type=EvidenceType.ASSESSMENT,
        source_type="teacher",
        source_reference="Mrs. Ngcobo",
        academic_year=2025,
        term=3,
        subject="Mathematics",
        content={
            "score": 51,
            "max_score": 100,
            "assessment_name": "Term 3 Test",
        },
        observed_at=_dt(2025, 9, 12),
    ),
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-001",
        evidence_type=EvidenceType.ATTENDANCE,
        source_type="system",
        source_reference="attendance-system",
        academic_year=2025,
        term=3,
        subject=None,
        content={"days_present": 38, "days_total": 50, "rate": 0.76},
        observed_at=_dt(2025, 9, 27),
    ),
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-001",
        evidence_type=EvidenceType.OBSERVATION,
        source_type="teacher",
        source_reference="Mrs. Ngcobo",
        academic_year=2025,
        term=3,
        subject="Mathematics",
        content={
            "note": (
                "Amara is quieter in class this term. Submits homework "
                "late but work quality shows understanding of core "
                "concepts."
            )
        },
        observed_at=_dt(2025, 9, 18),
    ),
]

# ── Learner B — Persistent science strength ──────────────────────

LEARNER_B_EVIDENCE = [
    # Term 1
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-002",
        evidence_type=EvidenceType.ASSESSMENT,
        source_type="teacher",
        source_reference="Dr. Mensah",
        academic_year=2025,
        term=1,
        subject="Science",
        content={
            "score": 88,
            "max_score": 100,
            "assessment_name": "Term 1 Practical + Theory",
        },
        observed_at=_dt(2025, 3, 14),
    ),
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-002",
        evidence_type=EvidenceType.OBSERVATION,
        source_type="teacher",
        source_reference="Dr. Mensah",
        academic_year=2025,
        term=1,
        subject="Science",
        content={
            "note": (
                "Thabo shows excellent scientific reasoning. "
                "Designs thoughtful experiments."
            )
        },
        observed_at=_dt(2025, 3, 22),
    ),
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-002",
        evidence_type=EvidenceType.PROJECT,
        source_type="teacher",
        source_reference="Dr. Mensah",
        academic_year=2025,
        term=1,
        subject="Science",
        content={
            "project_name": "Water Filtration Model",
            "grade": "A",
            "note": "Innovative use of local materials.",
        },
        observed_at=_dt(2025, 3, 25),
    ),
    # Term 2
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-002",
        evidence_type=EvidenceType.ASSESSMENT,
        source_type="teacher",
        source_reference="Dr. Mensah",
        academic_year=2025,
        term=2,
        subject="Science",
        content={
            "score": 91,
            "max_score": 100,
            "assessment_name": "Term 2 Practical + Theory",
        },
        observed_at=_dt(2025, 6, 11),
    ),
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-002",
        evidence_type=EvidenceType.ATTENDANCE,
        source_type="system",
        source_reference="attendance-system",
        academic_year=2025,
        term=2,
        subject=None,
        content={"days_present": 49, "days_total": 50, "rate": 0.98},
        observed_at=_dt(2025, 6, 25),
    ),
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-002",
        evidence_type=EvidenceType.LEARNER_REFLECTION,
        source_type="learner",
        source_reference="LRN-002",
        academic_year=2025,
        term=2,
        subject="Science",
        content={
            "reflection": (
                "Science is my favourite subject. "
                "I want to be an engineer."
            )
        },
        observed_at=_dt(2025, 6, 22),
    ),
    # Term 3
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-002",
        evidence_type=EvidenceType.ASSESSMENT,
        source_type="teacher",
        source_reference="Dr. Mensah",
        academic_year=2025,
        term=3,
        subject="Science",
        content={
            "score": 85,
            "max_score": 100,
            "assessment_name": "Term 3 Practical + Theory",
        },
        observed_at=_dt(2025, 9, 13),
    ),
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-002",
        evidence_type=EvidenceType.OBSERVATION,
        source_type="teacher",
        source_reference="Dr. Mensah",
        academic_year=2025,
        term=3,
        subject="Science",
        content={
            "note": (
                "Thabo mentors younger students in the science club. "
                "Consistent effort and curiosity."
            )
        },
        observed_at=_dt(2025, 9, 20),
    ),
]

# ── Learner C — Divergent evidence (scores vs. observations) ────

LEARNER_C_EVIDENCE = [
    # Term 1
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-003",
        evidence_type=EvidenceType.ASSESSMENT,
        source_type="teacher",
        source_reference="Ms. Achebe",
        academic_year=2025,
        term=1,
        subject="English",
        content={
            "score": 78,
            "max_score": 100,
            "assessment_name": "Term 1 Comprehension & Writing",
        },
        observed_at=_dt(2025, 3, 16),
    ),
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-003",
        evidence_type=EvidenceType.OBSERVATION,
        source_type="teacher",
        source_reference="Ms. Achebe",
        academic_year=2025,
        term=1,
        subject="English",
        content={
            "note": (
                "Naledi produces good written work but rarely "
                "participates in class discussion."
            )
        },
        observed_at=_dt(2025, 3, 21),
    ),
    # Term 2: Good scores, concerning observations
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-003",
        evidence_type=EvidenceType.ASSESSMENT,
        source_type="teacher",
        source_reference="Ms. Achebe",
        academic_year=2025,
        term=2,
        subject="English",
        content={
            "score": 81,
            "max_score": 100,
            "assessment_name": "Term 2 Comprehension & Writing",
        },
        observed_at=_dt(2025, 6, 9),
    ),
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-003",
        evidence_type=EvidenceType.OBSERVATION,
        source_type="teacher",
        source_reference="Ms. Achebe",
        academic_year=2025,
        term=2,
        subject="English",
        content={
            "note": (
                "Naledi seems withdrawn. Sits alone at break. "
                "Assessment scores remain strong but classroom "
                "engagement is low."
            )
        },
        observed_at=_dt(2025, 6, 18),
    ),
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-003",
        evidence_type=EvidenceType.ATTENDANCE,
        source_type="system",
        source_reference="attendance-system",
        academic_year=2025,
        term=2,
        subject=None,
        content={"days_present": 44, "days_total": 50, "rate": 0.88},
        observed_at=_dt(2025, 6, 25),
    ),
    # Term 3: Scores still good, observations still concerning
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-003",
        evidence_type=EvidenceType.ASSESSMENT,
        source_type="teacher",
        source_reference="Ms. Achebe",
        academic_year=2025,
        term=3,
        subject="English",
        content={
            "score": 76,
            "max_score": 100,
            "assessment_name": "Term 3 Comprehension & Writing",
        },
        observed_at=_dt(2025, 9, 11),
    ),
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-003",
        evidence_type=EvidenceType.OBSERVATION,
        source_type="teacher",
        source_reference="Mr. Okafor",
        academic_year=2025,
        term=3,
        subject="English",
        content={
            "note": (
                "New teacher this term. Naledi does well on tests but "
                "does not volunteer in class. No issues with behaviour."
            )
        },
        observed_at=_dt(2025, 9, 19),
    ),
    Evidence(
        source_system="synthetic_dataset",
        ingestion_method=IngestionMethod.SYNTHETIC,
        learner_id="LRN-003",
        evidence_type=EvidenceType.LEARNER_REFLECTION,
        source_type="learner",
        source_reference="LRN-003",
        academic_year=2025,
        term=3,
        subject="English",
        content={
            "reflection": (
                "I prefer writing to talking in front of the class. "
                "I think I'm doing okay."
            )
        },
        observed_at=_dt(2025, 9, 22),
    ),
    # Note: No learner reflection in Terms 1 & 2.
    # Missing data is NOT negative evidence (safety rule #3).
]

ALL_EVIDENCE = LEARNER_A_EVIDENCE + LEARNER_B_EVIDENCE + LEARNER_C_EVIDENCE


async def seed_database(db_path: str = "allps_dev.db") -> None:
    """Seed a database with all synthetic learners and evidence."""
    store = SQLiteStore(db_path)
    await store.initialize()

    try:
        for learner in LEARNERS:
            await store.add_learner(learner)
            print(
                f"  Added learner: {learner.display_name} "
                f"({learner.learner_id})"
            )

        for evidence in ALL_EVIDENCE:
            await store.add_evidence(evidence)

        print(f"  Added {len(ALL_EVIDENCE)} evidence records")
        print(f"\nDatabase seeded at: {db_path}")
    finally:
        await store.close()


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "allps_dev.db"
    asyncio.run(seed_database(db))
