"""FastAPI application factory and server entrypoint for ALLPS Teacher Interface.

Coordinates all services and serves the teacher single-page workspace.
"""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
import os
from pathlib import Path
import sys
from typing import Any, AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from allps.auth import get_ingest_api_key, hash_pin, verify_pin
from allps.runtime import RuntimeRegistry
from allps.services.analysis_service import AnalysisService
from allps.services.evidence_service import EvidenceService
from allps.services.export_service import ExportService
from allps.services.handover_service import HandoverService
from allps.services.intake_service import IntakeService
from allps.services.review_service import ReviewService
from allps.storage.sqlite_store import SQLiteStore
from allps.web.routes import router

# Synthetic pilot teachers — class teacher, subject teachers, and unrelated class cohort.
# PINs are hashed at import time; plaintext never stored.
# Replace these with a proper provisioning step before real deployment.
_PILOT_TEACHERS = [
    ("TCH-OCHIENG", "Ms. Ochieng", "5678"),
    ("TCH-BANDA", "Mr. Banda", "1234"),
    ("TCH-WANJIKU", "Ms. Wanjiku", "2345"),
    ("TCH-OTIENO", "Mr. Otieno", "3456"),
    ("TCH-KAMAU", "Mrs. Kamau", "4567"),
]


def _ensure_repo_root_on_path() -> None:
    """Allow console entrypoints (e.g. allps-web) to resolve repo-local data/ and examples/."""
    repo_root = Path(__file__).resolve().parents[3]
    if (repo_root / "data" / "synthetic" / "seed_data.py").is_file():
        root_str = str(repo_root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)


def _build_default_mock_responses(records_by_learner: dict[str, list[Any]]) -> dict[str, str]:
    """Import and build dynamic mock responses from demo_e2e for offline deterministic testing."""
    _ensure_repo_root_on_path()
    try:
        from examples.demo_e2e import build_mock_responses
        return build_mock_responses(records_by_learner)
    except Exception:
        return {}


async def build_mock_responses_from_store(
    store: SQLiteStore,
    ev_service: EvidenceService,
) -> dict[str, str]:
    """Load current evidence for demonstration learners and build mock synthesis responses."""
    records_by_learner: dict[str, list[Any]] = {}
    for lid in ("LRN-001", "LRN-002", "LRN-003"):
        if await store.learner_exists(lid):
            records_by_learner[lid] = await ev_service.get_learner_history(lid)
    return _build_default_mock_responses(records_by_learner)


def _resolve_allow_demo_reset(explicit: bool | None) -> bool:
    env_val = os.environ.get("ALLPS_ALLOW_DEMO_RESET")
    if explicit is not None:
        if env_val is not None and env_val.strip().lower() in ("0", "false", "no"):
            return False
        return explicit
    if env_val is not None:
        return env_val.strip().lower() not in ("0", "false", "no")
    return True


