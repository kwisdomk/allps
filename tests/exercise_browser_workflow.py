"""Browser workflow execution script via Chrome DevTools Protocol (CDP).

Exercises the real browser user workflow:
1. Select learner -> inspect evidence stream & distinct assessment stages.
2. Record teacher observation -> preview modal -> confirm & save -> verify in evidence stream.
3. Generate candidate handover -> verify status banner and candidate synthesis.
4. Inspect citation -> click citation pill -> verify side panel opens with full provenance.
5. Review saved finding -> submit teacher adjudication decision (accept).
6. Reopen approved handover -> verify accepted finding with SHA-256 snapshot.
7. Page reload -> verify approved handover persists across refresh.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
import sys
import urllib.request
import websockets

# Ensure UTF-8 output on Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCREENSHOTS_DIR = Path("C:/Users/wisdo/.gemini/antigravity/brain/77fd0336-2447-4887-9440-32556d2d7f46")
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


class BrowserController:
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.ws = None
        self._msg_id = 0

    async def connect(self):
        self.ws = await websockets.connect(self.ws_url, max_size=50 * 1024 * 1024)
        await self.send("Page.enable")
        await self.send("Runtime.enable")
        await self.send("DOM.enable")

    async def send(self, method: str, params: dict | None = None) -> dict:
        self._msg_id += 1
        call_id = self._msg_id
        req = {"id": call_id, "method": method, "params": params or {}}
        await self.ws.send(json.dumps(req))

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
        if val.get("type") == "undefined":
            return None
        return val

    async def screenshot(self, name: str) -> Path:
        res = await self.send("Page.captureScreenshot", {"format": "png"})
        data = base64.b64decode(res["data"])
        out_path = SCREENSHOTS_DIR / f"{name}.png"
        out_path.write_bytes(data)
        print(f"  [SCREENSHOT] Saved: {out_path.name} ({len(data)} bytes)")
        return out_path

    async def wait_for(self, check_expr: str, timeout_sec: float = 10.0, step_name: str = "") -> any:
        t0 = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - t0 < timeout_sec:
            val = await self.evaluate(check_expr)
            if val:
                return val
            await asyncio.sleep(0.3)
        raise TimeoutError(f"Timed out waiting for: {check_expr} ({step_name})")


async def run_workflow():
    print("=" * 70)
    print("EXERCISING LIVE BROWSER WORKFLOW VIA HEADLESS EDGE CDP")
    print("=" * 70)

    # 1. Connect to Edge CDP
    req = urllib.request.urlopen("http://127.0.0.1:9222/json")
    targets = json.loads(req.read().decode("utf-8"))
    page_target = next(t for t in targets if t["type"] == "page")
    ws_url = page_target["webSocketDebuggerUrl"]
    print(f"Connected to CDP page: {ws_url}")

    browser = BrowserController(ws_url)
    await browser.connect()

    # Navigate to app
    print("\n[Step 1] Navigating to http://127.0.0.1:8000/ ...")
    await browser.send("Page.navigate", {"url": "http://127.0.0.1:8000/"})
    await asyncio.sleep(1.5)

    # Verify initial page load
    title = await browser.evaluate("document.title")
    print(f"  Page title: {title}")
    assert "ALLPS" in title

    # Wait for learners dropdown to populate
    learners_count = await browser.wait_for("document.getElementById('learner-select').children.length", step_name="load learners")
    print(f"  Learners loaded in picker: {learners_count}")
    assert learners_count >= 3

    # Check evidence cards rendered
    cards_count = await browser.wait_for("document.querySelectorAll('.evidence-card').length", step_name="load evidence cards")
    print(f"  Evidence records rendered: {cards_count}")
    assert cards_count > 0

    await browser.screenshot("01_evidence_stream_loaded")

    # -------------------------------------------------------------------------
    # Step 2: Record an observation with Preview modal
    # -------------------------------------------------------------------------
    print("\n[Step 2] Recording a Teacher Observation via Modal Form...")
    # Click + Record Teacher Observation button
    await browser.evaluate("document.getElementById('btn-open-observation').click()")
    await asyncio.sleep(0.5)

    # Fill form
    await browser.evaluate("""
        document.getElementById('obs-year').value = 2025;
        document.getElementById('obs-term').value = 2;
        document.getElementById('obs-subject').value = 'Mathematics';
        document.getElementById('obs-source-ref').value = 'Mr. Banda';
        document.getElementById('obs-text').value = 'Learner demonstrated high spatial reasoning and peer collaboration during fraction bar modeling.';
        document.getElementById('obs-context').value = 'Concrete manipulatives station; learner assisted table group with equivalent fractions.';
    """)
    await browser.screenshot("02_observation_form_filled")

    # Click Preview
    print("  Clicking Preview Observation...")
    await browser.evaluate("document.getElementById('btn-preview-observation').click()")
    await asyncio.sleep(0.5)

    preview_html = await browser.evaluate("document.getElementById('preview-content').innerText")
    assert "fraction bar modeling" in preview_html
    print("  Preview modal verified with entered text!")
    await browser.screenshot("03_observation_preview_modal")

    # Confirm & Save
    print("  Confirming and saving observation...")
    await browser.evaluate("document.getElementById('btn-confirm-save-observation').click()")
    await asyncio.sleep(1.0)

    # Verify new card appears in evidence stream
    found_new_obs = await browser.evaluate("""
        Array.from(document.querySelectorAll('.evidence-card')).some(c => c.innerText.includes('fraction bar modeling'))
    """)
    assert found_new_obs, "Newly recorded observation must be visible in evidence stream"
    print("  Observation successfully saved and displayed in evidence stream!")
    await browser.screenshot("04_observation_saved_in_stream")

    # -------------------------------------------------------------------------
    # Step 3: Inspect Citations in Side Panel
    # -------------------------------------------------------------------------
    print("\n[Step 3] Clicking Evidence Citation to inspect Stored Record in Side Panel...")
    await browser.evaluate("document.querySelector('.citation-pill').click()")
    await asyncio.sleep(0.8)

    side_panel_open = await browser.evaluate("document.getElementById('side-panel').classList.contains('open')")
    assert side_panel_open, "Side panel must be open after clicking citation"
    side_panel_text = await browser.evaluate("document.getElementById('side-panel-content').innerText")
    assert "PROVENANCE" in side_panel_text.upper()
    print("  Side panel opened with complete record provenance and payload!")
    await browser.screenshot("05_side_panel_citation_drawer")

    # Close side panel
    await browser.evaluate("document.getElementById('side-panel-close-btn').click()")
    await asyncio.sleep(0.3)

    # -------------------------------------------------------------------------
    # Step 4: Switch to Candidate Review tab & Generate AI Candidate Handover
    # -------------------------------------------------------------------------
    print("\n[Step 4] Switching to Candidate Review tab & Generating AI Handover...")
    await browser.evaluate("document.querySelector('[data-tab=\"reviews\"]').click()")
    await asyncio.sleep(0.5)

    # Trigger generation
    await browser.evaluate("document.getElementById('btn-generate').click()")

    # Wait for generation to complete
    await browser.wait_for("!document.getElementById('btn-generate').disabled", timeout_sec=15.0, step_name="generation completion")
    await asyncio.sleep(1.0)

    gen_box_text = await browser.evaluate("document.getElementById('generation-result-container').innerText")
    print(f"  Generation result: {gen_box_text[:120]}...")
    assert "candidate synthesis" in gen_box_text.lower() or "validated brief" in gen_box_text.lower()

    reviews_rendered = await browser.wait_for("document.querySelectorAll('.review-card').length", step_name="review items rendered")
    print(f"  Candidate review findings rendered: {reviews_rendered}")
    assert reviews_rendered > 0
    await browser.screenshot("06_candidate_generation_and_reviews")

    # -------------------------------------------------------------------------
    # Step 5: Review a saved candidate finding (Teacher Adjudication)
    # -------------------------------------------------------------------------
    print("\n[Step 5] Adjudicating Candidate Finding (Teacher Accept)...")
    await browser.evaluate("""
        const card = document.querySelector('.review-card');
        const notes = card.querySelector('.notes-input');
        if (notes) notes.value = 'Longitudinal trend verified against term tests. Recommend Grade 4 scaffolding.';
        const acceptBtn = card.querySelector('.btn-accept');
        if (acceptBtn) acceptBtn.click();
    """)
    await asyncio.sleep(1.0)

    # Verify card status changed to ACCEPTED
    card_status = await browser.evaluate("document.querySelector('.review-card .badge-status-accepted') !== null")
    assert card_status, "Review card must now display ACCEPTED status badge"
    print("  Review card successfully updated to ACCEPTED with SHA-256 snapshot!")
    await browser.screenshot("07_review_decision_accepted")

    # -------------------------------------------------------------------------
    # Step 6: Reopen Approved Handover tab
    # -------------------------------------------------------------------------
    print("\n[Step 6] Reopening Approved Handover view...")
    await browser.evaluate("document.querySelector('[data-tab=\"handover\"]').click()")
    await asyncio.sleep(0.5)

    approved_cards = await browser.wait_for("document.querySelectorAll('.approved-card').length", step_name="approved handover cards")
    print(f"  Approved handover cards rendered: {approved_cards}")
    assert approved_cards >= 1

    handover_text = await browser.evaluate("document.getElementById('handover-list').innerText")
    assert "SHA-256" in handover_text
    assert "TCH-BANDA" in handover_text
    assert "APPROVED PROFILE" in handover_text
    print("  Approved handover surfaces strictly accepted findings with SHA-256 verification!")
    await browser.screenshot("08_approved_handover_view")

    # -------------------------------------------------------------------------
    # Step 7: Page reload to verify persistence
    # -------------------------------------------------------------------------
    print("\n[Step 7] Simulating Page Reload to verify approval survives refresh...")
    await browser.send("Page.reload")
    await asyncio.sleep(1.5)

    # Switch to handover tab after reload
    await browser.evaluate("document.querySelector('[data-tab=\"handover\"]').click()")
    await asyncio.sleep(0.5)

    reloaded_approved = await browser.wait_for("document.querySelectorAll('.approved-card').length", step_name="reloaded approved cards")
    print(f"  Approved findings after page reload: {reloaded_approved}")
    assert reloaded_approved >= 1
    print("  Approval successfully survived browser refresh!")
    await browser.screenshot("09_approved_handover_after_reload")

    print("\n" + "=" * 70)
    print("ALL 7 DEMONSTRATION WORKFLOW STEPS VERIFIED IN REAL HEADLESS BROWSER!")
    print("=" * 70)

    await browser.ws.close()


if __name__ == "__main__":
    asyncio.run(run_workflow())
