/**
 * ALLPS Teacher Workspace — Single Frontend API Client and UI Controller
 *
 * Enforces:
 * - Direct coordinate via thin web API contracts (no direct SQLite, no direct LM Studio)
 * - Strict separation between Candidate Generation and Human Review
 * - Side-panel citation drawer for full record provenance
 * - Observation preview before saving with retry idempotency
 * - Server-side human authority boundary for review decisions
 */

// ── API Client ───────────────────────────────────────────────────────────────

class ApiClient {
  constructor(baseUrl = "/api") {
    this.baseUrl = baseUrl;
  }

  async _request(path, options = {}) {
    const url = `${this.baseUrl}${path}`;
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    const response = await fetch(url, { ...options, headers });

    const contentType = response.headers.get("content-type") || "";
    let data;
    if (contentType.includes("application/json")) {
      data = await response.json();
    } else {
      data = await response.text();
    }

    if (!response.ok) {
      const errorMsg = data && data.detail ? data.detail : `HTTP ${response.status}: ${response.statusText}`;
      const error = new Error(errorMsg);
      error.status = response.status;
      error.data = data;
      throw error;
    }

    return data;
  }

  async getConfig() {
    return this._request("/config");
  }

  async getLearners() {
    return this._request("/learners");
  }

  async getEvidence(learnerId, filters = {}) {
    const params = new URLSearchParams();
    if (filters.subject) params.append("subject", filters.subject);
    if (filters.academic_year) params.append("academic_year", filters.academic_year);
    if (filters.term) params.append("term", filters.term);
    if (filters.evidence_type) params.append("evidence_type", filters.evidence_type);

    const queryStr = params.toString() ? `?${params.toString()}` : "";
    return this._request(`/learners/${encodeURIComponent(learnerId)}/evidence${queryStr}`);
  }

  async getEvidenceDetail(evidenceId) {
    return this._request(`/evidence/${encodeURIComponent(evidenceId)}`);
  }

  async postObservation(learnerId, payload) {
    return this._request(`/learners/${encodeURIComponent(learnerId)}/evidence`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async generateHandover(learnerId, subject = null, mode = "auto") {
    return this._request(`/learners/${encodeURIComponent(learnerId)}/generate`, {
      method: "POST",
      body: JSON.stringify({ subject, mode }),
    });
  }

  async getReviews(learnerId) {
    return this._request(`/learners/${encodeURIComponent(learnerId)}/reviews`);
  }

  async postReviewDecision(reviewId, status, teacherNotes = null) {
    return this._request(`/reviews/${encodeURIComponent(reviewId)}/decision`, {
      method: "POST",
      body: JSON.stringify({ status, teacher_notes: teacherNotes }),
    });
  }

  async getApprovedHandover(learnerId) {
    return this._request(`/learners/${encodeURIComponent(learnerId)}/handover`);
  }

  async getLatestBrief(learnerId) {
    return this._request(`/learners/${encodeURIComponent(learnerId)}/brief`);
  }
}

// ── Application State & Controller ──────────────────────────────────────────

const api = new ApiClient();

const state = {
  learners: [],
  activeLearnerId: null,
  activeTab: "evidence",
  filters: {
    subject: "",
    academic_year: "",
    term: "",
    evidence_type: "",
  },
  config: {
    review_authority_available: false,
    server_reviewer_id: null,
    default_mode: "auto",
  },
  isGenerating: false,
  // Stable observation draft state
  observationDraft: {
    source_event_id: crypto.randomUUID ? crypto.randomUUID() : `draft-${Date.now()}`,
    academic_year: 2025,
    term: 1,
    subject: "",
    source_reference: "Mr. Banda",
    observation: "",
    context: "",
    event_datetime: new Date().toISOString().slice(0, 16),
  },
};

// ── DOM Elements ────────────────────────────────────────────────────────────

const elements = {
  learnerSelect: document.getElementById("learner-select"),
  filterSubject: document.getElementById("filter-subject"),
  filterYear: document.getElementById("filter-year"),
  filterTerm: document.getElementById("filter-term"),
  filterType: document.getElementById("filter-type"),

  tabBtns: document.querySelectorAll(".tab-btn"),
  viewPanels: document.querySelectorAll(".view-panel"),

  evidenceList: document.getElementById("evidence-list"),
  evidenceCountBadge: document.getElementById("evidence-count-badge"),

  reviewsList: document.getElementById("reviews-list"),
  reviewsCountBadge: document.getElementById("reviews-count-badge"),
  btnGenerate: document.getElementById("btn-generate"),
  generateSubject: document.getElementById("generate-subject"),
  generateMode: document.getElementById("generate-mode"),
  generationResultContainer: document.getElementById("generation-result-container"),

  handoverList: document.getElementById("handover-list"),
  handoverCountBadge: document.getElementById("handover-count-badge"),

  authBanner: document.getElementById("auth-status-banner"),

  // Side Panel
  sidePanel: document.getElementById("side-panel"),
  sidePanelOverlay: document.getElementById("side-panel-overlay"),
  sidePanelCloseBtn: document.getElementById("side-panel-close-btn"),
  sidePanelContent: document.getElementById("side-panel-content"),

  // Observation Modal
  btnOpenObservation: document.getElementById("btn-open-observation"),
  observationDialog: document.getElementById("observation-dialog"),
  observationForm: document.getElementById("observation-form"),
  btnPreviewObservation: document.getElementById("btn-preview-observation"),
  btnCloseObservation: document.getElementById("btn-close-observation"),

  // Observation Preview Dialog
  previewDialog: document.getElementById("preview-dialog"),
  previewContent: document.getElementById("preview-content"),
  btnConfirmSaveObservation: document.getElementById("btn-confirm-save-observation"),
  btnBackToEditObservation: document.getElementById("btn-back-to-edit-observation"),

  // Field Inputs
  obsYear: document.getElementById("obs-year"),
  obsTerm: document.getElementById("obs-term"),
  obsSubject: document.getElementById("obs-subject"),
  obsSourceRef: document.getElementById("obs-source-ref"),
  obsDatetime: document.getElementById("obs-datetime"),
  obsText: document.getElementById("obs-text"),
  obsContext: document.getElementById("obs-context"),
  obsErrorAlert: document.getElementById("obs-error-alert"),
};

// ── Initialization ──────────────────────────────────────────────────────────

async function init() {
  bindEvents();
  await loadConfig();
  await loadLearners();
  if (state.learners.length > 0) {
    state.activeLearnerId = state.learners[0].learner_id;
    elements.learnerSelect.value = state.activeLearnerId;
    await refreshAllViews();
  }
}

function bindEvents() {
  // Learner change
  elements.learnerSelect.addEventListener("change", (e) => {
    state.activeLearnerId = e.target.value;
    refreshAllViews();
  });

  // Filters change
  const filterElements = [elements.filterSubject, elements.filterYear, elements.filterTerm, elements.filterType];
  filterElements.forEach((el) => {
    el.addEventListener("change", () => {
      state.filters.subject = elements.filterSubject.value;
      state.filters.academic_year = elements.filterYear.value;
      state.filters.term = elements.filterTerm.value;
      state.filters.evidence_type = elements.filterType.value;
      loadEvidenceView();
    });
  });

  // Tab switching
  elements.tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const tabName = btn.dataset.tab;
      switchTab(tabName);
    });
  });

  // Generate Handover
  elements.btnGenerate.addEventListener("click", handleGenerateHandover);

  // Side Panel
  elements.sidePanelCloseBtn.addEventListener("click", closeSidePanel);
  elements.sidePanelOverlay.addEventListener("click", closeSidePanel);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeSidePanel();
  });

  // Observation Form Modal
  elements.btnOpenObservation.addEventListener("click", openObservationDialog);
  elements.btnCloseObservation.addEventListener("click", () => elements.observationDialog.close());

  // Preview Button
  elements.btnPreviewObservation.addEventListener("click", handleObservationPreview);

  // Preview Back & Confirm
  elements.btnBackToEditObservation.addEventListener("click", () => {
    elements.previewDialog.close();
    elements.observationDialog.showModal();
  });

  elements.btnConfirmSaveObservation.addEventListener("click", handleSaveObservation);
}

