# ALLPS — Workstream 1: Git Audit & Submission Snapshot Report

**Project**: ALLPS (Agentic Longitudinal Learner Profile System)  
**Submission Track**: Education: The Long View — African Agentic AI Design Challenge  
**Submission Date**: 15 October 2026  
**Audit Status**: Verified & Frozen Baseline  

---

## 1. Executive Summary

This Git Audit provides an authoritative, evidence-backed inspection of the ALLPS repository across local branches, working trees, remotes, reflogs, tag objects, and commit history. 

### Confirmed Submission Baseline
* **Exact Submission Commit**: [`b504e0c647f14718d062b186ab8613af189ea29f`](https://github.com/kwisdomk/ALLPS/commit/b504e0c647f14718d062b186ab8613af189ea29f)
* **Commit Subject**: `docs: finalize YouTube demo video URL to https://youtu.be/MXhL38vzq-s`
* **Author / Tagger**: Wisdom Kinoti | KWAIX `<wisdomkinoti001@gmail.com>`
* **Timestamp**: `2026-10-15 07:42:58 +0300` (Nairobi local time)
* **Published Remote State**: GitHub `origin/master` resolves directly to `b504e0c647f14718d062b186ab8613af189ea29f`.
* **Current Working Tree Status**: Clean (no uncommitted tracked modifications).

---

## 2. Investigation of Conflicting Release Hashes

During the submission process, three distinct Git hashes were referenced in logs and reports. Our forensic audit resolved each hash to its precise Git object type and role:

| Hash | Git Object Type | Resolved Target | Description & Resolution |
| :--- | :--- | :--- | :--- |
| `b504e0c647f14718d062b186ab8613af189ea29f` | **Commit** | N/A (HEAD of `master`) | **The Confirmed Submission Commit**. Contains the final, verified challenge deliverables, complete documentation suite, and verified YouTube video URL (`MXhL38vzq-s`). |
| `c13db9772dbe09f16bb824d32c440ce09f8b0855` | **Annotated Tag** | `b504e0c647f14718d062b186ab8613af189ea29f` | **Tag Object for `v1.0.0-challenge-submission`**. In Git, an annotated tag (`git tag -a`) is an independent repository object with its own SHA-1 hash, metadata, tagger signature, and message. Peeling this tag (`git rev-parse v1.0.0-challenge-submission^{commit}`) resolves directly to commit `b504e0c...`. This was incorrectly perceived as a conflicting commit hash when it was actually the tag container object. |
| `d55f87e9f20132676cc65b31d1f62193dd1c8eb1` | **Commit** | Parent of `b504e0c` | **Superseded Pre-Submission Commit**. Committed at `07:21:07 +0300`. It was initially tagged prior to noticing a YouTube upload link correction. Commit `b504e0c` succeeded it 21 minutes later. |

### Exact Diff Between `d55f87e` and `b504e0c`
A strict line-by-line diff between the superseded commit `d55f87e` and confirmed snapshot `b504e0c` confirms that **zero code, test, model, or schema changes** were introduced. The difference is strictly the demonstration video link correction:

```diff
diff --git a/README.md b/README.md
@@ -3,7 +3,7 @@
 > **Repository**: [https://github.com/kwisdomk/ALLPS](https://github.com/kwisdomk/ALLPS)  
-> **Video Demonstration**: [YouTube Walkthrough (2m 45s)](https://youtu.be/0VsipM2FLGk)  
+> **Video Demonstration**: [YouTube Walkthrough (2m 45s)](https://youtu.be/MXhL38vzq-s)  
 > **Public Portal**: [https://allps.kwaix.dev](https://allps.kwaix.dev)  
...
diff --git a/docs/SUBMISSION.md b/docs/SUBMISSION.md
@@ -2,7 +2,7 @@
 > **Repository**: [https://github.com/kwisdomk/ALLPS](https://github.com/kwisdomk/ALLPS)  
-> **Video Demonstration**: [https://youtu.be/0VsipM2FLGk](https://youtu.be/0VsipM2FLGk)  
+> **Video Demonstration**: [https://youtu.be/MXhL38vzq-s](https://youtu.be/MXhL38vzq-s)  
```

---

## 3. Remote Repositories & Branch Topology

### 3.1 Remote Configuration
* **Remote Name**: `origin`
* **Fetch URL**: `https://github.com/kwisdomk/ALLPS.git`
* **Push URL**: `https://github.com/kwisdomk/ALLPS.git`
* **Remote HEAD**: `b504e0c647f14718d062b186ab8613af189ea29f` (`refs/heads/master`)
* **Remote Tag**: `c13db9772dbe09f16bb824d32c440ce09f8b0855` (`refs/tags/v1.0.0-challenge-submission`)

### 3.2 Branch Inventory
| Branch Name | Local / Remote | Commit SHA | Status / Purpose |
| :--- | :--- | :--- | :--- |
| `master` | Local & Remote (`origin/master`) | `b504e0c` | **Frozen Submitted Baseline**. Production branch. |
| `docs/post-submission-closeout` | Local Worktree (`Q:/ALLPS-closeout-20261015`) | `b504e0c` | Active closeout branch containing preservation manifests, evidence verification, and post-submission docs. |
| `live-verification-demo` | Local Worktree (`Q:/ALLPS-web`) | `efbad6e` | Historical development branch used during live UI capture and verification. |
| `docs-submission-evals` | Local | `f3022e0` | Historical development branch merged into `master` at commit `56e8a75`. |
| `feature/agentic-mcp-import` | Local | `03b6f8b` | Historical development branch merged into `master` at commit `6e74810`. |
| `teacher-website` | Local | `2fa3d6b` | Historical feature branch for FastAPI single-page teacher workspace. |
| `verify-live-ai-runtime` | Local | `03b6f8b` | Historical branch for LM Studio runtime discovery probing. |

### 3.3 Active Worktrees
1. `Q:/ALLPS` on `master` at `b504e0c` (main repository)
2. `Q:/ALLPS-closeout-20261015` on `docs/post-submission-closeout` at `b504e0c` (isolated closeout worktree)
3. `Q:/ALLPS-web` on `live-verification-demo` at `efbad6e` (auxiliary development worktree)

---

## 4. Release Tag Discrepancy & Proposal

### The Discrepancy
* In `pyproject.toml`, the declared package version is:
  ```toml
  [project]
  name = "allps"
  version = "0.1.0"
  ```
* The Challenge submission prompt specifies: `Release: v0.1.0 — African Agentic AI Design Challenge`.
* However, the currently published Git tag on GitHub is: `v1.0.0-challenge-submission`.
* This occurred because `package.json` declared version `1.0.0` for `@modelcontextprotocol/server-filesystem`, and the submission milestone was conceptually treated as a 1.0 submission.

### Proposed Annotated Release Tag
To align Git tagging with `pyproject.toml` (`0.1.0`) while preserving the existing published tag for challenge evaluators, we propose creating an annotated tag:

* **Tag Name**: `v0.1.0` (or `v0.1.0-challenge-submission`)
* **Target Commit**: `b504e0c647f14718d062b186ab8613af189ea29f`
* **Annotation Message**:
  ```text
  ALLPS v0.1.0 — African Agentic AI Design Challenge Official Submission
  Target commit: b504e0c647f14718d062b186ab8613af189ea29f
  Submission date: 15 October 2026
  Package version: 0.1.0
  Dual-server FastMCP + Filesystem agent with local Qwen 3.5 4B inference
  ```

> [!IMPORTANT]
> In accordance with Hard Constraints, **no tag will be created, deleted, or pushed to the remote repository without explicit user authorization**. The existing remote tag `v1.0.0-challenge-submission` remains intact on GitHub.
