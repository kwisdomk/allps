# Hosted ALLPS demonstration

This deploys the teacher interface and FastAPI together on Render, using one
worker and SQLite on a persistent disk. Vercel can retain the informational portal.
The current Render blueprint enables synthetic data. It is not a real-school pilot.

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
| ALLPS_DB_PATH | /var/data/allps.db on Render |
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
the local `.env` without the surrounding single quotes, and change
`ALLPS_DB_PATH` to `/var/data/allps.db` on Render. Attach the persistent disk
at `/var/data` before starting the service.

1. Review and push the selected application changes plus `render.yaml` to a
   release branch; do not deploy an older GitHub revision.
2. Connect Render and select that branch/repository for a Blueprint deployment.
3. Review the billable Starter service and 1 GB persistent disk before creation.
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

7. Complete browser verification on desktop and mobile, then restart/redeploy
   the service and confirm the released report persists.
8. Add an application subdomain to Render only after verification. Keep the
   existing informational portal available until the new application is verified.

## Production acceptance still required

- A genuine AMD synthesis must pass existing output validation; a provider ping
  or mocked transport test does not establish valid learner handover generation.
- The pasted Token Lab account expires December 12, 2026. Confirm renewal,
  usage limits and service suitability before promising ongoing availability.
- Cloud inference transmits the synthesis payload to AMD. The old local-only,
  zero-egress statements do not apply to this hosted configuration. Use synthetic
  data until school authorization and data handling terms are established.
- Use a single instance/worker with this SQLite design. Do not put the database
  on ephemeral storage or scale multiple services against separate copies.
- Schedule consistent SQLite backups using SQLite's backup API, export copies
  outside the service, and prove restore into an isolated database. Disk snapshots
  alone are not a demonstrated database recovery process.
- Real-school deployment requires school/account/class provisioning, credential
  lifecycle, tenancy decisions, monitoring, restore evidence and a reviewed
  release. Disabling synthetic seeding does not supply those workflows.
- Reproducible dependency locking and a clean Linux install still need verification.

References: [Render FastAPI](https://render.com/docs/deploy-fastapi),
[persistent disks](https://render.com/docs/disks),
[secret configuration](https://render.com/docs/configure-environment-variables).
