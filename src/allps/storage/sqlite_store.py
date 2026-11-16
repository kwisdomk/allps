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
    Evidence,
    EvidenceType,
    ImportManifest,
    IngestionMethod,
    Learner,
    Pattern,
    PatternType,
    ReviewItem,
    ReviewStatus,
)
from allps.models.evidence import _deep_unfreeze

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
        """Clear workspace learner/evidence/review data while preserving teacher accounts and audit log."""
        tables = (
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

