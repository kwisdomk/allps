# Project structure cleanup — 11 November 2026

Cleanup was prepared in the main `Q:\ALLPS` checkout after teacher-review-authority
was integrated into `dev` at `be56993`. The starting tracked file tree matched
`dev`. The baseline snapshot copy was not accessed or modified.

## File moves

| Previous location | Current location |
| --- | --- |
| `ARCHITECTURE.md` | [architecture.md](../architecture.md) |
| `DEVELOPMENT_RESEARCH.md` | [development_research.md](../development_research.md) |
| `EVALS.md` | [evals.md](../evals.md) |
| `ROADMAP.md` | [roadmap.md](../roadmap.md) |
| `allps_architecture_map.md` | [architecture_map.md](../architecture_map.md) |
| `docs/AI_CONTRACT.md` | [ai_contract.md](../ai_contract.md) |
| `docs/DATA_QUALITY.md` | [data_quality.md](../data_quality.md) |
| `docs/phase2_plan.md` | [phase2_plan.md](phase2_plan.md) |
| `ALLPS AI Education System Architecture.png` | [proposed_architecture.png](../../assets/diagrams/proposed_architecture.png) |
| `ALLPS Architecture Workflow Diagram.png` | [architecture_workflow.png](../../assets/diagrams/architecture_workflow.png) |
| `examples/test_live_lmstudio.py` | [run_live_lmstudio.py](../../examples/run_live_lmstudio.py) |
| Local root demo MP4 | `assets/demo/allps_demo.mp4` (ignored local artifact) |
| `allps_code_bundle.txt` | `exports/allps_code_bundle.txt` (ignored local artifact) |
| `allps_full_codebase.txt` | `exports/allps_full_codebase.txt` (ignored local artifact) |

No document contents were combined or discarded. `docs/contracts.md` and
`docs/submission.md` remain separate documents. Links within moved documents
were rebased, and machine-specific `file:///Q:/ALLPS/...` links were converted
to repository-relative links. Source-module documentation references were updated.

The architecture documentation distinguishes the pre-build concept diagram from
the implemented workflow. The LM Studio example was renamed for clarity; pytest
already limits collection to `tests/`, so the rename does not repair a collection
problem. Its contents are unchanged.

## Generated outputs

[generate_demo_video.py](../../scripts/generate_demo_video.py) now resolves its
paths from its own repository location, writes `assets/demo/allps_demo.mp4`,
creates the output directory, and uses `tmp/demo_video/` for intermediate files.
Its screenshot input remains `assets/screenshots/`.

`exports/`, `tmp/`, and `data/runtime/` are explicitly ignored. MP4 files remain
ignored. The local video and code exports were relocated without regeneration.

## Preserved work and deferred runtime files

- `src/allps/models/import_manifest.py` and `tests/test_evidence_identity.py`
  remain untracked intake groundwork; neither was edited or implemented.
- `.bob/` was left intact.
- Existing root and `data/` databases, including WAL/SHM companions, were left
  at their original paths. Database defaults were not changed, so this cleanup
  does not silently switch an existing operator to a new empty database.
- Existing `temp_audio/`, datasets, import fixtures, traces, and screenshots
  were preserved. The generator uses the new temporary directory on future runs.

Process inventory through CIM was unavailable in this session, so active database
ownership could not be established. Relocating databases and retiring the older
audio directory remain deferred; no live SQLite files were moved independently.

## Verification

| Check | Result |
| --- | --- |
| Existing local Markdown link targets | 50 checked; no missing targets |
| Stale moved-path and machine-specific-link scan of existing docs | Passed |
| Tracked Python compilation | 61 files passed |
| Moved diagrams and LM Studio example versus original Git blobs | Byte-identical |
| Runtime code in the two modules whose docstrings changed | AST unchanged after removing module docstrings |
| Generator output and screenshot path resolution | Passed |
| Generated-output ignore rules | Passed |
| `tests/test_models.py` | 26 passed |
| Full suite excluding unfinished intake tests (cleanup staged, isolated run) | **266 passed, 2 failed** — see note below |
| Same two tests isolated on clean baseline | **5 passed** — timeout failures are load-dependent, not a regression |

The full-suite command was:

```powershell
.venv-dev\Scripts\python.exe -m pytest -q --ignore=tests/test_evidence_identity.py -o faulthandler_timeout=60 --tb=short --durations=5
```

Result: **266 passed, 2 failed** in 264s. The two failures are
`test_demo_cli_execution_deterministic` and `test_demo_cli_execution_live_refusal`
in `tests/test_demo_e2e.py`. Both use `subprocess.run(..., timeout=30)` to spawn a
Python CLI subprocess. When run after 260 seconds of prior suite work, system load
causes the subprocess to exceed 30 s; `subprocess.TimeoutExpired` is raised.

Isolation check: running `tests/test_demo_e2e.py` alone on the clean baseline
(cleanup stashed) produced **5 passed** with the same two tests completing in 25 s
and 18 s respectively — well under the 30 s timeout. The failures are an
environmental sensitivity to system load during a long run, present before and after
the cleanup, and not caused by any change in this cleanup.

Live LM Studio inference and video regeneration were not required for relocation
and were not run. Temporary verification files are under ignored `tmp/`.

## Git state

Branch `chore/project-structure` was created from `dev` (`be56993`) and all cleanup
edits were carried across. The two Windows case-only renames were recorded using a
two-step `git mv -f` (rename through a temporary name) to force Git to track the
lowercase paths:

```
docs/AI_CONTRACT.md → docs/ai_contract.md
docs/DATA_QUALITY.md → docs/data_quality.md
```

`git ls-files` confirms both are tracked with lowercase paths. All 19 changes are
staged. `.bob/`, `src/allps/models/import_manifest.py`, and
`tests/test_evidence_identity.py` are outside the staged set.

The cleanup remains uncommitted for review, as instructed. Intake implementation
follows verified cleanup as a separate feature; it has not started.

Protected refs remain unchanged: `master` and the dereferenced
`v1.0.0-challenge-submission` tag both resolve to `b504e0c`; `dev` remains at
`be56993`. The annotated tag object is separate from its underlying commit.
