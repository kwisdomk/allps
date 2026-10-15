# ALLPS — Official Submission Materials

> **Challenge Track**: Education: The Long View — African Agentic AI Design Challenge  
> **Repository**: [https://github.com/kwisdomk/ALLPS](https://github.com/kwisdomk/ALLPS)  
> **Video Demonstration**: [https://youtu.be/MXhL38vzq-s](https://youtu.be/MXhL38vzq-s)  
> **Target Audience**: Challenge Judges & Technical Review Panel

---

## 1. Project Description (~300 Words)

**Theme & Mission:**  
ALLPS (**Agentic Longitudinal Learner Profile System**) addresses the Education track sub-themes of **Longitudinal Strength Tracking** and **Holistic Skill Profiling**. Built on the foundational principle *"Record evidence without reducing learners to labels,"* ALLPS solves the critical loss of learner developmental context across primary school transitions in Africa.

**Intended School & Workflow:**  
In resource-constrained African public schools, high pupil-to-teacher ratios (50–80:1) and frequent teacher turnover leave educators with disconnected termly mark sheets. A multi-year trajectory remains invisible until high-stakes national exams. ALLPS serves the **end-of-year teacher transition handover workflow**. When a learner moves from Grade 3 to Grade 4, an incoming educator receives a coherent, multi-year pedagogical profile rather than starting from scratch.

**System Functionality:**  
ALLPS couples an **atomic, immutable evidence ledger** with a **deterministic longitudinal comparability engine** and **bounded local open-weight AI orchestration**. The system ingests dated classroom assessments, attendance logs, and qualitative teacher observations with explicit system origin (`source_system`, `ingestion_method`). Before any AI synthesis occurs, the deterministic engine validates 9-key comparability (subject, grade, skill, form version, language, rubric scale, assessment stage), preventing false equating across incompatible scales. A local open-weight model (`allps-qwen35-base-4b` via LM Studio) then synthesizes a plain-language candidate transition brief citing exact evidence UUIDs with zero cloud data egress.

**Human Oversight & Non-Negotiable Review Gate:**  
AI is treated as the lowest-authority contributor. Candidate briefs enter a dedicated review inbox in a `PENDING` state and are strictly barred from the published learner profile. A sovereign human educator reviews findings, adds qualitative context, and adjudicates (`Accept`, `Reject`, or `Needs Context`). Accepting a finding creates an immutable cryptographic SHA-256 snapshot. Direct and indirect peer ranking (*"bottom 10%"*, *"below grade average"*) and deficit labels (*"slow learner"*) are deterministically blocked.

*(Word count: 304 words)*

---

## 2. Under-Three-Minute Demo Recording Outline

**Focus**: Unedited, genuine tool-using agent run showing local AI inference, protocol tool calls, failure detection, recovery, and human review.

| Timeline | Stage | Screen Activity & Narrative | Key Proof Point |
| :--- | :--- | :--- | :--- |
| **0:00 – 0:35** (35s) | **Real MCP Wire Protocol & Security Gate** | Run `python examples/demonstrate_mcp_wire_protocol.py` in the terminal. Show standard JSON-RPC 2.0 handshake over stdio, discovery of 7 FastMCP tools, and query of `get_learner_history`. Show an autonomous agent attempting to self-approve a review item (`reviewer_id="autonomous-agent-007"`), visibly failing with `PermissionError` and returning `is_error=True`. Query `get_surfaced_profile` to prove the published profile remains completely empty. | **Tool-using agent run + security failure gate** |
| **0:35 – 1:15** (40s) | **Teacher Observation & Citation Drawer** | Switch to the browser (`http://127.0.0.1:8000`). Select `Learner 001 (LRN-001)`. Show the 9 chronological evidence cards. Click `+ Record Observation`. Fill out a factual Grade 3 observation (*"Demonstrated strong spatial reasoning during fraction bar modeling"*). Click `Preview Observation` to show structured event time vs recording time. Commit observation (evidence increments to 10). Click the citation pill on the new card to open the side-panel drawer showing source attribution (`Mr. Banda / ALLPS_TEACHER_WEB`). | **Evidence ingestion, preview modal, & citation drawer** |
| **1:15 – 2:05** (50s) | **LIVE AI Generation & Validation Recovery** | Switch to the `Candidate Review` tab. Highlight `Mode: LIVE`. Click `⚡ Generate AI Candidate Handover`. Show terminal / UI executing local LM Studio inference (`allps-qwen35-base-4b`). <br>*(Failure & Recovery)*: If the model makes an ungrounded numerical claim, the UI displays `Deterministic Validation Rejected LLM Draft` with explicit errors. Click generate to trigger verified synthesis. UI renders `Synthesis Completed Successfully`, `REV 1`, and the green `LIVE LLM (live_ai)` badge. Review Finding 1 with clickable citations, co-occurring factors, and explicit limitations. | **Genuine local AI inference, deterministic validation gate, & recovery** |
| **2:05 – 2:40** (35s) | **Teacher Adjudication & SHA-256 Snapshot** | Teacher `TCH-BANDA` enters pedagogical notes: *"Confirmed downward trajectory across Grade 3 math terms. Scaffolding recommended for Grade 4."* Click `✓ Accept Finding`. Show the generated cryptographic snapshot badge (`SHA: 0a70374733c45e5d…`). Switch to the `Approved Handover` tab to prove only the accepted finding appears. | **Human-in-the-loop review & cryptographic snapshot** |
| **2:40 – 3:00** (20s) | **Persistence & Re-Synthesis Isolation** | Press `F5` / reload the browser to demonstrate INT-01 persistence (full brief and approved profile re-hydrate faithfully from SQLite). Click `Generate AI Candidate Handover` a second time: show revision incrementing to `REV 2`, review status returning to `PENDING`, and approved handover count remaining strictly 1 with zero inherited approval. Briefly show `https://allps.kwaix.dev` disclaimer. | **Reload persistence & revision state isolation** |