// ── Tab Management ──────────────────────────────────────────────────────────

function switchTab(tabName) {
  state.activeTab = tabName;
  elements.tabBtns.forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tabName);
  });
  elements.viewPanels.forEach((panel) => {
    panel.classList.toggle("active", panel.id === `view-${tabName}`);
  });

  if (tabName === "evidence") loadEvidenceView();
  else if (tabName === "reviews") loadReviewsView();
  else if (tabName === "handover") loadApprovedHandoverView();
}

// ── Config & Learners ───────────────────────────────────────────────────────

async function loadConfig() {
  try {
    state.config = await api.getConfig();
    renderAuthStatus();
    if (state.config.default_mode && elements.generateMode) {
      elements.generateMode.value = state.config.default_mode;
    }
  } catch (err) {
    console.error("Failed to load config:", err);
  }
}

function renderAuthStatus() {
  const isAvailable = state.config.review_authority_available;
  const reviewerId = state.config.server_reviewer_id;

  if (isAvailable) {
    elements.authBanner.className = "status-pill active";
    elements.authBanner.title = "Prototype Trust Limitation: Server-configured reviewer ID for demonstration, not verified cryptographic identity.";
    elements.authBanner.innerHTML = `
      <span class="pulse-dot"></span>
      <span>Configured Reviewer: <strong>${escapeHtml(reviewerId)}</strong> <span style="font-size:10px; opacity:0.8;">(Demo Config)</span></span>
    `;
  } else {
    elements.authBanner.className = "status-pill disabled";
    elements.authBanner.title = "Decision submission disabled: Server authority unconfigured.";
    elements.authBanner.innerHTML = `
      <span class="pulse-dot"></span>
      <span>Authority: <strong>Disabled (503)</strong></span>
    `;
  }
}

async function loadLearners() {
  try {
    state.learners = await api.getLearners();
    elements.learnerSelect.innerHTML = "";
    state.learners.forEach((l) => {
      const opt = document.createElement("option");
      opt.value = l.learner_id;
      opt.textContent = `${l.display_name} (${l.learner_id})`;
      elements.learnerSelect.appendChild(opt);
    });
  } catch (err) {
    console.error("Failed to load learners:", err);
  }
}

async function refreshAllViews() {
  await Promise.all([
    loadEvidenceView(),
    loadReviewsView(),
    loadApprovedHandoverView(),
  ]);
}

// ── View 1: Evidence View ───────────────────────────────────────────────────

