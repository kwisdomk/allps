# ALLPS v2 readiness review — November 16, 2026

## Plan and checkout

No document explicitly titled v2.0 was found in this checkout. The reviewed
documents are `docs/roadmap.md` and `docs/dev/phase2_plan.md`. The latter is an
older governance implementation plan, with unchecked steps that already have
implementations and tests; it is not a reliable current completion checklist.

The checkout is `master` at ce0d4cb, four commits ahead of its locally cached
origin/master. That is not a fresh GitHub comparison. Substantial uncommitted
class-handover implementation and tests predated this review and were preserved.

## Verified current position

- Baseline full test suite: **316 passed**, five deprecation warnings,
  745.26 seconds. This run began before the new deployment changes.
- New hosted-deployment checks: **3 passed**. These use a mocked AMD transport;
  they do not claim an actual AMD call.
- Real HTTP walkthrough at `http://127.0.0.1:8768`: **passed**, on a separate
  synthetic database, explicitly using deterministic synthesis.
- Walkthrough includes authentication, evidence, generation for three learners,
  simulated educator review, completion/disclosure of section reviews, frozen
  class release v1, second-educator access, subject-scoped export, and explicit
  acknowledgment. The review actions are synthetic test simulation.
- The class-handover tests also cover incomplete evidence, pre-release privacy,
  subject isolation, responses, post-release changes, revisions and hash checks.

## Changes made during this review

- Configurable server-side hosted inference endpoint, key and exact model ID.
  AMD Token Lab configuration replaces local discovery in hosted mode.
- Fail-closed hosted entrypoint with strong provisioned credentials, stable
  signing secret, Secure cookies, login throttling and no-store API responses.
- Hosted mode never seeds default pilot passwords, refuses known defaults in
  an existing database, disables reseeding and forces live synthesis.
- Health check, Render persistent-disk blueprint, ignored local-secret example,
  deployment guide and reusable synthetic HTTP walkthrough.

These are local working-tree changes, not committed, merged, or deployed.

## Remaining release gates

| Gate | Current evidence |
| --- | --- |
| Full AMD synthesis and validation | Blocked: full API key not available; supplied key is masked |
| Render creation/deploy | Render connector was found but connection not confirmed |
| Public HTTPS teacher application | Not deployed in this run |
| Browser desktop/mobile walkthrough | Blocked: browser host and native computer-control pipe unavailable |
| Persistent restart/redeploy check | Requires live host |
| Backups and proven restore | Not verified |
| Clean Linux install and dependency lock | Not verified |
| Real-school account/class operations and data handling | Requires a separate pilot-readiness decision |
| Original v2.0 requirements traceability | Exact v2.0 plan location still needed |

The current outcome is a locally verified workflow plus deployment preparation.
It is not evidence of a live or production-ready school deployment.
See [deployment instructions](deployment.md) for the concrete remaining steps.

## November 17 continuation

- Release branch: `release/judges-amd-demo-20261117`.
- Focused class handover, API, educator authority, intake/export and hosted
  checks: **55 passed**, five deprecation warnings, 352.23 seconds.
- Updated hosted checks: **4 passed**, including enforcement of live inference
  when a client requests mock, deterministic or auto modes.
- Release wheel builds and starts outside the repository import paths. Packaged
  synthetic seeding, static assets, HTTPS authentication and three learners passed.
- Added a Linux/Python 3.12 CI workflow for the full suite and wheel startup;
  its result must be checked after publication.
- Hosted controls hide disabled reseeding operations and lock the inference mode.
- `scripts/prepare_demo_env.py` creates ignored private configuration without
  overwriting an existing file or printing passwords.
- AMD live synthesis, public deployment, browser presentation and restart
  persistence remain release gates. Local packaging checks do not establish
  Linux deployment, live inference or real-school production readiness.
