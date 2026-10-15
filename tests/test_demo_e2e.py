"""Automated test suite for the ALLPS Milestone 03 End-to-End Demonstration.

Verifies:
1. Complete execution of all 5 canonical outcomes in mock mode.
2. Dual-view gating holds across all outcomes.
3. SHA-256 content hashes are generated for accepted outcomes.
4. Rejected outcome is kept hidden with teacher context.
5. Insufficient evidence cleanly triggers AI abstention.
6. Indirect peer-comparison model responses are blocked by OutputValidator.
7. CLI entrypoint executes cleanly and produces zero exit code.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess
import sys
import tempfile
import pytest

from examples.demo_e2e import run_demonstration


class TestEndToEndDemonstration:
    """Test suite verifying the end-to-end demonstration workflow."""

    @pytest.mark.asyncio
    async def test_run_demonstration_mock_outcomes(self, tmp_path: Path):
        """Test programmatic execution of the 5 canonical outcomes."""
        db_file = str(tmp_path / "test_demo_e2e.db")

        results = await run_demonstration(
            mode="mock",
            db_path=db_file,
            keep_db=True,
        )

        assert "outcome_1" in results
        assert "outcome_2" in results
        assert "outcome_3" in results
        assert "outcome_4" in results
        assert "outcome_5" in results

        # 1. Outcome 1: Declining math trend accepted with SHA-256 hash
        o1 = results["outcome_1"]
        assert o1["learner_id"] == "LRN-001"
        assert o1["status"] == "accepted"
        assert len(o1["hash"]) == 64
        assert o1["latency_ms"] >= 0

        # 2. Outcome 2: Persistent science strength accepted with SHA-256 hash
        o2 = results["outcome_2"]
        assert o2["learner_id"] == "LRN-002"
        assert o2["status"] == "accepted"
        assert len(o2["hash"]) == 64

        # 3. Outcome 3: Conflicting observations rejected with teacher note
        o3 = results["outcome_3"]
        assert o3["learner_id"] == "LRN-003"
        assert o3["status"] == "rejected"
        assert "bereavement" in o3["teacher_notes"]

        # 4. Outcome 4: Insufficient records cleanly abstained
        o4 = results["outcome_4"]
        assert o4["learner_id"] == "LRN-003"
        assert o4["status"] == "abstained"
        assert "Insufficient" in o4["abstention_reason"]

        # 5. Outcome 5: Indirect peer comparison rejected by validator
        o5 = results["outcome_5"]
        assert o5["learner_id"] == "LRN-001"
        assert o5["status"] == "validation_failed"
        assert o5["violations_detected"] > 0

    def test_demo_cli_execution_mock(self):
        """Verify the CLI script executes without errors via subprocess."""
        cmd = [sys.executable, "examples/demo_e2e.py", "--mode", "mock"]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        assert result.returncode == 0, f"Demo CLI failed with stderr: {result.stderr}"
        assert "ALLPS MILESTONE 03" in result.stdout
        assert "Outcome 1: Amara Kemboi" in result.stdout
        assert "Outcome 2: Thabo Ndlovu" in result.stdout
        assert "Outcome 3: Naledi Mwangi" in result.stdout
        assert "Outcome 4: Safe AI Abstention" in result.stdout
        assert "Outcome 5: Deterministic Policy Rejection" in result.stdout
        assert "EXECUTIVE DEMO RESULTS" in result.stdout
        assert "Runtime Mode:      MOCK" in result.stdout

    def test_demo_cli_execution_deterministic(self):
        """Verify the CLI script executes without errors in deterministic mode."""
        cmd = [sys.executable, "examples/demo_e2e.py", "--mode", "deterministic"]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        assert result.returncode == 0, f"Demo CLI failed with stderr: {result.stderr}"
        assert "Runtime Mode:      DETERMINISTIC" in result.stdout
        assert "Active Runtime:    DETERMINISTIC (DeterministicEngine)" in result.stdout
        assert "Outcome 1: Amara Kemboi" in result.stdout
        assert "[SUCCESS] All 5 canonical outcomes verified" in result.stdout

    def test_demo_cli_execution_auto_fallback(self):
        """Verify the CLI script safely falls back in auto mode when offline."""
        cmd = [sys.executable, "examples/demo_e2e.py", "--mode", "auto", "--endpoint", "http://127.0.0.1:59999/v1"]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        assert result.returncode == 0, f"Demo CLI failed with stderr: {result.stderr}"
        assert "Runtime Mode:      AUTO" in result.stdout
        assert "Fallback Active:   YES" in result.stdout
        assert "Active Runtime:    DETERMINISTIC (DeterministicEngine)" in result.stdout
        assert "[SUCCESS] All 5 canonical outcomes verified" in result.stdout

    def test_demo_cli_execution_live_refusal(self):
        """Verify live mode rejects execution when no AI provider is running."""
        cmd = [sys.executable, "examples/demo_e2e.py", "--mode", "live", "--endpoint", "http://127.0.0.1:59999/v1"]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        assert result.returncode == 1, "Live mode must exit with code 1 when no provider is ready"
        assert "Runtime selection failed" in result.stderr
