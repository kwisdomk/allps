"""SQLite persistence layer for ALLPS.

Evidence records are immutable — there is no update_evidence method.
All timestamps are stored as ISO 8601 strings.
JSON fields (content, supporting_evidence, etc.) are stored as TEXT.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
from typing import Any, Sequence

import aiosqlite

from allps.models import (
    AuditEntry,
    ClassEnrollment,
    ClassRelease,
    DiffSeverity,
    Evidence,
    EvidenceType,
    ImportManifest,
    IngestionMethod,
    Learner,
    Pattern,
    PatternType,
    PostReleaseChange,
    PublishedReportSection,
    ReceiptStatus,
    ReportReceipt,
    ReportViewEvent,
    ReviewItem,
    ReviewStatus,
    SchoolClass,
    SectionReview,
    SectionReviewState,
    SubjectResponse,
    SubjectResponseType,
    TeacherAssignment,
    TeacherRole,
)
from allps.models.evidence import _deep_unfreeze

_HANDOVER_SCHEMA = """
CREATE TABLE IF NOT EXISTS classes (
    class_id      TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    grade         TEXT NOT NULL,
    academic_year INTEGER NOT NULL,
    term          INTEGER NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS class_enrollments (
    class_id    TEXT NOT NULL,
    learner_id  TEXT NOT NULL,
    enrolled_at TEXT NOT NULL,
    PRIMARY KEY (class_id, learner_id)
);

CREATE INDEX IF NOT EXISTS idx_enrollments_learner ON class_enrollments(learner_id);

CREATE TABLE IF NOT EXISTS teacher_assignments (
    assignment_id TEXT PRIMARY KEY,
    teacher_id    TEXT NOT NULL,
    class_id      TEXT NOT NULL,
    role          TEXT NOT NULL,
    subject       TEXT,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_assignments_teacher ON teacher_assignments(teacher_id);
CREATE INDEX IF NOT EXISTS idx_assignments_class ON teacher_assignments(class_id);

CREATE TABLE IF NOT EXISTS section_reviews (
    section_review_id           TEXT PRIMARY KEY,
    class_id                    TEXT NOT NULL,
    learner_id                  TEXT NOT NULL,
    scope                       TEXT NOT NULL,
    review_state                TEXT NOT NULL DEFAULT 'not_reviewed',
    approved_summary            TEXT,
    teacher_notes               TEXT,
    missing_evidence_disclosure TEXT,
    citations_json              TEXT NOT NULL DEFAULT '[]',
    reviewed_by                 TEXT,
    reviewed_at                 TEXT,
    updated_at                  TEXT NOT NULL,
    UNIQUE(class_id, learner_id, scope)
);

CREATE INDEX IF NOT EXISTS idx_section_reviews_class ON section_reviews(class_id, learner_id);

CREATE TABLE IF NOT EXISTS class_releases (
    release_id             TEXT PRIMARY KEY,
    class_id               TEXT NOT NULL,
    version_number         INTEGER NOT NULL,
    released_by            TEXT NOT NULL,
    released_by_name       TEXT NOT NULL,
    released_at            TEXT NOT NULL,
    frozen_enrollment_json TEXT NOT NULL,
    frozen_subjects_json   TEXT NOT NULL,
    notes                  TEXT
);

CREATE INDEX IF NOT EXISTS idx_class_releases_class ON class_releases(class_id, version_number);

CREATE TABLE IF NOT EXISTS published_report_sections (
    published_section_id        TEXT PRIMARY KEY,
    release_id                  TEXT NOT NULL,
    class_id                    TEXT NOT NULL,
    learner_id                  TEXT NOT NULL,
    scope                       TEXT NOT NULL,
    section_title               TEXT NOT NULL,
    review_state                TEXT NOT NULL,
    evidence_availability_json  TEXT NOT NULL,
    approved_summary            TEXT NOT NULL,
    teacher_notes               TEXT,
    missing_evidence_disclosure TEXT,
    citations_json              TEXT NOT NULL,
    approved_content_hash       TEXT NOT NULL DEFAULT '',
    evidence_fingerprints_json  TEXT NOT NULL,
    analysis_signature_json     TEXT NOT NULL,
    approved_by                 TEXT NOT NULL,
    approved_by_name            TEXT NOT NULL,
    approved_at                 TEXT NOT NULL,
    released_by                 TEXT NOT NULL,
    released_at                 TEXT NOT NULL,
    UNIQUE(release_id, learner_id, scope)
);

CREATE INDEX IF NOT EXISTS idx_pub_sections_release ON published_report_sections(release_id, learner_id);

CREATE TABLE IF NOT EXISTS report_view_events (
    view_id      TEXT PRIMARY KEY,
    release_id   TEXT NOT NULL,
    class_id     TEXT NOT NULL,
    learner_id   TEXT NOT NULL,
    scope        TEXT NOT NULL,
    teacher_id   TEXT NOT NULL,
    teacher_name TEXT NOT NULL,
    viewed_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_view_events_release_learner ON report_view_events(release_id, learner_id, viewed_at);

CREATE TABLE IF NOT EXISTS report_receipts (
    receipt_id      TEXT PRIMARY KEY,
    release_id      TEXT NOT NULL,
    class_id        TEXT NOT NULL,
    learner_id      TEXT NOT NULL,
    teacher_id      TEXT NOT NULL,
    teacher_name    TEXT NOT NULL,
    subject         TEXT,
    status          TEXT NOT NULL DEFAULT 'not_viewed',
    first_viewed_at TEXT,
    last_viewed_at  TEXT,
    view_count      INTEGER NOT NULL DEFAULT 0,
    acknowledged_at TEXT,
    UNIQUE(release_id, learner_id, teacher_id)
);

CREATE INDEX IF NOT EXISTS idx_receipts_release_learner ON report_receipts(release_id, learner_id);

CREATE TABLE IF NOT EXISTS subject_responses (
    response_id          TEXT PRIMARY KEY,
    release_id           TEXT NOT NULL,
    published_section_id TEXT NOT NULL,
    class_id             TEXT NOT NULL,
    learner_id           TEXT NOT NULL,
    subject              TEXT NOT NULL,
    teacher_id           TEXT NOT NULL,
    teacher_name         TEXT NOT NULL,
    response_type        TEXT NOT NULL,
    content              TEXT NOT NULL,
    related_change_id    TEXT,
    created_at           TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_subject_responses_section ON subject_responses(published_section_id, created_at);

CREATE TABLE IF NOT EXISTS post_release_changes (
    change_id                    TEXT PRIMARY KEY,
    release_id                   TEXT NOT NULL,
    class_id                     TEXT NOT NULL,
    learner_id                   TEXT NOT NULL,
    scope                        TEXT NOT NULL,
    severity                     TEXT NOT NULL,
    headline                     TEXT NOT NULL,
    explanation                  TEXT NOT NULL,
    why_it_matters               TEXT NOT NULL,
    comparison_json              TEXT NOT NULL,
    new_evidence_ids_json        TEXT NOT NULL,
    opened_by_teacher_id         TEXT,
    opened_by_name               TEXT,
    opened_at                    TEXT,
    response_id                  TEXT,
    response_added_by_name       TEXT,
    response_added_at            TEXT,
    reviewed_by_class_teacher_id TEXT,
    reviewed_by_name             TEXT,
    reviewed_at                  TEXT,
    review_resolution_notes      TEXT,
    superseded_by_release_id     TEXT,
    superseded_version_number    INTEGER,
    created_at                   TEXT NOT NULL,
    UNIQUE(release_id, learner_id, scope)
);

CREATE INDEX IF NOT EXISTS idx_changes_class ON post_release_changes(class_id, learner_id);
"""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS teachers (
    teacher_id   TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    pin_hash     TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS learners (
    learner_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    learner_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    source_system TEXT NOT NULL,
    ingestion_method TEXT NOT NULL,
    source_event_id TEXT,
    source_type TEXT NOT NULL,
    source_reference TEXT NOT NULL,
    academic_year INTEGER NOT NULL,
    term INTEGER NOT NULL,
    subject TEXT,
    content TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    canonical_fingerprint TEXT,
    FOREIGN KEY (learner_id) REFERENCES learners(learner_id),
    UNIQUE(source_system, source_event_id)
);

CREATE INDEX IF NOT EXISTS idx_evidence_learner
    ON evidence(learner_id);
CREATE INDEX IF NOT EXISTS idx_evidence_time
    ON evidence(academic_year, term, observed_at);

CREATE TABLE IF NOT EXISTS patterns (
    pattern_id TEXT PRIMARY KEY,
    learner_id TEXT NOT NULL,
    pattern_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    supporting_evidence TEXT NOT NULL,
    conflicting_evidence TEXT NOT NULL,
    limitations TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    FOREIGN KEY (learner_id) REFERENCES learners(learner_id)
);

CREATE TABLE IF NOT EXISTS review_items (
    review_id TEXT PRIMARY KEY,
    pattern_id TEXT NOT NULL,
    assigned_to TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    teacher_notes TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    reviewer_id TEXT,
    approved_content_hash TEXT,
    revision INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (pattern_id) REFERENCES patterns(pattern_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    audit_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    input_summary TEXT NOT NULL,
    output_reference TEXT,
    approval_state TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_tool ON audit_log(tool_name);

CREATE TABLE IF NOT EXISTS candidate_briefs (
    brief_id TEXT PRIMARY KEY,
    learner_id TEXT NOT NULL,
    pattern_id TEXT,
    review_id TEXT,
    generation_revision INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    summary TEXT NOT NULL,
    findings TEXT NOT NULL,
    contradictions TEXT NOT NULL,
    limitations TEXT NOT NULL,
    abstention_reason TEXT,
    runtime_method TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    FOREIGN KEY (learner_id) REFERENCES learners(learner_id)
);

CREATE INDEX IF NOT EXISTS idx_briefs_learner ON candidate_briefs(learner_id);
CREATE INDEX IF NOT EXISTS idx_briefs_pattern ON candidate_briefs(pattern_id);
CREATE INDEX IF NOT EXISTS idx_briefs_review ON candidate_briefs(review_id);

CREATE TABLE IF NOT EXISTS import_manifests (
    manifest_id TEXT PRIMARY KEY,
    source_system TEXT NOT NULL,
    file_name TEXT NOT NULL,
    import_method TEXT NOT NULL,
    file_sha256 TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    accepted_count INTEGER NOT NULL,
    rejected_count INTEGER NOT NULL,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    imported_by TEXT,
    imported_at TEXT NOT NULL,
    notes TEXT,
    UNIQUE(file_sha256, source_system)
);

CREATE INDEX IF NOT EXISTS idx_manifests_sha256 ON import_manifests(file_sha256);
CREATE INDEX IF NOT EXISTS idx_manifests_source ON import_manifests(source_system);
"""


class SQLiteStore:
    """Async SQLite storage for ALLPS domain objects.

    Evidence records are immutable — there is no update_evidence method.
    """

    def __init__(self, db_path: str = "allps.db") -> None:
        self._is_temp = False
        if db_path == ":memory:":
            import os, tempfile, uuid
            self._db_path = os.path.join(tempfile.gettempdir(), f"allps_mem_{uuid.uuid4().hex}.db")
            self._is_temp = True
        else:
            self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Create connection and ensure schema exists."""
        self._db = await aiosqlite.connect(self._db_path, timeout=10.0)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode = WAL;")
        await self._db.execute("PRAGMA busy_timeout = 10000;")
        await self._db.execute("PRAGMA foreign_keys = ON;")
        await self._db.executescript(_SCHEMA)
        await self.migrate()
        await self._db.commit()

    async def create_connection(self) -> aiosqlite.Connection:
        """Create a new, isolated connection to the SQLite database."""
        conn = await aiosqlite.connect(self._db_path, timeout=10.0)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA busy_timeout = 10000;")
        await conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    @asynccontextmanager
    async def transaction(self):
        """Isolate transaction ownership with a dedicated connection.

        Ensures BEGIN IMMEDIATE, atomicity, and keeps rollback strictly
        within the transaction's ownership boundary.
        """
        conn = await self.create_connection()
        try:
            await conn.execute("BEGIN IMMEDIATE")
            yield conn
            await conn.commit()
        except Exception:
            if conn.in_transaction:
                await conn.rollback()
            raise
        finally:
            await conn.close()

    async def migrate(self) -> None:
        """Non-destructive migration for existing databases."""
        async with self.db.execute("PRAGMA table_info(evidence)") as cursor:
            columns = [row["name"] for row in await cursor.fetchall()]
        
        if "source_event_id" not in columns:
            await self.db.execute("ALTER TABLE evidence ADD COLUMN source_event_id TEXT")
            await self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_idemp ON evidence(source_system, source_event_id)")

        if "canonical_fingerprint" not in columns:
            await self.db.execute("ALTER TABLE evidence ADD COLUMN canonical_fingerprint TEXT")
            await self.db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_fingerprint "
                "ON evidence(canonical_fingerprint) WHERE canonical_fingerprint IS NOT NULL"
            )

        async with self.db.execute("PRAGMA table_info(review_items)") as cursor:
            rev_columns = [row["name"] for row in await cursor.fetchall()]

        if "reviewer_id" not in rev_columns:
            await self.db.execute("ALTER TABLE review_items ADD COLUMN reviewer_id TEXT")
        if "approved_content_hash" not in rev_columns:
            await self.db.execute("ALTER TABLE review_items ADD COLUMN approved_content_hash TEXT")
        if "revision" not in rev_columns:
            await self.db.execute("ALTER TABLE review_items ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")

        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS candidate_briefs (
                brief_id TEXT PRIMARY KEY,
                learner_id TEXT NOT NULL,
                pattern_id TEXT,
                review_id TEXT,
                generation_revision INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL,
                summary TEXT NOT NULL,
                findings TEXT NOT NULL,
                contradictions TEXT NOT NULL,
                limitations TEXT NOT NULL,
                abstention_reason TEXT,
                runtime_method TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                FOREIGN KEY (learner_id) REFERENCES learners(learner_id)
            )
        """)
        await self.db.execute("CREATE INDEX IF NOT EXISTS idx_briefs_learner ON candidate_briefs(learner_id)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS idx_briefs_pattern ON candidate_briefs(pattern_id)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS idx_briefs_review ON candidate_briefs(review_id)")

        # teachers table (added in feature/teacher-review-authority)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS teachers (
                teacher_id   TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                pin_hash     TEXT NOT NULL,
                created_at   TEXT NOT NULL
            )
        """)

        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS import_manifests (
                manifest_id TEXT PRIMARY KEY,
                source_system TEXT NOT NULL,
                file_name TEXT NOT NULL,
                import_method TEXT NOT NULL,
                file_sha256 TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                accepted_count INTEGER NOT NULL,
                rejected_count INTEGER NOT NULL,
                duplicate_count INTEGER NOT NULL DEFAULT 0,
                imported_by TEXT,
                imported_at TEXT NOT NULL,
                notes TEXT,
                UNIQUE(file_sha256, source_system)
            )
        """)
        await self.db.execute("CREATE INDEX IF NOT EXISTS idx_manifests_sha256 ON import_manifests(file_sha256)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS idx_manifests_source ON import_manifests(source_system)")
        await self.db.executescript(_HANDOVER_SCHEMA)
        async with self.db.execute("PRAGMA table_info(published_report_sections)") as cursor:
            pub_cols = [row["name"] for row in await cursor.fetchall()]
        if "approved_content_hash" not in pub_cols:
            await self.db.execute(
                "ALTER TABLE published_report_sections ADD COLUMN approved_content_hash TEXT NOT NULL DEFAULT ''"
            )

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None
        if self._is_temp:
            import os
            for path in [self._db_path, f"{self._db_path}-wal", f"{self._db_path}-shm"]:
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass


    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError(
                "Store not initialized. Call initialize() first."
            )
        return self._db

    # ── Learners ──────────────────────────────────────────────────

    async def add_learner(
        self,
        learner: Learner,
        commit: bool = True,
        conn: aiosqlite.Connection | None = None,
    ) -> Learner:
        """Insert a new learner."""
        db = conn or self.db
        await db.execute(
            "INSERT INTO learners (learner_id, display_name, created_at) "
            "VALUES (?, ?, ?)",
            (
                learner.learner_id,
                learner.display_name,
                learner.created_at.isoformat(),
            ),
        )
        if commit:
            await db.commit()
        return learner

    async def get_learner(
        self, learner_id: str, conn: aiosqlite.Connection | None = None
    ) -> Learner | None:
        """Retrieve a learner by ID, or None if not found."""
        db = conn or self.db
        async with db.execute(
            "SELECT * FROM learners WHERE learner_id = ?", (learner_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return Learner(
                learner_id=row["learner_id"],
                display_name=row["display_name"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )

    async def learner_exists(
        self, learner_id: str, conn: aiosqlite.Connection | None = None
    ) -> bool:
        """Check if a learner exists."""
        db = conn or self.db
        async with db.execute(
            "SELECT 1 FROM learners WHERE learner_id = ?", (learner_id,)
        ) as cursor:
            return await cursor.fetchone() is not None

    # ── Teachers ──────────────────────────────────────────────────

    async def add_teacher(
        self,
        teacher_id: str,
        display_name: str,
        pin_hash: str,
        commit: bool = True,
        conn: aiosqlite.Connection | None = None,
    ) -> None:
        """Insert a teacher record. Silently skips if teacher_id already exists."""
        db = conn or self.db
        await db.execute(
            "INSERT OR IGNORE INTO teachers (teacher_id, display_name, pin_hash, created_at) "
            "VALUES (?, ?, ?, ?)",
            (teacher_id, display_name, pin_hash, datetime.now(timezone.utc).isoformat()),
        )
        if commit:
            await db.commit()

    async def get_teacher(
        self,
        teacher_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> dict | None:
        """Return teacher row as dict, or None if not found."""
        db = conn or self.db
        async with db.execute(
            "SELECT teacher_id, display_name, pin_hash FROM teachers WHERE teacher_id = ?",
            (teacher_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return {
                "teacher_id": row["teacher_id"],
                "display_name": row["display_name"],
                "pin_hash": row["pin_hash"],
            }

    # ── Evidence (immutable — no update method) ───────────────────

    @staticmethod
    def _row_to_evidence(row: aiosqlite.Row) -> Evidence:
        """Hydrate an Evidence model from a SQLite row."""
        return Evidence(
            evidence_id=row["evidence_id"],
            learner_id=row["learner_id"],
            evidence_type=EvidenceType(row["evidence_type"]),
            source_system=row["source_system"],
            ingestion_method=IngestionMethod(row["ingestion_method"]),
            source_event_id=row["source_event_id"],
            source_type=row["source_type"],
            source_reference=row["source_reference"],
            academic_year=row["academic_year"],
            term=row["term"],
            subject=row["subject"],
            content=json.loads(row["content"]),
            observed_at=datetime.fromisoformat(row["observed_at"]),
            recorded_at=datetime.fromisoformat(row["recorded_at"]),
        )

    async def add_evidence(
        self,
        evidence: Evidence,
        commit: bool = True,
        conn: aiosqlite.Connection | None = None,
    ) -> Evidence:
        """Insert a new evidence record. Evidence is immutable."""
        db = conn or self.db
        await db.execute(
            """INSERT INTO evidence
               (evidence_id, learner_id, evidence_type, source_system,
                ingestion_method, source_event_id, source_type, source_reference,
                academic_year, term, subject, content, observed_at,
                recorded_at, canonical_fingerprint)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                evidence.evidence_id,
                evidence.learner_id,
                evidence.evidence_type.value,
                evidence.source_system,
                evidence.ingestion_method.value,
                evidence.source_event_id,
                evidence.source_type,
                evidence.source_reference,
                evidence.academic_year,
                evidence.term,
                evidence.subject,
                json.dumps(_deep_unfreeze(evidence.content)),
                evidence.observed_at.isoformat(),
                evidence.recorded_at.isoformat(),
                evidence.canonical_fingerprint,
            ),
        )
        if commit:
            await db.commit()
        return evidence

    async def get_evidence_by_id(
        self,
        evidence_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> Evidence | None:
        """Retrieve a single evidence record by its UUID."""
        db = conn or self.db
        async with db.execute(
            "SELECT * FROM evidence WHERE evidence_id = ?",
            (evidence_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return self._row_to_evidence(row)

    async def get_evidence_by_ids(
        self,
        evidence_ids: Sequence[str],
        conn: aiosqlite.Connection | None = None,
    ) -> dict[str, Evidence]:
        """Retrieve multiple evidence records keyed by evidence_id."""
        unique_ids = [eid for eid in dict.fromkeys(evidence_ids) if eid]
        if not unique_ids:
            return {}
        db = conn or self.db
        placeholders = ",".join("?" for _ in unique_ids)
        query = f"SELECT * FROM evidence WHERE evidence_id IN ({placeholders})"
        found: dict[str, Evidence] = {}
        async with db.execute(query, tuple(unique_ids)) as cursor:
            async for row in cursor:
                ev = self._row_to_evidence(row)
                found[ev.evidence_id] = ev
        return found

    async def get_evidence_by_fingerprint(
        self,
        fingerprint: str,
        conn: aiosqlite.Connection | None = None,
    ) -> Evidence | None:
        """Retrieve evidence by its canonical record fingerprint."""
        db = conn or self.db
        async with db.execute(
            "SELECT * FROM evidence WHERE canonical_fingerprint = ?",
            (fingerprint,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return self._row_to_evidence(row)

    async def get_evidence_by_source_event(
        self,
        source_system: str,
        source_event_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> Evidence | None:
        """Retrieve evidence by its idempotent system identifiers."""
        db = conn or self.db
        async with db.execute(
            "SELECT * FROM evidence WHERE source_system = ? AND source_event_id = ?",
            (source_system, source_event_id),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return self._row_to_evidence(row)

    async def get_evidence_for_learner(
        self,
        learner_id: str,
        *,
        evidence_type: str | None = None,
        academic_year: int | None = None,
        term: int | None = None,
        subject: str | None = None,
        conn: aiosqlite.Connection | None = None,
    ) -> list[Evidence]:
        """Retrieve evidence for a learner, chronologically ordered.

        Orders by academic_year ASC, term ASC, observed_at ASC.
        """
        query = "SELECT * FROM evidence WHERE learner_id = ?"
        params: list = [learner_id]

        if evidence_type is not None:
            query += " AND evidence_type = ?"
            params.append(evidence_type)
        if academic_year is not None:
            query += " AND academic_year = ?"
            params.append(academic_year)
        if term is not None:
            query += " AND term = ?"
            params.append(term)
        if subject is not None:
            query += " AND subject = ?"
            params.append(subject)

        query += " ORDER BY academic_year ASC, term ASC, observed_at ASC"

        results = []
        db = conn or self.db
        async with db.execute(query, params) as cursor:
            async for row in cursor:
                results.append(self._row_to_evidence(row))
        return results

    # ── Import Manifests ──────────────────────────────────────────

    @staticmethod
    def _row_to_manifest(row: aiosqlite.Row) -> ImportManifest:
        """Hydrate an ImportManifest model from a SQLite row."""
        return ImportManifest(
            manifest_id=row["manifest_id"],
            source_system=row["source_system"],
            file_name=row["file_name"],
            import_method=row["import_method"],
            file_sha256=row["file_sha256"],
            row_count=row["row_count"],
            accepted_count=row["accepted_count"],
            rejected_count=row["rejected_count"],
            duplicate_count=row["duplicate_count"],
            imported_by=row["imported_by"],
            imported_at=datetime.fromisoformat(row["imported_at"]),
            notes=row["notes"],
        )

    async def add_import_manifest(
        self,
        manifest: ImportManifest,
        commit: bool = True,
        conn: aiosqlite.Connection | None = None,
    ) -> ImportManifest:
        """Record a file import manifest. Raises ValueError on duplicate (file_sha256, source_system)."""
        db = conn or self.db
        try:
            await db.execute(
                """INSERT INTO import_manifests
                   (manifest_id, source_system, file_name, import_method,
                    file_sha256, row_count, accepted_count, rejected_count,
                    duplicate_count, imported_by, imported_at, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    manifest.manifest_id,
                    manifest.source_system,
                    manifest.file_name,
                    manifest.import_method,
                    manifest.file_sha256,
                    manifest.row_count,
                    manifest.accepted_count,
                    manifest.rejected_count,
                    manifest.duplicate_count,
                    manifest.imported_by,
                    manifest.imported_at.isoformat(),
                    manifest.notes,
                ),
            )
        except Exception as e:
            if "UNIQUE constraint failed" in str(e):
                raise ValueError(
                    f"File with SHA-256 '{manifest.file_sha256}' from source "
                    f"'{manifest.source_system}' has already been imported. "
                    "Re-importing the same file would duplicate evidence records."
                ) from e
            raise
        if commit:
            await db.commit()
        return manifest

    async def get_import_manifest_by_hash(
        self,
        file_sha256: str,
        source_system: str,
        conn: aiosqlite.Connection | None = None,
    ) -> ImportManifest | None:
        """Check whether a file has already been imported from this source system."""
        db = conn or self.db
        async with db.execute(
            "SELECT * FROM import_manifests WHERE file_sha256 = ? AND source_system = ?",
            (file_sha256, source_system),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return self._row_to_manifest(row)

    async def list_import_manifests(
        self,
        source_system: str | None = None,
        conn: aiosqlite.Connection | None = None,
    ) -> list[dict]:
        """List import history, optionally filtered by source system."""
        db = conn or self.db
        if source_system:
            query = "SELECT * FROM import_manifests WHERE source_system = ? ORDER BY imported_at DESC"
            params: list = [source_system]
        else:
            query = "SELECT * FROM import_manifests ORDER BY imported_at DESC"
            params = []
        results = []
        async with db.execute(query, params) as cursor:
            async for row in cursor:
                results.append({
                    "manifest_id": row["manifest_id"],
                    "source_system": row["source_system"],
                    "file_name": row["file_name"],
                    "import_method": row["import_method"],
                    "file_sha256": row["file_sha256"],
                    "row_count": row["row_count"],
                    "accepted_count": row["accepted_count"],
                    "rejected_count": row["rejected_count"],
                    "duplicate_count": row["duplicate_count"],
                    "imported_by": row["imported_by"],
                    "imported_at": row["imported_at"],
                    "notes": row["notes"],
                })
        return results

    # ── Patterns ──────────────────────────────────────────────────

    async def add_pattern(
        self,
        pattern: Pattern,
        commit: bool = True,
        conn: aiosqlite.Connection | None = None,
    ) -> Pattern:
        """Insert a new pattern."""
        db = conn or self.db
        await db.execute(
            """INSERT INTO patterns
               (pattern_id, learner_id, pattern_type, summary,
                supporting_evidence, conflicting_evidence,
                limitations, generated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pattern.pattern_id,
                pattern.learner_id,
                pattern.pattern_type.value,
                pattern.summary,
                json.dumps(pattern.supporting_evidence),
                json.dumps(pattern.conflicting_evidence),
                json.dumps(pattern.limitations),
                pattern.generated_at.isoformat(),
            ),
        )
        if commit:
            await db.commit()
        return pattern

    async def get_pattern(
        self,
        pattern_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> Pattern | None:
        """Retrieve a pattern by ID."""
        db = conn or self.db
        async with db.execute(
            "SELECT * FROM patterns WHERE pattern_id = ?", (pattern_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return Pattern(
                pattern_id=row["pattern_id"],
                learner_id=row["learner_id"],
                pattern_type=PatternType(row["pattern_type"]),
                summary=row["summary"],
                supporting_evidence=json.loads(row["supporting_evidence"]),
                conflicting_evidence=json.loads(row["conflicting_evidence"]),
                limitations=json.loads(row["limitations"]),
                generated_at=datetime.fromisoformat(row["generated_at"]),
            )

    async def get_patterns_for_learner(
        self,
        learner_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> list[Pattern]:
        """Retrieve all patterns generated for a learner."""
        db = conn or self.db
        results: list[Pattern] = []
        async with db.execute(
            "SELECT * FROM patterns WHERE learner_id = ? ORDER BY generated_at ASC",
            (learner_id,),
        ) as cursor:
            async for row in cursor:
                results.append(
                    Pattern(
                        pattern_id=row["pattern_id"],
                        learner_id=row["learner_id"],
                        pattern_type=PatternType(row["pattern_type"]),
                        summary=row["summary"],
                        supporting_evidence=json.loads(row["supporting_evidence"]),
                        conflicting_evidence=json.loads(row["conflicting_evidence"]),
                        limitations=json.loads(row["limitations"]),
                        generated_at=datetime.fromisoformat(row["generated_at"]),
                    )
                )
        return results

    async def get_pattern_by_signature(
        self,
        learner_id: str,
        pattern_type: str,
        summary: str,
        conn: aiosqlite.Connection | None = None,
    ) -> Pattern | None:
        """Find an existing pattern with identical signature for deduplication."""
        db = conn or self.db
        async with db.execute(
            """SELECT * FROM patterns
               WHERE learner_id = ? AND pattern_type = ? AND summary = ?
               LIMIT 1""",
            (learner_id, pattern_type, summary),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return Pattern(
                pattern_id=row["pattern_id"],
                learner_id=row["learner_id"],
                pattern_type=PatternType(row["pattern_type"]),
                summary=row["summary"],
                supporting_evidence=json.loads(row["supporting_evidence"]),
                conflicting_evidence=json.loads(row["conflicting_evidence"]),
                limitations=json.loads(row["limitations"]),
                generated_at=datetime.fromisoformat(row["generated_at"]),
            )

    # ── Review Items ──────────────────────────────────────────────

    async def add_review_item(
        self,
        item: ReviewItem,
        commit: bool = True,
        conn: aiosqlite.Connection | None = None,
    ) -> ReviewItem:
        """Insert a new review item."""
        db = conn or self.db
        await db.execute(
            """INSERT INTO review_items
               (review_id, pattern_id, assigned_to, status,
                teacher_notes, created_at, resolved_at,
                reviewer_id, approved_content_hash, revision)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item.review_id,
                item.pattern_id,
                item.assigned_to,
                item.status.value,
                item.teacher_notes,
                item.created_at.isoformat(),
                item.resolved_at.isoformat() if item.resolved_at else None,
                item.reviewer_id,
                item.approved_content_hash,
                item.revision,
            ),
        )
        if commit:
            await db.commit()
        return item

    async def get_review_item(
        self,
        review_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> ReviewItem | None:
        """Retrieve a review item by review_id."""
        db = conn or self.db
        async with db.execute(
            "SELECT * FROM review_items WHERE review_id = ?", (review_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return ReviewItem(
                review_id=row["review_id"],
                pattern_id=row["pattern_id"],
                assigned_to=row["assigned_to"],
                status=ReviewStatus(row["status"]),
                teacher_notes=row["teacher_notes"],
                created_at=datetime.fromisoformat(row["created_at"]),
                resolved_at=datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None,
                reviewer_id=row["reviewer_id"],
                approved_content_hash=row["approved_content_hash"],
                revision=row["revision"] if "revision" in row.keys() else 0,
            )

    async def get_review_items_for_pattern(
        self,
        pattern_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> list[ReviewItem]:
        """Retrieve all review items for a given pattern."""
        db = conn or self.db
        results: list[ReviewItem] = []
        async with db.execute(
            "SELECT * FROM review_items WHERE pattern_id = ? ORDER BY created_at ASC",
            (pattern_id,),
        ) as cursor:
            async for row in cursor:
                results.append(
                    ReviewItem(
                        review_id=row["review_id"],
                        pattern_id=row["pattern_id"],
                        assigned_to=row["assigned_to"],
                        status=ReviewStatus(row["status"]),
                        teacher_notes=row["teacher_notes"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        resolved_at=datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None,
                        reviewer_id=row["reviewer_id"],
                        approved_content_hash=row["approved_content_hash"],
                        revision=row["revision"] if "revision" in row.keys() else 0,
                    )
                )
        return results

    async def get_pending_reviews(
        self,
        assigned_to: str | None = None,
        conn: aiosqlite.Connection | None = None,
    ) -> list[ReviewItem]:
        """Retrieve all pending review items, optionally filtered by teacher assignment."""
        db = conn or self.db
        if assigned_to:
            query = "SELECT * FROM review_items WHERE status = 'pending' AND assigned_to = ? ORDER BY created_at ASC"
            params: list = [assigned_to]
        else:
            query = "SELECT * FROM review_items WHERE status = 'pending' ORDER BY created_at ASC"
            params = []

        results: list[ReviewItem] = []
        async with db.execute(query, params) as cursor:
            async for row in cursor:
                results.append(
                    ReviewItem(
                        review_id=row["review_id"],
                        pattern_id=row["pattern_id"],
                        assigned_to=row["assigned_to"],
                        status=ReviewStatus(row["status"]),
                        teacher_notes=row["teacher_notes"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        resolved_at=datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None,
                        reviewer_id=row["reviewer_id"],
                        approved_content_hash=row["approved_content_hash"],
                        revision=row["revision"] if "revision" in row.keys() else 0,
                    )
                )
        return results

    async def update_review_item(
        self,
        item: ReviewItem,
        commit: bool = True,
        conn: aiosqlite.Connection | None = None,
    ) -> ReviewItem:
        """Unconditional update — only for internal migrations.  Prefer update_review_at_revision."""
        db = conn or self.db
        await db.execute(
            """UPDATE review_items
               SET status = ?, teacher_notes = ?, resolved_at = ?,
                   reviewer_id = ?, approved_content_hash = ?, assigned_to = ?,
                   revision = revision + 1
               WHERE review_id = ?""",
            (
                item.status.value,
                item.teacher_notes,
                item.resolved_at.isoformat() if item.resolved_at else None,
                item.reviewer_id,
                item.approved_content_hash,
                item.assigned_to,
                item.review_id,
            ),
        )
        if commit:
            await db.commit()
        return item

    async def update_review_at_revision(
        self,
        item: ReviewItem,
        expected_revision: int,
        conn: aiosqlite.Connection | None = None,
    ) -> bool:
        """Conditionally update a review item only if its revision matches expected_revision.

        Atomically increments revision on success.
        Returns True if the row was updated (optimistic lock held), False on conflict.
        Must be called inside a store.transaction() block.
        """
        db = conn or self.db
        cursor = await db.execute(
            """UPDATE review_items
               SET status = ?, teacher_notes = ?, resolved_at = ?,
                   reviewer_id = ?, approved_content_hash = ?, assigned_to = ?,
                   revision = revision + 1
               WHERE review_id = ? AND revision = ?""",
            (
                item.status.value,
                item.teacher_notes,
                item.resolved_at.isoformat() if item.resolved_at else None,
                item.reviewer_id,
                item.approved_content_hash,
                item.assigned_to,
                item.review_id,
                expected_revision,
            ),
        )
        return cursor.rowcount == 1

    async def resolve_review_if_pending(
        self,
        item: ReviewItem,
        conn: aiosqlite.Connection | None = None,
    ) -> bool:
        """Atomically resolve a review only if it is still pending AND revision matches.

        Kept for backwards-compatibility; delegates to update_review_at_revision with
        the additional constraint that status must still be 'pending'.
        Returns True if the row was updated, False if another caller got there first.
        Must be called inside a store.transaction() block.
        """
        db = conn or self.db
        cursor = await db.execute(
            """UPDATE review_items
               SET status = ?, teacher_notes = ?, resolved_at = ?,
                   reviewer_id = ?, approved_content_hash = ?, assigned_to = ?,
                   revision = revision + 1
               WHERE review_id = ? AND revision = ? AND status = 'pending'""",
            (
                item.status.value,
                item.teacher_notes,
                item.resolved_at.isoformat() if item.resolved_at else None,
                item.reviewer_id,
                item.approved_content_hash,
                item.assigned_to,
                item.review_id,
                item.revision,
            ),
        )
        return cursor.rowcount == 1

    async def get_surfaced_profile(
        self,
        learner_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> list[dict]:
        """Retrieve published profile for a learner, strictly exposing accepted patterns.

        Unreviewed, pending, or rejected patterns are excluded by the human-in-the-loop gate.
        Validates the cryptographic content hash against pattern summary to detect tampering.
        """
        import hashlib

        db = conn or self.db
        query = """
            SELECT p.pattern_id, p.learner_id, p.pattern_type, p.summary,
                   p.supporting_evidence, p.conflicting_evidence, p.limitations,
                   p.generated_at, r.review_id, r.status, r.teacher_notes,
                   r.reviewer_id, r.approved_content_hash, r.resolved_at,
                   COALESCE(r.revision, 0) AS revision
            FROM patterns p
            INNER JOIN review_items r ON p.pattern_id = r.pattern_id
            WHERE p.learner_id = ? AND r.status = 'accepted'
            ORDER BY p.generated_at ASC
        """
        results = []
        async with db.execute(query, (learner_id,)) as cursor:
            async for row in cursor:
                summary = row["summary"]
                expected_hash = row["approved_content_hash"]
                actual_hash = (
                    hashlib.sha256(summary.strip().encode("utf-8")).hexdigest()
                    if summary
                    else ""
                )
                verified = bool(expected_hash and actual_hash == expected_hash)
                if not verified:
                    continue

                results.append({
                    "pattern_id": row["pattern_id"],
                    "learner_id": row["learner_id"],
                    "pattern_type": row["pattern_type"],
                    "summary": summary,
                    "supporting_evidence": json.loads(row["supporting_evidence"]),
                    "conflicting_evidence": json.loads(row["conflicting_evidence"]),
                    "limitations": json.loads(row["limitations"]),
                    "generated_at": row["generated_at"],
                    "review": {
                        "review_id": row["review_id"],
                        "status": row["status"],
                        "reviewer_id": row["reviewer_id"],
                        "teacher_notes": row["teacher_notes"],
                        "resolved_at": row["resolved_at"],
                        "approved_content_hash": expected_hash,
                        "hash_verified": True,
                        "revision": row["revision"] if "revision" in row.keys() else 0,
                    },
                })
        return results

    # ── Audit Log ─────────────────────────────────────────────────

    async def add_audit_entry(
        self,
        entry: AuditEntry,
        commit: bool = True,
        conn: aiosqlite.Connection | None = None,
    ) -> AuditEntry:
        """Insert an audit log entry."""
        db = conn or self.db
        await db.execute(
            """INSERT INTO audit_log
               (audit_id, timestamp, tool_name, input_summary,
                output_reference, approval_state)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                entry.audit_id,
                entry.timestamp.isoformat(),
                entry.tool_name,
                json.dumps(entry.input_summary),
                entry.output_reference,
                entry.approval_state,
            ),
        )
        if commit:
            await db.commit()
        return entry

    async def get_audit_log(
        self,
        tool_name: str | None = None,
        conn: aiosqlite.Connection | None = None,
    ) -> list[AuditEntry]:
        """Retrieve audit log entries, optionally filtered by tool name."""
        if tool_name:
            query = (
                "SELECT * FROM audit_log WHERE tool_name = ? "
                "ORDER BY timestamp ASC"
            )
            params: list = [tool_name]
        else:
            query = "SELECT * FROM audit_log ORDER BY timestamp ASC"
            params = []

        results = []
        db = conn or self.db
        async with db.execute(query, params) as cursor:
            async for row in cursor:
                results.append(
                    AuditEntry(
                        audit_id=row["audit_id"],
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                        tool_name=row["tool_name"],
                        input_summary=json.loads(row["input_summary"]),
                        output_reference=row["output_reference"],
                        approval_state=row["approval_state"],
                    )
                )
        return results

    # ── Candidate Briefs (INT-01) ──────────────────────────────────

    async def add_candidate_brief(
        self,
        brief: dict[str, Any],
        commit: bool = True,
        conn: aiosqlite.Connection | None = None,
    ) -> dict[str, Any]:
        """Persist a complete CandidateHandoverBrief with full provenance and associations."""
        db = conn or self.db
        findings_raw = brief.get("findings", [])
        if isinstance(findings_raw, str):
            findings_json = findings_raw
        else:
            findings_list = []
            for f in findings_raw:
                if hasattr(f, "model_dump"):
                    findings_list.append(f.model_dump(mode="json"))
                elif isinstance(f, dict):
                    findings_list.append(f)
                else:
                    findings_list.append(dict(f))
            findings_json = json.dumps(findings_list)

        contradictions_json = (
            brief["contradictions"]
            if isinstance(brief.get("contradictions"), str)
            else json.dumps(brief.get("contradictions", []))
        )
        limitations_json = (
            brief["limitations"]
            if isinstance(brief.get("limitations"), str)
            else json.dumps(brief.get("limitations", []))
        )
        gen_at = brief.get("generated_at")
        if isinstance(gen_at, datetime):
            gen_at_str = gen_at.isoformat()
        elif gen_at:
            gen_at_str = str(gen_at)
        else:
            gen_at_str = datetime.now(timezone.utc).isoformat()

        await db.execute(
            """INSERT INTO candidate_briefs
               (brief_id, learner_id, pattern_id, review_id, generation_revision,
                status, summary, findings, contradictions, limitations,
                abstention_reason, runtime_method, generated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                brief["brief_id"],
                brief["learner_id"],
                brief.get("pattern_id"),
                brief.get("review_id"),
                brief.get("generation_revision", 1),
                brief["status"] if isinstance(brief["status"], str) else getattr(brief["status"], "value", str(brief["status"])),
                brief["summary"],
                findings_json,
                contradictions_json,
                limitations_json,
                brief.get("abstention_reason"),
                brief.get("runtime_method", "unknown"),
                gen_at_str,
            ),
        )
        if commit:
            await db.commit()
        return brief

    async def get_generation_revision_count(
        self,
        learner_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> int:
        """Get the number of candidate briefs generated so far for this learner."""
        db = conn or self.db
        async with db.execute(
            "SELECT COUNT(*) AS cnt FROM candidate_briefs WHERE learner_id = ?",
            (learner_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return row["cnt"] if row else 0

    async def get_latest_candidate_brief(
        self,
        learner_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> dict[str, Any] | None:
        """Retrieve the latest persisted candidate brief for a learner."""
        db = conn or self.db
        async with db.execute(
            """SELECT * FROM candidate_briefs
               WHERE learner_id = ?
               ORDER BY generation_revision DESC, generated_at DESC
               LIMIT 1""",
            (learner_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return {
                "brief_id": row["brief_id"],
                "learner_id": row["learner_id"],
                "pattern_id": row["pattern_id"],
                "review_id": row["review_id"],
                "generation_revision": row["generation_revision"],
                "status": row["status"],
                "summary": row["summary"],
                "findings": json.loads(row["findings"]),
                "contradictions": json.loads(row["contradictions"]),
                "limitations": json.loads(row["limitations"]),
                "abstention_reason": row["abstention_reason"],
                "runtime_method": row["runtime_method"],
                "generated_at": row["generated_at"],
            }

    async def get_candidate_brief_by_pattern(
        self,
        pattern_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> dict[str, Any] | None:
        """Retrieve the candidate brief associated with a pattern ID."""
        db = conn or self.db
        async with db.execute(
            "SELECT * FROM candidate_briefs WHERE pattern_id = ? ORDER BY generation_revision DESC LIMIT 1",
            (pattern_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return {
                "brief_id": row["brief_id"],
                "learner_id": row["learner_id"],
                "pattern_id": row["pattern_id"],
                "review_id": row["review_id"],
                "generation_revision": row["generation_revision"],
                "status": row["status"],
                "summary": row["summary"],
                "findings": json.loads(row["findings"]),
                "contradictions": json.loads(row["contradictions"]),
                "limitations": json.loads(row["limitations"]),
                "abstention_reason": row["abstention_reason"],
                "runtime_method": row["runtime_method"],
                "generated_at": row["generated_at"],
            }

    # ── Workspace Diagnostics & Reset ──────────────────────────────

    async def get_database_status(
        self,
        recent_limit: int = 5,
        conn: aiosqlite.Connection | None = None,
    ) -> dict[str, Any]:
        """Return live counts, freshness timestamps, and most recent activity."""
        db = conn or self.db

        async def _count(sql: str, params: tuple[Any, ...] = ()) -> int:
            async with db.execute(sql, params) as cursor:
                row = await cursor.fetchone()
                return int(row["cnt"]) if row else 0

        async def _scalar(sql: str) -> str | None:
            async with db.execute(sql) as cursor:
                row = await cursor.fetchone()
                return row[0] if row and row[0] is not None else None

        learners_count = await _count("SELECT COUNT(*) AS cnt FROM learners")
        evidence_count = await _count("SELECT COUNT(*) AS cnt FROM evidence")
        patterns_count = await _count("SELECT COUNT(*) AS cnt FROM patterns")
        review_items_count = await _count("SELECT COUNT(*) AS cnt FROM review_items")
        pending_reviews_count = await _count(
            "SELECT COUNT(*) AS cnt FROM review_items WHERE status = 'pending'"
        )
        accepted_reviews_count = await _count(
            "SELECT COUNT(*) AS cnt FROM review_items WHERE status = 'accepted'"
        )
        rejected_reviews_count = await _count(
            "SELECT COUNT(*) AS cnt FROM review_items WHERE status = 'rejected'"
        )
        needs_context_reviews_count = await _count(
            "SELECT COUNT(*) AS cnt FROM review_items WHERE status = 'needs_context'"
        )
        candidate_briefs_count = await _count("SELECT COUNT(*) AS cnt FROM candidate_briefs")
        import_manifests_count = await _count("SELECT COUNT(*) AS cnt FROM import_manifests")
        audit_entries_count = await _count("SELECT COUNT(*) AS cnt FROM audit_log")

        latest_evidence_recorded_at = await _scalar("SELECT MAX(recorded_at) FROM evidence")
        latest_evidence_observed_at = await _scalar("SELECT MAX(observed_at) FROM evidence")
        latest_pattern_generated_at = await _scalar("SELECT MAX(generated_at) FROM patterns")
        latest_manifest_imported_at = await _scalar("SELECT MAX(imported_at) FROM import_manifests")
        latest_audit_at = await _scalar("SELECT MAX(timestamp) FROM audit_log")

        recent_evidence: list[dict[str, Any]] = []
        async with db.execute(
            """SELECT evidence_id, learner_id, evidence_type, subject,
                      academic_year, term, source_system, ingestion_method,
                      source_reference, recorded_at, observed_at
               FROM evidence
               ORDER BY recorded_at DESC, rowid DESC
               LIMIT ?""",
            (recent_limit,),
        ) as cursor:
            async for row in cursor:
                recent_evidence.append({
                    "evidence_id": row["evidence_id"],
                    "learner_id": row["learner_id"],
                    "evidence_type": row["evidence_type"],
                    "subject": row["subject"],
                    "academic_year": row["academic_year"],
                    "term": row["term"],
                    "source_system": row["source_system"],
                    "ingestion_method": row["ingestion_method"],
                    "source_reference": row["source_reference"],
                    "recorded_at": row["recorded_at"],
                    "observed_at": row["observed_at"],
                })

        recent_audit: list[dict[str, Any]] = []
        async with db.execute(
            """SELECT audit_id, timestamp, tool_name, output_reference, approval_state
               FROM audit_log
               ORDER BY timestamp DESC, rowid DESC
               LIMIT ?""",
            (recent_limit,),
        ) as cursor:
            async for row in cursor:
                recent_audit.append({
                    "audit_id": row["audit_id"],
                    "timestamp": row["timestamp"],
                    "tool_name": row["tool_name"],
                    "output_reference": row["output_reference"],
                    "approval_state": row["approval_state"],
                })

        return {
            "db_path": self._db_path,
            "learners_count": learners_count,
            "evidence_count": evidence_count,
            "patterns_count": patterns_count,
            "review_items_count": review_items_count,
            "pending_reviews_count": pending_reviews_count,
            "accepted_reviews_count": accepted_reviews_count,
            "rejected_reviews_count": rejected_reviews_count,
            "needs_context_reviews_count": needs_context_reviews_count,
            "candidate_briefs_count": candidate_briefs_count,
            "import_manifests_count": import_manifests_count,
            "audit_entries_count": audit_entries_count,
            "latest_evidence_recorded_at": latest_evidence_recorded_at,
            "latest_evidence_observed_at": latest_evidence_observed_at,
            "latest_pattern_generated_at": latest_pattern_generated_at,
            "latest_manifest_imported_at": latest_manifest_imported_at,
            "latest_audit_at": latest_audit_at,
            "recent_evidence": recent_evidence,
            "recent_audit": recent_audit,
        }

    async def reset_workspace_data(self, *, actor: str = "system") -> dict[str, int]:
        """Clear workspace learner/evidence/review/handover data while preserving teacher accounts, classes, assignments, and audit log."""
        tables = (
            "post_release_changes",
            "subject_responses",
            "report_view_events",
            "report_receipts",
            "published_report_sections",
            "class_releases",
            "section_reviews",
            "class_enrollments",
            "candidate_briefs",
            "review_items",
            "patterns",
            "evidence",
            "import_manifests",
            "learners",
        )
        cleared: dict[str, int] = {}
        async with self.transaction() as conn:
            for table in tables:
                async with conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}") as cursor:
                    row = await cursor.fetchone()
                    cleared[table] = int(row["cnt"]) if row else 0
                await conn.execute(f"DELETE FROM {table}")

            await self.add_audit_entry(
                AuditEntry(
                    tool_name="workspace_reset",
                    input_summary={"actor": actor, "cleared": cleared},
                    output_reference=None,
                    approval_state="reset",
                ),
                commit=False,
                conn=conn,
            )
        return cleared

    # ── Classes, Enrollments & Teacher Assignments ─────────────────

    async def add_class(
        self,
        school_class: SchoolClass,
        commit: bool = True,
        conn: aiosqlite.Connection | None = None,
    ) -> SchoolClass:
        """Create or preserve a school class cohort."""
        db = conn or self.db
        await db.execute(
            """INSERT OR IGNORE INTO classes
               (class_id, display_name, grade, academic_year, term, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                school_class.class_id,
                school_class.display_name,
                school_class.grade,
                school_class.academic_year,
                school_class.term,
                school_class.created_at.isoformat(),
            ),
        )
        if commit and conn is None:
            await db.commit()
        return school_class

    async def get_class(
        self,
        class_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> SchoolClass | None:
        db = conn or self.db
        async with db.execute("SELECT * FROM classes WHERE class_id = ?", (class_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return SchoolClass(
                class_id=row["class_id"],
                display_name=row["display_name"],
                grade=row["grade"],
                academic_year=row["academic_year"],
                term=row["term"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )

    async def list_classes(self, conn: aiosqlite.Connection | None = None) -> list[SchoolClass]:
        db = conn or self.db
        out: list[SchoolClass] = []
        async with db.execute("SELECT * FROM classes ORDER BY class_id ASC") as cursor:
            async for row in cursor:
                out.append(SchoolClass(
                    class_id=row["class_id"],
                    display_name=row["display_name"],
                    grade=row["grade"],
                    academic_year=row["academic_year"],
                    term=row["term"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                ))
        return out

    async def enroll_learner(
        self,
        class_id: str,
        learner_id: str,
        *,
        enrolled_at: datetime | None = None,
        commit: bool = True,
        conn: aiosqlite.Connection | None = None,
    ) -> ClassEnrollment:
        """Idempotently enroll a learner in a school class."""
        db = conn or self.db
        ts = (enrolled_at or datetime.now(timezone.utc)).isoformat()
        await db.execute(
            "INSERT OR IGNORE INTO class_enrollments (class_id, learner_id, enrolled_at) VALUES (?, ?, ?)",
            (class_id, learner_id, ts),
        )
        if commit and conn is None:
            await db.commit()
        return ClassEnrollment(
            class_id=class_id,
            learner_id=learner_id,
            enrolled_at=datetime.fromisoformat(ts),
        )

    async def get_class_learners(
        self,
        class_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> list[Learner]:
        """List all learners enrolled in a class ordered by learner_id."""
        db = conn or self.db
        out: list[Learner] = []
        async with db.execute(
            """SELECT l.learner_id, l.display_name, l.created_at
               FROM learners l
               JOIN class_enrollments ce ON ce.learner_id = l.learner_id
               WHERE ce.class_id = ?
               ORDER BY l.learner_id ASC""",
            (class_id,),
        ) as cursor:
            async for row in cursor:
                out.append(Learner(
                    learner_id=row["learner_id"],
                    display_name=row["display_name"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                ))
        return out

    async def get_learner_classes(
        self,
        learner_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> list[SchoolClass]:
        """List classes in which a learner is enrolled."""
        db = conn or self.db
        out: list[SchoolClass] = []
        async with db.execute(
            """SELECT c.*
               FROM classes c
               JOIN class_enrollments ce ON ce.class_id = c.class_id
               WHERE ce.learner_id = ?
               ORDER BY c.academic_year DESC, c.term DESC, c.class_id ASC""",
            (learner_id,),
        ) as cursor:
            async for row in cursor:
                out.append(SchoolClass(
                    class_id=row["class_id"],
                    display_name=row["display_name"],
                    grade=row["grade"],
                    academic_year=row["academic_year"],
                    term=row["term"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                ))
        return out

    async def add_teacher_assignment(
        self,
        assignment: TeacherAssignment,
        commit: bool = True,
        conn: aiosqlite.Connection | None = None,
    ) -> TeacherAssignment:
        """Idempotently record a teacher's class/subject responsibility."""
        db = conn or self.db
        if assignment.subject is None:
            sql_check = (
                "SELECT assignment_id FROM teacher_assignments "
                "WHERE teacher_id = ? AND class_id = ? AND role = ? AND subject IS NULL"
            )
            params: tuple[Any, ...] = (assignment.teacher_id, assignment.class_id, assignment.role.value)
        else:
            sql_check = (
                "SELECT assignment_id FROM teacher_assignments "
                "WHERE teacher_id = ? AND class_id = ? AND role = ? AND subject = ?"
            )
            params = (assignment.teacher_id, assignment.class_id, assignment.role.value, assignment.subject)

        async with db.execute(sql_check, params) as cursor:
            existing = await cursor.fetchone()
            if existing:
                return assignment.model_copy(update={"assignment_id": existing["assignment_id"]})

        await db.execute(
            """INSERT INTO teacher_assignments
               (assignment_id, teacher_id, class_id, role, subject, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                assignment.assignment_id,
                assignment.teacher_id,
                assignment.class_id,
                assignment.role.value,
                assignment.subject,
                assignment.created_at.isoformat(),
            ),
        )
        if commit and conn is None:
            await db.commit()
        return assignment

    async def get_teacher_assignments(
        self,
        teacher_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> list[TeacherAssignment]:
        db = conn or self.db
        out: list[TeacherAssignment] = []
        async with db.execute(
            "SELECT * FROM teacher_assignments WHERE teacher_id = ? ORDER BY class_id ASC, role ASC, subject ASC",
            (teacher_id,),
        ) as cursor:
            async for row in cursor:
                out.append(TeacherAssignment(
                    assignment_id=row["assignment_id"],
                    teacher_id=row["teacher_id"],
                    class_id=row["class_id"],
                    role=TeacherRole(row["role"]),
                    subject=row["subject"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                ))
        return out

    async def get_class_assignments(
        self,
        class_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> list[TeacherAssignment]:
        db = conn or self.db
        out: list[TeacherAssignment] = []
        async with db.execute(
            "SELECT * FROM teacher_assignments WHERE class_id = ? ORDER BY role ASC, subject ASC, teacher_id ASC",
            (class_id,),
        ) as cursor:
            async for row in cursor:
                out.append(TeacherAssignment(
                    assignment_id=row["assignment_id"],
                    teacher_id=row["teacher_id"],
                    class_id=row["class_id"],
                    role=TeacherRole(row["role"]),
                    subject=row["subject"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                ))
        return out

    # ── Section Reviews (Pre-Release Readiness Slots) ───────────────

    @staticmethod
    def _row_to_section_review(row: aiosqlite.Row) -> SectionReview:
        return SectionReview(
            section_review_id=row["section_review_id"],
            class_id=row["class_id"],
            learner_id=row["learner_id"],
            scope=row["scope"],
            review_state=SectionReviewState(row["review_state"]),
            approved_summary=row["approved_summary"],
            teacher_notes=row["teacher_notes"],
            missing_evidence_disclosure=row["missing_evidence_disclosure"],
            citations=tuple(json.loads(row["citations_json"])),
            reviewed_by=row["reviewed_by"],
            reviewed_at=datetime.fromisoformat(row["reviewed_at"]) if row["reviewed_at"] else None,
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    async def upsert_section_review(
        self,
        section: SectionReview,
        commit: bool = True,
        conn: aiosqlite.Connection | None = None,
    ) -> SectionReview:
        """Create or update a pre-release Student/Subject Review slot."""
        db = conn or self.db
        await db.execute(
            """INSERT INTO section_reviews
               (section_review_id, class_id, learner_id, scope, review_state,
                approved_summary, teacher_notes, missing_evidence_disclosure,
                citations_json, reviewed_by, reviewed_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(class_id, learner_id, scope) DO UPDATE SET
                   review_state = excluded.review_state,
                   approved_summary = excluded.approved_summary,
                   teacher_notes = excluded.teacher_notes,
                   missing_evidence_disclosure = excluded.missing_evidence_disclosure,
                   citations_json = excluded.citations_json,
                   reviewed_by = excluded.reviewed_by,
                   reviewed_at = excluded.reviewed_at,
                   updated_at = excluded.updated_at""",
            (
                section.section_review_id,
                section.class_id,
                section.learner_id,
                section.scope,
                section.review_state.value,
                section.approved_summary,
                section.teacher_notes,
                section.missing_evidence_disclosure,
                json.dumps(list(section.citations)),
                section.reviewed_by,
                section.reviewed_at.isoformat() if section.reviewed_at else None,
                section.updated_at.isoformat(),
            ),
        )
        if commit and conn is None:
            await db.commit()
        fetched = await self.get_section_review(section.class_id, section.learner_id, section.scope, conn=conn)
        return fetched or section

    async def get_section_review(
        self,
        class_id: str,
        learner_id: str,
        scope: str,
        conn: aiosqlite.Connection | None = None,
    ) -> SectionReview | None:
        db = conn or self.db
        async with db.execute(
            "SELECT * FROM section_reviews WHERE class_id = ? AND learner_id = ? AND scope = ?",
            (class_id, learner_id, scope),
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_section_review(row) if row else None

    async def get_section_reviews_for_class(
        self,
        class_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> list[SectionReview]:
        db = conn or self.db
        out: list[SectionReview] = []
        async with db.execute(
            "SELECT * FROM section_reviews WHERE class_id = ? ORDER BY learner_id ASC, scope ASC",
            (class_id,),
        ) as cursor:
            async for row in cursor:
                out.append(self._row_to_section_review(row))
        return out

    async def get_section_reviews_for_learner(
        self,
        class_id: str,
        learner_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> list[SectionReview]:
        db = conn or self.db
        out: list[SectionReview] = []
        async with db.execute(
            "SELECT * FROM section_reviews WHERE class_id = ? AND learner_id = ? ORDER BY scope ASC",
            (class_id, learner_id),
        ) as cursor:
            async for row in cursor:
                out.append(self._row_to_section_review(row))
        return out

    # ── Class Releases & Frozen Published Report Sections ──────────

    @staticmethod
    def _row_to_class_release(row: aiosqlite.Row) -> ClassRelease:
        return ClassRelease(
            release_id=row["release_id"],
            class_id=row["class_id"],
            version_number=row["version_number"],
            released_by=row["released_by"],
            released_by_name=row["released_by_name"],
            released_at=datetime.fromisoformat(row["released_at"]),
            frozen_enrollment=tuple(json.loads(row["frozen_enrollment_json"])),
            frozen_subjects=tuple(json.loads(row["frozen_subjects_json"])),
            notes=row["notes"],
        )

    @staticmethod
    def _row_to_published_section(row: aiosqlite.Row) -> PublishedReportSection:
        return PublishedReportSection(
            published_section_id=row["published_section_id"],
            release_id=row["release_id"],
            class_id=row["class_id"],
            learner_id=row["learner_id"],
            scope=row["scope"],
            section_title=row["section_title"],
            review_state=SectionReviewState(row["review_state"]),
            evidence_availability=json.loads(row["evidence_availability_json"]),
            approved_summary=row["approved_summary"],
            teacher_notes=row["teacher_notes"],
            missing_evidence_disclosure=row["missing_evidence_disclosure"],
            citations=tuple(json.loads(row["citations_json"])),
            approved_content_hash=row["approved_content_hash"] if "approved_content_hash" in row.keys() else "",
            evidence_fingerprints=json.loads(row["evidence_fingerprints_json"]),
            analysis_signature=json.loads(row["analysis_signature_json"]),
            approved_by=row["approved_by"],
            approved_by_name=row["approved_by_name"],
            approved_at=datetime.fromisoformat(row["approved_at"]),
            released_by=row["released_by"],
            released_at=datetime.fromisoformat(row["released_at"]),
        )

    async def create_class_release(
        self,
        release: ClassRelease,
        sections: Sequence[PublishedReportSection],
        initial_receipts: Sequence[ReportReceipt],
        *,
        conn: aiosqlite.Connection | None = None,
    ) -> ClassRelease:
        """Atomically persist a frozen ClassRelease, its PublishedReportSections, and initial ReportReceipts."""
        async def _write(c: aiosqlite.Connection) -> None:
            await c.execute(
                """INSERT INTO class_releases
                   (release_id, class_id, version_number, released_by, released_by_name,
                    released_at, frozen_enrollment_json, frozen_subjects_json, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    release.release_id,
                    release.class_id,
                    release.version_number,
                    release.released_by,
                    release.released_by_name,
                    release.released_at.isoformat(),
                    json.dumps(list(release.frozen_enrollment)),
                    json.dumps(list(release.frozen_subjects)),
                    release.notes,
                ),
            )
            for sec in sections:
                await c.execute(
                    """INSERT INTO published_report_sections
                       (published_section_id, release_id, class_id, learner_id, scope,
                        section_title, review_state, evidence_availability_json,
                        approved_summary, teacher_notes, missing_evidence_disclosure,
                        citations_json, approved_content_hash, evidence_fingerprints_json,
                        analysis_signature_json, approved_by, approved_by_name,
                        approved_at, released_by, released_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        sec.published_section_id,
                        sec.release_id,
                        sec.class_id,
                        sec.learner_id,
                        sec.scope,
                        sec.section_title,
                        sec.review_state.value,
                        json.dumps(sec.evidence_availability),
                        sec.approved_summary,
                        sec.teacher_notes,
                        sec.missing_evidence_disclosure,
                        json.dumps(list(sec.citations)),
                        sec.approved_content_hash,
                        json.dumps(sec.evidence_fingerprints),
                        json.dumps(sec.analysis_signature),
                        sec.approved_by,
                        sec.approved_by_name,
                        sec.approved_at.isoformat(),
                        sec.released_by,
                        sec.released_at.isoformat(),
                    ),
                )
            for rc in initial_receipts:
                await c.execute(
                    """INSERT OR IGNORE INTO report_receipts
                       (receipt_id, release_id, class_id, learner_id, teacher_id,
                        teacher_name, subject, status, first_viewed_at, last_viewed_at,
                        view_count, acknowledged_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        rc.receipt_id,
                        rc.release_id,
                        rc.class_id,
                        rc.learner_id,
                        rc.teacher_id,
                        rc.teacher_name,
                        rc.subject,
                        rc.status.value,
                        rc.first_viewed_at.isoformat() if rc.first_viewed_at else None,
                        rc.last_viewed_at.isoformat() if rc.last_viewed_at else None,
                        rc.view_count,
                        rc.acknowledged_at.isoformat() if rc.acknowledged_at else None,
                    ),
                )

        if conn is not None:
            await _write(conn)
        else:
            async with self.transaction() as c:
                await _write(c)
        return release

    async def get_latest_class_release(
        self,
        class_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> ClassRelease | None:
        db = conn or self.db
        async with db.execute(
            "SELECT * FROM class_releases WHERE class_id = ? ORDER BY version_number DESC LIMIT 1",
            (class_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_class_release(row) if row else None

    async def get_class_release(
        self,
        release_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> ClassRelease | None:
        db = conn or self.db
        async with db.execute(
            "SELECT * FROM class_releases WHERE release_id = ?",
            (release_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_class_release(row) if row else None

    async def list_class_releases(
        self,
        class_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> list[ClassRelease]:
        db = conn or self.db
        out: list[ClassRelease] = []
        async with db.execute(
            "SELECT * FROM class_releases WHERE class_id = ? ORDER BY version_number DESC",
            (class_id,),
        ) as cursor:
            async for row in cursor:
                out.append(self._row_to_class_release(row))
        return out

    async def get_published_sections_for_release(
        self,
        release_id: str,
        learner_id: str | None = None,
        conn: aiosqlite.Connection | None = None,
    ) -> list[PublishedReportSection]:
        db = conn or self.db
        if learner_id is not None:
            sql = "SELECT * FROM published_report_sections WHERE release_id = ? AND learner_id = ? ORDER BY scope ASC"
            params: tuple[Any, ...] = (release_id, learner_id)
        else:
            sql = "SELECT * FROM published_report_sections WHERE release_id = ? ORDER BY learner_id ASC, scope ASC"
            params = (release_id,)
        out: list[PublishedReportSection] = []
        async with db.execute(sql, params) as cursor:
            async for row in cursor:
                out.append(self._row_to_published_section(row))
        return out

    async def get_published_sections_for_learner(
        self,
        learner_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> tuple[ClassRelease | None, list[PublishedReportSection]]:
        """Return latest release covering learner_id along with its frozen sections."""
        db = conn or self.db
        async with db.execute(
            """SELECT r.*
               FROM class_releases r
               JOIN published_report_sections ps ON ps.release_id = r.release_id
               WHERE ps.learner_id = ?
               ORDER BY r.version_number DESC, r.released_at DESC
               LIMIT 1""",
            (learner_id,),
        ) as cursor:
            rel_row = await cursor.fetchone()
            if not rel_row:
                return None, []
            release = self._row_to_class_release(rel_row)
        sections = await self.get_published_sections_for_release(release.release_id, learner_id=learner_id, conn=conn)
        return release, sections

    # ── Viewing History & Separate Acknowledgments ──────────────────

    @staticmethod
    def _row_to_view_event(row: aiosqlite.Row) -> ReportViewEvent:
        return ReportViewEvent(
            view_id=row["view_id"],
            release_id=row["release_id"],
            class_id=row["class_id"],
            learner_id=row["learner_id"],
            scope=row["scope"],
            teacher_id=row["teacher_id"],
            teacher_name=row["teacher_name"],
            viewed_at=datetime.fromisoformat(row["viewed_at"]),
        )

    @staticmethod
    def _row_to_receipt(row: aiosqlite.Row) -> ReportReceipt:
        return ReportReceipt(
            receipt_id=row["receipt_id"],
            release_id=row["release_id"],
            class_id=row["class_id"],
            learner_id=row["learner_id"],
            teacher_id=row["teacher_id"],
            teacher_name=row["teacher_name"],
            subject=row["subject"],
            status=ReceiptStatus(row["status"]),
            first_viewed_at=datetime.fromisoformat(row["first_viewed_at"]) if row["first_viewed_at"] else None,
            last_viewed_at=datetime.fromisoformat(row["last_viewed_at"]) if row["last_viewed_at"] else None,
            view_count=int(row["view_count"]),
            acknowledged_at=datetime.fromisoformat(row["acknowledged_at"]) if row["acknowledged_at"] else None,
        )

    async def record_report_view_event(
        self,
        event: ReportViewEvent,
        *,
        subject: str | None = None,
        conn: aiosqlite.Connection | None = None,
    ) -> tuple[ReportViewEvent, ReportReceipt]:
        """Append viewing event and update receipt without downgrading acknowledgment."""
        ts = event.viewed_at.isoformat()
        import uuid as _uuid

        async def _write(c: aiosqlite.Connection) -> None:
            await c.execute(
                """INSERT INTO report_view_events
                   (view_id, release_id, class_id, learner_id, scope, teacher_id, teacher_name, viewed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.view_id,
                    event.release_id,
                    event.class_id,
                    event.learner_id,
                    event.scope,
                    event.teacher_id,
                    event.teacher_name,
                    ts,
                ),
            )
            await c.execute(
                """INSERT INTO report_receipts
                   (receipt_id, release_id, class_id, learner_id, teacher_id,
                    teacher_name, subject, status, first_viewed_at, last_viewed_at,
                    view_count, acknowledged_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'viewed', ?, ?, 1, NULL)
                   ON CONFLICT(release_id, learner_id, teacher_id) DO UPDATE SET
                       teacher_name = excluded.teacher_name,
                       first_viewed_at = COALESCE(report_receipts.first_viewed_at, excluded.first_viewed_at),
                       last_viewed_at = excluded.last_viewed_at,
                       view_count = report_receipts.view_count + 1,
                       status = CASE
                           WHEN report_receipts.status = 'acknowledged' THEN 'acknowledged'
                           ELSE 'viewed'
                       END""",
                (
                    str(_uuid.uuid4()),
                    event.release_id,
                    event.class_id,
                    event.learner_id,
                    event.teacher_id,
                    event.teacher_name,
                    subject,
                    ts,
                    ts,
                ),
            )

        if conn is not None:
            await _write(conn)
        else:
            async with self.transaction() as c:
                await _write(c)

        receipt = await self.get_report_receipt(event.release_id, event.learner_id, event.teacher_id, conn=conn)
        assert receipt is not None
        return event, receipt

    async def acknowledge_report_receipt(
        self,
        *,
        release_id: str,
        class_id: str,
        learner_id: str,
        teacher_id: str,
        teacher_name: str,
        subject: str | None = None,
        acknowledged_at: datetime | None = None,
        conn: aiosqlite.Connection | None = None,
    ) -> ReportReceipt:
        """Record explicit receipt acknowledgment separately from viewing."""
        ts = (acknowledged_at or datetime.now(timezone.utc)).isoformat()
        import uuid as _uuid

        async def _write(c: aiosqlite.Connection) -> None:
            await c.execute(
                """INSERT INTO report_receipts
                   (receipt_id, release_id, class_id, learner_id, teacher_id,
                    teacher_name, subject, status, first_viewed_at, last_viewed_at,
                    view_count, acknowledged_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'acknowledged', ?, ?, 1, ?)
                   ON CONFLICT(release_id, learner_id, teacher_id) DO UPDATE SET
                       teacher_name = excluded.teacher_name,
                       status = 'acknowledged',
                       first_viewed_at = COALESCE(report_receipts.first_viewed_at, excluded.first_viewed_at),
                       last_viewed_at = COALESCE(report_receipts.last_viewed_at, excluded.last_viewed_at),
                       view_count = CASE
                           WHEN report_receipts.view_count = 0 THEN 1
                           ELSE report_receipts.view_count
                       END,
                       acknowledged_at = COALESCE(report_receipts.acknowledged_at, excluded.acknowledged_at)""",
                (
                    str(_uuid.uuid4()),
                    release_id,
                    class_id,
                    learner_id,
                    teacher_id,
                    teacher_name,
                    subject,
                    ts,
                    ts,
                    ts,
                ),
            )

        if conn is not None:
            await _write(conn)
        else:
            async with self.transaction() as c:
                await _write(c)

        receipt = await self.get_report_receipt(release_id, learner_id, teacher_id, conn=conn)
        assert receipt is not None
        return receipt

    async def get_report_view_events(
        self,
        release_id: str,
        learner_id: str | None = None,
        scope: str | None = None,
        conn: aiosqlite.Connection | None = None,
    ) -> list[ReportViewEvent]:
        db = conn or self.db
        clauses = ["release_id = ?"]
        params: list[Any] = [release_id]
        if learner_id is not None:
            clauses.append("learner_id = ?")
            params.append(learner_id)
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        sql = f"SELECT * FROM report_view_events WHERE {' AND '.join(clauses)} ORDER BY viewed_at ASC, rowid ASC"
        out: list[ReportViewEvent] = []
        async with db.execute(sql, tuple(params)) as cursor:
            async for row in cursor:
                out.append(self._row_to_view_event(row))
        return out

    async def get_report_receipt(
        self,
        release_id: str,
        learner_id: str,
        teacher_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> ReportReceipt | None:
        db = conn or self.db
        async with db.execute(
            "SELECT * FROM report_receipts WHERE release_id = ? AND learner_id = ? AND teacher_id = ?",
            (release_id, learner_id, teacher_id),
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_receipt(row) if row else None

    async def get_report_receipts_for_release(
        self,
        release_id: str,
        learner_id: str | None = None,
        conn: aiosqlite.Connection | None = None,
    ) -> list[ReportReceipt]:
        db = conn or self.db
        if learner_id is not None:
            sql = "SELECT * FROM report_receipts WHERE release_id = ? AND learner_id = ? ORDER BY subject ASC, teacher_name ASC"
            params: tuple[Any, ...] = (release_id, learner_id)
        else:
            sql = "SELECT * FROM report_receipts WHERE release_id = ? ORDER BY learner_id ASC, subject ASC, teacher_name ASC"
            params = (release_id,)
        out: list[ReportReceipt] = []
        async with db.execute(sql, params) as cursor:
            async for row in cursor:
                out.append(self._row_to_receipt(row))
        return out

    # ── Attached Subject Responses ────────────────────────────────

    @staticmethod
    def _row_to_subject_response(row: aiosqlite.Row) -> SubjectResponse:
        return SubjectResponse(
            response_id=row["response_id"],
            release_id=row["release_id"],
            published_section_id=row["published_section_id"],
            class_id=row["class_id"],
            learner_id=row["learner_id"],
            subject=row["subject"],
            teacher_id=row["teacher_id"],
            teacher_name=row["teacher_name"],
            response_type=SubjectResponseType(row["response_type"]),
            content=row["content"],
            related_change_id=row["related_change_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    async def add_subject_response(
        self,
        response: SubjectResponse,
        commit: bool = True,
        conn: aiosqlite.Connection | None = None,
    ) -> SubjectResponse:
        db = conn or self.db
        await db.execute(
            """INSERT INTO subject_responses
               (response_id, release_id, published_section_id, class_id, learner_id,
                subject, teacher_id, teacher_name, response_type, content,
                related_change_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                response.response_id,
                response.release_id,
                response.published_section_id,
                response.class_id,
                response.learner_id,
                response.subject,
                response.teacher_id,
                response.teacher_name,
                response.response_type.value,
                response.content,
                response.related_change_id,
                response.created_at.isoformat(),
            ),
        )
        if commit and conn is None:
            await db.commit()
        return response

    async def get_subject_responses_for_release(
        self,
        release_id: str,
        learner_id: str | None = None,
        subject: str | None = None,
        conn: aiosqlite.Connection | None = None,
    ) -> list[SubjectResponse]:
        db = conn or self.db
        clauses = ["release_id = ?"]
        params: list[Any] = [release_id]
        if learner_id is not None:
            clauses.append("learner_id = ?")
            params.append(learner_id)
        if subject is not None:
            clauses.append("subject = ?")
            params.append(subject)
        sql = f"SELECT * FROM subject_responses WHERE {' AND '.join(clauses)} ORDER BY created_at ASC, rowid ASC"
        out: list[SubjectResponse] = []
        async with db.execute(sql, tuple(params)) as cursor:
            async for row in cursor:
                out.append(self._row_to_subject_response(row))
        return out

    # ── Post-Release Changes & 5-Step Progress Lifecycle ──────────

    @staticmethod
    def _row_to_post_release_change(row: aiosqlite.Row) -> PostReleaseChange:
        return PostReleaseChange(
            change_id=row["change_id"],
            release_id=row["release_id"],
            class_id=row["class_id"],
            learner_id=row["learner_id"],
            scope=row["scope"],
            severity=DiffSeverity(row["severity"]),
            headline=row["headline"],
            explanation=row["explanation"],
            why_it_matters=row["why_it_matters"],
            comparison=json.loads(row["comparison_json"]),
            new_evidence_ids=tuple(json.loads(row["new_evidence_ids_json"])),
            opened_by_teacher_id=row["opened_by_teacher_id"],
            opened_by_name=row["opened_by_name"],
            opened_at=datetime.fromisoformat(row["opened_at"]) if row["opened_at"] else None,
            response_id=row["response_id"],
            response_added_by_name=row["response_added_by_name"],
            response_added_at=datetime.fromisoformat(row["response_added_at"]) if row["response_added_at"] else None,
            reviewed_by_class_teacher_id=row["reviewed_by_class_teacher_id"],
            reviewed_by_name=row["reviewed_by_name"],
            reviewed_at=datetime.fromisoformat(row["reviewed_at"]) if row["reviewed_at"] else None,
            review_resolution_notes=row["review_resolution_notes"],
            superseded_by_release_id=row["superseded_by_release_id"],
            superseded_version_number=row["superseded_version_number"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    async def upsert_post_release_change(
        self,
        change: PostReleaseChange,
        commit: bool = True,
        conn: aiosqlite.Connection | None = None,
    ) -> PostReleaseChange:
        db = conn or self.db
        await db.execute(
            """INSERT INTO post_release_changes
               (change_id, release_id, class_id, learner_id, scope, severity,
                headline, explanation, why_it_matters, comparison_json,
                new_evidence_ids_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(release_id, learner_id, scope) DO UPDATE SET
                   severity = excluded.severity,
                   headline = excluded.headline,
                   explanation = excluded.explanation,
                   why_it_matters = excluded.why_it_matters,
                   comparison_json = excluded.comparison_json,
                   new_evidence_ids_json = excluded.new_evidence_ids_json""",
            (
                change.change_id,
                change.release_id,
                change.class_id,
                change.learner_id,
                change.scope,
                change.severity.value,
                change.headline,
                change.explanation,
                change.why_it_matters,
                json.dumps(change.comparison),
                json.dumps(list(change.new_evidence_ids)),
                change.created_at.isoformat(),
            ),
        )
        if commit and conn is None:
            await db.commit()
        async with db.execute(
            "SELECT * FROM post_release_changes WHERE release_id = ? AND learner_id = ? AND scope = ?",
            (change.release_id, change.learner_id, change.scope),
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None
            return self._row_to_post_release_change(row)

    async def get_post_release_changes(
        self,
        *,
        class_id: str | None = None,
        release_id: str | None = None,
        learner_id: str | None = None,
        conn: aiosqlite.Connection | None = None,
    ) -> list[PostReleaseChange]:
        db = conn or self.db
        clauses: list[str] = []
        params: list[Any] = []
        if class_id is not None:
            clauses.append("class_id = ?")
            params.append(class_id)
        if release_id is not None:
            clauses.append("release_id = ?")
            params.append(release_id)
        if learner_id is not None:
            clauses.append("learner_id = ?")
            params.append(learner_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM post_release_changes {where} ORDER BY created_at DESC, rowid DESC"
        out: list[PostReleaseChange] = []
        async with db.execute(sql, tuple(params)) as cursor:
            async for row in cursor:
                out.append(self._row_to_post_release_change(row))
        return out

    async def get_post_release_change_by_id(
        self,
        change_id: str,
        conn: aiosqlite.Connection | None = None,
    ) -> PostReleaseChange | None:
        db = conn or self.db
        async with db.execute("SELECT * FROM post_release_changes WHERE change_id = ?", (change_id,)) as cursor:
            row = await cursor.fetchone()
            return self._row_to_post_release_change(row) if row else None

    async def mark_change_opened(
        self,
        *,
        release_id: str,
        learner_id: str,
        scope: str,
        teacher_id: str,
        teacher_name: str,
        opened_at: datetime | None = None,
        conn: aiosqlite.Connection | None = None,
    ) -> None:
        db = conn or self.db
        ts = (opened_at or datetime.now(timezone.utc)).isoformat()
        await db.execute(
            """UPDATE post_release_changes
               SET opened_by_teacher_id = COALESCE(opened_by_teacher_id, ?),
                   opened_by_name = COALESCE(opened_by_name, ?),
                   opened_at = COALESCE(opened_at, ?)
               WHERE release_id = ? AND learner_id = ? AND scope = ?""",
            (teacher_id, teacher_name, ts, release_id, learner_id, scope),
        )
        if conn is None:
            await db.commit()

    async def mark_change_response_added(
        self,
        *,
        release_id: str,
        learner_id: str,
        scope: str,
        response_id: str,
        teacher_name: str,
        added_at: datetime | None = None,
        conn: aiosqlite.Connection | None = None,
    ) -> None:
        db = conn or self.db
        ts = (added_at or datetime.now(timezone.utc)).isoformat()
        await db.execute(
            """UPDATE post_release_changes
               SET response_id = COALESCE(response_id, ?),
                   response_added_by_name = COALESCE(response_added_by_name, ?),
                   response_added_at = COALESCE(response_added_at, ?)
               WHERE release_id = ? AND learner_id = ? AND scope = ?""",
            (response_id, teacher_name, ts, release_id, learner_id, scope),
        )
        if conn is None:
            await db.commit()

    async def mark_change_reviewed(
        self,
        *,
        change_id: str,
        teacher_id: str,
        teacher_name: str,
        notes: str | None = None,
        reviewed_at: datetime | None = None,
        conn: aiosqlite.Connection | None = None,
    ) -> PostReleaseChange | None:
        db = conn or self.db
        ts = (reviewed_at or datetime.now(timezone.utc)).isoformat()
        await db.execute(
            """UPDATE post_release_changes
               SET reviewed_by_class_teacher_id = ?,
                   reviewed_by_name = ?,
                   reviewed_at = ?,
                   review_resolution_notes = ?
               WHERE change_id = ?""",
            (teacher_id, teacher_name, ts, notes, change_id),
        )
        if conn is None:
            await db.commit()
        return await self.get_post_release_change_by_id(change_id, conn=conn)

    async def mark_changes_superseded(
        self,
        *,
        class_id: str,
        superseded_by_release_id: str,
        superseded_version_number: int,
        conn: aiosqlite.Connection | None = None,
    ) -> None:
        db = conn or self.db
        await db.execute(
            """UPDATE post_release_changes
               SET superseded_by_release_id = ?,
                   superseded_version_number = ?
               WHERE class_id = ?
                 AND release_id != ?
                 AND superseded_by_release_id IS NULL""",
            (
                superseded_by_release_id,
                superseded_version_number,
                class_id,
                superseded_by_release_id,
            ),
        )
        if conn is None:
            await db.commit()
