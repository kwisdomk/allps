# ALLPS — System Architecture Map

> **Agentic Longitudinal Learner Profile System**
> Visual map of components, data flows, and approval boundaries

---

## Full System Flow Diagram

```mermaid
flowchart TB
    %% ── Data Sources ──────────────────────────────────────
    subgraph SOURCES["📥 Data Sources"]
        direction LR
        S1["🧪 Assessments<br/><i>score, max_score, rubric</i>"]
        S2["📋 Attendance<br/><i>daily status or term counts</i>"]
        S3["👁️ Teacher Observations<br/><i>classroom notes, behaviour</i>"]
        S4["💭 Learner Reflections<br/><i>self-reported reflections</i>"]
        S5["📂 Projects<br/><i>portfolio evidence</i>"]
    end

    %% ── Upstream Systems ──────────────────────────────────
    subgraph UPSTREAM["🏫 Source Systems"]
        direction LR
        U1["school_sis"]
        U2["moodle"]
        U3["attendance_system"]
        U4["csv_import"]
        U5["manual_observation"]
    end

    %% ── MCP Client / Agent ────────────────────────────────
    subgraph AGENT["🤖 MCP Client — Orchestration Agent"]
        direction TB
        AG["Agent Loop<br/><i>allps.agent (Phase 3: PydanticAI / LangGraph)</i>"]
        LLM["LLM Backend<br/><i>Pluggable: local open-weight model<br/>or Gemini API</i>"]
        AG -- "prompt with<br/>retrieved evidence" --> LLM
        LLM -- "sourced draft<br/>handover brief" --> AG
    end

    %% ── MCP Protocol Layer ────────────────────────────────
    subgraph MCP_LAYER["⚙️ Model Context Protocol — stdio JSON-RPC"]
        direction TB
        MCP_SERVER["ALLPS MCP Server<br/><i>allps.mcp.server &nbsp;·&nbsp; FastMCP</i>"]

        subgraph TOOLS["MCP Tools"]
            direction LR
            T1["ingest_evidence<br/><i>validate + store observation</i>"]
            T2["get_learner_history<br/><i>chronological retrieval<br/>+ optional filters</i>"]
            T3["analyse_longitudinal_pattern<br/><i>strict 9-key comparability<br/>deterministic engine</i>"]
            T4["flag_pattern_for_review<br/><i>route to teacher inbox</i><br/>✅ Implemented"]
            T5["resolve_teacher_review<br/><i>accept / reject / needs_context</i><br/>✅ Implemented"]
        end
        MCP_SERVER --- TOOLS
    end

    %% ── Service Layer ─────────────────────────────────────
    subgraph SERVICES["📦 Service Layer"]
        direction LR
        ES["Evidence Service<br/><i>allps.services.evidence_service</i><br/>Pydantic validation · UTC enforcement<br/>idempotency · audit logging"]
        AS["Analysis Service<br/><i>allps.services.analysis_service</i><br/>strict comparability engine<br/>trend · persistence · divergence<br/>baseline delta · ordinal rubric"]
    end

    %% ── Storage ───────────────────────────────────────────
    subgraph DB["🗄️ Async SQLite Store — allps.storage.sqlite_store"]
        direction LR
        DB_L["learners"]
        DB_E["evidence<br/><i>frozen, append-only via MCP</i>"]
        DB_P["patterns<br/><i>candidate longitudinal patterns</i>"]
        DB_R["review_items<br/><i>pending · accepted<br/>rejected · needs_context</i>"]
        DB_A["audit_log<br/><i>tool invocation trail</i>"]
    end

    %% ── Domain Models ─────────────────────────────────────
    subgraph MODELS["📐 Domain Models — allps.models (frozen Pydantic v2)"]
        direction LR
        M1["Learner"]
        M2["Evidence"]
        M3["Pattern"]
        M4["ReviewItem"]
        M5["AuditEntry"]
    end

    %% ── Teacher Review Boundary ───────────────────────────
    subgraph REVIEW_GATE["🔒 Teacher Approval Boundary — Human-in-the-Loop"]
        direction TB
        TEACHER["👩‍🏫 Teacher Review<br/><i>Professional educator judgement</i>"]
        DECISION{{"Accept · Reject · Needs Context"}}
        TEACHER --> DECISION
    end

    %% ── Final Output ──────────────────────────────────────
    subgraph OUTPUT["✅ Final Output"]
        HANDOVER["📄 Approved Learner Handover<br/><i>Sourced transition brief with:<br/>• cited evidence_ids<br/>• stated limitations<br/>• explicit abstentions</i>"]
    end

    %% ── Policies ──────────────────────────────────────────
    subgraph POLICIES["🛡️ Safety Policies — allps.policies"]
        POL["Prohibited Label Screening<br/><i>✅ Implemented</i><br/>Blocks: 'slow learner', 'lazy', 'ADHD'"]
    end

    %% ══════════════════════════════════════════════════════
    %% ARROWS — Data Flow
    %% ══════════════════════════════════════════════════════

    %% Sources → Upstream → MCP
    SOURCES -- "raw observations" --> UPSTREAM
    UPSTREAM -- "source_system +<br/>ingestion_method" --> T1

    %% Agent ↔ MCP (separate request / response arrows)
    AG -- "tool request:<br/>get_learner_history()" --> MCP_SERVER
    MCP_SERVER -- "result:<br/>chronological evidence[]" --> AG

    AG -- "tool request:<br/>analyse_longitudinal_pattern()" --> MCP_SERVER
    MCP_SERVER -- "result:<br/>Pattern[] with<br/>supporting_evidence" --> AG

    AG -- "tool request:<br/>ingest_evidence()" --> MCP_SERVER

    %% MCP → Services
    T1 --> ES
    T2 --> ES
    T3 --> AS
    AS -- "reads evidence<br/>via EvidenceService" --> ES

    %% Services → Storage
    ES -- "read / write" --> DB
    AS -- "store patterns" --> DB_P

    %% Storage ↔ Models
    DB --- MODELS

    %% Policies guard ingestion
    POLICIES -. "screens content<br/>before storage" .-> ES

    %% Agent drafts → Teacher Review
    AG -- "candidate handover<br/>draft with citations" --> REVIEW_GATE
    DB_R -- "pending ReviewItems" --> TEACHER

    %% Teacher decisions
    DECISION -- "✅ accepted" --> HANDOVER
    DECISION -- "❌ rejected<br/>(with teacher notes)" --> DB_R
    DECISION -- "❓ needs_context<br/>(request more evidence)" --> AG

    %% External service
    LLM -. "API call<br/>(when using hosted model)" .-> EXT_API["☁️ External Model API<br/><i>e.g. Gemini API</i>"]
    EXT_API -. "generated text" .-> LLM
```

