# Hosted ALLPS demonstration

The teacher interface and FastAPI run together on Render with one worker and
SQLite. The current judge service uses Render Free and synthetic data; its local
database is ephemeral. Saved reviews and releases are lost on restart, redeploy
or idle spin-down, and the synthetic dataset is seeded again at startup.
No Supabase or PostgreSQL integration is used. This is not a real-school pilot.

The checked-in `render.yaml` still describes a paid Starter service with a
persistent disk. It does not represent the manually configured Free service;
do not apply that blueprint when the deployment budget is free-only.

## Secrets and provisioning

Keep the AMD key in Render's secret environment variables. For local development,
run `python scripts/prepare_demo_env.py` to create `.env` (ignored by Git) with
five unique demo passwords and a stable session secret. This preserves an
existing `.env`. Replace the AMD key placeholder privately in your IDE, and start from
the repository root:

```powershell
.\.venv-dev\Scripts\python.exe -m uvicorn allps.web.deployment:create_hosted_app --factory --env-file .env --port 8000
```

Hosted cookies require HTTPS. Use HTTPS when testing the hosted factory; the
ordinary `allps-web` command remains the local HTTP demonstration entrypoint.

Required environment variables:

| Name | Value |
| --- | --- |
| ALLPS_AI_BASE_URL | https://api.tokenlab.amd.com/v1 |
| ALLPS_AI_PROVIDER | AMD Token Lab |
| ALLPS_AI_MODEL | Gemma-4-31B-IT; exact user-supplied catalog ID |
| ALLPS_AI_API_KEY | Full Token Lab key; never placed in frontend code |
| ALLPS_SESSION_SECRET | At least 32 random characters; stable across restarts |
| ALLPS_DB_PATH | Absolute writable SQLite path; ephemeral on Free. `/var/data/allps.db` requires an attached paid disk. |
| ALLPS_SYNTHETIC_DEMO | true for the separate demonstration service |
| ALLPS_TEACHERS_JSON | JSON array of teacher_id, display_name, password |

The synthetic workflow requires IDs TCH-OCHIENG, TCH-BANDA, TCH-WANJIKU,
TCH-OTIENO, and TCH-KAMAU, each with a unique strong password (12-64 characters,
at most 72 UTF-8 bytes). Example schema, with the password replaced before use:

```json
[{"teacher_id":"TCH-OCHIENG","display_name":"Ms. Ochieng","password":"REPLACE_WITH_RANDOM_PASSWORD"}]
```

Provision all five, not just the example account. Startup never inserts known
demo PINs in hosted mode and refuses a database containing those default PINs.
Provisioning inserts new accounts only: changing the environment does not rotate
an existing stored credential. Use a new isolated demo database for the first
hosted deployment. Credential rotation/account administration needs an explicit
operational workflow before real-school use.

## Deployment sequence

The judge-demo release branch is `release/judges-amd-demo-20261117`. Select this
branch when configuring a manual Web Service. Use `pip install .` to build and
`uvicorn allps.web.deployment:create_hosted_app --factory --host 0.0.0.0 --port $PORT --workers 1`
to start. Configure `/healthz` as the health check. Copy private values from
the local `.env` without the surrounding single quotes. Keep the configured
absolute SQLite path on the existing Free service; changing that path selects
a different database. A new disposable Free service can use `/tmp/allps-demo.db`.

1. Review and push the selected application changes plus `render.yaml` to a
   release branch; do not deploy an older GitHub revision.
2. Select that branch/repository for a manual Render Web Service deployment.
3. Choose Free and skip the disk. The existing paid blueprint is not this configuration.
4. Supply the AMD key and educator-account JSON as secrets; never commit them.
5. Confirm `/healthz`, sign-in, and genuine `live_ai` synthesis using the catalog
   model. Hosted generation rejects client attempts to choose mock/deterministic.
6. Run the synthetic walkthrough against the HTTPS deployment. This **writes**
   candidate findings and simulates teacher review and class release; only run it
   on the separate synthetic demonstration service:

