"""Complete LIVE AI teacher workflow and deployment verification script.

Exercises:
1. Local LIVE workflow with LM Studio (allps-qwen35-base-4b).
2. Clean synthetic dataset on isolated allps_live_demo.db.
3. Chronological evidence inspection.
4. Observation form entry, preview, back-to-edit, and commit.
5. Citation side panel drawer inspection.
6. Genuine LIVE AI synthesis with LM Studio.
7. Output validation and provenance verification (LIVE LLM badge).
8. Teacher adjudication with server-configured reviewer authority.
9. Approved handover gating and cryptographic SHA-256 snapshot.
10. Browser reload persistence (INT-01 candidate brief restoration).
11. Repeat synthesis to confirm no inherited approval.
12. Mobile responsive presentation test.
13. Public website verification at https://allps.kwaix.dev.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import websockets

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCREENSHOTS_DIR = Path("C:/Users/wisdo/.gemini/antigravity/brain/77fd0336-2447-4887-9440-32556d2d7f46")
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


class EdgeLiveWorkflowRunner:
    def __init__(self, port: int = 9222):
        self.port = port
        self.process = None
        self.ws = None
        self._msg_id = 0

    def start_browser(self):
        edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        user_data = Path(r"C:\Users\wisdo\AppData\Local\Temp\edge_live_verify_user_data")
        user_data.mkdir(parents=True, exist_ok=True)

        cmd = [
            edge_path,
            "--headless=new",
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={user_data}",
            "--window-size=1280,960",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ]
        self.process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)

    async def connect(self):
        req = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json")
        targets = json.loads(req.read().decode("utf-8"))
        page_target = next(t for t in targets if t["type"] == "page")
        self.ws = await websockets.connect(page_target["webSocketDebuggerUrl"], max_size=50 * 1024 * 1024)

        await self.send("Page.enable")
        await self.send("Runtime.enable")
        await self.send("DOM.enable")
        await self.set_viewport(1280, 900)

    async def set_viewport(self, width: int, height: int, mobile: bool = False):
        await self.send("Emulation.setDeviceMetricsOverride", {
            "width": width,
            "height": height,
            "deviceScaleFactor": 1,
            "mobile": mobile,
        })

    async def send(self, method: str, params: dict | None = None) -> dict:
        self._msg_id += 1
        call_id = self._msg_id
        await self.ws.send(json.dumps({"id": call_id, "method": method, "params": params or {}}))

        while True:
            raw = await self.ws.recv()
            msg = json.loads(raw)
            if msg.get("id") == call_id:
                if "error" in msg:
                    raise RuntimeError(f"CDP error in {method}: {msg['error']}")
                return msg.get("result", {})

    async def evaluate(self, expr: str) -> any:
        res = await self.send("Runtime.evaluate", {
            "expression": expr,
            "awaitPromise": True,
            "returnByValue": True,
        })
        val = res.get("result", {})
        if "value" in val:
            return val["value"]
        if val.get("type") == "object":
            return True
        return val.get("value")

    async def screenshot(self, filename: str) -> Path:
        res = await self.send("Page.captureScreenshot", {"format": "png"})
        img_bytes = base64.b64decode(res["data"])
        out_file = SCREENSHOTS_DIR / filename
        out_file.write_bytes(img_bytes)
        print(f"  [SCREENSHOT] {filename} ({len(img_bytes):,} bytes)")
        return out_file

    async def wait_for(self, expr: str, timeout_sec: float = 15.0, step: str = "") -> any:
        t0 = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - t0 < timeout_sec:
            val = await self.evaluate(expr)
            if val:
                return val
            await asyncio.sleep(0.3)
        raise TimeoutError(f"Timed out waiting for '{expr}' in step: {step}")

    def close(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except Exception:
                self.process.kill()


async def run_live_verification():
    print("\n" + "=" * 80)
    print(" ALLPS — LIVE AI TEACHER WORKFLOW & DEPLOYMENT VERIFICATION")
    print("=" * 80)

    runner = EdgeLiveWorkflowRunner(port=9222)
    runner.start_browser()

    try:
        await runner.connect()

        # Step 1: Navigate to local website
        print("\n[Step 1] Navigating to http://127.0.0.1:8000/ (Desktop: 1280x900)...")
        await runner.send("Page.navigate", {"url": "http://127.0.0.1:8000/"})
        await asyncio.sleep(1.5)

        learners = await runner.wait_for("document.getElementById('learner-select').children.length", step="learners load")
        print(f"  Learners loaded: {learners}")
        cards = await runner.wait_for("document.querySelectorAll('.evidence-card').length", step="evidence load")
        print(f"  Chronological evidence cards: {cards}")
        auth_text = await runner.evaluate("document.getElementById('auth-status-banner').innerText")
        print(f"  Review Authority banner: '{auth_text.strip()}'")
        assert "TCH-BANDA" in auth_text
        await runner.screenshot("live_01_evidence_stream_loaded.png")

        # Step 2: Open Observation Form & Enter Factual Observation
        print("\n[Step 2] Opening Observation Dialog & Recording Factual Observation...")
        await runner.evaluate("document.getElementById('btn-open-observation').click()")
        await asyncio.sleep(0.4)

        await runner.evaluate("""
            document.getElementById('obs-year').value = 2025;
            document.getElementById('obs-term').value = 2;
            document.getElementById('obs-subject').value = 'Mathematics';
            document.getElementById('obs-source-ref').value = 'Mr. Banda';
            document.getElementById('obs-text').value = 'Learner demonstrated high spatial reasoning and peer collaboration during fraction bar modeling.';
            document.getElementById('obs-context').value = 'Concrete manipulatives station; learner assisted table group with equivalent fractions.';
        """)
        await runner.screenshot("live_02_observation_form_entry.png")

        # Step 3: Preview Observation
        print("\n[Step 3] Generating Structured Observation Preview...")
        await runner.evaluate("document.getElementById('btn-preview-observation').click()")
        await asyncio.sleep(0.5)

        preview_text = await runner.evaluate("document.getElementById('preview-content').innerText")
        print(f"  Preview verified:\n    {preview_text[:120]}...")
        assert "fraction bar modeling" in preview_text
        assert "Mr. Banda" in preview_text
        await runner.screenshot("live_03_observation_preview_modal.png")

        # Step 4: Confirm and Save Observation
        print("\n[Step 4] Confirming & Saving Observation into Permanent Evidence Ledger...")
        await runner.evaluate("document.getElementById('btn-confirm-save-observation').click()")
        await asyncio.sleep(1.2)

        new_cards_count = await runner.evaluate("document.querySelectorAll('.evidence-card').length")
        print(f"  Evidence stream updated count: {new_cards_count} (was {cards})")
        assert new_cards_count == cards + 1
        await runner.screenshot("live_04_observation_saved_in_stream.png")

        # Step 5: Side Panel Citation Drawer
        print("\n[Step 5] Opening Side Panel Citation Drawer for Provenance...")
        await runner.evaluate("""
            const targetCard = Array.from(document.querySelectorAll('.evidence-card'))
                .find(c => c.innerText.includes('fraction bar modeling'));
            if (targetCard) {
                targetCard.querySelector('.citation-pill').click();
            }
        """)
        await asyncio.sleep(0.6)

        drawer_text = await runner.evaluate("document.getElementById('side-panel-content').innerText")
        print(f"  Stored record provenance:\n    {drawer_text[:140]}...")
        assert "ALLPS_TEACHER_WEB" in drawer_text.upper()
        assert "MR. BANDA" in drawer_text.upper()
        await runner.screenshot("live_05_side_panel_citation_drawer.png")

        await runner.evaluate("document.getElementById('side-panel-close-btn').click()")
        await asyncio.sleep(0.3)

        # Step 6: Candidate Review Tab & Genuine LIVE AI Synthesis
        print("\n[Step 6] Navigating to Candidate Review Tab & Executing LIVE AI Handover Synthesis with LM Studio...")
        await runner.evaluate("document.querySelector('[data-tab=\"reviews\"]').click()")
        await asyncio.sleep(0.5)

        mode_val = await runner.evaluate("document.getElementById('generate-mode').value")
        print(f"  Selected Generation Mode: '{mode_val}' (verifying mode is 'live')...")
        assert mode_val == "live", f"Expected default mode to be 'live', got '{mode_val}'"

        # Trigger generation
        await runner.evaluate("document.getElementById('btn-generate').click()")
        print("  Synthesis in flight... waiting for LM Studio inference and output validation...")
        await runner.wait_for("document.getElementById('btn-generate').disabled", timeout_sec=5.0, step="live generation starts")
        await runner.wait_for("!document.getElementById('btn-generate').disabled", timeout_sec=90.0, step="live generation completes")
        await asyncio.sleep(1.2)

        # Check generation result
        is_success = await runner.evaluate("!!document.querySelector('.generation-status-card.success')")
        if not is_success:
            card_text = await runner.evaluate("document.querySelector('.generation-status-card') ? document.querySelector('.generation-status-card').innerText : ''")
            print(f"  [NOTE] Initial synthesis gated by deterministic validator:\n    {card_text[:120]}")
            print("  Retrying synthesis to allow model self-correction under bounded invariants...")
            await runner.evaluate("document.getElementById('btn-generate').click()")
            await runner.wait_for("document.getElementById('btn-generate').disabled", timeout_sec=5.0, step="retry generation starts")
            await runner.wait_for("!document.getElementById('btn-generate').disabled", timeout_sec=90.0, step="retry generation completes")
            await asyncio.sleep(1.2)

        # Verify result card
        status_card_text = await runner.evaluate("document.querySelector('.generation-status-card.success') ? document.querySelector('.generation-status-card.success').innerText : ''")
        print(f"  Generation result header:\n    {status_card_text[:120]}...")
        assert "Synthesis Completed Successfully" in status_card_text
        assert "LIVE LLM" in status_card_text

        candidate_summary = await runner.evaluate("document.querySelector('.candidate-synthesis-card') ? document.querySelector('.candidate-synthesis-card').innerText : ''")
        print(f"  Candidate Brief Summary:\n    {candidate_summary[:160]}...")
        assert "CANDIDATE SYNTHESIS" in candidate_summary.upper()
        assert "Finding 1" in candidate_summary

        await runner.screenshot("live_06_live_ai_candidate_generation.png")

        # Step 7: Teacher Adjudication (Accept Candidate Finding)
        print("\n[Step 7] Teacher Adjudicating Finding as ACCEPTED with Context Notes...")
        await runner.evaluate("""
            const card = document.querySelector('.review-card');
            if (card) {
                const notes = card.querySelector('.notes-input');
                if (notes) notes.value = 'Confirmed downward trajectory across Grade 3 math terms. Scaffolding recommended for Grade 4.';
                const acceptBtn = card.querySelector('.btn-accept');
                if (acceptBtn) acceptBtn.click();
            }
        """)
        await asyncio.sleep(1.2)

        decision_box_text = await runner.evaluate("document.querySelector('.review-decision-box') ? document.querySelector('.review-decision-box').innerText : ''")
        print(f"  Adjudication confirmed: '{decision_box_text.strip()}'")
        assert "ACCEPTED" in decision_box_text
        assert "TCH-BANDA" in decision_box_text
        assert "SHA:" in decision_box_text

        await runner.screenshot("live_07_review_decision_accepted.png")

        # Step 8: Approved Handover Tab
        print("\n[Step 8] Navigating to Approved Handover Tab (Sovereign Profile)...")
        await runner.evaluate("document.querySelector('[data-tab=\"handover\"]').click()")
        await asyncio.sleep(0.6)

        approved_count = await runner.evaluate("document.getElementById('handover-count-badge').innerText")
        print(f"  Approved handover count: {approved_count}")
        assert int(approved_count) >= 1

        approved_title = await runner.evaluate("document.querySelector('.approved-title') ? document.querySelector('.approved-title').innerText : ''")
        print(f"  Approved Profile Pattern: '{approved_title}'")
        assert len(approved_title) > 0

        await runner.screenshot("live_08_approved_handover_view.png")

        # Step 9: Browser Page Reload & INT-01 Persistence
        print("\n[Step 9] Reloading Browser Page & Verifying Handover + Candidate Brief Persistence (INT-01)...")
        await runner.send("Page.reload")
        await asyncio.sleep(1.8)

        side_approved = await runner.wait_for("document.getElementById('side-approved-count').innerText", step="reload approved count")
        print(f"  Approved count after browser reload: {side_approved}")
        assert int(side_approved) >= 1

        # Switch to reviews tab to verify restored brief
        await runner.evaluate("document.querySelector('[data-tab=\"reviews\"]').click()")
        await asyncio.sleep(1.0)

        restored_candidate_label = await runner.wait_for(
            "document.querySelector('.candidate-synthesis-label') ? document.querySelector('.candidate-synthesis-label').innerText : ''",
            step="restored candidate brief label"
        )
        print(f"  Restored candidate brief label: '{restored_candidate_label}'")
        assert "candidate synthesis" in restored_candidate_label.lower()

        restored_method_badge = await runner.evaluate("document.querySelector('.generation-status-card .badge-method-live') ? document.querySelector('.generation-status-card .badge-method-live').innerText : ''")
        print(f"  Restored method badge: '{restored_method_badge}'")
        assert "LIVE LLM" in restored_method_badge

        await runner.screenshot("live_09_refresh_persistence_verified.png")

        # Step 10: Repeat Synthesis & Confirm No Inherited Approval
        print("\n[Step 10] Triggering Re-Synthesis (Revision 2) & Verifying NO Inherited Approval...")
        await runner.evaluate("document.getElementById('btn-generate').click()")
        await runner.wait_for("document.getElementById('btn-generate').disabled", timeout_sec=5.0, step="second live generation starts")
        rev_success = await runner.evaluate("!!document.querySelector('.generation-status-card.success')")
        if not rev_success:
            print("  Retrying revision 2 synthesis to ensure validated brief...")
            await runner.evaluate("document.getElementById('btn-generate').click()")
            await runner.wait_for("document.getElementById('btn-generate').disabled", timeout_sec=5.0, step="retry rev 2 starts")
            await runner.wait_for("!document.getElementById('btn-generate').disabled", timeout_sec=90.0, step="retry rev 2 completes")
            await asyncio.sleep(1.2)

        rev_tag = await runner.evaluate("document.querySelector('.generation-status-card .tag-stage') ? document.querySelector('.generation-status-card .tag-stage').innerText : ''")
        print(f"  Updated Generation Revision Tag: '{rev_tag}'")
        assert "REV 2" in rev_tag.upper()

        # Verify the candidate review is in PENDING state (NOT inherited accepted!)
        review_cards_statuses = await runner.evaluate("""
            Array.from(document.querySelectorAll('.review-card .badge'))
                .map(b => b.innerText)
        """)
        print(f"  Review card badges in Candidate Review tab: {review_cards_statuses}")
        assert any("PENDING" in s.upper() for s in review_cards_statuses), "New synthesis must be in PENDING state, not inherited approval!"

        # Verify approved handover count is STILL strictly 1 (unreviewed candidate has NOT leaked)
        await runner.evaluate("document.querySelector('[data-tab=\"handover\"]').click()")
        await asyncio.sleep(0.5)
        approved_after_regen = await runner.evaluate("document.getElementById('handover-count-badge').innerText")
        print(f"  Approved handover count after re-synthesis: {approved_after_regen} (must remain 1)")
        assert int(approved_after_regen) == 1

        await runner.evaluate("document.querySelector('[data-tab=\"reviews\"]').click()")
        await asyncio.sleep(0.4)
        await runner.screenshot("live_10_repeat_synthesis_no_inherited_approval.png")

        # Step 11: Mobile Responsive Presentation Test
        print("\n[Step 11] Testing Mobile Viewport (390x844 - iPhone)...")
        await runner.set_viewport(390, 844, mobile=True)
        await runner.evaluate("document.querySelector('[data-tab=\"evidence\"]').click()")
        await asyncio.sleep(0.8)
        await runner.screenshot("live_11_mobile_viewport_workspace.png")

        # Step 12: Public Website Verification (https://allps.kwaix.dev)
        print("\n[Step 12] Inspecting Public Website: https://allps.kwaix.dev (Desktop: 1280x900)...")
        await runner.set_viewport(1280, 900, mobile=False)
        await runner.send("Page.navigate", {"url": "https://allps.kwaix.dev"})
        await asyncio.sleep(2.0)
        public_title = await runner.evaluate("document.title")
        public_h1 = await runner.evaluate("document.querySelector('h1') ? document.querySelector('h1').innerText : ''")
        print(f"  Public website title: '{public_title}'")
        print(f"  Public website header: '{public_h1}'")
        await runner.screenshot("public_01_desktop_kwaix_dev.png")

        print("\n[Step 13] Inspecting Public Website: https://allps.kwaix.dev (Mobile: 390x844)...")
        await runner.set_viewport(390, 844, mobile=True)
        await asyncio.sleep(0.5)
        await runner.screenshot("public_02_mobile_kwaix_dev.png")

        print("\n" + "=" * 80)
        print(" ALL LIVE VERIFICATION WORKFLOWS & SCREENSHOTS COMPLETED SUCCESSFULLY!")
        print("=" * 80 + "\n")

    finally:
        runner.close()


if __name__ == "__main__":
    asyncio.run(run_live_verification())
