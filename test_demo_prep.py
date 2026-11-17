"""ALLPS Demo Preparation & Readiness Verification Script.

Helps verify environment configuration, local/relay AI availability, and the full
end-to-end teacher demo workflow (in-process on a disposable temp database, or
against a running local/hosted server).

Usage examples:
  # Default pre-demo prep check (config audit + LM Studio/relay probe + full in-process rehearsal in auto mode):
  python test_demo_prep.py

  # Require live AI (LM Studio / configured provider) during rehearsal:
  python test_demo_prep.py --mode live

  # Offline deterministic rehearsal + full pytest suite:
  python test_demo_prep.py --mode mock --with-pytest

  # Preflight environment & provider checks only (no demo rehearsal):
  python test_demo_prep.py --check-only

  # Safe read-only check against a running local or hosted server:
  python test_demo_prep.py --url http://127.0.0.1:8000
  python test_demo_prep.py --url https://allps.kwaix.dev
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any
import uuid

from dotenv import dotenv_values, load_dotenv
import httpx

ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

REQUIRED_TEACHER_IDS = {
    "TCH-OCHIENG",
    "TCH-BANDA",
    "TCH-WANJIKU",
    "TCH-OTIENO",
    "TCH-KAMAU",
}
DEMO_PINS = {
    "TCH-OCHIENG": "5678",
    "TCH-BANDA": "1234",
}


@dataclass
class CheckResult:
    """Single pre-demo check outcome."""

    name: str
    status: str  # "PASS" | "WARN" | "FAIL"
    detail: str


class DemoPrepReport:
    """Tracks check outcomes and renders a presenter-friendly summary."""

    def __init__(self) -> None:
        self.results: list[CheckResult] = []

    def record(self, name: str, status: str, detail: str) -> None:
        self.results.append(CheckResult(name=name, status=status, detail=detail))
        tag = {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]"}[status]
        print(f"  {tag} {name}: {detail}", flush=True)

    def has_failures(self) -> bool:
        return any(item.status == "FAIL" for item in self.results)

    def print_summary(self) -> int:
        passes = sum(1 for r in self.results if r.status == "PASS")
        warns = sum(1 for r in self.results if r.status == "WARN")
        fails = sum(1 for r in self.results if r.status == "FAIL")
        print("\n" + "=" * 78, flush=True)
        print(f" DEMO PREP SUMMARY: {passes} passed, {warns} warnings, {fails} failed", flush=True)
        print("=" * 78, flush=True)
        return 1 if fails else 0


def _print_section(title: str) -> None:
    print(f"\n--- {title} " + "-" * max(4, 73 - len(title)), flush=True)


def _check_hosted_env_file(path: Path, report: DemoPrepReport) -> None:
    """Audit .env without printing any secret values."""
    if not path.exists():
        report.record("Hosted .env", "WARN", "Not found (optional for local-only demo; create via scripts/prepare_demo_env.py)")
        return

    values = dotenv_values(path)
    base_url = (values.get("ALLPS_AI_BASE_URL") or "").strip()
    model = (values.get("ALLPS_AI_MODEL") or "").strip()
    api_key = (values.get("ALLPS_AI_API_KEY") or "").strip()
    session_secret = (values.get("ALLPS_SESSION_SECRET") or "").strip()
    teachers_raw = (values.get("ALLPS_TEACHERS_JSON") or "").strip()

    issues: list[str] = []
    if not base_url.startswith("https://"):
        issues.append("ALLPS_AI_BASE_URL missing or not https://")
    if not model:
        issues.append("ALLPS_AI_MODEL missing")
    if not api_key or "REPLACE_WITH" in api_key:
        issues.append("ALLPS_AI_API_KEY is missing or still a placeholder")
    if len(session_secret) < 32:
        issues.append("ALLPS_SESSION_SECRET must be >= 32 chars")

    try:
        teachers = json.loads(teachers_raw) if teachers_raw else []
        teacher_ids = {t.get("teacher_id") for t in teachers if isinstance(t, dict)}
        if not REQUIRED_TEACHER_IDS.issubset(teacher_ids):
            issues.append("ALLPS_TEACHERS_JSON missing one or more required synthetic teacher IDs")
        for t in teachers:
            pw = t.get("password", "") if isinstance(t, dict) else ""
            if not (12 <= len(pw) <= 64 and len(pw.encode("utf-8")) <= 72):
                issues.append(f"Password policy invalid for {t.get('teacher_id', 'unknown')}")
                break
    except json.JSONDecodeError:
        issues.append("ALLPS_TEACHERS_JSON is not valid JSON")

    if issues:
        report.record("Hosted .env", "WARN", "; ".join(issues))
    else:
        report.record("Hosted .env", "PASS", f"Valid structure (provider={values.get('ALLPS_AI_PROVIDER', 'unset')}, model={model})")


def _check_local_ai_env_file(path: Path, report: DemoPrepReport) -> dict[str, str | None]:
    """Audit .env.local-ai without printing keys."""
    if not path.exists():
        report.record("Local AI .env.local-ai", "WARN", "Not found (run scripts/prepare_local_inference.py if using HTTPS relay)")
        return {}

    values = dotenv_values(path)
    relay_key = values.get("ALLPS_LOCAL_RELAY_KEY") or ""
    model = (values.get("ALLPS_LOCAL_MODEL") or "").strip()
    has_upstream = bool((values.get("ALLPS_LOCAL_UPSTREAM_KEY") or "").strip())

    issues: list[str] = []
    if len(relay_key) < 32:
        issues.append("ALLPS_LOCAL_RELAY_KEY < 32 chars")
    if not model:
        issues.append("ALLPS_LOCAL_MODEL is empty")

    if issues:
        report.record("Local AI .env.local-ai", "FAIL", "; ".join(issues))
    else:
        upstream_note = "upstream key set" if has_upstream else "no upstream token configured"
        report.record("Local AI .env.local-ai", "PASS", f"Relay key valid, model='{model}' ({upstream_note})")
    return dict(values)


def check_environment_and_configs(report: DemoPrepReport) -> dict[str, str | None]:
    """Verify repository structure, imports, and environment files."""
    _print_section("1. Environment & Config Audit")

    report.record("Python runtime", "PASS", f"{sys.version.split()[0]} ({sys.executable})")

    required_paths = [
        ROOT_DIR / "data" / "synthetic" / "seed_data.py",
        ROOT_DIR / "src" / "allps" / "web" / "app.py",
        ROOT_DIR / "src" / "allps" / "web" / "static" / "index.html",
    ]
    missing = [str(p.relative_to(ROOT_DIR)) for p in required_paths if not p.exists()]
    if missing:
        report.record("Workspace files", "FAIL", f"Missing: {', '.join(missing)}")
    else:
        report.record("Workspace files", "PASS", "Core web app, static SPA, and synthetic dataset present")

    _check_hosted_env_file(ROOT_DIR / ".env", report)
    local_env = _check_local_ai_env_file(ROOT_DIR / ".env.local-ai", report)

    for profile_name in (".env.local-ai-render", ".env.amd-render"):
        profile_path = ROOT_DIR / profile_name
        if profile_path.exists():
            vals = dotenv_values(profile_path)
            report.record(
                f"Render profile {profile_name}",
                "PASS",
                f"Present (provider={vals.get('ALLPS_AI_PROVIDER', '?')}, model={vals.get('ALLPS_AI_MODEL', '?')})",
            )
    return local_env


async def check_local_providers(
    local_env: dict[str, str | None],
    report: DemoPrepReport,
    *,
    require_live: bool,
) -> None:
    """Probe LM Studio, Ollama, and the local HTTPS inference relay if running."""
    _print_section("2. Local AI & Inference Relay Probe")
    target_model = (local_env.get("ALLPS_LOCAL_MODEL") or "qwen3.5-4b").strip()
    upstream_key = (local_env.get("ALLPS_LOCAL_UPSTREAM_KEY") or "").strip()
    relay_key = (local_env.get("ALLPS_LOCAL_RELAY_KEY") or "").strip()

    lm_headers = {"Authorization": f"Bearer {upstream_key}"} if upstream_key else {}
    lm_ready = False
    async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
        # LM Studio check (check authenticated if upstream key is set, plus check whether unauthenticated works)
        try:
            resp = await client.get("http://127.0.0.1:1234/v1/models", headers=lm_headers)
            auth_note = "authenticated" if upstream_key else "unauthenticated"
            if resp.status_code == 200 and upstream_key:
                try:
                    unauth_lm = await client.get("http://127.0.0.1:1234/v1/models")
                    auth_note = (
                        "no token required"
                        if unauth_lm.status_code == 200
                        else f"token auth required (HTTP {unauth_lm.status_code} without token)"
                    )
                except httpx.HTTPError:
                    auth_note = "token auth required (unauthenticated probe failed)"
            if resp.status_code == 200:
                models = [m.get("id") for m in resp.json().get("data", []) if isinstance(m, dict)]
                matched = target_model in models or "allps-qwen35-base-4b" in models
                status = "PASS" if matched else "WARN"
                lm_ready = matched
                report.record(
                    "LM Studio (127.0.0.1:1234)",
                    status,
                    f"Reachable ({auth_note}); loaded models={models}" + ("" if matched else f" (expected '{target_model}')"),
                )
            elif resp.status_code in (401, 403):
                report.record(
                    "LM Studio (127.0.0.1:1234)",
                    "WARN",
                    "Reachable but returned auth error — check ALLPS_LOCAL_UPSTREAM_KEY in .env.local-ai",
                )
            else:
                report.record("LM Studio (127.0.0.1:1234)", "WARN", f"Returned HTTP {resp.status_code}")
        except httpx.HTTPError as exc:
            report.record(
                "LM Studio (127.0.0.1:1234)",
                "FAIL" if require_live else "WARN",
                f"Unavailable ({type(exc).__name__}; start LM Studio server on port 1234 for live local AI)",
            )

        # Ollama check (only warn if LM Studio is not ready)
        try:
            resp = await client.get("http://127.0.0.1:11434/v1/models")
            if resp.status_code == 200:
                models = [m.get("id") for m in resp.json().get("data", []) if isinstance(m, dict)]
                report.record("Ollama (127.0.0.1:11434)", "PASS", f"Reachable; models={models}")
        except httpx.HTTPError:
            if not lm_ready:
                report.record("Ollama (127.0.0.1:11434)", "WARN", "Not running (optional if using LM Studio)")

        # Local inference relay check (port 8789)
        try:
            health = await client.get("http://127.0.0.1:8789/healthz")
            if health.status_code == 200:
                unauth = await client.get("http://127.0.0.1:8789/v1/models")
                if unauth.status_code != 401:
                    report.record("Inference Relay (8789)", "FAIL", f"Expected 401 without Bearer key, got {unauth.status_code}")
                elif relay_key:
                    auth = await client.get(
                        "http://127.0.0.1:8789/v1/models",
                        headers={"Authorization": f"Bearer {relay_key}"},
                    )
                    if auth.status_code == 200:
                        report.record("Inference Relay (8789)", "PASS", "Healthy, enforces 401, and serves configured model")
                    else:
                        report.record("Inference Relay (8789)", "WARN", f"Healthy, but /v1/models returned HTTP {auth.status_code} (is LM Studio loaded?)")
                else:
                    report.record("Inference Relay (8789)", "PASS", "Healthy and enforces 401 (no local relay key to test /v1/models)")
        except httpx.HTTPError:
            detail = "Not running (start via: uvicorn allps.web.inference_relay:create_relay_app --factory --host 127.0.0.1 --port 8789 --env-file .env.local-ai)"
            report.record("Inference Relay (8789)", "WARN", detail)

    if require_live and not lm_ready:
        report.record("Live AI Readiness", "WARN", "LM Studio target model not confirmed; live generation may fail if no hosted provider is configured")


async def _exercise_api_workflow(
    client: httpx.AsyncClient,
    report: DemoPrepReport,
    *,
    mode: str,
    class_pin: str,
    subject_pin: str,
    write_workflow: bool,
) -> None:
    """Exercise the demo workflow over HTTP against an httpx client."""
    # 1. Health & unauthenticated boundary
    health = await client.get("/healthz")
    if health.status_code == 200 and health.json().get("status") == "ok":
        report.record("GET /healthz", "PASS", "200 OK")
    else:
        report.record("GET /healthz", "FAIL", f"Unexpected response {health.status_code}: {health.text}")
        return

    unauth = await client.get("/api/learners")
    if unauth.status_code == 401:
        report.record("Auth boundary", "PASS", "Unauthenticated GET /api/learners rejected with 401")
    else:
        report.record("Auth boundary", "FAIL", f"Expected 401 when signed out, got {unauth.status_code}")
        return

    cfg_resp = await client.get("/api/config")
    cfg_resp.raise_for_status()
    cfg = cfg_resp.json()
    report.record(
        "GET /api/config",
        "PASS",
        f"hosted={cfg.get('hosted')}, synthetic={cfg.get('is_synthetic_demonstration')}, default_mode={cfg.get('default_mode')}",
    )

    if not write_workflow:
        if class_pin:
            login = await client.post("/api/auth/login", json={"teacher_id": "TCH-OCHIENG", "pin": class_pin})
            if login.status_code == 200:
                learners = (await client.get("/api/learners")).json()
                report.record("Read-only session check", "PASS", f"Signed in as TCH-OCHIENG; visible learners={len(learners)}")
                await client.post("/api/auth/logout")
            else:
                report.record("Read-only session check", "FAIL", f"Login failed with HTTP {login.status_code}")
        else:
            report.record("Read-only session check", "WARN", "Skipped login (set ALLPS_DEMO_CLASS_PASSWORD to test hosted sign-in)")
        return

    if not cfg.get("is_synthetic_demonstration"):
        report.record("Synthetic guard", "FAIL", "Refusing write rehearsal because is_synthetic_demonstration is false")
        return

    # 2. Class teacher sign-in & learner verification
    login = await client.post("/api/auth/login", json={"teacher_id": "TCH-OCHIENG", "pin": class_pin})
    if login.status_code != 200:
        report.record("Class teacher login", "FAIL", f"HTTP {login.status_code}: {login.text}")
        return
    learners = (await client.get("/api/learners")).json()
    learner_ids = {row["learner_id"] for row in learners}
    if {"LRN-001", "LRN-002", "LRN-003"}.issubset(learner_ids):
        report.record("Seeded demo cohort", "PASS", f"Loaded {len(learners)} learners (LRN-001, LRN-002, LRN-003)")
    else:
        report.record("Seeded demo cohort", "FAIL", f"Unexpected learner IDs: {sorted(learner_ids)}")
        return

    # 3. Record an idempotent observation + verify deficit label policy rejection
    bad_obs = await client.post(
        "/api/learners/LRN-001/evidence",
        json={
            "event_datetime": datetime.now(timezone.utc).isoformat(),
            "academic_year": 2026,
            "term": 3,
            "subject": "Mathematics",
            "observation": "Student is a slow learner in multiplication.",
            "source_reference": "Ms. Ochieng",
        },
    )
    if bad_obs.status_code == 422:
        report.record("Deficit-label policy gate", "PASS", "Blocked prohibited deficit label with HTTP 422")
    else:
        report.record("Deficit-label policy gate", "FAIL", f"Expected 422, got {bad_obs.status_code}")

    good_obs = await client.post(
        "/api/learners/LRN-001/evidence",
        json={
            "event_datetime": datetime.now(timezone.utc).isoformat(),
            "academic_year": 2026,
            "term": 3,
            "subject": "Mathematics",
            "observation": "Completed step-by-step fraction strips with concrete manipulatives during guided group work.",
            "context": "Participated actively when paired with visual number line cards.",
            "source_reference": "Ms. Ochieng",
            "source_event_id": f"demo-prep-{uuid.uuid4().hex[:8]}",
        },
    )
    if good_obs.status_code == 201:
        report.record("Teacher observation entry", "PASS", f"Recorded evidence_id={good_obs.json()['evidence_id']}")
    else:
        report.record("Teacher observation entry", "FAIL", f"HTTP {good_obs.status_code}: {good_obs.text}")
        return

    # 4. Generate briefs for LRN-001, LRN-002, LRN-003 (and Science abstention in non-mock modes)
    generation_targets: list[tuple[str, str | None, str]] = [
        ("LRN-001", None, "Amara Kemboi (Math trend)"),
        ("LRN-002", None, "Thabo Ndlovu (Science strength)"),
        ("LRN-003", None, "Naledi Mwangi (English divergence)"),
    ]
    if mode != "mock":
        generation_targets.append(("LRN-003", "Science", "Naledi Mwangi (Science abstention)"))

    for lid, subj, expected_label in generation_targets:
        t0 = time.perf_counter()
        payload: dict[str, Any] = {"mode": mode}
        if subj:
            payload["subject"] = subj
        gen_resp = await client.post(f"/api/learners/{lid}/generate", json=payload)
        elapsed = time.perf_counter() - t0
        if gen_resp.status_code != 200:
            report.record(f"Generate {expected_label}", "FAIL", f"HTTP {gen_resp.status_code}: {gen_resp.text}")
            continue
        data = gen_resp.json()
        status_val = data.get("status")
        runtime_method = data.get("runtime_method")
        if mode == "live" and runtime_method != "live_ai":
            report.record(
                f"Generate {expected_label}",
                "FAIL",
                f"Requested live mode, got status={status_val}, runtime_method={runtime_method}, errors={data.get('errors')}",
            )
            continue
        if status_val in ("success", "abstained"):
            check_level = "WARN" if (mode == "auto" and runtime_method != "live_ai") else "PASS"
            suffix = " (fallback engaged; live AI was not used)" if check_level == "WARN" else ""
            report.record(
                f"Generate {expected_label}",
                check_level,
                f"status={status_val}, runtime={runtime_method}, elapsed={elapsed:.2f}s{suffix}",
            )
        else:
            report.record(
                f"Generate {expected_label}",
                "FAIL",
                f"status={status_val}, runtime={runtime_method}, errors={data.get('errors')}",
            )

    # 5. Confirm sovereign gate (nothing surfaced before teacher decision) + adjudicate
    pre_handover = (await client.get("/api/learners/LRN-001/handover")).json()
    if pre_handover.get("accepted_pattern_count", 0) == 0:
        report.record("Pre-approval sovereign gate", "PASS", "0 patterns surfaced while review is pending")
    else:
        report.record("Pre-approval sovereign gate", "FAIL", f"Expected 0 surfaced patterns, found {pre_handover.get('accepted_pattern_count')}")

    for lid, decision_status, note in (
        ("LRN-001", "accepted", "Demo prep: verified declining Math series with citation grounding."),
        ("LRN-002", "accepted", "Demo prep: verified persistent Science strength."),
        ("LRN-003", "rejected", "Demo prep: hold for spoken fluency context before surfacing."),
    ):
        reviews = (await client.get(f"/api/learners/{lid}/reviews")).json()
        pending = [r for r in reviews if r["status"] == "pending"]
        for item in pending:
            dec = await client.post(
                f"/api/reviews/{item['review_id']}/decision",
                json={
                    "status": decision_status,
                    "expected_revision": item["revision"],
                    "teacher_notes": note,
                    "is_correction": False,
                },
            )
            if dec.status_code != 200:
                report.record(f"Review decision {lid}", "FAIL", f"HTTP {dec.status_code}: {dec.text}")
                return

    post_handover = (await client.get("/api/learners/LRN-001/handover")).json()
    patterns = post_handover.get("patterns", [])
    has_hash = bool(patterns and (patterns[0].get("review") or {}).get("approved_content_hash"))
    if patterns and has_hash:
        sha_prefix = patterns[0]["review"]["approved_content_hash"][:16]
        report.record("Approved SHA-256 snapshot", "PASS", f"LRN-001 surfaced with hash {sha_prefix}...")
    else:
        report.record("Approved SHA-256 snapshot", "FAIL", "LRN-001 approved pattern missing SHA-256 hash")

    # 6. Prepare sections and freeze class release
    for lid in ("LRN-001", "LRN-002", "LRN-003"):
        scopes = (await client.get(f"/api/learners/{lid}/availability")).json()["scopes"]
        for scope, info in scopes.items():
            sufficient = info["status"] == "sufficient"
            sec = await client.post(
                f"/api/classes/CLS-G3-BLUE/learners/{lid}/sections/{scope}",
                json={
                    "review_state": "ready_for_release" if sufficient else "reviewed_incomplete",
                    "approved_summary": f"Demo prep review ({scope}) for {lid}.",
                    "missing_evidence_disclosure": None if sufficient else info["human_message"],
                },
            )
            sec.raise_for_status()

    rel_resp = await client.post("/api/classes/CLS-G3-BLUE/release", json={"notes": "Demo prep frozen handover"})
    if rel_resp.status_code == 201:
        release = rel_resp.json()["release"]
        release_id = release["release_id"]
        report.record("Freeze class release", "PASS", f"Published CLS-G3-BLUE v{release['version_number']} ({release_id})")
    else:
        report.record("Freeze class release", "FAIL", f"HTTP {rel_resp.status_code}: {rel_resp.text}")
        return

    # 7. Subject teacher scoped view, export, view log, acknowledgment
    await client.post("/api/auth/logout")
    subj_login = await client.post("/api/auth/login", json={"teacher_id": "TCH-BANDA", "pin": subject_pin})
    if subj_login.status_code != 200:
        report.record("Subject teacher login", "FAIL", f"HTTP {subj_login.status_code}: {subj_login.text}")
        return

    published = (await client.get("/api/learners/LRN-001/published")).json()
    pub_scopes = {s["scope"] for s in published.get("sections", [])}
    if pub_scopes == {"student", "Mathematics"}:
        report.record("Subject-scoped visibility", "PASS", "Mr. Banda sees only {'student', 'Mathematics'}")
    else:
        report.record("Subject-scoped visibility", "FAIL", f"Expected {{'student', 'Mathematics'}}, got {pub_scopes}")

    exp_json = await client.get("/api/learners/LRN-001/handover/export?format=json")
    exp_html = await client.get("/api/learners/LRN-001/handover/export?format=html")
    if exp_json.status_code == 200 and exp_html.status_code == 200:
        report.record("Handover export (JSON/HTML)", "PASS", f"JSON={len(exp_json.content)}B, HTML={len(exp_html.content)}B")
    else:
        report.record("Handover export (JSON/HTML)", "FAIL", f"json={exp_json.status_code}, html={exp_html.status_code}")

    view_resp = await client.post(f"/api/releases/{release_id}/learners/LRN-001/view", json={"scope": "Mathematics"})
    ack_resp = await client.post(f"/api/releases/{release_id}/learners/LRN-001/acknowledge")
    if view_resp.status_code == 200 and ack_resp.status_code == 200 and ack_resp.json().get("status") == "acknowledged":
        report.record("Receipt view & acknowledgment", "PASS", "View logged separately and receipt acknowledged")
    else:
        report.record("Receipt view & acknowledgment", "FAIL", f"view={view_resp.status_code}, ack={ack_resp.status_code}")


async def run_inprocess_rehearsal(mode: str, report: DemoPrepReport) -> None:
    """Run the full demo against an isolated in-memory/temp-DB FastAPI app."""
    _print_section(f"3. In-Process Demo Rehearsal (mode={mode}, disposable temp DB)")
    from allps.web.app import create_app

    tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tmp_file.name
    tmp_file.close()

    try:
        app = create_app(
            db_path=db_path,
            mode=mode,
            seed_demo_data=True,
            allow_demo_reset=True,
        )
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://demo-prep.local", timeout=120.0) as client:
                await _exercise_api_workflow(
                    client,
                    report,
                    mode=mode,
                    class_pin=DEMO_PINS["TCH-OCHIENG"],
                    subject_pin=DEMO_PINS["TCH-BANDA"],
                    write_workflow=True,
                )
    finally:
        for suffix in ("", "-shm", "-wal"):
            candidate = Path(db_path + suffix)
            if candidate.exists():
                try:
                    candidate.unlink()
                except OSError:
                    pass


async def run_remote_check(url: str, mode: str, write_workflow: bool, report: DemoPrepReport) -> None:
    """Check a running local or hosted server."""
    _print_section(f"3. Running Server Check ({url}, write={write_workflow})")
    class_pin = os.environ.get("ALLPS_DEMO_CLASS_PASSWORD", DEMO_PINS["TCH-OCHIENG"] if "127.0.0.1" in url or "localhost" in url else "")
    subject_pin = os.environ.get("ALLPS_DEMO_SUBJECT_PASSWORD", DEMO_PINS["TCH-BANDA"] if "127.0.0.1" in url or "localhost" in url else "")
    async with httpx.AsyncClient(base_url=url.rstrip("/"), timeout=180.0, follow_redirects=True) as client:
        await _exercise_api_workflow(
            client,
            report,
            mode=mode,
            class_pin=class_pin,
            subject_pin=subject_pin,
            write_workflow=write_workflow,
        )


def run_pytest_suite(report: DemoPrepReport) -> None:
    """Run the existing pytest suite as an optional pre-demo confidence gate."""
    _print_section("4. Automated Pytest Suite")
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=str(ROOT_DIR))
    if proc.returncode == 0:
        report.record("Pytest suite", "PASS", "All tests passed (python -m pytest -q)")
    else:
        report.record("Pytest suite", "FAIL", f"pytest exited with code {proc.returncode}")


async def async_main(args: argparse.Namespace) -> int:
    print("=" * 78, flush=True)
    print(" ALLPS DEMO PREPARATION & PREFLIGHT CHECK", flush=True)
    print("=" * 78, flush=True)

    if args.env_file:
        env_path = Path(args.env_file)
        if not env_path.is_absolute():
            env_path = ROOT_DIR / env_path
        if not env_path.exists():
            print(f"Error: --env-file '{env_path}' does not exist.", flush=True)
            return 2
        load_dotenv(env_path, override=True)
        print(f"Loaded environment overrides from {env_path.name} (secrets not printed).", flush=True)

    report = DemoPrepReport()
    local_env = check_environment_and_configs(report)
    await check_local_providers(local_env, report, require_live=(args.mode == "live"))

    if not args.check_only:
        if args.url:
            await run_remote_check(args.url, args.mode, args.write, report)
        else:
            await run_inprocess_rehearsal(args.mode, report)

    if args.with_pytest:
        run_pytest_suite(report)

    return report.print_summary()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--mode",
        choices=["auto", "deterministic", "mock", "live"],
        default="auto",
        help="Inference mode for demo rehearsal (default: auto).",
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Optional .env file (e.g. .env or .env.local-ai-render) to load before running.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check configs and local AI/relay connectivity without running the API rehearsal.",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Optional running server URL (e.g. http://127.0.0.1:8000 or https://allps.kwaix.dev).",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="When --url is given, run mutating demo steps (only allowed on synthetic demos).",
    )
    parser.add_argument(
        "--with-pytest",
        action="store_true",
        help="Also execute `python -m pytest -q` after the demo prep checks.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main(parse_args())))