```powershell
# Set these two variables privately to the configured strong demo passwords.
.\.venv-dev\Scripts\python.exe scripts/verify_deployment.py --url https://YOUR-SERVICE.onrender.com --mode live
```

The variables are `ALLPS_DEMO_CLASS_PASSWORD` (Ochieng) and
`ALLPS_DEMO_SUBJECT_PASSWORD` (Banda). The script reports actual runtime methods,
checks subject-scoped exports, and verifies explicit acknowledgment.

7. Complete browser verification on desktop and mobile. On Free, a restart
   restores the synthetic seed rather than preserving the released report.
8. Configure and verify the custom domain as described below.

## Direct custom domain: allps.kwaix.dev

For testing the public application with LM Studio on a local computer, see
[local inference through HTTPS](local_inference_https.md). Its private provider
profiles let the operator switch to the restricted relay and restore AMD without
changing educator accounts or weakening the teacher review gate.

Serve both `/` and `/api/*` from the same Render service through the custom
domain. This preserves the existing same-origin client and Secure, HttpOnly,
SameSite=Strict session cookies. No Vercel proxy or cross-origin cookie change
is required. Users sign in again on the custom domain because cookies from
`allps-judges.onrender.com` are not shared with it.

1. In Render, open `allps-judges` -> Settings -> Custom Domains, add
   `allps.kwaix.dev`, and save.
2. DNS is authoritative at Name.com. In `kwaix.dev` -> Manage DNS Records,
   edit only the existing `allps` CNAME:

   | Field | Value |
   | --- | --- |
   | Type | CNAME |
   | Host | allps |
   | Answer | allps-judges.onrender.com |
   | TTL | Existing/default value |

   Enter a hostname without `https://` or a path. Preserve root, www, MX, TXT
   and other unrelated records and the existing nameservers. If conflicting
   A/AAAA records exist at the exact `allps` hostname, reconcile only those
   records with Render's instructions.
3. Return to Render and click Verify. Wait for domain verification and TLS
   certificate issuance; do not bypass certificate warnings.
4. Confirm HTTP redirects to HTTPS, `/healthz` returns 200, static assets load,
   signed-out learner access returns 401, and class/subject teacher sign-in
   works through `https://allps.kwaix.dev`.
5. Check the actual teacher journey in a browser. DNS propagation alone does
   not establish working authentication or presentation.

Before this change the `allps` CNAME pointed to `cname.vercel-dns.com`.
Keep that value as the DNS rollback reference while the old Vercel project
assignment remains available. The main `kwaix.dev` site is independent of
this subdomain change.

## Production acceptance still required

- A genuine AMD synthesis must pass existing output validation; a provider ping
  or mocked transport test does not establish valid learner handover generation.
- The pasted Token Lab account expires December 12, 2026. Confirm renewal,
  usage limits and service suitability before promising ongoing availability.
- Cloud inference transmits the synthesis payload to AMD. The old local-only,
  zero-egress statements do not apply to this hosted configuration. Use synthetic
  data until school authorization and data handling terms are established.
- Use a single instance/worker with this SQLite design. Ephemeral storage is
  acceptable only for the explicitly disposable synthetic judge demo. Durable
  school use requires persistent storage and tested recovery. Do not scale
  multiple services against separate database copies.
- Schedule consistent SQLite backups using SQLite's backup API, export copies
  outside the service, and prove restore into an isolated database. Disk snapshots
  alone are not a demonstrated database recovery process.
- Real-school deployment requires school/account/class provisioning, credential
  lifecycle, tenancy decisions, monitoring, restore evidence and a reviewed
  release. Disabling synthetic seeding does not supply those workflows.
- Linux installation, tests and wheel-startup CI passed for `2452d7b`; rerun
  those checks for subsequent releases. Dependency locking remains unverified.

References: [Render FastAPI](https://render.com/docs/deploy-fastapi),
[persistent disks](https://render.com/docs/disks),
[secret configuration](https://render.com/docs/configure-environment-variables),
[custom domains](https://render.com/docs/custom-domains),
[subdomain DNS](https://render.com/docs/configure-other-dns),
[Name.com CNAME records](https://www.name.com/support/articles/115004895548-adding-a-cname-record).