async function loadEvidenceView() {
  if (!state.activeLearnerId) return;

  elements.evidenceList.innerHTML = `<div class="empty-state">Loading evidence records...</div>`;

  try {
    const records = await api.getEvidence(state.activeLearnerId, state.filters);
    elements.evidenceCountBadge.textContent = records.length;
    const sideCount = document.getElementById("side-evidence-count");
    if (sideCount) sideCount.textContent = records.length;

    if (records.length === 0) {
      elements.evidenceList.innerHTML = `
        <div class="empty-state">
          <h3>No evidence records found</h3>
          <p>No records matched the selected filters for learner ${escapeHtml(state.activeLearnerId)}.</p>
        </div>
      `;
      return;
    }

    elements.evidenceList.innerHTML = "";
    records.forEach((r) => {
      const card = renderEvidenceCard(r);
      elements.evidenceList.appendChild(card);
    });
  } catch (err) {
    elements.evidenceList.innerHTML = `
      <div class="empty-state" style="color: var(--danger);">
        <h3>Error loading evidence</h3>
        <p>${escapeHtml(err.message)}</p>
      </div>
    `;
  }
}

function renderEvidenceCard(r) {
  const card = document.createElement("div");
  card.className = "evidence-card";

  // Stage Badge
  let stageBadgeHtml = "";
  if (r.assessment_stage) {
    const stageClass = `badge-stage-${r.assessment_stage.toLowerCase()}`;
    const stageLabels = {
      opener: "Opener / Breakfast Test",
      cat: "Continuous Assessment (CAT)",
      midterm: "Midterm Assessment",
      end_term: "End-Term Assessment",
    };
    const stageLabel = stageLabels[r.assessment_stage.toLowerCase()] || r.assessment_stage.toUpperCase();
    stageBadgeHtml = `<span class="badge ${stageClass}">${escapeHtml(stageLabel)}</span>`;
  }

  // Type Badge
  const typeBadgeClass = `badge-${r.evidence_type.toLowerCase().replace(/_/g, "-")}`;
  const typeBadge = `<span class="badge ${typeBadgeClass}">${escapeHtml(r.evidence_type.replace(/_/g, " "))}</span>`;

  // Missing status badge
  let missingBadge = "";
  if (r.is_missing_outcome) {
    const reasonText = r.missing_reason ? `: ${r.missing_reason}` : "";
    missingBadge = `<span class="badge badge-missing">Missing Result (${escapeHtml(r.missing_status || "Unavailable")}${escapeHtml(reasonText)})</span>`;
  }

  // Content display
  let contentHtml = "";
  if (r.evidence_type === "assessment") {
    if (r.is_missing_outcome) {
      contentHtml = `<em>Missing assessment result: ${escapeHtml(r.missing_reason || "Not recorded")}</em>`;
    } else if (r.score !== undefined && r.max_score !== undefined) {
      contentHtml = `<span class="score-val">${r.score} / ${r.max_score} marks</span>`;
      if (r.measured_skill) {
        contentHtml += ` <span style="color: var(--text-muted); font-size: 12px;">(${escapeHtml(r.measured_skill)})</span>`;
      }
    } else if (r.content.level) {
      contentHtml = `<strong>Level: ${escapeHtml(r.content.level)}</strong> (${escapeHtml(r.content.rubric || "Standard Rubric")})`;
    } else {
      contentHtml = `<span>${escapeHtml(JSON.stringify(r.content))}</span>`;
    }
  } else if (r.evidence_type === "attendance") {
    const present = r.content.days_present ?? "—";
    const total = r.content.days_total ?? "—";
    const rate = r.content.rate !== undefined ? `(${Math.round(r.content.rate * 100)}%)` : "";
    contentHtml = `<strong>${present} / ${total} days present ${rate}</strong>`;
  } else if (r.evidence_type === "observation") {
    const obs = r.content.observation || r.content.note || "";
    const ctx = r.content.context ? `<div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">Context: ${escapeHtml(r.content.context)}</div>` : "";
    contentHtml = `<div>${escapeHtml(obs)}</div>${ctx}`;
  } else if (r.evidence_type === "learner_reflection") {
    const refl = r.content.reflection || "";
    contentHtml = `<em>"${escapeHtml(refl)}"</em>`;
  } else {
    contentHtml = `<span>${escapeHtml(JSON.stringify(r.content))}</span>`;
  }

  const obsDate = new Date(r.observed_at).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });

  card.innerHTML = `
    <div class="evidence-header">
      <div class="evidence-badges">
        ${typeBadge}
        ${stageBadgeHtml}
        ${missingBadge}
        ${r.subject ? `<span class="tag tag-stage">${escapeHtml(r.subject)}</span>` : ""}
      </div>
      <div class="evidence-dates">
        Year ${r.academic_year} · Term ${r.term} · Observed ${obsDate}
      </div>
    </div>
    <div class="evidence-content">
      ${contentHtml}
    </div>
    <div class="evidence-provenance">
      <span>Source: ${escapeHtml(r.source_reference)} (${escapeHtml(r.source_system)})</span>
      <button type="button" class="citation-pill" data-evidence-id="${escapeHtml(r.evidence_id)}">
        ID: ${escapeHtml(r.evidence_id.slice(0, 8))}…
      </button>
    </div>
  `;

  // Citation button click
  const citeBtn = card.querySelector(".citation-pill");
  citeBtn.addEventListener("click", () => openSidePanel(r.evidence_id));

  return card;
}

