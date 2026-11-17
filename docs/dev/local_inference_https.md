# Local inference through HTTPS

The public teacher app stays at `https://allps.kwaix.dev`. Its server can call
a restricted HTTPS relay to LM Studio on the developer's computer. This is a
synthetic-data testing configuration. The computer, LM Studio, relay and tunnel
must remain running. AMD Token Lab remains the independent hosted provider.

## Private credentials

Run from the repository root:

```powershell
.\.venv-dev\Scripts\python.exe scripts/prepare_local_inference.py
```

This creates ignored `.env.local-ai` without changing the AMD `.env`.
The two local keys have different destinations:

- `ALLPS_LOCAL_RELAY_KEY`: generated key used by Render to authenticate to the relay.
- `ALLPS_LOCAL_UPSTREAM_KEY`: an LM Studio API token used only between the relay
  and `127.0.0.1:1234`. Add it privately if LM Studio requires authentication.
- `ALLPS_LOCAL_MODEL`: exact loaded model ID, initially `qwen3.5-4b`.

Generate LM Studio tokens through Developer -> Server Settings -> Manage Tokens.
Do not put either key in browser code, command arguments or chat.

## Run the restricted relay and tunnel

Start the relay in one terminal:

```powershell
.\.venv-dev\Scripts\python.exe -m uvicorn allps.web.inference_relay:create_relay_app --factory --host 127.0.0.1 --port 8789 --env-file .env.local-ai --no-access-log
```

It exposes authenticated `GET /v1/models` and `POST /v1/chat/completions`.
Other LM Studio APIs are not forwarded. Requests are limited to the configured
model, non-streaming messages, 256 KiB and one active generation. The incoming
relay credential is never forwarded to LM Studio. Provider errors are sanitized.

Use the official `cloudflared` client in a second terminal:

```powershell
.\tmp\tools\cloudflared.exe tunnel --url http://127.0.0.1:8789 --protocol http2 --edge-ip-version 4 --no-autoupdate
```

Use the HTTPS root URL printed by the tunnel. Quick Tunnels have temporary
hostnames and no uptime guarantee; restarting the tunnel requires updating
Render's provider endpoint. Publish the relay, not port 1234 directly.

Prepare private Render profiles using that URL:

```powershell
.\.venv-dev\Scripts\python.exe scripts/prepare_local_inference.py --public-url https://YOUR-TUNNEL.trycloudflare.com
```

This writes ignored `.env.local-ai-render` and `.env.amd-render`. It never
changes the live Render service or the existing `.env`. Copy values privately
from the chosen profile into Render's Environment page without the outer
single quotes. Change all six provider settings together:

- `ALLPS_AI_BASE_URL`
- `ALLPS_AI_PROVIDER`
- `ALLPS_AI_MODEL`
- `ALLPS_AI_API_KEY`
- `ALLPS_AI_TIMEOUT`
- `ALLPS_PROBE_TIMEOUT`

Do not change educator credentials, the session secret or database path.
Saving the environment redeploys the service, resetting its ephemeral Free-tier
database. Recheck synthetic data and sign-in after switching.

## Acceptance checks

Before changing Render, verify public HTTPS, unauthenticated rejection (401),
model allowlisting, management-route rejection (404), and a genuine local-model
handover through the existing output validator. A model-list response alone
does not prove valid learner synthesis.

After switching Render, test generation at the custom domain and record the
configured provider, exact model and actual `live_ai` result. Simulated teacher
review/release tests must run only against the synthetic demonstration service.

Restore `.env.amd-render` after the local check, then independently repeat the
custom-domain generation and review workflow using AMD. Never silently fall
back to deterministic or mock inference when either live provider fails.

Stop the relay and tunnel when local testing ends unless intentionally keeping
them available. Keep the LM Studio native token private; revoke it in LM Studio
when it is no longer needed.

References: [LM Studio authentication](https://lmstudio.ai/docs/developer/core/authentication),
[Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/),
[official client downloads](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/).
