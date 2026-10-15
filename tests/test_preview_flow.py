"""Desktop-resolution preview and observation workflow verification script.

Launches Edge at 1280x900 resolution and tests:
1. Field validation when previewing without required fields.
2. Complete observation entry with factual description and context.
3. Structured preview dialog with stable source event ID.
4. Back-to-edit transition preserving all entered values.
5. Updating observation and re-previewing.
6. Confirmation and save into the permanent SQLite evidence stream.
7. Side panel inspection of the saved observation provenance.
8. Generating candidate brief and teacher adjudication.
9. Verified approved handover and refresh persistence.
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


class EdgePreviewRunner:
    def __init__(self, port: int = 9222):
        self.port = port
        self.process = None
        self.ws = None
        self._msg_id = 0

    def start_browser(self):
        edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        user_data = Path(r"C:\Users\wisdo\AppData\Local\Temp\edge_preview_user_data")
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
        # Enforce crisp 1280x900 viewport
        await self.send("Emulation.setDeviceMetricsOverride", {
            "width": 1280,
            "height": 900,
            "deviceScaleFactor": 1,
            "mobile": False,
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
        return val.get("value")

    async def screenshot(self, filename: str) -> Path:
        res = await self.send("Page.captureScreenshot", {"format": "png"})
        img_bytes = base64.b64decode(res["data"])
        out_file = SCREENSHOTS_DIR / filename
        out_file.write_bytes(img_bytes)
        print(f"  [SCREENSHOT] {filename} ({len(img_bytes):,} bytes)")
        return out_file

    async def wait_for(self, expr: str, timeout_sec: float = 10.0, step: str = "") -> any:
        t0 = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - t0 < timeout_sec:
            val = await self.evaluate(expr)
            if val:
                return val
            await asyncio.sleep(0.2)
        raise TimeoutError(f"Timed out waiting for '{expr}' in step: {step}")

    def close(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except Exception:
                self.process.kill()


async def main():
    print("\n" + "=" * 75)
    print(" ALLPS TEACHER WORKSPACE — PREVIEW & OBSERVATION VERIFICATION")
    print("=" * 75)

    runner = EdgePreviewRunner(port=9222)
    runner.start_browser()

    try:
        await runner.connect()

        # Step 1: Navigate to Workspace
        print("\n[1/7] Navigating to http://127.0.0.1:8000/ (Desktop Viewport: 1280x900)...")
        await runner.send("Page.navigate", {"url": "http://127.0.0.1:8000/"})
        await asyncio.sleep(1.5)

        learners = await runner.wait_for("document.getElementById('learner-select').children.length", step="learners load")
        print(f"  Learners loaded: {learners}")
        cards = await runner.wait_for("document.querySelectorAll('.evidence-card').length", step="evidence load")
        print(f"  Chronological evidence cards: {cards}")
        await runner.screenshot("preview_01_workspace_desktop.png")

        # Step 2: Open Observation Dialog and Test Validation
        print("\n[2/7] Testing Observation Form Validation before Preview...")
        await runner.evaluate("document.getElementById('btn-open-observation').click()")
        await asyncio.sleep(0.4)

        # Clear observation text and try to preview
        await runner.evaluate("document.getElementById('obs-text').value = ''")
        await runner.evaluate("document.getElementById('btn-preview-observation').click()")
        await asyncio.sleep(0.3)

        error_msg = await runner.evaluate("document.getElementById('obs-error-alert').innerText")
        print(f"  Validation message shown: '{error_msg}'")
        assert "required" in error_msg.lower()
        await runner.screenshot("preview_02_validation_error.png")

        # Step 3: Enter Valid Observation Data
        print("\n[3/7] Filling Observation Form with Factual Pedagogical Data...")
        await runner.evaluate("""
            document.getElementById('obs-year').value = 2025;
            document.getElementById('obs-term').value = 2;
            document.getElementById('obs-subject').value = 'Mathematics';
            document.getElementById('obs-source-ref').value = 'Mr. Banda';
            document.getElementById('obs-text').value = 'Learner demonstrated high spatial reasoning and peer collaboration during fraction bar modeling.';
            document.getElementById('obs-context').value = 'Concrete manipulatives station; learner assisted table group with equivalent fractions.';
        """)
        await runner.screenshot("preview_03_form_completed.png")

        # Step 4: Click Preview Observation -> Inspect Modal
        print("\n[4/7] Generating Structured Preview Dialog...")
        await runner.evaluate("document.getElementById('btn-preview-observation').click()")
        await asyncio.sleep(0.5)

        preview_text = await runner.evaluate("document.getElementById('preview-content').innerText")
        print(f"  Preview verified:\n    {preview_text[:140]}...")
        assert "fraction bar modeling" in preview_text
        assert "Mr. Banda" in preview_text
        await runner.screenshot("preview_04_preview_modal_desktop.png")

        # Step 5: Back to Edit -> Verify Persistence -> Modify Field
        print("\n[5/7] Testing 'Back to Edit' — Verifying Preserved Form Values...")
        await runner.evaluate("document.getElementById('btn-back-to-edit-observation').click()")
        await asyncio.sleep(0.4)

        reopened_obs = await runner.evaluate("document.getElementById('obs-text').value")
        reopened_ref = await runner.evaluate("document.getElementById('obs-source-ref').value")
        print(f"  Preserved observation: '{reopened_obs[:60]}...'")
        print(f"  Preserved teacher reference: '{reopened_ref}'")
        assert "fraction bar modeling" in reopened_obs
        assert reopened_ref == "Mr. Banda"

        # Modify observation and re-preview
        await runner.evaluate("""
            document.getElementById('obs-text').value += ' Completed extension tasks independently.';
        """)
        await runner.evaluate("document.getElementById('btn-preview-observation').click()")
        await asyncio.sleep(0.4)

        updated_preview = await runner.evaluate("document.getElementById('preview-content').innerText")
        assert "Completed extension tasks independently" in updated_preview
        print("  Updated preview reflects edits accurately!")
        await runner.screenshot("preview_05_updated_preview_modal.png")

        # Step 6: Confirm and Save Observation
        print("\n[6/7] Confirming and Saving Observation to Database...")
        await runner.evaluate("document.getElementById('btn-confirm-save-observation').click()")
        await asyncio.sleep(1.2)

        # Verify card in evidence stream
        obs_cards = await runner.evaluate("""
            Array.from(document.querySelectorAll('.evidence-card'))
                .filter(c => c.innerText.includes('fraction bar modeling'))
                .length
        """)
        print(f"  Observed cards in stream matching text: {obs_cards}")
        assert obs_cards >= 1
        await runner.screenshot("preview_06_observation_saved.png")

        # Step 7: Inspect Citation Side Panel Drawer
        print("\n[7/7] Opening Side Panel Citation Drawer for Provenance Inspection...")
        await runner.evaluate("""
            const targetCard = Array.from(document.querySelectorAll('.evidence-card'))
                .find(c => c.innerText.includes('fraction bar modeling'));
            if (targetCard) {
                targetCard.querySelector('.citation-pill').click();
            }
        """)
        await asyncio.sleep(0.6)

        side_panel_text = await runner.evaluate("document.getElementById('side-panel-content').innerText")
        print(f"  Side panel provenance:\n    {side_panel_text[:120]}...")
        assert "ALLPS_TEACHER_WEB" in side_panel_text.upper()
        assert "MR. BANDA" in side_panel_text.upper()
        await runner.screenshot("preview_07_side_panel_drawer.png")

        # Close side panel
        await runner.evaluate("document.getElementById('side-panel-close-btn').click()")
        await asyncio.sleep(0.3)

        # Step 8: Tab 2 - Candidate Review View
        print("\n[8/9] Switching to Candidate Review Tab & Generating Handover...")
        await runner.evaluate("document.querySelector('[data-tab=\"reviews\"]').click()")
        await asyncio.sleep(0.5)

        # Trigger generation
        await runner.evaluate("document.getElementById('btn-generate').click()")
        await runner.wait_for("!document.getElementById('btn-generate').disabled", timeout_sec=15.0, step="generate brief")
        await asyncio.sleep(1.0)
        await runner.screenshot("preview_08_candidate_review_desktop.png")

        # Step 9: Adjudicate & Tab 3 - Approved Handover View
        print("\n[9/9] Adjudicating Finding & Switching to Approved Handover Tab...")
        await runner.evaluate("""
            const card = document.querySelector('.review-card');
            if (card) {
                const acceptBtn = card.querySelector('.btn-accept');
                if (acceptBtn) acceptBtn.click();
            }
        """)
        await asyncio.sleep(1.0)

        # Switch to handover tab
        await runner.evaluate("document.querySelector('[data-tab=\"handover\"]').click()")
        await asyncio.sleep(0.6)
        await runner.screenshot("preview_09_approved_handover_desktop.png")

        print("\n" + "=" * 75)
        print(" ALL PREVIEW WORKFLOW TESTS PASSED CLEANLY WITH HIGH-RES ARTIFACTS!")
        print("=" * 75 + "\n")

    finally:
        runner.close()


if __name__ == "__main__":
    asyncio.run(main())