// ── View 2: Candidate Review View ───────────────────────────────────────────

async function loadReviewsView() {
  if (!state.activeLearnerId) return;

  // 1. Restore persisted candidate brief on load / refresh (INT-01)
  try {
    const briefRes = await api.getLatestBrief(state.activeLearnerId);
    if (briefRes && briefRes.brief) {
      const b = briefRes.brief;
      renderGenerationResult({
        status: b.status === "abstained" ? "abstained" : "success",
        runtime_method: b.runtime_method,
        generation_revision: b.generation_revision,
        review_id: b.review_id,
        pattern_id: b.pattern_id,
        brief: {
          summary: b.summary,
          findings: b.findings,
          contradictions: b.contradictions,
          limitations: b.limitations,
          abstention_reason: b.abstention_reason,
        },
      });
    } else {
      elements.generationResultContainer.innerHTML = "";
    }
  } catch (err) {
    console.warn("Could not restore candidate brief:", err);
  }

  // 2. Load candidate review items
  try {
    const reviews = await api.getReviews(state.activeLearnerId);
    elements.reviewsCountBadge.textContent = reviews.length;

    const pendingCount = reviews.filter((r) => r.status === "pending").length;
    const sidePending = document.getElementById("side-pending-count");
    if (sidePending) sidePending.textContent = pendingCount;

    if (reviews.length === 0) {
      elements.reviewsList.innerHTML = `
        <div class="empty-state">
          <h3>No candidate reviews saved</h3>
          <p>No candidate patterns are currently awaiting adjudication. Generate a candidate handover above to begin.</p>
        </div>
      `;
      return;
    }

    elements.reviewsList.innerHTML = "";
    reviews.forEach((rev) => {
      const card = renderReviewCard(rev);
      elements.reviewsList.appendChild(card);
    });
  } catch (err) {
    elements.reviewsList.innerHTML = `
      <div class="empty-state" style="color: var(--danger);">
        <h3>Error loading candidate reviews</h3>
        <p>${escapeHtml(err.message)}</p>
      </div>
    `;
  }
}

function getMethodBadge(method) {
  const m = (method || "").toLowerCase();
  let cls = "badge-method-mock";
  let label = "MOCK";
  if (m.includes("live") || m.includes("lmstudio") || m.includes("openai") || m.includes("gemini")) {
    cls = "badge-method-live";
    label = "LIVE LLM";
  } else if (m.includes("deterministic") || m.includes("heuristic") || m.includes("rule")) {
    cls = "badge-method-deterministic";
    label = "DETERMINISTIC";
  } else if (m.includes("fallback")) {
    cls = "badge-method-fallback";
    label = "FALLBACK";
  } else if (m.includes("mock")) {
    cls = "badge-method-mock";
    label = "MOCK SYNTHESIS";
  } else {
    label = (method || "UNKNOWN").toUpperCase();
  }
  return `<span class="badge ${cls}" title="Runtime Provenance: ${escapeHtml(method || 'unknown')}">${escapeHtml(label)}</span>`;
}