---

## Component Legend

| Symbol | Component | Module / Location | Status |
|--------|-----------|-------------------|--------|
| 📥 | **Data Sources** | 5 evidence types: `assessment`, `attendance`, `observation`, `learner_reflection`, `project` | ✅ Implemented |
| 🏫 | **Source Systems** | `source_system` field (`school_sis`, `moodle`, `attendance_system`, `csv_import`, etc.) | ✅ Implemented |
| 🤖 | **Orchestration Agent** | [`allps.agent`](file:///q:/ALLPS/src/allps/agent/__init__.py) — Bounded Pydantic AI orchestration | ✅ Implemented |
| 🧠 | **LLM Backend** | Pluggable: deterministic fallback, local open-weight model (`allps-qwen35-base-4b`), or hosted Gemini API | ✅ Implemented |
| ⚙️ | **MCP Server** | [`allps.mcp.server`](file:///q:/ALLPS/src/allps/mcp/server.py) — FastMCP, stdio transport | ✅ Implemented |
| 🔧 | **MCP Tools** | `ingest_evidence`, `get_learner_history`, `analyse_longitudinal_pattern` | ✅ Implemented |
| 🔧 | **Review Tools** | `flag_pattern_for_review`, `resolve_teacher_review`, `get_pending_reviews`, `get_surfaced_profile` | ✅ Implemented |
| 📦 | **Evidence Service** | [`allps.services.evidence_service`](file:///q:/ALLPS/src/allps/services/evidence_service.py) | ✅ Implemented |
| 📦 | **Analysis Service** | [`allps.services.analysis_service`](file:///q:/ALLPS/src/allps/services/analysis_service.py) | ✅ Implemented |
| 🗄️ | **SQLite Store** | [`allps.storage.sqlite_store`](file:///q:/ALLPS/src/allps/storage/sqlite_store.py) — async via `aiosqlite` | ✅ Implemented |
| 📐 | **Domain Models** | [`allps.models`](file:///q:/ALLPS/src/allps/models/__init__.py) — `Learner`, `Evidence`, `Pattern`, `ReviewItem`, `AuditEntry` | ✅ Implemented |
| 🛡️ | **Safety Policies** | [`allps.policies`](file:///q:/ALLPS/src/allps/policies/__init__.py) — prohibited label screening | ✅ Implemented |
| 🔒 | **Teacher Approval Gate** | [`ReviewItem`](file:///q:/ALLPS/src/allps/models/review.py) — `pending` → `accepted` / `rejected` / `needs_context` | ✅ Implemented & Enforced |
| ✅ | **Approved Handover** | Sourced transition brief with evidence citations, limitations, and SHA-256 snapshot | ✅ Implemented |
| ☁️ | **External Model API** | Local LM Studio endpoint (`allps-qwen35-base-4b`) + remote Gemini API support | ✅ Implemented |

---

## Flow Summary

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           END-TO-END DATA FLOW                              │
│                                                                              │
│   Assessments ─┐                                                             │
│   Attendance  ─┤                                                             │
│   Observations ┼─→ Source Systems ─→ ingest_evidence ─→ Evidence Service     │
│   Reflections ─┤       (provenance)      (MCP tool)      (validation)        │
│   Projects   ──┘                                                             │
│                                                       │                      │
│                                                       ▼                      │
│                                              ┌─── SQLite ───┐               │
│                                              │  evidence     │               │
│                                              │  patterns     │               │
│                                              │  review_items │               │
│                                              │  audit_log    │               │
│                                              └───────────────┘               │
│                                                       │                      │
│                                      ┌────────────────┘                      │
│                                      ▼                                       │
│   Agent ←── tool request ──→ MCP Server ──→ Services                         │
│     │   ←── tool result  ───┘                                                │
│     │                                                                        │
│     ├──→ LLM (Gemini API / local model)                                      │
│     │   ←── sourced draft ──┘                                                │
│     │                                                                        │
│     └──→ Candidate Handover Draft                                            │
│              │                                                               │
│              ▼                                                               │
│     ┌──────────────────────────────┐                                         │
│     │  🔒 TEACHER APPROVAL GATE   │                                         │
│     │    accept / reject /         │                                         │
│     │    needs_context             │                                         │
│     └──────────┬───────────────────┘                                         │
│                │                                                             │
│                ▼                                                             │
│     ✅ Approved Learner Handover                                             │
│        (cited evidence, limitations, abstentions)                            │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions

> [!IMPORTANT]
> **Teacher Approval Boundary**: No pattern enters the published learner profile unless a human teacher explicitly sets `ReviewItem.status = ACCEPTED`. Autonomous agents are prohibited from self-approving.

> [!NOTE]
> **Separate request/response arrows**: The agent sends tool requests to the MCP server and receives structured results back — these are distinct protocol messages over stdio JSON-RPC, not a single round-trip.

> [!TIP]
> **Deterministic fallback**: The analysis engine is fully deterministic (strict 9-key comparability, no LLM involved). The LLM is only used in the agent orchestration layer for natural-language synthesis of the handover brief.