def create_app(
    db_path: str = "allps_demo.db",
    mode: str = "auto",
    seed_demo_data: bool = True,
    allowed_origins: list[str] | None = None,
    ingest_api_key: str | None = None,
    allow_demo_reset: bool | None = None,
    teacher_accounts: list[tuple[str, str, str]] | None = None,
    seed_school: bool = True,
    secure_cookies: bool = False,
    hosted: bool = False,
) -> FastAPI:
    """Create and configure the ALLPS teacher website FastAPI instance."""
    _ensure_repo_root_on_path()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # Initialize storage
        store = SQLiteStore(db_path)
        await store.initialize()

        # Seed pilot teacher accounts & school class/assignment structure (idempotent)
        for teacher_id, display_name, pin in (_PILOT_TEACHERS if teacher_accounts is None else teacher_accounts):
            await store.add_teacher(teacher_id, display_name, hash_pin(pin))

        try:
            from data.synthetic.seed_data import seed_school_structure
            if seed_school:
                await seed_school_structure(store, seed_pilot_accounts=not hosted)
        except Exception:
            if hosted:
                await store.close()
                raise

        # Ensure pre-existing demo learners (if any) belong to Grade 3 Blue
        for demo_lid in ("LRN-001", "LRN-002", "LRN-003"):
            if await store.learner_exists(demo_lid) and not await store.get_learner_classes(demo_lid):
                await store.enroll_learner("CLS-G3-BLUE", demo_lid)

        # Seed synthetic Kenyan demonstration dataset if empty or requested
        if seed_demo_data:
            if await store.count_learners() == 0:
                from data.synthetic.seed_data import seed_store
                await seed_store(store, reset=False, actor="startup_autoseed", seed_pilot_accounts=not hosted)

        # Initialize services
        if hosted:
            for teacher_id, _, default_pin in _PILOT_TEACHERS:
                existing = await store.get_teacher(teacher_id)
                if existing and verify_pin(default_pin, existing["pin_hash"]):
                    await store.close()
                    raise ValueError("Hosted startup refused: database contains a default demo credential")
        ev_service = EvidenceService(store)
        an_service = AnalysisService(ev_service, store)
        rev_service = ReviewService(store)
        handover_service = HandoverService(store, ev_service, an_service)
        intake_service = IntakeService(ev_service, store)
        export_service = ExportService(store, rev_service, handover_service=handover_service)
        registry = RuntimeRegistry()

        # Preload records to construct mock responses for offline mock mode
        mock_responses = await build_mock_responses_from_store(store, ev_service)

        # Store in app state
        app.state.store = store
        app.state.db_path = db_path
        app.state.allow_demo_reset = _resolve_allow_demo_reset(allow_demo_reset)
        app.state.evidence_service = ev_service
        app.state.analysis_service = an_service
        app.state.review_service = rev_service
        app.state.handover_service = handover_service
        app.state.intake_service = intake_service
        app.state.export_service = export_service
        app.state.runtime_registry = registry
        app.state.default_mode = mode
        app.state.secure_cookies = secure_cookies
        app.state.hosted = hosted
        app.state.is_synthetic = seed_demo_data
        app.state.mock_responses = mock_responses
        app.state.ingest_api_key = get_ingest_api_key(ingest_api_key)

        yield

        # Cleanup
        await store.close()

    app = FastAPI(
        title="ALLPS — Teacher Interface & Bounded AI Integration",
        description="Teacher-facing workspace for longitudinal learner continuity.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # SEC-02: Explicit allowed origins (reject permissive credentialed wildcard)
    origins = allowed_origins or [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # Mount API routes
    app.include_router(router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        await app.state.store.ping()
        return {"status": "ok"}

    # Static assets
    static_dir = Path(__file__).resolve().parent / "static"
    if not static_dir.exists():
        static_dir.mkdir(parents=True, exist_ok=True)

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_index() -> FileResponse:
        return FileResponse(str(static_dir / "index.html"))

    @app.get("/{unmatched_path:path}", include_in_schema=False, response_model=None)
    async def serve_not_found(unmatched_path: str) -> FileResponse | JSONResponse:
        """Show the branded 404 for browser paths while keeping API misses JSON."""
        if unmatched_path == "api" or unmatched_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        return FileResponse(str(static_dir / "404.html"), status_code=404)

    return app


def main() -> None:
    """Run local development server via uvicorn."""
    import uvicorn

    parser = argparse.ArgumentParser(description="ALLPS Teacher Website Server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default="allps_demo.db")
    parser.add_argument("--mode", default="auto", choices=["auto", "live", "deterministic", "mock"])
    parser.add_argument("--no-seed", action="store_true", help="Start without auto-seeding an empty database")
    args = parser.parse_args()

    app = create_app(db_path=args.db, mode=args.mode, seed_demo_data=not args.no_seed)

    print(f"\n==================================================================")
    print(f" ALLPS Teacher Website")
    print(f" URL:   http://{args.host}:{args.port}")
    print(f" DB:    {args.db}")
    print(f" Mode:  {args.mode.upper()}")
    print(f"==================================================================\n")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