function renderReviewCard(rev) {
  const card = document.createElement("div");
  card.className = "review-card";

  const statusClass = `badge-status-${rev.status.toLowerCase()}`;
  const statusBadge = `<span class="badge ${statusClass}">${escapeHtml(rev.status.toUpperCase())}</span>`;
  const revBadge = rev.generation_revision != null ? `<span class="tag tag-stage">Rev ${escapeHtml(String(rev.generation_revision))}</span>` : "";
  const methodBadge = (rev.candidate_brief && rev.candidate_brief.runtime_method)
    ? getMethodBadge(rev.candidate_brief.runtime_method)
    : "";

  // Citations
  let citationsHtml = "None";
  if (rev.supporting_evidence_ids && rev.supporting_evidence_ids.length > 0) {
    citationsHtml = rev.supporting_evidence_ids
      .map((id) => `<button type="button" class="citation-pill" data-evidence-id="${escapeHtml(id)}">${escapeHtml(id.slice(0, 8))}…</button>`)
      .join(" ");
  }

  // Limitations
  let limitationsHtml = "";
  if (rev.limitations && rev.limitations.length > 0) {
    limitationsHtml = `
      <div class="review-limitations">
        <strong>Caveats / Limitations:</strong> ${escapeHtml(rev.limitations.join("; "))}
      </div>
    `;
  }

  // Teacher adjudication area
  const isAuthorityAvailable = state.config.review_authority_available;
  const isPending = rev.status === "pending";

  let actionAreaHtml = "";
  if (isPending) {
    actionAreaHtml = `
      <div class="review-action-area">
        <label style="font-size: 11px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; font-family: var(--font-mono);">
          Teacher Adjudication Notes (Optional Context):
        </label>
        <textarea class="notes-input" rows="2" placeholder="Record teacher rationale or pedagogical recommendations...">${escapeHtml(rev.teacher_notes || "")}</textarea>
        <div class="review-btn-row">
          <button type="button" class="btn btn-accept btn-sm" ${!isAuthorityAvailable ? "disabled" : ""}>
            ✓ Accept Finding
          </button>
          <button type="button" class="btn btn-reject btn-sm" ${!isAuthorityAvailable ? "disabled" : ""}>
            ✕ Reject
          </button>
          <button type="button" class="btn btn-needs-context btn-sm" ${!isAuthorityAvailable ? "disabled" : ""}>
            ? Needs Context
          </button>
          ${!isAuthorityAvailable ? `<span style="font-size: 11px; color: var(--rose-accent);">Authority disabled: waiting for backend server auth.</span>` : ""}
        </div>
      </div>
    `;
  } else {
    actionAreaHtml = `
      <div class="review-decision-box">
        <span>Decision: <strong>${escapeHtml(rev.status.toUpperCase())}</strong> by <code>${escapeHtml(rev.reviewer_id || "Teacher")}</code></span>
        ${rev.approved_content_hash ? `<span class="hash-badge" title="SHA-256 Hash">SHA: ${escapeHtml(rev.approved_content_hash.slice(0, 16))}…</span>` : ""}
      </div>
      ${rev.teacher_notes ? `<div style="font-size: 12px; color: var(--text-secondary); font-style: italic; margin-top: 4px;">Notes: "${escapeHtml(rev.teacher_notes)}"</div>` : ""}
    `;
  }

  card.innerHTML = `
    <div class="review-header">
      <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
        <span class="tag tag-stage">${escapeHtml(rev.pattern_type.toUpperCase())}</span>
        ${revBadge}
        ${methodBadge}
        ${statusBadge}
      </div>
      <div class="evidence-dates">
        Generated: ${new Date(rev.generated_at).toLocaleString()}
      </div>
    </div>
    <div class="review-summary">
      ${escapeHtml(rev.summary)}
    </div>
    ${limitationsHtml}
    <div class="evidence-provenance" style="border: none; padding: 0;">
      <span style="font-size: 12px;"><strong>Supporting Citations:</strong> ${citationsHtml}</span>
    </div>
    ${actionAreaHtml}
  `;

  // Bind citation pills
  card.querySelectorAll(".citation-pill").forEach((btn) => {
    btn.addEventListener("click", () => openSidePanel(btn.dataset.evidenceId));
  });

  // Bind decision buttons
  if (isPending && rev.review_id) {
    const notesInput = card.querySelector(".notes-input");
    const acceptBtn = card.querySelector(".btn-accept");
    const rejectBtn = card.querySelector(".btn-reject");
    const needsContextBtn = card.querySelector(".btn-needs-context");

    if (acceptBtn) {
      acceptBtn.addEventListener("click", () => handleReviewDecision(rev.review_id, "accepted", notesInput.value));
    }
    if (rejectBtn) {
      rejectBtn.addEventListener("click", () => handleReviewDecision(rev.review_id, "rejected", notesInput.value));
    }
    if (needsContextBtn) {
      needsContextBtn.addEventListener("click", () => handleReviewDecision(rev.review_id, "needs_context", notesInput.value));
    }
  }

  return card;
}

async function handleGenerateHandover() {
  if (state.isGenerating || !state.activeLearnerId) return;

  state.isGenerating = true;
  elements.btnGenerate.disabled = true;
  elements.btnGenerate.textContent = "Synthesizing Longitudinal Records...";
  elements.generationResultContainer.innerHTML = `
    <div class="generation-status-card" style="background: #f1f5f9; border: 1px solid #cbd5e1; color: #334155;">
      <span>Executing bounded AI handover pipeline via runtime registry...</span>
    </div>
  `;

  try {
    const subject = elements.generateSubject.value || null;
    const mode = elements.generateMode.value || "auto";

    const res = await api.generateHandover(state.activeLearnerId, subject, mode);
    renderGenerationResult(res);

    // Reload reviews to show newly persisted patterns
    await loadReviewsView();
  } catch (err) {
    elements.generationResultContainer.innerHTML = `
      <div class="generation-status-card inference_failed">
        <div>
          <strong>Generation Pipeline Error:</strong>
          <p>${escapeHtml(err.message)}</p>
        </div>
      </div>
    `;
  } finally {
    state.isGenerating = false;
    elements.btnGenerate.disabled = false;
    elements.btnGenerate.textContent = "⚡ Generate AI Candidate Handover";
  }
}

