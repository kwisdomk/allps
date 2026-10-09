"""Shared test fixtures for ALLPS."""

import pytest_asyncio

from allps.services.evidence_service import EvidenceService
from allps.storage.sqlite_store import SQLiteStore


@pytest_asyncio.fixture
async def store():
    """Create an in-memory SQLite store for testing."""
    s = SQLiteStore(":memory:")
    await s.initialize()
    yield s
    await s.close()


@pytest_asyncio.fixture
async def service(store):
    """Create an evidence service with in-memory store."""
    return EvidenceService(store)
