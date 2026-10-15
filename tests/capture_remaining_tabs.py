import asyncio
import base64
import json
from pathlib import Path
import urllib.request
import websockets

async def capture_tabs():
    req = urllib.request.urlopen("http://127.0.0.1:9222/json")
    targets = json.loads(req.read().decode("utf-8"))
    page = next(t for t in targets if t["type"] == "page")
    ws = await websockets.connect(page["webSocketDebuggerUrl"])

    async def send(method, params=None):
        req = {"id": 1, "method": method, "params": params or {}}
        await ws.send(json.dumps(req))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("id") == 1:
                return msg.get("result", {})

    await send("Emulation.setDeviceMetricsOverride", {"width": 1280, "height": 900, "deviceScaleFactor": 1, "mobile": False})

    # Switch to reviews tab
    await send("Runtime.evaluate", {"expression": "document.querySelector('[data-tab=\"reviews\"]').click()"})
    await asyncio.sleep(0.8)
    res = await send("Page.captureScreenshot", {"format": "png"})
    Path("C:/Users/wisdo/.gemini/antigravity/brain/77fd0336-2447-4887-9440-32556d2d7f46/preview_08_candidate_review_desktop.png").write_bytes(base64.b64decode(res["data"]))
    print("Saved preview_08_candidate_review_desktop.png")

    # Switch to handover tab
    await send("Runtime.evaluate", {"expression": "document.querySelector('[data-tab=\"handover\"]').click()"})
    await asyncio.sleep(0.8)
    res = await send("Page.captureScreenshot", {"format": "png"})
    Path("C:/Users/wisdo/.gemini/antigravity/brain/77fd0336-2447-4887-9440-32556d2d7f46/preview_09_approved_handover_desktop.png").write_bytes(base64.b64decode(res["data"]))
    print("Saved preview_09_approved_handover_desktop.png")

    await ws.close()

if __name__ == "__main__":
    asyncio.run(capture_tabs())
