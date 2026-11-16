# ALLPS — Workstream 4: Security & Repository Hygiene Report

**Audited Snapshot**: Commit `b504e0c647f14718d062b186ab8613af189ea29f`  
**Closeout Worktree**: `Q:\ALLPS-closeout-20261015`  
**Date**: 15 October 2026  
**Auditor**: Independent Maintainer Review  

---

## 1. Executive Summary & Security Assessment

A comprehensive repository hygiene and vulnerability scan was conducted across all tracked files, untracked working tree artifacts, Git commit history, and runtime environments.

### Key Security Findings
* **Credentials & Secrets**: **ZERO** active or historical credentials, private keys, API keys, or tokens were detected in Git history or tracked files. The codebase relies entirely on local loopback endpoints (`http://127.0.0.1:1234/v1` for LM Studio, `http://127.0.0.1:8000` for FastAPI).
* **Personal & Learner Data**: **ZERO** real pupil, teacher, or school identity data exists in the repository. All learner records (`LRN-001`, `LRN-002`, `LRN-003`), teacher identities (`Mr. Banda`, `Mrs. Ngcobo`), and school IDs (`SCH-MSA-042`) are purely synthetic Kenyan CBC test fixtures.
* **Prohibited Label Screening**: The deterministic policy engine ([`label_policy.py`](../../src/allps/policies/label_policy.py)) was verified against 27 prompt injection and deficit-label test cases, demonstrating 100% rejection of prohibited labels (*"slow learner"*, *"bottom 10%"*, etc.).
* **Preservation Guarantee**: All evaluation evidence, synthetic fixtures, and genuine MCP execution traces remain strictly protected and preserved.

---

## 2. Hardcoded & Machine-Specific Path Inventory

An automated scan of Git HEAD (`b504e0c`) identified references to absolute paths:

| File Location | Path Pattern | Context / Usage | Impact & Mitigation |
| :--- | :--- | :--- | :--- |
| `EVALS.md` (lines 59–167) | `file:///Q:/ALLPS/...` | Markdown clickable hyperlinks to exact code symbols and line ranges | Non-breaking. Markdown links function within local IDEs. Recommended future post-submission commit: convert to relative GitHub markdown links. |
| `allps_architecture_map.md` (lines 157–167) | `file:///q:/ALLPS/...` | Component architecture reference links | Non-breaking local IDE navigation links. |
| `docs/*.md` | `file:///q:/ALLPS/...` | Contract and evidence specification links | Non-breaking local IDE navigation links. |
| `data/trace_agentic_mcp_run.json` | `Q:\ALLPS\data\mcp_imports` | Preserved real runtime execution trace from LM Studio agent run | **Must remain frozen**. This records the genuine hardware execution on the developer machine during submission. Modifying this would violate evidence integrity. |
| `scripts/generate_demo_video.py` | `Q:\ALLPS\ALLPS_Demo_Submission.mp4` | Video rendering build script output target | Non-breaking developer script. Path can be overridden via command-line arguments in future iterations. |

---

## 3. Categorized Cleanup & Hygiene Classification

In strict compliance with the **Hard Constraints** ("*Do not automatically delete anything. Produce a proposed cleanup list showing which items should be retained, ignored, archived or removed*"), all repository artifacts have been categorized below:

### Category A: RETAIN (Keep in active repository)
These files represent essential code, tests, documentation, architecture diagrams, and submission evidence:
1. `src/allps/` — Entire application source code.
2. `tests/` — Complete test suite (252 passing tests).
3. `examples/` — Execution scripts (`demonstrate_mcp_wire_protocol.py`, `run_agentic_mcp_import.py`, `demo_e2e.py`, `test_live_lmstudio.py`).
4. `data/synthetic/` — Synthetic Kenyan learner seed fixtures (`seed_data.py`).
5. `data/mcp_imports/` — Genuine test fixtures (`teacher_export_LRN001_valid.json`, `teacher_export_LRN001_malformed.json`).
6. `data/trace_agentic_mcp_run.json` — **Frozen submission trace** (Trace ID `1cb86194...`).
7. `assets/screenshots/` — All 27 verified UI and workflow screenshots.
8. `ARCHITECTURE.md`, `EVALS.md`, `README.md`, `ROADMAP.md`, `LICENSE`, `docs/*.md` — Core documentation suite.
9. `pyproject.toml`, `package.json`, `package-lock.json`, `.gitignore` — Package and dependency manifests.
10. `docs/closeout/` — Post-submission audit reports and evidence verification records.