function renderGenerationResult(res) {
  const status = res.status; // success | abstained | validation_failed | inference_failed
  const method = res.runtime_method || "unknown";
  const revBadge = res.generation_revision != null ? `<span class="tag tag-stage" style="margin-left: 6px;">Rev ${escapeHtml(String(res.generation_revision))}</span>` : "";
  const methodBadge = getMethodBadge(method);

  if (status === "success" && res.brief) {
    let findingsHtml = "";
    if (res.brief.findings) {
      findingsHtml = res.brief.findings
        .map((f, i) => {
          const cites = (f.supporting_evidence_ids || [])
            .map((id) => `<button type="button" class="citation-pill" data-evidence-id="${escapeHtml(id)}">${escapeHtml(id.slice(0, 8))}…</button>`)
            .join(" ");

          const coFactors = (f.co_occurring_factors || [])
            .map((cf) => `<li>${escapeHtml(cf)}</li>`)
            .join("");

          const inquiries = (f.teacher_inquiries || [])
            .map((ti) => `<li>${escapeHtml(ti)}</li>`)
            .join("");

          return `
            <div class="finding-item">
              <div><strong>Finding ${i + 1}:</strong> ${escapeHtml(f.observation)}</div>
              ${cites ? `<div style="font-size: 11px;">Citations: ${cites}</div>` : ""}
              ${coFactors ? `<div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;"><strong>Co-occurring Factors:</strong> <ul>${coFactors}</ul></div>` : ""}
              ${inquiries ? `<div style="font-size: 12px; color: var(--blue-accent); margin-top: 4px;"><strong>Teacher Inquiries:</strong> <ul>${inquiries}</ul></div>` : ""}
            </div>
          `;
        })
        .join("");
    }

    elements.generationResultContainer.innerHTML = `
      <div class="generation-status-card success">
        <div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <strong>Synthesis Completed Successfully</strong>
            ${revBadge}
          </div>
          <div style="font-size: 12px; margin-top: 4px; display: flex; align-items: center; gap: 6px;">
            <span>Runtime Provenance:</span>
            ${methodBadge}
            <code style="font-size: 11px; opacity: 0.8;">(${escapeHtml(method)})</code>
          </div>
        </div>
        <span class="badge badge-status-accepted">Validated Brief</span>
      </div>

      <div class="candidate-synthesis-card">
        <div class="candidate-synthesis-label">
          ⚠️ Candidate synthesis — not approved. Requires teacher adjudication below.
        </div>
        <div style="font-size: 14px; font-weight: 500;">
          ${escapeHtml(res.brief.summary)}
        </div>
        <div style="display: flex; flex-direction: column; gap: 8px; margin-top: 6px;">
          ${findingsHtml}
        </div>
        ${res.brief.limitations && res.brief.limitations.length > 0 ? `<div style="font-size: 12px; color: var(--apple-orange-text); margin-top: 4px;"><strong>Limitations:</strong> ${escapeHtml(res.brief.limitations.join("; "))}</div>` : ""}
      </div>
    `;

    // Bind citations
    elements.generationResultContainer.querySelectorAll(".citation-pill").forEach((btn) => {
      btn.addEventListener("click", () => openSidePanel(btn.dataset.evidenceId));
    });
  } else if (status === "abstained") {
    elements.generationResultContainer.innerHTML = `
      <div class="generation-status-card abstained">
        <div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <strong>AI Safely Abstained</strong>
            ${revBadge}
          </div>
          <div style="font-size: 12px; margin-top: 4px; display: flex; align-items: center; gap: 6px;">
            <span>Runtime:</span>
            ${methodBadge}
          </div>
          <p style="margin-top: 4px;">${escapeHtml(res.brief ? res.brief.abstention_reason : "Insufficient longitudinal evidence to formulate a reliable pedagogical trajectory.")}</p>
        </div>
        <span class="badge badge-status-pending">Clean Abstention</span>
      </div>
    `;
  } else if (status === "validation_failed") {
    const errorList = (res.errors || []).map((e) => `<li>${escapeHtml(e)}</li>`).join("");
    elements.generationResultContainer.innerHTML = `
      <div class="generation-status-card validation_failed">
        <div>
          <strong>Deterministic Validation Rejected LLM Draft</strong>
          <div style="font-size: 12px;">Policy gate enforced; ungrounded or non-compliant output discarded.</div>
          <ul style="margin-top: 4px; padding-left: 18px; font-size: 12px;">
            ${errorList}
          </ul>
        </div>
        <span class="badge badge-status-rejected">Gated & Hidden</span>
      </div>
    `;
  } else {
    // inference_failed
    const errorList = (res.errors || []).map((e) => `<li>${escapeHtml(e)}</li>`).join("");
    elements.generationResultContainer.innerHTML = `
      <div class="generation-status-card inference_failed">
        <div>
          <strong>Inference Execution Failed</strong>
          <div style="font-size: 12px;">The runtime engine was unable to complete the request.</div>
          <ul style="margin-top: 4px; padding-left: 18px; font-size: 12px;">
            ${errorList}
          </ul>
        </div>
        <span class="badge badge-status-rejected">Inference Error</span>
      </div>
    `;
  }
}

async function handleReviewDecision(reviewId, status, teacherNotes) {
  try {
    await api.postReviewDecision(reviewId, status, teacherNotes);
    await loadReviewsView();
    await loadApprovedHandoverView();
  } catch (err) {
    alert(`Could not submit review decision: ${err.message}`);
  }
}

// ── View 3: Approved Handover View ───────────────────────────────────────────

async function loadApprovedHandoverView() {
  if (!state.activeLearnerId) return;

  try {
    const profile = await api.getApprovedHandover(state.activeLearnerId);
    const count = profile.accepted_pattern_count || 0;
    elements.handoverCountBadge.textContent = count;
    const sideApproved = document.getElementById("side-approved-count");
    if (sideApproved) sideApproved.textContent = count;

    if (count === 0) {
      elements.handoverList.innerHTML = `
        <div class="empty-state">
          <h3>No approved transition findings</h3>
          <p>This profile contains zero approved findings. Unreviewed, pending, or rejected findings remain strictly hidden until sovereign educator approval.</p>
        </div>
      `;
      return;
    }

    elements.handoverList.innerHTML = "";
    profile.patterns.forEach((p) => {
      const card = renderApprovedCard(p);
      elements.handoverList.appendChild(card);
    });
  } catch (err) {
    elements.handoverList.innerHTML = `
      <div class="empty-state" style="color: var(--danger);">
        <h3>Error loading approved handover</h3>
        <p>${escapeHtml(err.message)}</p>
      </div>
    `;
  }
}

function renderApprovedCard(p) {
  const card = document.createElement("div");
  card.className = "approved-card";

  const rev = p.review || {};
  const resolvedDate = rev.resolved_at
    ? new Date(rev.resolved_at).toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      })
    : "Verified";

  let citationsHtml = "None";
  if (p.supporting_evidence && p.supporting_evidence.length > 0) {
    citationsHtml = p.supporting_evidence
      .map((id) => `<button type="button" class="citation-pill" data-evidence-id="${escapeHtml(id)}">${escapeHtml(id.slice(0, 8))}…</button>`)
      .join(" ");
  }

  card.innerHTML = `
    <div class="approved-header">
      <div style="display: flex; align-items: center; gap: 8px;">
        <span class="tag tag-stage">${escapeHtml(p.pattern_type.toUpperCase())}</span>
        <span class="badge badge-status-accepted">✓ APPROVED PROFILE</span>
      </div>
      <div class="hash-badge" title="Cryptographically verified SHA-256 snapshot of approved pattern">
        SHA-256: ${escapeHtml(rev.approved_content_hash ? rev.approved_content_hash.slice(0, 16) : "VERIFIED")}…
      </div>
    </div>
    <div class="approved-title">
      ${escapeHtml(p.summary)}
    </div>
    <div style="font-size: 12px; color: var(--text-secondary);">
      <strong>Supporting Citations:</strong> ${citationsHtml}
    </div>
    <div class="approved-details">
      <div><strong>Teacher Decision:</strong> Approved by <code>${escapeHtml(rev.reviewer_id || "Teacher")}</code> on ${resolvedDate}</div>
      ${rev.teacher_notes ? `<div><strong>Pedagogical Notes:</strong> <em>"${escapeHtml(rev.teacher_notes)}"</em></div>` : ""}
    </div>
  `;

  // Bind citations
  card.querySelectorAll(".citation-pill").forEach((btn) => {
    btn.addEventListener("click", () => openSidePanel(btn.dataset.evidenceId));
  });

  return card;
}

// ── Side Panel (Citation Drawer) ─────────────────────────────────────────────

async function openSidePanel(evidenceId) {
  elements.sidePanel.classList.add("open");
  elements.sidePanelOverlay.classList.add("open");
  elements.sidePanelContent.innerHTML = `<div class="empty-state">Loading citation record ${escapeHtml(evidenceId)}...</div>`;

  try {
    const r = await api.getEvidenceDetail(evidenceId);
    renderSidePanelDetail(r);
  } catch (err) {
    elements.sidePanelContent.innerHTML = `
      <div class="empty-state" style="color: var(--danger);">
        <h3>Citation Lookup Failed</h3>
        <p>${escapeHtml(err.message)}</p>
      </div>
    `;
  }
}

function renderSidePanelDetail(r) {
  let stageText = r.assessment_stage ? r.assessment_stage.toUpperCase() : "N/A";
  let payloadPretty = JSON.stringify(r.content, null, 2);

  elements.sidePanelContent.innerHTML = `
    <div class="record-field-group">
      <label>Evidence ID</label>
      <div class="field-val" style="font-family: var(--font-mono); font-weight: 600;">${escapeHtml(r.evidence_id)}</div>
    </div>

    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
      <div class="record-field-group">
        <label>Learner ID</label>
        <div class="field-val">${escapeHtml(r.learner_id)}</div>
      </div>
      <div class="record-field-group">
        <label>Evidence Type</label>
        <div class="field-val">${escapeHtml(r.evidence_type.toUpperCase())}</div>
      </div>
    </div>

    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
      <div class="record-field-group">
        <label>Academic Year & Term</label>
        <div class="field-val">${r.academic_year} · Term ${r.term}</div>
      </div>
      <div class="record-field-group">
        <label>Subject</label>
        <div class="field-val">${escapeHtml(r.subject || "General / None")}</div>
      </div>
    </div>

    ${r.evidence_type === "assessment" ? `
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
      <div class="record-field-group">
        <label>Assessment Stage</label>
        <div class="field-val"><strong>${escapeHtml(stageText)}</strong></div>
      </div>
      <div class="record-field-group">
        <label>Comparison Authorized</label>
        <div class="field-val">${r.comparison_authorized ? "✓ Yes" : "✕ No"}</div>
      </div>
    </div>
    ` : ""}

    <div class="record-field-group">
      <label>Observed Timestamp (Timezone-Aware UTC)</label>
      <div class="field-val">${new Date(r.observed_at).toUTCString()}</div>
    </div>

    <div class="record-field-group">
      <label>Recorded In ALLPS</label>
      <div class="field-val">${new Date(r.recorded_at).toUTCString()}</div>
    </div>

    <div class="record-field-group">
      <label>Provenance & Attribution</label>
      <div class="field-val">
        Author: <strong>${escapeHtml(r.source_reference)}</strong> (${escapeHtml(r.source_type)})<br>
        Originating System: <code>${escapeHtml(r.source_system)}</code> (${escapeHtml(r.ingestion_method)})<br>
        ${r.source_event_id ? `Source Event ID: <code>${escapeHtml(r.source_event_id)}</code>` : ""}
      </div>
    </div>

    <div class="record-field-group">
      <label>Stored Original Payload</label>
      <pre class="field-val" style="font-family: var(--font-mono); font-size: 12px; white-space: pre-wrap;">${escapeHtml(payloadPretty)}</pre>
    </div>
  `;
}

function closeSidePanel() {
  elements.sidePanel.classList.remove("open");
  elements.sidePanelOverlay.classList.remove("open");
}

// ── Observation Form & Preview Modal ────────────────────────────────────────

function openObservationDialog() {
  elements.obsErrorAlert.style.display = "none";
  elements.obsErrorAlert.textContent = "";

  // Populate from draft state
  elements.obsYear.value = state.observationDraft.academic_year;
  elements.obsTerm.value = state.observationDraft.term;
  elements.obsSubject.value = state.observationDraft.subject;
  elements.obsSourceRef.value = state.observationDraft.source_reference;
  elements.obsDatetime.value = state.observationDraft.event_datetime;
  elements.obsText.value = state.observationDraft.observation;
  elements.obsContext.value = state.observationDraft.context;

  elements.observationDialog.showModal();
}

function handleObservationPreview() {
  // Sync draft from inputs
  state.observationDraft.academic_year = parseInt(elements.obsYear.value, 10);
  state.observationDraft.term = parseInt(elements.obsTerm.value, 10);
  state.observationDraft.subject = elements.obsSubject.value;
  state.observationDraft.source_reference = elements.obsSourceRef.value.trim();
  state.observationDraft.event_datetime = elements.obsDatetime.value;
  state.observationDraft.observation = elements.obsText.value.trim();
  state.observationDraft.context = elements.obsContext.value.trim();

  // Validate required fields
  if (!state.observationDraft.observation) {
    showObsError("Observation text is required.");
    return;
  }
  if (!state.observationDraft.source_reference) {
    showObsError("Attributed teacher name/reference is required.");
    return;
  }
  if (!state.observationDraft.event_datetime) {
    showObsError("Observation date/time is required.");
    return;
  }

  elements.obsErrorAlert.style.display = "none";

  // Build preview breakdown
  elements.previewContent.innerHTML = `
    <div class="record-field-group">
      <label>Learner</label>
      <div class="field-val"><strong>${escapeHtml(state.activeLearnerId)}</strong></div>
    </div>
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
      <div class="record-field-group">
        <label>Academic Time</label>
        <div class="field-val">Year ${state.observationDraft.academic_year} · Term ${state.observationDraft.term}</div>
      </div>
      <div class="record-field-group">
        <label>Subject</label>
        <div class="field-val">${escapeHtml(state.observationDraft.subject || "General / None")}</div>
      </div>
    </div>
    <div class="record-field-group">
      <label>Observed Date & Time (Event Time)</label>
      <div class="field-val">${escapeHtml(state.observationDraft.event_datetime)}</div>
    </div>
    <div class="record-field-group">
      <label>Source Reference & Channel</label>
      <div class="field-val">${escapeHtml(state.observationDraft.source_reference)} (Teacher Observation via Web Form)</div>
    </div>
    <div class="record-field-group">
      <label>Factual Observation</label>
      <div class="field-val">${escapeHtml(state.observationDraft.observation)}</div>
    </div>
    ${state.observationDraft.context ? `
    <div class="record-field-group">
      <label>Co-Occurring Context</label>
      <div class="field-val">${escapeHtml(state.observationDraft.context)}</div>
    </div>
    ` : ""}
    <div class="record-field-group">
      <label>Retry Idempotency Source Event ID</label>
      <div class="field-val" style="font-family: var(--font-mono); font-size: 11px;">${escapeHtml(state.observationDraft.source_event_id)}</div>
    </div>
  `;

  elements.observationDialog.close();
  elements.previewDialog.showModal();
}

async function handleSaveObservation() {
  elements.btnConfirmSaveObservation.disabled = true;
  elements.btnConfirmSaveObservation.textContent = "Saving...";

  const payload = {
    event_datetime: new Date(state.observationDraft.event_datetime).toISOString(),
    academic_year: state.observationDraft.academic_year,
    term: state.observationDraft.term,
    subject: state.observationDraft.subject || null,
    observation: state.observationDraft.observation,
    context: state.observationDraft.context || null,
    source_reference: state.observationDraft.source_reference,
    source_event_id: state.observationDraft.source_event_id,
  };

  try {
    await api.postObservation(state.activeLearnerId, payload);

    elements.previewDialog.close();

    // Reset draft with new UUID for next observation
    state.observationDraft.source_event_id = crypto.randomUUID ? crypto.randomUUID() : `draft-${Date.now()}`;
    state.observationDraft.observation = "";
    state.observationDraft.context = "";

    await loadEvidenceView();
  } catch (err) {
    // Preserve values! Reopen form with error message
    elements.previewDialog.close();
    elements.observationDialog.showModal();
    showObsError(`Save failed: ${err.message}`);
  } finally {
    elements.btnConfirmSaveObservation.disabled = false;
    elements.btnConfirmSaveObservation.textContent = "Confirm & Save Observation";
  }
}

function showObsError(msg) {
  elements.obsErrorAlert.style.display = "block";
  elements.obsErrorAlert.textContent = msg;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// Launch on DOM ready
document.addEventListener("DOMContentLoaded", init);
