"""Tests for external school-system ingestion endpoints and approved handover document exports."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import AsyncGenerator

import httpx
import pytest
import pytest_asyncio

from allps.web.app import create_app

INGEST_KEY = "test-sis-ingest-key-2026"


@pytest_asyncio.fixture
async def api_client(tmp_path: Path) -> AsyncGenerator[tuple[httpx.AsyncClient, object], None]:
    """Isolated FastAPI client with seeded pilot teachers/learners and configured ingest API key."""
    db_file = str(tmp_path / "test_intake_export.db")
    app = create_app(
        db_path=db_file,
        mode="deterministic",
        seed_demo_data=True,
        ingest_api_key=INGEST_KEY,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with app.router.lifespan_context(app):
            yield client, app


def _sample_assessment(
    *,
    learner_id: str,
    term: int,
    score: int,
    observed_at: str,
    event_id: str,
    source_system: str = "native_school_results",
) -> dict:
    return {
        "learner_id": learner_id,
        "learner_display_name": "Wanjiku Kamau",
        "evidence_type": "assessment",
        "source_system": source_system,
        "ingestion_method": "api",
        "source_event_id": event_id,
        "source_type": "system",
        "source_reference": "exam-results-v2",
        "academic_year": 2025,
        "term": term,
        "subject": "Mathematics",
        "observed_at": observed_at,
        "content": {
            "grade": "Grade 4",
            "score": score,
            "max_score": 100,
            "measured_skill": "fractions_and_decimals",
            "form": "End Term Paper",
            "form_version": "v1.0",
            "language": "English",
            "assessment_stage": "end_term",
            "comparison_authorized": True,
        },
    }


# ── Authentication & Fail-Closed Tests ──────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_fails_closed_when_api_key_unconfigured(tmp_path: Path, monkeypatch):
    """When ALLPS_INGEST_API_KEY is unset, /api/ingest/* must fail closed with 503."""
    monkeypatch.delenv("ALLPS_INGEST_API_KEY", raising=False)
    app = create_app(
        db_path=str(tmp_path / "unconfigured.db"),
        mode="deterministic",
        seed_demo_data=True,
        ingest_api_key=None,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with app.router.lifespan_context(app):
            resp = await client.post(
                "/api/ingest/records",
                json={"records": [_sample_assessment(learner_id="LRN-001", term=1, score=70, observed_at="2025-03-10T09:00:00Z", event_id="E1")]},
                headers={"X-API-Key": "anything"},
            )
            assert resp.status_code == 503


@pytest.mark.asyncio
async def test_ingest_requires_valid_api_key_even_with_teacher_cookie(api_client):
    """Teacher cookie alone must not satisfy API-key auth on /api/ingest/records or /file."""
    client, _ = api_client
    login_resp = await client.post("/api/auth/login", json={"teacher_id": "TCH-BANDA", "pin": "1234"})
    assert login_resp.status_code == 200

    rec = _sample_assessment(
        learner_id="LRN-AUTH-1",
        term=1,
        score=80,
        observed_at="2025-03-10T09:00:00Z",
        event_id="AUTH-1",
    )
    # Missing key
    r1 = await client.post("/api/ingest/records", json={"records": [rec]})
    assert r1.status_code == 401

    # Wrong Bearer key
    r2 = await client.post(
        "/api/ingest/records",
        json={"records": [rec]},
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert r2.status_code == 401

    # Missing key on /file
    r3 = await client.post(
        "/api/ingest/file",
        data={"source_system": "school_sis"},
        files={"file": ("scores.json", b"[]", "application/json")},
    )
    assert r3.status_code == 401


# ── Batch JSON Record Ingestion ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_records_batch_dedup_and_partial_rejection(api_client):
    """Verify record ingestion, learner auto-create, Level 1/2 dedup, and partial error isolation."""
    client, _ = api_client
    headers = {"Authorization": f"Bearer {INGEST_KEY}"}

    batch_payload = {
        "source_system": "native_school_results",
        "class_id": "CLS-G3-BLUE",
        "records": [
            _sample_assessment(
                learner_id="LRN-SIS-01",
                term=1,
                score=78,
                observed_at="2025-03-20T10:00:00Z",
                event_id="SIS-EVT-1",
            ),
            # Exact replay of SIS-EVT-1 (Level 1)
            _sample_assessment(
                learner_id="LRN-SIS-01",
                term=1,
                score=78,
                observed_at="2025-03-20T10:00:00Z",
                event_id="SIS-EVT-1",
            ),
            # Same observation under a different event_id (Level 2 canonical fingerprint)
            _sample_assessment(
                learner_id="LRN-SIS-01",
                term=1,
                score=78,
                observed_at="2025-03-20T10:00:00Z",
                event_id="SIS-EVT-1-COPY",
            ),
            # Conflict on existing event_id with altered score (must reject without crashing batch)
            _sample_assessment(
                learner_id="LRN-SIS-01",
                term=1,
                score=42,
                observed_at="2025-03-20T10:00:00Z",
                event_id="SIS-EVT-1",
            ),
            # Prohibited deficit label in observation (must reject)
            {
                "learner_id": "LRN-SIS-01",
                "evidence_type": "observation",
                "source_system": "native_school_results",
                "ingestion_method": "api",
                "source_event_id": "SIS-OBS-BAD",
                "source_type": "teacher",
                "source_reference": "Mr. Kamau",
                "academic_year": 2025,
                "term": 1,
                "observed_at": "2025-03-21T10:00:00Z",
                "content": {"note": "Learner is a slow learner in arithmetic."},
            },
        ],
    }

    resp = await client.post("/api/ingest/records", json=batch_payload, headers=headers)
    assert resp.status_code == 200, resp.text
    summary = resp.json()
    assert summary["total"] == 5
    assert summary["accepted_count"] == 1
    assert summary["duplicate_count"] == 2
    assert summary["rejected_count"] == 2
    assert len(summary["errors"]) == 2

    # Confirm learner auto-created with display_name and evidence persisted for assigned teacher
    await client.post("/api/auth/login", json={"teacher_id": "TCH-OCHIENG", "pin": "5678"})
    learners_resp = await client.get("/api/learners")
    learners = {l["learner_id"]: l for l in learners_resp.json()}
    assert "LRN-SIS-01" in learners
    assert learners["LRN-SIS-01"]["display_name"] == "Wanjiku Kamau"

    ev_resp = await client.get("/api/learners/LRN-SIS-01/evidence")
    assert ev_resp.status_code == 200
    assert len(ev_resp.json()) == 1


# ── File Upload Ingestion (CSV & JSON) + ImportManifest ─────────────────────


@pytest.mark.asyncio
async def test_ingest_csv_file_manifest_and_duplicate_file_guard(api_client):
    """CSV upload persists records + ImportManifest, blocks exact file re-upload with 409."""
    client, _ = api_client
    api_headers = {"X-API-Key": INGEST_KEY}

    csv_body = (
        "learner_id,evidence_type,source_event_id,source_type,source_reference,"
        "academic_year,term,subject,observed_at,grade,score,max_score,measured_skill,"
        "form,form_version,language,assessment_stage,comparison_authorized\n"
        "LRN-CSV-01,assessment,CSV-1,system,sis-csv-export,2025,1,Mathematics,"
        "2025-03-25T08:00:00+00:00,Grade 5,65,100,fractions,End Term,v1.0,English,end_term,true\n"
        "LRN-CSV-01,assessment,CSV-2,system,sis-csv-export,2025,2,Mathematics,"
        "2025-06-25T08:00:00+00:00,Grade 5,74,100,fractions,End Term,v1.0,English,end_term,true\n"
    ).encode("utf-8")
    expected_sha = hashlib.sha256(csv_body).hexdigest()

    resp1 = await client.post(
        "/api/ingest/file",
        headers=api_headers,
        data={
            "source_system": "kenya_sis_csv",
            "import_method": "csv_import",
            "imported_by": "registrar_01",
            "notes": "Term 1-2 Maths export",
        },
        files={"file": ("maths_results.csv", csv_body, "text/csv")},
    )
    assert resp1.status_code == 201, resp1.text
    data1 = resp1.json()
    manifest = data1["manifest"]
    assert manifest["file_sha256"] == expected_sha
    assert manifest["row_count"] == 2
    assert manifest["accepted_count"] == 2
    assert manifest["duplicate_count"] == 0
    assert manifest["rejected_count"] == 0

    # Re-uploading identical bytes from same source_system must return 409 Conflict
    resp_dup = await client.post(
        "/api/ingest/file",
        headers=api_headers,
        data={"source_system": "kenya_sis_csv", "import_method": "csv_import"},
        files={"file": ("maths_results_renamed.csv", csv_body, "text/csv")},
    )
    assert resp_dup.status_code == 409
    assert resp_dup.json()["detail"]["existing_manifest"]["manifest_id"] == manifest["manifest_id"]

    # Uploading same bytes from a DIFFERENT source_system is allowed, rows are Level-2 deduped
    resp_other_src = await client.post(
        "/api/ingest/file",
        headers=api_headers,
        data={"source_system": "backup_sis_mirror", "import_method": "csv_import"},
        files={"file": ("maths_results.csv", csv_body, "text/csv")},
    )
    assert resp_other_src.status_code == 201
    assert resp_other_src.json()["manifest"]["accepted_count"] == 0
    assert resp_other_src.json()["manifest"]["duplicate_count"] == 2

    # List manifests via API key
    list_resp = await client.get("/api/ingest/manifests", headers=api_headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 2


@pytest.mark.asyncio
async def test_ingest_json_export_and_malformed_file_rejection(api_client):
    """JSON export_meta + records structure imports cleanly; malformed files return 422."""
    client, _ = api_client
    api_headers = {"X-API-Key": INGEST_KEY}

    json_payload = {
        "export_meta": {
            "source_system": "school_evidence_portal",
            "originating_teacher": "Mrs. Ngcobo",
            "academic_year": 2025,
            "term": 3,
        },
        "records": [
            {
                "source_event_id": "JSON-OBS-01",
                "learner_id": "LRN-001",
                "evidence_type": "observation",
                "ingestion_method": "api",
                "source_type": "teacher",
                "subject": "Mathematics",
                "observed_at": "2025-10-06T10:30:00Z",
                "content": {"note": "Demonstrated clear reasoning with fraction strips."},
            }
        ],
    }

    resp = await client.post(
        "/api/ingest/file",
        headers=api_headers,
        data={"source_system": "school_evidence_portal", "import_method": "api"},
        files={"file": ("export.json", json.dumps(json_payload).encode("utf-8"), "application/json")},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["manifest"]["accepted_count"] == 1

    bad_resp = await client.post(
        "/api/ingest/file",
        headers=api_headers,
        data={"source_system": "school_evidence_portal"},
        files={"file": ("broken.json", b"{not valid json", "application/json")},
    )
    assert bad_resp.status_code == 422


# ── End-to-End Ingestion -> Teacher Approval -> Document Export Pipeline ────


@pytest.mark.asyncio
async def test_e2e_ingest_approve_and_export_docs_with_strict_gating(api_client):
    """Ingest 3-term results -> generate brief -> verify unapproved never exports -> approve -> export PDF/HTML/MD/JSON."""
    client, app = api_client
    api_headers = {"X-API-Key": INGEST_KEY}
    learner_id = "LRN-E2E-EXPORT"

    # 1. Native school results system pushes 3 comparable terms of Mathematics marks
    records = [
        _sample_assessment(learner_id=learner_id, term=1, score=84, observed_at="2025-03-28T09:00:00Z", event_id="E2E-T1"),
        _sample_assessment(learner_id=learner_id, term=2, score=70, observed_at="2025-07-04T09:00:00Z", event_id="E2E-T2"),
        _sample_assessment(learner_id=learner_id, term=3, score=56, observed_at="2025-10-10T09:00:00Z", event_id="E2E-T3"),
    ]
    ingest_resp = await client.post(
        "/api/ingest/records",
        json={"class_id": "CLS-G3-BLUE", "records": records},
        headers=api_headers,
    )
    assert ingest_resp.status_code == 200
    assert ingest_resp.json()["accepted_count"] == 3

    # Authenticate as class teacher (Ms. Ochieng)
    login_resp = await client.post("/api/auth/login", json={"teacher_id": "TCH-OCHIENG", "pin": "5678"})
    assert login_resp.status_code == 200

    # 2. Generate candidate handover (deterministic mode -> enters PENDING review)
    gen_resp = await client.post(
        f"/api/learners/{learner_id}/generate",
        json={"subject": "Mathematics", "mode": "deterministic"},
    )
    assert gen_resp.status_code == 200
    gen_data = gen_resp.json()
    assert gen_data["status"] == "success"
    review_id = gen_data["review_id"]
    assert review_id is not None

    # 3. Before teacher acceptance: exported docs must contain 0 approved patterns & zero leaked text
    pre_json = await client.get(f"/api/learners/{learner_id}/handover/export?format=json")
    assert pre_json.status_code == 200
    assert pre_json.json()["accepted_pattern_count"] == 0
    assert pre_json.json()["patterns"] == []

    pre_pdf = await client.get(f"/api/learners/{learner_id}/handover/export?format=pdf")
    assert pre_pdf.status_code == 200
    assert pre_pdf.content.startswith(b"%PDF-1.4")
    assert b"No human-approved transition findings" in pre_pdf.content

    # 4. Class teacher accepts the finding
    dec_resp = await client.post(
        f"/api/reviews/{review_id}/decision",
        json={
            "status": "accepted",
            "teacher_notes": "Confirmed declining fractions trend; schedule remedial group.",
            "expected_revision": 0,
        },
    )
    assert dec_resp.status_code == 200
    sha_hash = dec_resp.json()["approved_content_hash"]
    assert len(sha_hash) == 64

    # 5. Export PDF (attachment)
    pdf_resp = await client.get(f"/api/learners/{learner_id}/handover/export?format=pdf&download=true")
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert f'filename="allps_handover_{learner_id}.pdf"' in pdf_resp.headers["content-disposition"]
    assert "attachment" in pdf_resp.headers["content-disposition"]
    pdf_bytes = pdf_resp.content
    assert pdf_bytes.startswith(b"%PDF-1.4")
    assert b"xref" in pdf_bytes
    assert pdf_bytes.rstrip().endswith(b"%%EOF")
    assert b"TCH-OCHIENG" in pdf_bytes
    assert sha_hash.encode("ascii") in pdf_bytes
    assert b"Wanjiku Kamau" in pdf_bytes
    assert b"native_school_results" in pdf_bytes

    # 6. Export Printable HTML (inline)
    html_resp = await client.get(f"/api/learners/{learner_id}/handover/export?format=html&download=false")
    assert html_resp.status_code == 200
    assert "text/html" in html_resp.headers["content-type"]
    assert "inline" in html_resp.headers["content-disposition"]
    assert "@media print" in html_resp.text
    assert "window.print()" in html_resp.text
    assert sha_hash in html_resp.text
    assert "Confirmed declining fractions trend" in html_resp.text

    # 7. Export Markdown & JSON
    md_resp = await client.get(f"/api/learners/{learner_id}/handover/export?format=md")
    assert md_resp.status_code == 200
    assert "text/markdown" in md_resp.headers["content-type"]
    assert sha_hash in md_resp.text
    assert "TCH-OCHIENG" in md_resp.text

    json_resp = await client.get(f"/api/learners/{learner_id}/handover/export?format=json")
    assert json_resp.status_code == 200
    export_data = json_resp.json()
    assert export_data["accepted_pattern_count"] == 1
    assert export_data["learner"]["display_name"] == "Wanjiku Kamau"
    assert len(export_data["cited_evidence"]) == 3

    # 8. Error handling & audit log check
    not_found = await client.get("/api/learners/LRN-NOPE/handover/export?format=pdf")
    assert not_found.status_code == 404

    bad_fmt = await client.get(f"/api/learners/{learner_id}/handover/export?format=docx")
    assert bad_fmt.status_code == 422

    audit_entries = await app.state.store.get_audit_log(tool_name="export_handover_document")
    assert len(audit_entries) >= 5


@pytest.mark.asyncio
async def test_rejected_finding_never_appears_in_exports_and_ui_has_print_controls(api_client):
    """Rejected findings must stay excluded from exports, and SPA includes print/export controls."""
    client, _ = api_client
    api_headers = {"X-API-Key": INGEST_KEY}
    learner_id = "LRN-REJECT-EXP"

    records = [
        _sample_assessment(learner_id=learner_id, term=1, score=80, observed_at="2025-03-28T09:00:00Z", event_id="REJ-T1"),
        _sample_assessment(learner_id=learner_id, term=2, score=70, observed_at="2025-07-04T09:00:00Z", event_id="REJ-T2"),
        _sample_assessment(learner_id=learner_id, term=3, score=60, observed_at="2025-10-10T09:00:00Z", event_id="REJ-T3"),
    ]
    await client.post(
        "/api/ingest/records",
        json={"class_id": "CLS-G3-BLUE", "records": records},
        headers=api_headers,
    )
    await client.post("/api/auth/login", json={"teacher_id": "TCH-OCHIENG", "pin": "5678"})

    gen_resp = await client.post(
        f"/api/learners/{learner_id}/generate",
        json={"subject": "Mathematics", "mode": "deterministic"},
    )
    review_id = gen_resp.json()["review_id"]
    assert review_id is not None

    rej_resp = await client.post(
        f"/api/reviews/{review_id}/decision",
        json={
            "status": "rejected",
            "teacher_notes": "Learner experienced temporary illness during Term 3 exam.",
            "expected_revision": 0,
        },
    )
    assert rej_resp.status_code == 200

    for fmt in ("pdf", "html", "md", "json"):
        resp = await client.get(f"/api/learners/{learner_id}/handover/export?format={fmt}")
        assert resp.status_code == 200
        assert b"temporary illness" not in resp.content

    index_resp = await client.get("/")
    assert index_resp.status_code == 200
    app_js_resp = await client.get("/static/app.js")
    assert app_js_resp.status_code == 200
    assert "/handover/export?format=html&download=false" in app_js_resp.text
    assert "/handover/export?format=pdf&download=true" in app_js_resp.text


def test_simple_pdf_builder_handles_multipage_and_unicode():
    """Verify multi-page pagination and WinAnsi/Latin-1 punctuation normalization in PDF output."""
    from allps.services.export_service import _SimplePDFBuilder

    pdf = _SimplePDFBuilder()
    for i in range(70):
        pdf.add_wrapped(f"Line {i + 1} — teacher’s note (verified) “quote” → ok", max_chars=80)
    raw = pdf.build()
    assert raw.startswith(b"%PDF-1.4")
    assert b"Page 1 of " in raw
    assert b"Page 2 of " in raw
    assert raw.rstrip().endswith(b"%%EOF")