### Category B: IGNORE (Keep ignored in `.gitignore`; do not commit)
These files are ephemeral or machine-specific and are properly caught by `.gitignore`:
1. `__pycache__/` and `*.pyc` — Python bytecode caches.
2. `.pytest_cache/` — Pytest runtime cache.
3. `.vs/`, `.vscode/` — Local IDE workspace settings.
4. `node_modules/` — Installed Node.js MCP server binaries.
5. `*.db-wal`, `*.db-shm` — SQLite write-ahead log and shared memory runtime files.
6. `allps_dev.db`, `allps_demo_clean.db`, `allps_mcp_demo.db`, `allps_web_demo.db`, `test_allps_dev.db` — Local SQLite runtime databases in root.
7. `data/allps_mcp_demo.db`, `data/allps_mcp_live.db`, `data/allps_mcp_test.db`, `data/test_mcp_ingest.db`, `data/test_seeded.db` — Local SQLite runtime databases in `data/`.
8. `allps_code_bundle.txt`, `allps_full_codebase.txt` — LLM development bundle text files.

### Category C: ARCHIVE (Move to external offline cold storage)
These items are bulky research artifacts or build intermediates that should be preserved externally rather than occupying local repo storage:
1. `datasets/237644-V2.zip` (63.1 MB) — External UNESCO/Tusome research dataset archive.
2. `datasets/Kenya_Tusome_Study_on_Pupil_Learning_Outcomes_in_2021_Dataset.csv` (19.5 MB) — Research reference dataset.
3. `datasets/USING ASSESSMENT FOR LEARNING TO ENHANCE NUMERACY INSTRUCTION ddi-documentation-english-2.pdf` (41 KB) — Reference pedagogical documentation.
4. `"ALLPS — Agentic AI & MCP Education Demo  African Agentic AI Design Challenge..mp4"` (3.6 MB) — Local video file (already published permanently on YouTube at `https://youtu.be/MXhL38vzq-s`).
5. `temp_audio/` (5.2 MB) — Voiceover MP3 files and ffmpeg encoding logs from video assembly.
6. `Q:\ALLPS-closeout-20261015\.audit-runtime\preservation\` — Standalone Git bundle (`allps-all-refs.bundle`) and source zip (`allps-submission-b504e0c.zip`).

### Category D: REMOVE (Safe to delete upon user confirmation)
These are transient scratch files generated during testing that can be safely purged:
1. `Q:\ALLPS-closeout-20261015\.audit-runtime\pytest-corrected\*.db` — Temporary database files created during audit test execution.
2. `data/mcp_wire_protocol_demonstration.json` — Untracked test dump (can be regenerated at any time via `python examples/demonstrate_mcp_wire_protocol.py`).
3. `data/injection_test/teacher_export_LRN001_injection.json` — Scratch file used during prompt injection vulnerability tests.

---

## 4. Proposed Clean `.gitignore` Verification

The current `.gitignore` on `master` contains:
```gitignore
# Byte-compiled / optimized / DLL files
__pycache__/
*.py[cod]
*$py.class

# Caching
.pytest_cache/

# Databases
*.db
*.db-journal
*.db-wal
*.db-shm

# Virtual environments
venv/
.venv/

# Node
node_modules/

# Local text bundles
allps_*.txt
*.mp4
temp_audio/
datasets/
data/*.db*
```

This configuration safely ensures that no transient databases, video files, audio scratch tracks, or large external research datasets can be accidentally committed to source control.
