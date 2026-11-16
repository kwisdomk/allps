"""FastAPI application factory and server entrypoint for ALLPS Teacher Interface.

Coordinates all services and serves the teacher single-page workspace.
"""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from pathlib import Path
import sys
from typing import Any, AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from allps.auth import get_ingest_api_key, hash_pin
from allps.runtime import RuntimeRegistry
from allps.services.analysis_service import AnalysisService
from allps.services.evidence_service import EvidenceService
from allps.services.export_service import ExportService
from allps.services.intake_service import IntakeService
from allps.services.review_service import ReviewService
from allps.storage.sqlite_store import SQLiteStore
from allps.web.routes import router

# Synthetic pilot teachers — two accounts for the handover scenario.
# PINs are hashed at import time; plaintext never stored.
# Replace these with a proper provisioning step before real deployment.
_PILOT_TEACHERS = [
    ("TCH-BANDA", "Mr. Banda", "1234"),
    ("TCH-OCHIENG", "Ms. Ochieng", "5678"),
]


def _build_default_mock_responses(records_by_learner: dict[str, list[Any]]) -> dict[str, str]:
    """Import and build dynamic mock responses from demo_e2e for offline deterministic testing."""
    try:
        from examples.demo_e2e import build_mock_responses
        return build_mock_responses(records_by_learner)
    except Exception:
        return {}


def create_app(
    db_path: str = "allps_demo.db",
    mode: str = "auto",
    seed_demo_data: bool = True,
    allowed_origins: list[str] | None = None,
    ingest_api_key: str | None = None,
) -> FastAPI:
    """Create and configure the ALLPS teacher website FastAPI instance."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # Initialize storage
        store = SQLiteStore(db_path)
        await store.initialize()

        # Seed pilot teacher accounts (idempotent — INSERT OR IGNORE)
        for teacher_id, display_name, pin in _PILOT_TEACHERS:
            await store.add_teacher(teacher_id, display_name, hash_pin(pin))

        # Seed synthetic Kenyan demonstration dataset if empty or requested
        if seed_demo_data:
            from data.synthetic.seed_data import ALL_EVIDENCE, LEARNERS
            async with store.db.execute("SELECT COUNT(*) AS cnt FROM learners") as cursor:
                row = await cursor.fetchone()
                count = row["cnt"] if row else 0

            if count == 0:
                for learner in LEARNERS:
                    await store.add_learner(learner)
                for ev in ALL_EVIDENCE:
                    await store.add_evidence(ev)

        # Initialize services
        ev_service = EvidenceService(store)
        an_service = AnalysisService(ev_service, store)
        rev_service = ReviewService(store)
        intake_service = IntakeService(ev_service, store)
        export_service = ExportService(store, rev_service)
        registry = RuntimeRegistry()

        # Preload records to construct mock responses for offline mock mode
        records_by_learner: dict[str, list[Any]] = {}
        for lid in ("LRN-001", "LRN-002", "LRN-003"):
            if await store.learner_exists(lid):
                records_by_learner[lid] = await ev_service.get_learner_history(lid)
        mock_responses = _build_default_mock_responses(records_by_learner)

        # Store in app state
        app.state.store = store
        app.state.evidence_service = ev_service
        app.state.analysis_service = an_service
        app.state.review_service = rev_service
        app.state.intake_service = intake_service
        app.state.export_service = export_service
        app.state.runtime_registry = registry
        app.state.default_mode = mode
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

    # Static assets
    static_dir = Path(__file__).resolve().parent / "static"
    if not static_dir.exists():
        static_dir.mkdir(parents=True, exist_ok=True)

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_index() -> FileResponse:
        return FileResponse(str(static_dir / "index.html"))

    return app


def main() -> None:
    """Run local development server via uvicorn."""
    import uvicorn

    parser = argparse.ArgumentParser(description="ALLPS Teacher Website Server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default="allps_demo.db")
    parser.add_argument("--mode", default="auto", choices=["auto", "live", "deterministic", "mock"])
    args = parser.parse_args()

    app = create_app(db_path=args.db, mode=args.mode, seed_demo_data=True)

    print(f"\n==================================================================")
    print(f" ALLPS Teacher Website")
    print(f" URL:   http://{args.host}:{args.port}")
    print(f" DB:    {args.db}")
    print(f" Mode:  {args.mode.upper()}")
    print(f"==================================================================\n")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
