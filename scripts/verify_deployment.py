"""Exercise a disposable synthetic deployment over real HTTP.

Simulates educator review for demonstration only. Never run against school data.
Credentials come from ALLPS_DEMO_CLASS_PASSWORD / ALLPS_DEMO_SUBJECT_PASSWORD.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os

import httpx


async def verify(url: str, mode: str, expected_provider: str | None = None) -> dict:
    report = {"url": url, "requested_mode": mode, "synthetic_review_simulation": True,
              "started_at_utc": datetime.now(timezone.utc).isoformat(), "steps": []}
    async with httpx.AsyncClient(base_url=url, timeout=300) as client:
        async def call(method, path, **kwargs):
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response
        assert (await call("GET", "/healthz")).json()["status"] == "ok"
        assert (await client.get("/api/learners")).status_code == 401
        config = (await call("GET", "/api/config")).json()
        assert config["is_synthetic_demonstration"], "Refusing to simulate reviews on non-synthetic data"
        report["inference_provider"] = config.get("inference_provider")
        if expected_provider is not None:
            assert config.get("inference_provider") == expected_provider, "Hosted provider does not match the requested verification"
        await call("POST", "/api/auth/login", json={"teacher_id": "TCH-OCHIENG", "pin": os.environ["ALLPS_DEMO_CLASS_PASSWORD"]})
        report["steps"].append("Health, authentication and synthetic-data boundary passed")
        for learner in ("LRN-001", "LRN-002", "LRN-003"):
            evidence = (await call("GET", f"/api/learners/{learner}/evidence")).json()
            assert evidence
            result = (await call("POST", f"/api/learners/{learner}/generate", json={"mode": mode})).json()
            assert result["status"] in ("success", "abstained"), result
            if mode == "live":
                assert result["runtime_method"] == "live_ai", result
            report["steps"].append({"learner": learner, "status": result["status"], "runtime_method": result["runtime_method"]})
            reviews = (await call("GET", f"/api/learners/{learner}/reviews")).json()
            for review in reviews:
                if review["status"] == "pending":
                    await call("POST", f"/api/reviews/{review['review_id']}/decision", json={
                        "status": "accepted", "expected_revision": review["revision"],
                        "teacher_notes": "Synthetic demonstration: simulated educator review.", "is_correction": False})
            scopes = (await call("GET", f"/api/learners/{learner}/availability")).json()["scopes"]
            for scope, availability in scopes.items():
                ready = availability["status"] == "sufficient"
                await call("POST", f"/api/classes/CLS-G3-BLUE/learners/{learner}/sections/{scope}", json={
                    "review_state": "ready_for_release" if ready else "reviewed_incomplete",
                    "approved_summary": f"Synthetic demonstration: {scope} evidence reviewed for {learner}.",
                    "missing_evidence_disclosure": None if ready else availability["human_message"]})
        release = (await call("POST", "/api/classes/CLS-G3-BLUE/release", json={"notes": "Synthetic demonstration release"})).json()["release"]
        report["release_version"] = release["version_number"]
        await call("POST", "/api/auth/logout")
        await call("POST", "/api/auth/login", json={"teacher_id": "TCH-BANDA", "pin": os.environ["ALLPS_DEMO_SUBJECT_PASSWORD"]})
        published = (await call("GET", "/api/learners/LRN-001/published")).json()
        assert {section["scope"] for section in published["sections"]} == {"student", "Mathematics"}
        exported = (await call("GET", "/api/learners/LRN-001/handover/export?format=json")).json()
        assert {section["scope"] for section in exported["published_sections"]} == {"student", "Mathematics"}
        release_id = release["release_id"]
        await call("POST", f"/api/releases/{release_id}/learners/LRN-001/view", json={"scope": "Mathematics"})
        acknowledgment = (await call("POST", f"/api/releases/{release_id}/learners/LRN-001/acknowledge")).json()
        assert acknowledgment["status"] == "acknowledged"
        report["steps"].append("Frozen release, second educator, scoped export and explicit acknowledgment passed")
    report["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--mode", choices=["live", "deterministic"], default="live")
    parser.add_argument("--expected-provider", help="Refuse to run if the hosted provider differs")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(verify(args.url, args.mode, args.expected_provider)), indent=2))
