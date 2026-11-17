"use strict";

/**
 * ALLPS Teacher Workspace — Authenticated Preview-Aligned Client
 *
 * Connects directly to the ALLPS FastAPI backend:
 * - Shows a dedicated sign-in page when signed out (workspace remains hidden)
 * - Derives teacher identity, roles, classes, learners, readiness, releases,
 *   candidate findings, and post-release updates from the authenticated backend
 * - Keeps learner selection scoped to the selected class via /api/learners?class_id=...
 * - Enforces role-appropriate UI for class teachers vs. subject teachers
 */

// ── API Client ───────────────────────────────────────────────────────────────

class ApiClient {
  constructor(baseUrl = "/api", onUnauthorized = null) {
    this.baseUrl = baseUrl;
    this.onUnauthorized = onUnauthorized;
  }

  async _request(path, options = {}) {
    const url = `${this.baseUrl}${path}`;
    const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
    const headers = isFormData
      ? { ...(options.headers || {}) }
      : { "Content-Type": "application/json", ...(options.headers || {}) };
    let response;
    try {
      response = await fetch(url, {
        credentials: "same-origin",
        ...options,
        headers,
      });
    } catch (networkErr) {
      const err = new Error(
        "Unable to reach the ALLPS backend server. Check that the server is running and try again."
      );
      err.isNetworkError = true;
      err.cause = networkErr;
      throw err;
    }

    const contentType = response.headers.get("content-type") || "";
    let data;
    if (contentType.includes("application/json")) {
      data = await response.json();
    } else {
      data = await response.text();
    }

    if (!response.ok) {
      let errorMsg = `HTTP ${response.status}: ${response.statusText}`;
      if (data && data.detail !== undefined) {
        if (typeof data.detail === "string") {
          errorMsg = data.detail;
        } else if (data.detail && typeof data.detail.message === "string") {
          errorMsg = data.detail.message;
        } else {
          errorMsg = JSON.stringify(data.detail);
        }
      }
      const error = new Error(errorMsg);
      error.status = response.status;
      error.data = data;
      if (response.status === 401 && path !== "/auth/login" && typeof this.onUnauthorized === "function") {
        this.onUnauthorized(errorMsg);
      }
      throw error;
    }

    return data;
  }

  async getConfig() {
    return this._request("/config");
  }

  async login(teacherId, pin) {
    return this._request("/auth/login", {
      method: "POST",
      body: JSON.stringify({ teacher_id: teacherId, pin }),
    });
  }

  async logout() {
    return this._request("/auth/logout", { method: "POST" });
  }

  async getWorkspace() {
    return this._request("/workspace");
  }

  async getLearners(classId = null) {
    const qs = classId ? `?class_id=${encodeURIComponent(classId)}` : "";
    return this._request(`/learners${qs}`);
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

  async importClassFile(classId, formData) {
    return this._request(`/classes/${encodeURIComponent(classId)}/import`, {
      method: "POST",
      body: formData,
    });
  }

  async getLearnerAvailability(learnerId) {
    return this._request(`/learners/${encodeURIComponent(learnerId)}/availability`);
  }

  async generateHandover(learnerId, subject = null, mode = "auto") {
    return this._request(`/learners/${encodeURIComponent(learnerId)}/generate`, {
      method: "POST",
      body: JSON.stringify({ subject, mode }),
    });
  }

  async getLatestBrief(learnerId) {
    return this._request(`/learners/${encodeURIComponent(learnerId)}/brief`);
  }

  async getReviews(learnerId) {
    return this._request(`/learners/${encodeURIComponent(learnerId)}/reviews`);
  }

  async postReviewDecision(
    reviewId,
    status,
    teacherNotes = null,
    expectedRevision = 0,
    isCorrection = false
  ) {
    return this._request(`/reviews/${encodeURIComponent(reviewId)}/decision`, {
      method: "POST",
      body: JSON.stringify({
        status,
        teacher_notes: teacherNotes,
        expected_revision: expectedRevision,
        is_correction: isCorrection,
      }),
    });
  }

  async getApprovedHandover(learnerId) {
    return this._request(`/learners/${encodeURIComponent(learnerId)}/handover`);
  }

  async getClassReadiness(classId) {
    return this._request(`/classes/${encodeURIComponent(classId)}/readiness`);
  }

  async updateSectionReview(classId, learnerId, scope, payload) {
    return this._request(
      `/classes/${encodeURIComponent(classId)}/learners/${encodeURIComponent(learnerId)}/sections/${encodeURIComponent(scope)}`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
  }

  async releaseClass(classId, notes = null) {
    return this._request(`/classes/${encodeURIComponent(classId)}/release`, {
      method: "POST",
      body: JSON.stringify({ notes }),
    });
  }

  async getPublishedHandover(learnerId) {
    return this._request(`/learners/${encodeURIComponent(learnerId)}/published`);
  }

  async recordReportView(releaseId, learnerId, scope = null) {
    return this._request(
      `/releases/${encodeURIComponent(releaseId)}/learners/${encodeURIComponent(learnerId)}/view`,
      {
        method: "POST",
        body: JSON.stringify({ scope }),
      }
    );
  }

  async acknowledgeReport(releaseId, learnerId) {
    return this._request(
      `/releases/${encodeURIComponent(releaseId)}/learners/${encodeURIComponent(learnerId)}/acknowledge`,
      { method: "POST" }
    );
  }

  async addSubjectResponse(releaseId, learnerId, payload) {
    return this._request(
      `/releases/${encodeURIComponent(releaseId)}/learners/${encodeURIComponent(learnerId)}/responses`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
  }

  async getClassChanges(classId) {
    return this._request(`/classes/${encodeURIComponent(classId)}/changes`);
  }

  async markChangeReviewed(classId, changeId, notes = null) {
    return this._request(
      `/classes/${encodeURIComponent(classId)}/changes/${encodeURIComponent(changeId)}/review`,
      {
        method: "POST",
        body: JSON.stringify({ notes }),
      }
    );
  }

  async getDbStatus(recentLimit = 5) {
    return this._request(`/db/status?recent_limit=${encodeURIComponent(recentLimit)}`);
  }

  async reseedDatabase(mode = "merge") {
    return this._request("/db/reseed", {
      method: "POST",
      body: JSON.stringify({ mode }),
    });
  }
}

// ── State & Elements ─────────────────────────────────────────────────────────

const state = {
  config: null,
  currentTeacher: null,
  workspace: null,
  activeClassId: null,
  learners: [],
  activeLearnerId: null,
  classReadiness: null,
  classChanges: [],
  publishedByLearner: {},
  evidenceByLearner: {},
  availabilityByLearner: {},
  reviewsByLearner: {},
  briefByLearner: {},
  generationResultByLearner: {},
  recordedViews: new Set(),
  dbStatus: null,
  isGenerating: false,
  isDbBusy: false,
  isLoggingIn: false,
  isLoggingOut: false,
  classSwitchSeq: 0,
  recordsSeq: 0,
  learnerSeq: 0,
  observationDraft: makeEmptyObservationDraft(),
};

function makeEmptyObservationDraft(sourceRef = "") {
  return {
    source_event_id: crypto.randomUUID ? crypto.randomUUID() : `draft-${Date.now()}`,
    academic_year: 2025,
    term: 3,
    subject: "",
    source_reference: sourceRef,
    observation: "",
    context: "",
    event_datetime: new Date().toISOString().slice(0, 16),
  };
}

const el = {
  bootLoading: document.getElementById("boot-loading"),
  signinView: document.getElementById("signin-view"),
  workspaceShell: document.getElementById("workspace-shell"),

  // Sign-in form
  signinFictionalNotice: document.getElementById("signin-fictional-notice"),
  loginForm: document.getElementById("login-form"),
  loginTeacherId: document.getElementById("login-teacher-id"),
  loginPin: document.getElementById("current-password"),
  btnTogglePin: document.getElementById("btn-toggle-pin"),
  btnSubmitLogin: document.getElementById("btn-submit-login"),
  loginErrorAlert: document.getElementById("login-error-alert"),
  loginErrorText: document.getElementById("login-error-text"),
  btnRetryConnection: document.getElementById("btn-retry-connection"),
  loginDemoPanel: document.getElementById("login-demo-panel"),
  loginTeacherPills: document.getElementById("login-teacher-pills"),

  // Sidebar & Topbar
  sidebarToggle: document.getElementById("sidebar-toggle"),
  navOverlay: document.getElementById("nav-overlay"),
  teacherInitials: document.getElementById("teacher-initials"),
  teacherName: document.getElementById("teacher-name"),
  teacherRole: document.getElementById("teacher-role"),
  btnAuthAction: document.getElementById("btn-auth-action"),
  reviewCount: document.getElementById("review-count"),
  updateCount: document.getElementById("update-count"),
  breadcrumb: document.getElementById("breadcrumb"),
  activeTermPill: document.getElementById("active-term-pill"),
  classSelect: document.getElementById("class-select"),
  learnerSelect: document.getElementById("learner-select"),

  // Demo banner & feedback
  workspaceDemoBanner: document.getElementById("workspace-demo-banner"),
  workspaceDemoTag: document.getElementById("workspace-demo-tag"),
  workspaceDemoCopy: document.getElementById("workspace-demo-copy"),
  btnRefreshData: document.getElementById("btn-refresh-data"),
  btnSeedMerge: document.getElementById("btn-seed-merge"),
  btnOpenResetDialog: document.getElementById("btn-open-reset-dialog"),
  resetDbDialog: document.getElementById("reset-db-dialog"),
  resetDialogDbName: document.getElementById("reset-dialog-db-name"),
  footerProvenanceNote: document.getElementById("footer-provenance-note"),
  workspaceStatusBanner: document.getElementById("workspace-status-banner"),
  workspaceStatusText: document.getElementById("workspace-status-text"),
  btnDismissWorkspaceStatus: document.getElementById("btn-dismiss-workspace-status"),

  // Main mount & dialogs
  main: document.getElementById("main"),
  releaseDialog: document.getElementById("release-dialog"),
  releaseSummary: document.getElementById("release-summary"),
  releaseNotesInput: document.getElementById("release-notes-input"),
  cancelRelease: document.getElementById("cancel-release"),
  confirmRelease: document.getElementById("confirm-release"),
  detailDialog: document.getElementById("detail-dialog"),
  detailContent: document.getElementById("detail-content"),
  toast: document.getElementById("toast"),

  // Observation modals
  observationDialog: document.getElementById("observation-dialog"),
  observationForm: document.getElementById("observation-form"),
  btnCloseObservation: document.getElementById("btn-close-observation"),
  btnCancelObservation: document.getElementById("btn-cancel-observation"),
  btnPreviewObservation: document.getElementById("btn-preview-observation"),
  previewDialog: document.getElementById("preview-dialog"),
  previewContent: document.getElementById("preview-content"),
  btnBackToEditObservation: document.getElementById("btn-back-to-edit-observation"),
  btnConfirmSaveObservation: document.getElementById("btn-confirm-save-observation"),
  obsYear: document.getElementById("obs-year"),
  obsTerm: document.getElementById("obs-term"),
  obsSubject: document.getElementById("obs-subject"),
  obsSourceRef: document.getElementById("obs-source-ref"),
  obsDatetime: document.getElementById("obs-datetime"),
  obsText: document.getElementById("obs-text"),
  obsContext: document.getElementById("obs-context"),
  obsErrorAlert: document.getElementById("obs-error-alert"),

  // Import report modal
  importDialog: document.getElementById("import-dialog"),
  importForm: document.getElementById("import-form"),
  btnCloseImport: document.getElementById("btn-close-import"),
  btnCancelImport: document.getElementById("btn-cancel-import"),
  btnSubmitImport: document.getElementById("btn-submit-import"),
  importErrorAlert: document.getElementById("import-error-alert"),
  importResultSummary: document.getElementById("import-result-summary"),
  importClassContext: document.getElementById("import-class-context"),
  importFile: document.getElementById("import-file"),
  importSourceSystem: document.getElementById("import-source-system"),
  importMaxScore: document.getElementById("import-max-score"),
  importYear: document.getElementById("import-year"),
  importTerm: document.getElementById("import-term"),
  importObservedAt: document.getElementById("import-observed-at"),
  importGrade: document.getElementById("import-grade"),
  importStage: document.getElementById("import-stage"),
  importFormName: document.getElementById("import-form-name"),
  importFormVersion: document.getElementById("import-form-version"),
  importLanguage: document.getElementById("import-language"),
  importNotes: document.getElementById("import-notes"),
  importComparisonAuthorized: document.getElementById("import-comparison-authorized"),
};

const api = new ApiClient("/api", handleSessionExpired);

// ── Formatting & Security Helpers ────────────────────────────────────────────

function html(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function initialsOf(name) {
  const parts = String(name || "")
    .replace(/^(Ms\.|Mr\.|Mrs\.|Dr\.)\s+/i, "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function formatStamp(value) {
  if (!value) return "";
  try {
    return new Intl.DateTimeFormat("en-KE", {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }).format(new Date(value));
  } catch {
    return String(value);
  }
}

function formatDate(value) {
  if (!value) return "";
  try {
    return new Intl.DateTimeFormat("en-KE", {
      day: "numeric",
      month: "short",
      year: "numeric",
    }).format(new Date(value));
  } catch {
    return String(value);
  }
}

function toast(message) {
  if (!el.toast) return;
  el.toast.textContent = message;
  el.toast.classList.add("visible");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.toast.classList.remove("visible"), 4200);
}

function showWorkspaceStatus(type, message) {
  if (!el.workspaceStatusBanner || !el.workspaceStatusText) return;
  el.workspaceStatusBanner.className = `feedback-banner ${type}`;
  el.workspaceStatusText.textContent = message;
  el.workspaceStatusBanner.hidden = false;
}

function clearWorkspaceStatus() {
  if (!el.workspaceStatusBanner || !el.workspaceStatusText) return;
  el.workspaceStatusBanner.hidden = true;
  el.workspaceStatusText.textContent = "";
}

const labelPattern = /\b(?:lazy|stupid|dumb|hopeless|adhd|autistic|autism|dyslexic|dyslexia|bipolar|uncooperative|defiant|troublemaker|retarded|slow[\s_-]+learner|problem[\s_-]+child|conduct[\s_-]+disorder)\b/i;

function validateSafeText(text, errorEl, required = true) {
  if (required && text.length < 3) {
    if (errorEl) errorEl.textContent = "Please add a short factual note (at least 3 characters).";
    return false;
  }
  if (labelPattern.test(text)) {
    if (errorEl) errorEl.textContent = "Describe what was observed factually without diagnostic or deficit labels.";
    return false;
  }
  if (errorEl) errorEl.textContent = "";
  return true;
}

// ── Role & Class Helpers (Authoritative Backend State) ───────────────────────

function getClasses() {
  return (state.workspace && state.workspace.classes) || [];
}

function getUniqueClasses() {
  const seen = new Map();
  for (const c of getClasses()) {
    if (!seen.has(c.class_id)) {
      seen.set(c.class_id, c);
    }
  }
  return Array.from(seen.values());
}

function getActiveClassAssignments() {
  if (!state.activeClassId) return [];
  return getClasses().filter((c) => c.class_id === state.activeClassId);
}

function getActiveClass() {
  return getActiveClassAssignments()[0] || null;
}

function isClassTeacherInActiveClass() {
  return getActiveClassAssignments().some((c) => c.role === "class_teacher");
}

function getAllowedSubjectsInActiveClass() {
  return Array.from(
    new Set(
      getActiveClassAssignments()
        .map((c) => c.subject)
        .filter(Boolean)
    )
  );
}

function getVisibleScopesForActiveClass() {
  if (isClassTeacherInActiveClass()) {
    if (state.classReadiness && Array.isArray(state.classReadiness.required_scopes)) {
      return state.classReadiness.required_scopes;
    }
    return ["student", "Mathematics", "English", "Science"];
  }
  return ["student", ...getAllowedSubjectsInActiveClass()];
}

function scopeTitle(scope) {
  return scope === "student" ? "Student Review" : scope;
}

function learnerObj(learnerId) {
  return state.learners.find((l) => l.learner_id === learnerId) || null;
}

function reviewStateLabel(val) {
  return (
    {
      ready_for_release: "Ready",
      reviewed_incomplete: "Reviewed — incomplete",
      needs_clarification: "Needs clarification",
      not_reviewed: "Not reviewed",
    }[val] || val
  );
}

function reviewStateBadge(val) {
  const color =
    val === "ready_for_release"
      ? "green"
      : val === "reviewed_incomplete" || val === "needs_clarification"
      ? "amber"
      : "";
  return `<span class="badge ${color}">${html(reviewStateLabel(val))}</span>`;
}

function availabilityBadge(avail) {
  if (!avail) return "";
  const st = avail.status;
  const color = st === "sufficient" ? "green" : st === "missing_result" || st === "source_trace_not_found" ? "red" : "amber";
  return `<span class="badge ${color}">${html(avail.label || st)}</span>`;
}

function typeLabel(type) {
  return (
    {
      assessment: "Assessments",
      attendance: "Attendance",
      observation: "Observations",
      learner_reflection: "Learner reflections",
      project: "Projects",
    }[type] || type
  );
}

function recordIcon(type) {
  return (
    {
      assessment: "▤",
      attendance: "◷",
      observation: "✎",
      learner_reflection: "◌",
      project: "◇",
    }[type] || "▤"
  );
}

function evidenceSummaryText(e) {
  const c = e.content || {};
  if (e.evidence_type === "assessment") {
    if (e.is_missing_outcome || c.status) {
      const st = String(c.status || "unavailable").replaceAll("_", " ");
      return c.reason ? `${st} — ${c.reason}` : st;
    }
    if (c.score !== undefined && c.score !== null) {
      return `${c.score} / ${c.max_score} marks${e.measured_skill ? ` (${e.measured_skill})` : ""}`;
    }
    return c.level || c.ordinal_level || "Assessment record";
  }
  if (e.evidence_type === "attendance" && c.days_present !== undefined) {
    const pct = c.rate !== undefined ? ` (${Math.round(c.rate * 100)}%)` : "";
    return `Attendance: ${c.days_present} of ${c.days_total} days${pct}`;
  }
  return c.note || c.observation || c.reflection || c.summary || c.project_name || "Source record available";
}

function learnerLink(learnerId, scope = "student", view = null) {
  const base = `#learner/${encodeURIComponent(learnerId)}/${encodeURIComponent(scope)}`;
  return view ? `${base}?view=${encodeURIComponent(view)}` : base;
}

// ── Sign-In, Sign-Out & Session Lifecycle ────────────────────────────────────

function clearWorkspaceStateAndDom() {
  state.currentTeacher = null;
  state.workspace = null;
  state.activeClassId = null;
  state.learners = [];
  state.activeLearnerId = null;
  state.classReadiness = null;
  state.classChanges = [];
  state.publishedByLearner = {};
  state.evidenceByLearner = {};
  state.availabilityByLearner = {};
  state.reviewsByLearner = {};
  state.briefByLearner = {};
  state.generationResultByLearner = {};
  state.recordedViews.clear();
  state.dbStatus = null;
  state.classSwitchSeq += 1;
  state.recordsSeq += 1;
  state.learnerSeq += 1;
  state.observationDraft = makeEmptyObservationDraft("");

  if (el.main) {
    el.main.innerHTML = `<div id="teacher-workspace-strip" hidden></div><div id="view-class-handover"></div>`;
  }
  if (el.classSelect) el.classSelect.innerHTML = `<option value="">Sign in to view classes</option>`;
  if (el.learnerSelect) el.learnerSelect.innerHTML = `<option value="">Sign in to view learners</option>`;
  if (el.teacherName) el.teacherName.textContent = "Educator";
  if (el.teacherRole) el.teacherRole.textContent = "Signed out";
  if (el.teacherInitials) el.teacherInitials.textContent = "?";
  if (el.reviewCount) el.reviewCount.textContent = "0";
  if (el.updateCount) el.updateCount.textContent = "0";

  clearWorkspaceStatus();
  if (el.toast) {
    el.toast.classList.remove("visible");
    clearTimeout(toast.timer);
  }
  [el.releaseDialog, el.detailDialog, el.observationDialog, el.previewDialog, el.resetDbDialog].forEach(
    (d) => {
      if (d && d.open) d.close();
    }
  );
  toggleNavigation(false);
}

function showSignInPage(errorMessage = null, { showRetry = false } = {}) {
  if (el.bootLoading) el.bootLoading.hidden = true;
  if (el.workspaceShell) el.workspaceShell.hidden = true;
  if (el.signinView) el.signinView.hidden = false;

  const isSynthetic = state.config ? Boolean(state.config.is_synthetic_demonstration) : true;
  if (el.signinFictionalNotice) {
    el.signinFictionalNotice.hidden = !isSynthetic;
  }

  renderDemoTeacherCards();

  if (errorMessage) {
    showLoginError(errorMessage, { showRetry });
  } else {
    clearLoginError();
  }

  if (el.loginPin) {
    el.loginPin.value = "";
    el.loginPin.type = "password";
  }
  if (el.btnTogglePin) {
    el.btnTogglePin.setAttribute("aria-pressed", "false");
    el.btnTogglePin.setAttribute("aria-label", "Show PIN or password");
    el.btnTogglePin.textContent = "Show";
  }
}

function showLoginError(message, { showRetry = false } = {}) {
  if (!el.loginErrorAlert || !el.loginErrorText) return;
  el.loginErrorText.textContent = message;
  el.loginErrorAlert.hidden = false;
  if (el.btnRetryConnection) {
    el.btnRetryConnection.hidden = !showRetry;
  }
}

function clearLoginError() {
  if (!el.loginErrorAlert || !el.loginErrorText) return;
  el.loginErrorAlert.hidden = true;
  el.loginErrorText.textContent = "";
  if (el.btnRetryConnection) {
    el.btnRetryConnection.hidden = true;
  }
}

function renderDemoTeacherCards() {
  if (!el.loginDemoPanel || !el.loginTeacherPills) return;
  const cfg = state.config;
  const showDemo = Boolean(cfg && cfg.show_demo_credentials && !cfg.hosted);
  const teachers = (cfg && cfg.available_teachers) || [];

  if (!showDemo || teachers.length === 0) {
    el.loginDemoPanel.hidden = true;
    el.loginTeacherPills.innerHTML = "";
    return;
  }

  el.loginDemoPanel.hidden = false;
  el.loginTeacherPills.innerHTML = "";
  const currentId = el.loginTeacherId ? el.loginTeacherId.value.trim() : "";

  teachers.forEach((t) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `demo-teacher-card${currentId === t.teacher_id ? " active" : ""}`;
    btn.dataset.teacherId = t.teacher_id;

    const pinLine = t.demo_pin ? `<span>PIN: ${html(t.demo_pin)}</span>` : "";
    btn.innerHTML = `
      <div>
        <strong>${html(t.display_name)}</strong>
        <small>${html(t.role_summary || "Educator")}</small>
      </div>
      <div class="demo-teacher-creds">
        <span>${html(t.teacher_id)}</span>
        ${pinLine}
      </div>
    `;

    btn.addEventListener("click", () => {
      if (el.loginTeacherId) el.loginTeacherId.value = t.teacher_id;
      clearLoginError();
      el.loginTeacherPills.querySelectorAll(".demo-teacher-card").forEach((card) => {
        card.classList.toggle("active", card.dataset.teacherId === t.teacher_id);
      });
      if (el.loginPin) el.loginPin.focus();
    });
    el.loginTeacherPills.appendChild(btn);
  });
}

function handleTogglePinVisibility() {
  if (!el.loginPin || !el.btnTogglePin) return;
  const isHidden = el.loginPin.type === "password";
  el.loginPin.type = isHidden ? "text" : "password";
  el.btnTogglePin.setAttribute("aria-pressed", isHidden ? "true" : "false");
  el.btnTogglePin.setAttribute("aria-label", isHidden ? "Hide PIN or password" : "Show PIN or password");
  el.btnTogglePin.textContent = isHidden ? "Hide" : "Show";
}

async function handleLoginSubmit(event) {
  event.preventDefault();
  if (state.isLoggingIn) return;

  const teacherId = el.loginTeacherId ? el.loginTeacherId.value.trim() : "";
  const pin = el.loginPin ? el.loginPin.value : "";

  if (!teacherId) {
    showLoginError("Please enter your Teacher ID.");
    if (el.loginTeacherId) el.loginTeacherId.focus();
    return;
  }
  if (!pin || pin.length < 4) {
    showLoginError("PIN or password must be at least 4 characters.");
    if (el.loginPin) el.loginPin.focus();
    return;
  }

  clearLoginError();
  state.isLoggingIn = true;
  if (el.btnSubmitLogin) {
    el.btnSubmitLogin.disabled = true;
    el.btnSubmitLogin.textContent = "Signing in…";
  }

  try {
    await api.login(teacherId, pin);
    if (el.loginPin) el.loginPin.value = "";
    location.hash = "#home";
    await bootstrapAuthenticatedSession();
  } catch (err) {
    if (err.isNetworkError) {
      showLoginError(err.message, { showRetry: false });
    } else if (err.status === 401) {
      showLoginError("Incorrect Teacher ID or PIN/password. Check your credentials and try again.");
    } else {
      showLoginError(err.message || "Sign-in failed.");
    }
  } finally {
    state.isLoggingIn = false;
    if (el.btnSubmitLogin) {
      el.btnSubmitLogin.disabled = false;
      el.btnSubmitLogin.textContent = "Sign in";
    }
  }
}

async function handleLogout() {
  if (state.isLoggingOut) return;
  state.isLoggingOut = true;
  if (el.btnAuthAction) {
    el.btnAuthAction.disabled = true;
    el.btnAuthAction.textContent = "Signing out…";
  }

  try {
    await api.logout();
  } catch (err) {
    // If 401, handleSessionExpired already cleared workspace & returned to sign-in
    if (err.status !== 401 && state.currentTeacher) {
      const detail = err.isNetworkError
        ? "Unable to reach the server to end your session."
        : err.message || "Unexpected server error.";
      showWorkspaceStatus(
        "error",
        `Sign-out failed: ${detail} Your session cookie may still be active—try signing out again.`
      );
      toast("Sign-out failed — session may still be active.");
    }
    state.isLoggingOut = false;
    if (el.btnAuthAction) {
      el.btnAuthAction.disabled = false;
      el.btnAuthAction.textContent = "Sign out";
    }
    return;
  }

  state.isLoggingOut = false;
  if (el.btnAuthAction) {
    el.btnAuthAction.disabled = false;
    el.btnAuthAction.textContent = "Sign out";
  }

  clearWorkspaceStateAndDom();
  location.hash = "#home";
  try {
    state.config = await api.getConfig();
  } catch (cfgErr) {
    state.config = null;
    showSignInPage(cfgErr.message, { showRetry: true });
    return;
  }
  showSignInPage();
}

function handleSessionExpired() {
  if (!state.currentTeacher && el.workspaceShell?.hidden !== false) {
    return;
  }
  clearWorkspaceStateAndDom();
  showSignInPage("Your teacher session has expired or was signed out. Please sign in again.");
}

// ── Boot & Authenticated Data Loading ────────────────────────────────────────

async function init() {
  bindStaticEvents();
  await checkSessionAndStart();
}

async function checkSessionAndStart() {
  if (el.bootLoading) el.bootLoading.hidden = false;
  if (el.signinView) el.signinView.hidden = true;
  if (el.workspaceShell) el.workspaceShell.hidden = true;

  try {
    state.config = await api.getConfig();
  } catch (err) {
    state.config = null;
    clearWorkspaceStateAndDom();
    showSignInPage(err.message, { showRetry: true });
    return;
  }

  if (!state.config.authenticated_teacher) {
    clearWorkspaceStateAndDom();
    showSignInPage();
    return;
  }

  await enterWorkspaceFromConfig();
}

async function bootstrapAuthenticatedSession() {
  try {
    state.config = await api.getConfig();
  } catch (err) {
    clearWorkspaceStateAndDom();
    showSignInPage(err.message, { showRetry: true });
    return;
  }

  if (!state.config.authenticated_teacher) {
    clearWorkspaceStateAndDom();
    showSignInPage("Session could not be verified. Please sign in again.");
    return;
  }

  await enterWorkspaceFromConfig();
}

async function enterWorkspaceFromConfig() {
  state.currentTeacher = state.config.authenticated_teacher;
  state.workspace = state.config.workspace || (await api.getWorkspace());
  state.observationDraft = makeEmptyObservationDraft(state.currentTeacher.display_name || "");

  const uniqueClasses = getUniqueClasses();
  if (!state.activeClassId || !uniqueClasses.some((c) => c.class_id === state.activeClassId)) {
    state.activeClassId = uniqueClasses[0]?.class_id || null;
  }

  renderShellChrome();

  if (el.bootLoading) el.bootLoading.hidden = true;
  if (el.signinView) el.signinView.hidden = true;
  if (el.workspaceShell) el.workspaceShell.hidden = false;

  await loadActiveClassContext({ loadDb: Boolean(state.config.allow_demo_reset) });
  renderCurrentRoute(true);
}

function renderShellChrome() {
  const teacher = state.currentTeacher;
  if (el.teacherInitials) el.teacherInitials.textContent = initialsOf(teacher?.display_name);
  if (el.teacherName) el.teacherName.textContent = teacher?.display_name || teacher?.teacher_id || "Educator";

  const activeCls = getActiveClass();
  const roleSummary = activeCls
    ? activeCls.role_label
    : getClasses()[0]?.role_label || "Teacher";
  if (el.teacherRole) el.teacherRole.textContent = roleSummary;

  if (el.activeTermPill) {
    el.activeTermPill.textContent = activeCls
      ? `${activeCls.academic_year} · Term ${activeCls.term}`
      : "No class assigned";
  }

  // Class selector
  const uniqueClasses = getUniqueClasses();
  if (el.classSelect) {
    el.classSelect.innerHTML = "";
    if (uniqueClasses.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "No assigned classes";
      el.classSelect.appendChild(opt);
      el.classSelect.disabled = true;
    } else {
      el.classSelect.disabled = false;
      uniqueClasses.forEach((cls) => {
        const opt = document.createElement("option");
        opt.value = cls.class_id;
        opt.textContent = `${cls.display_name} (${cls.role_label})`;
        opt.selected = cls.class_id === state.activeClassId;
        el.classSelect.appendChild(opt);
      });
    }
  }

  // Demo / Hosted banner controls
  const isSynthetic = Boolean(state.config?.is_synthetic_demonstration);
  const allowReset = Boolean(state.config?.allow_demo_reset);
  if (el.workspaceDemoBanner) {
    el.workspaceDemoBanner.hidden = !isSynthetic && !allowReset;
  }
  if (el.workspaceDemoTag) {
    el.workspaceDemoTag.textContent = isSynthetic ? "FICTIONAL DEMO" : "LIVE WORKSPACE";
  }
  if (el.workspaceDemoCopy) {
    el.workspaceDemoCopy.textContent = isSynthetic
      ? "Fictional school, teacher, and learner data · Connected to the ALLPS backend."
      : "Connected to the ALLPS backend.";
  }
  if (el.btnSeedMerge) el.btnSeedMerge.hidden = !allowReset;
  if (el.btnOpenResetDialog) el.btnOpenResetDialog.hidden = !allowReset;
  if (el.footerProvenanceNote) {
    el.footerProvenanceNote.textContent = isSynthetic
      ? "Fictional school, teacher, and learner data · Authenticated session"
      : "Authenticated educator session";
  }
}

function renderLearnerSelector() {
  if (!el.learnerSelect) return;
  el.learnerSelect.innerHTML = "";
  if (state.learners.length === 0) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = state.activeClassId ? "No learners in this class" : "No learners";
    el.learnerSelect.appendChild(opt);
    el.learnerSelect.disabled = true;
    state.activeLearnerId = null;
    return;
  }

  el.learnerSelect.disabled = false;
  if (!state.activeLearnerId || !state.learners.some((l) => l.learner_id === state.activeLearnerId)) {
    state.activeLearnerId = state.learners[0].learner_id;
  }

  state.learners.forEach((l) => {
    const opt = document.createElement("option");
    opt.value = l.learner_id;
    opt.textContent = `${l.display_name} (${l.learner_id})`;
    opt.selected = l.learner_id === state.activeLearnerId;
    el.learnerSelect.appendChild(opt);
  });
}

async function loadActiveClassContext({ loadDb = false } = {}) {
  if (!state.currentTeacher) return false;

  const requestSeq = ++state.classSwitchSeq;
  const targetClassId = state.activeClassId;
  renderShellChrome();

  if (!targetClassId) {
    state.learners = [];
    state.classReadiness = null;
    state.classChanges = [];
    state.publishedByLearner = {};
    renderLearnerSelector();
    updateSidebarBadges();
    return true;
  }

  // Authoritatively fetch learners enrolled in targetClassId
  const learnersPromise = api.getLearners(targetClassId);
  const readinessPromise = isClassTeacherInActiveClass()
    ? api.getClassReadiness(targetClassId)
    : Promise.resolve(null);
  const changesPromise = api.getClassChanges(targetClassId);
  const dbPromise = loadDb ? api.getDbStatus(5).catch(() => null) : Promise.resolve(null);

  const [learners, readiness, changes, dbStatus] = await Promise.all([
    learnersPromise,
    readinessPromise,
    changesPromise,
    dbPromise,
  ]);

  // Discard stale responses if another class switch or sign-out occurred in flight
  if (
    requestSeq !== state.classSwitchSeq ||
    targetClassId !== state.activeClassId ||
    !state.currentTeacher
  ) {
    return false;
  }

  state.learners = learners;
  state.classReadiness = readiness;
  state.classChanges = changes || [];
  if (dbStatus) {
    state.dbStatus = dbStatus;
    if (el.resetDialogDbName) {
      el.resetDialogDbName.textContent = dbStatus.db_name || "the active database";
    }
  }

  renderLearnerSelector();

  // For subject teachers when a class has a published release, preload published summary per enrolled learner
  const activeCls = getActiveClass();
  const nextPublished = {};
  if (activeCls && !isClassTeacherInActiveClass() && activeCls.latest_release && learners.length > 0) {
    const pubResults = await Promise.all(
      learners.map((l) =>
        api
          .getPublishedHandover(l.learner_id)
          .then((data) => [l.learner_id, data])
          .catch(() => [l.learner_id, null])
      )
    );
    if (
      requestSeq !== state.classSwitchSeq ||
      targetClassId !== state.activeClassId ||
      !state.currentTeacher
    ) {
      return false;
    }
    pubResults.forEach(([lid, data]) => {
      if (data) nextPublished[lid] = data;
    });
  }
  state.publishedByLearner = nextPublished;

  updateSidebarBadges();
  return true;
}

function updateSidebarBadges() {
  if (el.reviewCount) {
    let pendingReviews = 0;
    if (isClassTeacherInActiveClass() && state.classReadiness) {
      for (const l of state.classReadiness.learners || []) {
        for (const sc of state.classReadiness.required_scopes || []) {
          const slot = l.slots[sc];
          if (slot && !["ready_for_release", "reviewed_incomplete"].includes(slot.review_state)) {
            pendingReviews += 1;
          }
        }
      }
    } else if (!isClassTeacherInActiveClass()) {
      const items = (state.workspace && state.workspace.needs_attention) || [];
      pendingReviews = items.filter(
        (i) => i.kind === "pending_acknowledgment" && (!state.activeClassId || i.class_id === state.activeClassId)
      ).length;
    }
    el.reviewCount.textContent = String(pendingReviews);
  }

  if (el.updateCount) {
    const activeChanges = (state.classChanges || []).filter((c) => !c.superseded_by_release_id);
    el.updateCount.textContent = String(activeChanges.length);
  }
}

async function refreshWorkspaceFromServer({ showToast = false } = {}) {
  if (!state.currentTeacher) return;
  try {
    state.workspace = await api.getWorkspace();
    const committed = await loadActiveClassContext({ loadDb: Boolean(state.config?.allow_demo_reset) });
    if (!committed) return;
    state.evidenceByLearner = {};
    state.availabilityByLearner = {};
    state.reviewsByLearner = {};
    state.briefByLearner = {};
    renderCurrentRoute(false);
    if (showToast) toast("Workspace refreshed from database.");
  } catch (err) {
    showWorkspaceStatus("error", err.message);
  }
}

// ── Routing & Navigation ─────────────────────────────────────────────────────

function route() {
  const [path, query = ""] = location.hash.slice(1).split("?");
  return {
    parts: (path || "home").split("/").map(decodeURIComponent),
    query: new URLSearchParams(query),
  };
}

function navigate(hash) {
  if (location.hash === hash) renderCurrentRoute(true);
  else location.hash = hash;
}

function toggleNavigation(open) {
  document.body.classList.toggle("nav-open", open);
  if (el.navOverlay) el.navOverlay.hidden = !open;
  if (el.sidebarToggle) {
    el.sidebarToggle.setAttribute("aria-expanded", String(open));
    el.sidebarToggle.setAttribute("aria-label", open ? "Collapse navigation" : "Expand navigation");
  }
}

function renderCurrentRoute(recordView = false) {
  if (!state.currentTeacher) return;
  let current;
  try {
    current = route();
  } catch {
    location.hash = "#home";
    return;
  }

  const [page, id, scope] = current.parts;
  const activeNav = page === "learner" ? "class" : page;
  document.querySelectorAll("[data-nav]").forEach((a) => {
    const match = a.dataset.nav === activeNav;
    a.classList.toggle("active", match);
    if (match) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });

  const activeCls = getActiveClass();
  const titleMap = {
    home: "Home",
    class: activeCls ? `My classes / ${activeCls.display_name}` : "My classes",
    queue: "Reviews",
    records: "Records",
    updates: "Updates",
    learner: "My classes / Learner review",
  };
  if (el.breadcrumb) {
    el.breadcrumb.innerHTML = `Workspace <span>/</span><strong>${html(titleMap[page] || "Home")}</strong>`;
  }

  if (page === "class") renderClassPage();
  else if (page === "queue") renderQueuePage();
  else if (page === "records") renderRecordsPage();
  else if (page === "learner") renderLearnerPage(id, scope, recordView);
  else if (page === "updates") renderUpdatesPage();
  else renderHomePage();
}

// ── Page 1: Home ─────────────────────────────────────────────────────────────

function heading(kicker, title, description, actions = "") {
  return `
    <div class="page-heading">
      <div>
        <div class="eyebrow">${html(kicker)}</div>
        <h1>${html(title)}</h1>
        <p class="intro">${html(description)}</p>
      </div>
      ${actions ? `<div class="heading-actions">${actions}</div>` : ""}
    </div>
  `;
}

function emptyState(title, text, action = "") {
  return `<div class="empty-state"><h3>${html(title)}</h3><p>${html(text)}</p>${action}</div>`;
}

function statCard(label, value, foot, href) {
  return `
    <a class="stat stat-link" href="${href}">
      <div class="stat-top">
        <span class="stat-label">${html(label)}</span>
      </div>
      <div class="stat-value">${html(String(value))}</div>
      <div class="stat-foot">${html(foot)}</div>
    </a>
  `;
}

function renderHomePage() {
  const ws = state.workspace;
  const teacherName = ws?.display_name || state.currentTeacher?.display_name || "Educator";
  const classes = getUniqueClasses();
  const activeCls = getActiveClass();
  const isCT = isClassTeacherInActiveClass();
  const attention = (ws && ws.needs_attention) || [];
  const activeChanges = (state.classChanges || []).filter((c) => !c.superseded_by_release_id);

  let unfinishedCount = 0;
  let gapsCount = 0;
  if (isCT && state.classReadiness) {
    for (const l of state.classReadiness.learners || []) {
      for (const sc of state.classReadiness.required_scopes || []) {
        const slot = l.slots[sc];
        if (!slot) continue;
        if (!["ready_for_release", "reviewed_incomplete"].includes(slot.review_state)) unfinishedCount += 1;
        if (slot.review_state === "reviewed_incomplete" || slot.evidence_availability?.status !== "sufficient") {
          gapsCount += 1;
        }
      }
    }
  }

  const pendingAcks = attention.filter((i) => i.kind === "pending_acknowledgment").length;
  const statsHtml = isCT
    ? statCard("My classes", classes.length, "Open assigned classes", "#class") +
      statCard("Still to review", unfinishedCount, "Go to unfinished reviews", "#queue") +
      statCard("Evidence gaps", gapsCount, "See missing-evidence items", "#queue?status=incomplete") +
      statCard("Updates", activeChanges.length, "Post-release changes", "#updates")
    : statCard("My classes", classes.length, "Open released learner reviews", "#class") +
      statCard("Awaiting acknowledgment", pendingAcks, "Read released reviews", "#queue") +
      statCard("Active updates", activeChanges.length, "See changes in your subject", "#updates") +
      statCard("Learners in class", state.learners.length, activeCls ? activeCls.display_name : "No class", "#class");

  const attentionRows = attention
    .slice(0, 5)
    .map((item) => {
      const isMajor = item.kind === "major_change";
      const sym = isMajor ? "!" : item.kind === "class_readiness" ? "✓" : "↗";
      const badgeHtml = isMajor
        ? `<span class="badge red">Major change</span>`
        : item.kind === "minor_change"
        ? `<span class="badge green">Minor update</span>`
        : item.kind === "pending_acknowledgment"
        ? `<span class="badge amber">Awaiting acknowledgment</span>`
        : `<span class="badge">Readiness check</span>`;

      return `
        <button type="button" class="attention-row" style="width:100%;text-align:left;background:transparent;border:0;border-bottom:1px solid #edf0e9;"
          data-attention-class="${html(item.class_id || "")}"
          data-attention-learner="${html(item.learner_id || "")}"
          data-attention-scope="${html(item.scope || item.subject || "student")}"
          data-attention-kind="${html(item.kind || "")}">
          <span class="attention-symbol ${isMajor ? "red" : ""}" aria-hidden="true">${sym}</span>
          <div>
            <strong>${html(item.headline || "Action needed")}</strong>
            ${item.why_it_matters ? `<p>${html(item.why_it_matters)}</p>` : ""}
            <div class="row-meta">
              ${badgeHtml}
              <span>${html(item.class_name || item.class_id || "")}</span>
              ${item.learner_name ? `<span>· ${html(item.learner_name)}</span>` : ""}
            </div>
          </div>
          <span class="arrow" aria-hidden="true">›</span>
        </button>
      `;
    })
    .join("");

  const classCardsHtml = classes
    .map((cls) => {
      const rel = cls.latest_release;
      const isSelected = cls.class_id === state.activeClassId;
      const statusBadgeHtml =
        cls.learner_count === 0
          ? `<span class="badge outline">No learners</span>`
          : rel
          ? `<span class="badge green">Published · v${html(rel.version_number)}</span>`
          : `<span class="badge outline">Review in progress</span>`;

      let progressHtml = "";
      if (isSelected && cls.role === "class_teacher" && state.classReadiness && cls.learner_count > 0) {
        const learners = state.classReadiness.learners || [];
        const scopes = state.classReadiness.required_scopes || [];
        const total = learners.length * scopes.length;
        const done = total - unfinishedCount;
        progressHtml = `
          <div class="progress-label"><span>Review progress</span><strong>${done} / ${total}</strong></div>
          <progress max="${Math.max(1, total)}" value="${done}" aria-label="Reviewed class sections"></progress>
          <div class="class-status-line">
            <span>${unfinishedCount} unfinished</span>
            <span>${gapsCount} evidence gaps</span>
          </div>
        `;
      } else {
        progressHtml = `<p class="intro" style="margin-top:12px;">${
          cls.learner_count === 0
            ? "No learners are currently enrolled in this class."
            : cls.role === "class_teacher"
            ? "Open class readiness and learner reviews."
            : rel
            ? `Student Review + ${html(cls.subject)} Review released.`
            : "The class teacher is preparing this handover."
        }</p>`;
      }

      return `
        <div class="panel class-card ${isSelected ? "selected-class-card" : ""}">
          <div class="class-card-header">
            <span class="class-icon" aria-hidden="true">▦</span>
            ${statusBadgeHtml}
          </div>
          <h3>${html(cls.display_name)}</h3>
          <p class="class-sub">${html(cls.grade)} · Term ${html(cls.term)}, ${html(cls.academic_year)} · ${html(cls.learner_count)} learner${cls.learner_count === 1 ? "" : "s"}</p>
          ${progressHtml}
          <div class="class-card-bottom">
            <span>${html(cls.role_label)}</span>
            <button type="button" class="button secondary sm" data-select-class="${html(cls.class_id)}">
              ${isSelected ? "Open class →" : "Select & open →"}
            </button>
          </div>
        </div>
      `;
    })
    .join("");

  const roleDesc = activeCls
    ? activeCls.role === "class_teacher"
      ? "A clear view of your assigned classes, learner reviews to finish, and class release readiness."
      : `Shared Student Reviews and your ${String(activeCls.subject || "").toLowerCase()} reviews, scoped to your assigned classes.`
    : "No classes are currently assigned to your educator account.";

  el.main.innerHTML = `
    <div id="teacher-workspace-strip">
      ${heading("YOUR WORKSPACE", `Hello, ${teacherName}.`, roleDesc)}
    </div>
    <div id="view-class-handover">
      <div class="stats four">${statsHtml}</div>
      <div class="home-grid">
        <section>
          <div class="section-heading">
            <h2>Needs your attention</h2>
            <a class="text-link" href="#queue">See reviews →</a>
          </div>
          <div class="panel">
            ${
              attentionRows ||
              emptyState(
                "You are up to date",
                activeCls?.learner_count === 0
                  ? "No learners are enrolled in the selected class yet."
                  : "No pending handover items require your attention right now.",
                `<a class="button secondary" href="#class">Open my classes</a>`
              )
            }
          </div>
        </section>
        <section>
          <div class="section-heading">
            <h2>My classes</h2>
            <a class="text-link" href="#class">Open class →</a>
          </div>
          <div class="class-cards-stack">
            ${classCardsHtml || `<div class="panel">${emptyState("No classes assigned", "Contact an administrator to assign classes to your account.")}</div>`}
          </div>
        </section>
      </div>
      <div class="bottom-note">
        <span aria-hidden="true">↳</span>
        <div>
          <strong>Clear gaps. Honest handovers.</strong>
          <small>Missing information stays visible. Teachers verify disclosures rather than filling in unrecorded scores.</small>
        </div>
      </div>
    </div>
  `;

  el.main.querySelectorAll("[data-select-class]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const committed = await switchActiveClass(btn.dataset.selectClass);
      if (committed) navigate("#class");
    });
  });

  el.main.querySelectorAll("[data-attention-kind]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const cid = btn.dataset.attentionClass;
      const lid = btn.dataset.attentionLearner;
      const sc = btn.dataset.attentionScope || "student";
      if (cid && cid !== state.activeClassId) {
        const committed = await switchActiveClass(cid);
        if (!committed) return;
      }
      if (lid && state.learners.some((l) => l.learner_id === lid)) {
        state.activeLearnerId = lid;
        if (el.learnerSelect) el.learnerSelect.value = lid;
        navigate(learnerLink(lid, sc));
      } else {
        navigate("#class");
      }
    });
  });
}

// ── Page 2: My Classes ───────────────────────────────────────────────────────

function renderClassPage() {
  const activeCls = getActiveClass();
  if (!activeCls) {
    el.main.innerHTML =
      `<div id="teacher-workspace-strip" hidden></div><div id="view-class-handover">` +
      heading("MY CLASSES", "No class assigned", "Your educator account has no assigned classes.") +
      `<div class="panel">${emptyState("No classes available", "Ask an administrator to assign you to a class.")}</div></div>`;
    return;
  }

  const isCT = isClassTeacherInActiveClass();

  // Empty class handling (e.g., Grade 4 Red for Mrs. Kamau)
  if (state.learners.length === 0) {
    el.main.innerHTML =
      `<div id="teacher-workspace-strip" hidden></div><div id="view-class-handover">` +
      heading(
        `MY CLASSES / ${activeCls.display_name.toUpperCase()}`,
        `${activeCls.display_name}`,
        `${activeCls.grade} · Term ${activeCls.term}, ${activeCls.academic_year} · ${activeCls.role_label}`,
        `<button type="button" class="button primary" data-action="open-import">↑ Import marks / report</button>`
      ) +
      `<div class="panel">${emptyState(
        `No learners enrolled in ${activeCls.display_name}`,
        "This class currently has 0 enrolled learners. Import a class mark sheet CSV/JSON or enroll learners to populate this class.",
        `<button type="button" class="button primary" data-action="open-import">↑ Import marks / report</button>` +
          (getUniqueClasses().length > 1 ? ` <a class="button secondary" href="#home">View other classes</a>` : "")
      )}</div></div>`;
    return;
  }

  const q = route().query;
  const statusFilter = q.get("status") || "all";
  const sectionFilter = q.get("section") || "all";
  const visibleScopes = getVisibleScopesForActiveClass();

  if (!isCT) {
    const rel = activeCls.latest_release;
    if (!rel) {
      el.main.innerHTML =
        `<div id="teacher-workspace-strip" hidden></div><div id="view-class-handover">` +
        heading(
          `MY CLASSES / ${activeCls.display_name.toUpperCase()}`,
          `${activeCls.display_name}`,
          `${activeCls.grade} · Term ${activeCls.term}, ${activeCls.academic_year} · ${activeCls.role_label}`
        ) +
        `<div class="panel">${emptyState(
          "Waiting for class release",
          `The class teacher is still reviewing ${activeCls.display_name}. Shared Student Reviews and your ${activeCls.subject} reviews will appear here after release.`,
          `<a class="button secondary" href="#records">Browse permitted source records →</a>`
        )}</div></div>`;
      return;
    }

    const rowsHtml = state.learners
      .map((l) => {
        const pub = state.publishedByLearner[l.learner_id];
        const sections = (pub && pub.sections) || [];
        const ackAll = sections.length > 0 && sections.every((s) => s.acknowledgment?.acknowledged);
        const anyViewed = sections.some((s) => (s.viewing_history || []).length > 0);
        const ackBadge = ackAll
          ? `<span class="badge green">Acknowledged</span>`
          : anyViewed
          ? `<span class="badge amber">Viewed · not acknowledged</span>`
          : `<span class="badge">Not opened</span>`;

        const scopeCells = visibleScopes
          .map((sc) => {
            const sec = sections.find((s) => s.scope === sc);
            if (!sec) return `<td><span class="badge">Not in v${html(rel.version_number)}</span></td>`;
            return `<td><a class="section-status-link" href="${learnerLink(l.learner_id, sc)}">${reviewStateBadge(sec.review_state)}</a></td>`;
          })
          .join("");

        return `
          <tr data-search="${html(`${l.display_name} ${l.learner_id}`.toLowerCase())}">
            <td>
              <a class="learner-link" href="${learnerLink(l.learner_id, getAllowedSubjectsInActiveClass()[0] || "student")}">
                <span class="avatar">${html(l.learner_id.slice(-2))}</span>
                <span><strong>${html(l.display_name)}</strong><small>${html(l.learner_id)}</small></span>
              </a>
            </td>
            ${scopeCells}
            <td>${ackBadge}</td>
            <td><a class="button secondary sm" href="${learnerLink(l.learner_id, getAllowedSubjectsInActiveClass()[0] || "student")}">Open →</a></td>
          </tr>
        `;
      })
      .join("");

    el.main.innerHTML =
      `<div id="teacher-workspace-strip" hidden></div><div id="view-class-handover">` +
      heading(
        `MY CLASSES / ${activeCls.display_name.toUpperCase()}`,
        "Every learner, in view.",
        `Read each Student Review and ${activeCls.subject} Review released in v${rel.version_number}.`,
        `<span class="badge green">Released · version ${html(rel.version_number)}</span>`
      ) +
      `<div class="panel">
        <div class="filter-toolbar">
          <input class="search" data-search-input placeholder="Find a learner…" aria-label="Find a learner">
        </div>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Learner</th>
                ${visibleScopes.map((sc) => `<th>${html(scopeTitle(sc))}</th>`).join("")}
                <th>Acknowledgment</th>
                <th>Open</th>
              </tr>
            </thead>
            <tbody>${rowsHtml}</tbody>
          </table>
        </div>
        <div class="row-count" data-row-count>${state.learners.length} of ${state.learners.length} learners</div>
      </div></div>`;
    return;
  }

  // Class teacher readiness view
  const r = state.classReadiness;
  if (!r) {
    el.main.innerHTML = `<div class="panel">${emptyState("Loading class readiness…", "Fetching section states from backend.")}</div>`;
    return;
  }

  const scopes = r.required_scopes || [];
  const learners = r.learners || [];
  const rel = r.latest_release;
  const released = Boolean(rel);

  const filteredRows = learners.filter((l) => {
    const checkScopes = sectionFilter === "all" ? scopes : scopes.includes(sectionFilter) ? [sectionFilter] : [];
    if (statusFilter === "all") return true;
    return checkScopes.some((sc) => {
      const slot = l.slots[sc];
      if (!slot) return false;
      if (statusFilter === "unfinished") {
        return !["ready_for_release", "reviewed_incomplete"].includes(slot.review_state);
      }
      return slot.review_state === statusFilter;
    });
  });

  const rowsHtml = filteredRows
    .map((l) => {
      const cells = scopes
        .map((sc) => {
          const slot = l.slots[sc];
          if (!slot) return "<td>—</td>";
          const avail = slot.evidence_availability || {};
          const hints = [];
          if (slot.pending_findings_count > 0) hints.push(`${slot.pending_findings_count} AI finding(s)`);
          if (avail.status && avail.status !== "sufficient") hints.push(avail.label || avail.status);
          return `
            <td>
              <div class="slot-cell-wrap">
                <a class="section-status-link" href="${learnerLink(l.learner_id, sc)}">${reviewStateBadge(slot.review_state)}</a>
                ${hints.length ? `<span class="slot-subhint">${html(hints.join(" · "))}</span>` : ""}
              </div>
            </td>
          `;
        })
        .join("");

      const releaseCell = l.is_release_ready
        ? `<span class="badge green">${rel ? "Ready for v" + (rel.version_number + 1) : "Ready"}</span>`
        : `<span class="badge">Review needed</span>`;

      return `
        <tr data-search="${html(`${l.display_name} ${l.learner_id}`.toLowerCase())}">
          <td>
            <a class="learner-link" href="${learnerLink(l.learner_id, "student")}">
              <span class="avatar">${html(l.learner_id.slice(-2))}</span>
              <span><strong>${html(l.display_name)}</strong><small>${html(l.learner_id)}</small></span>
            </a>
          </td>
          ${cells}
          <td>${releaseCell}</td>
          <td><a class="button secondary sm" href="${learnerLink(l.learner_id, "student")}">Open →</a></td>
        </tr>
      `;
    })
    .join("");

  const stepsHtml = `
    <ol class="mini-steps" aria-label="Class handover progress">
      <li class="${released || r.can_release ? "done" : "current"}"><span class="step-number">${released || r.can_release ? "✓" : "1"}</span>Review class</li>
      <li class="${released ? "done" : r.can_release ? "current" : ""}"><span class="step-number">${released ? "✓" : "2"}</span>Release</li>
      <li class="${released ? "current" : ""}"><span class="step-number">3</span>Teacher follow-up</li>
    </ol>
  `;

  const releaseBtnLabel = rel ? `Release v${rel.version_number + 1}` : "Release class";
  const actionsHtml = `
    <button type="button" class="button secondary" data-action="open-import">↑ Import marks / report</button>
    <button type="button" class="button primary" data-action="release" ${r.can_release ? "" : "disabled"}>
      ${html(releaseBtnLabel)} ↗
    </button>
  `;

  const statusOptions = [
    ["all", "All statuses"],
    ["unfinished", "Unfinished"],
    ["not_reviewed", "Not reviewed"],
    ["needs_clarification", "Needs clarification"],
    ["reviewed_incomplete", "Reviewed — incomplete"],
    ["ready_for_release", "Ready"],
  ];

  el.main.innerHTML =
    `<div id="teacher-workspace-strip" hidden></div><div id="view-class-handover">` +
    heading(
      `MY CLASSES / ${activeCls.display_name.toUpperCase()}`,
      "Every learner, in view.",
      "Finish the Student Review and each Subject Review before releasing the class." +
        (rel ? ` Latest published: v${rel.version_number} by ${rel.released_by_name}.` : ""),
      actionsHtml
    ) +
    stepsHtml +
    (r.can_release
      ? `<div class="all-set"><h3>All sections reviewed. Ready when you are.</h3><p>Verified evidence gaps remain clearly disclosed in the released handover.</p></div>`
      : r.blocking_reasons.length > 0
      ? `<div class="callout"><strong>Before release (${r.blocking_reasons.length} item${r.blocking_reasons.length === 1 ? "" : "s"} remaining)</strong><p>${html(r.blocking_reasons.slice(0, 3).join(" · "))}${r.blocking_reasons.length > 3 ? ` (+${r.blocking_reasons.length - 3} more)` : ""}</p></div>`
      : "") +
    `<div class="panel mt">
      <div class="filter-toolbar">
        <input class="search" data-search-input placeholder="Find a learner…" aria-label="Find a learner">
        ${filterSelect("Status", "status", statusOptions, statusFilter)}
        ${filterSelect("Section", "section", [["all", "All sections"], ...scopes.map((s) => [s, scopeTitle(s)])], sectionFilter)}
      </div>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Learner</th>
              ${scopes.map((sc) => `<th>${html(scopeTitle(sc))}</th>`).join("")}
              <th>Release</th>
              <th>Open</th>
            </tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
        </table>
        ${!filteredRows.length ? emptyState("No learners match", "Choose another status or section filter.") : ""}
      </div>
      <div class="row-count" data-row-count>${filteredRows.length} of ${learners.length} learners</div>
    </div>
    <div class="legend">
      <span><i class="green-dot"></i> Reviewed and ready</span>
      <span><i class="amber-dot"></i> Evidence gap or clarification recorded</span>
    </div></div>`;
}

function filterSelect(label, key, options, selected) {
  return `
    <label>
      ${html(label)}
      <select data-filter="${html(key)}" aria-label="${html(label)}">
        ${options
          .map(
            ([val, text]) =>
              `<option value="${html(val)}" ${selected === val ? "selected" : ""}>${html(text)}</option>`
          )
          .join("")}
      </select>
    </label>
  `;
}

// ── Page 3: Reviews Queue ────────────────────────────────────────────────────

function renderQueuePage() {
  const activeCls = getActiveClass();
  if (!activeCls) {
    el.main.innerHTML = emptyState("No class assigned", "Select a class to view reviews.");
    return;
  }

  if (state.learners.length === 0) {
    el.main.innerHTML =
      heading("REVIEWS", "Your review queue", `${activeCls.display_name} has no enrolled learners.`) +
      `<div class="panel">${emptyState("No learners in this class", "Reviews will appear once learners are enrolled.")}</div>`;
    return;
  }

  const isCT = isClassTeacherInActiveClass();
  if (!isCT) {
    if (!activeCls.latest_release) {
      el.main.innerHTML =
        heading("REVIEWS", "Read. Acknowledge. Respond.", "Your acknowledgment records receipt separately from viewing.") +
        `<div class="panel">${emptyState(
          "Waiting for class release",
          `The class teacher is still reviewing ${activeCls.display_name}. Shared Student Reviews and your ${activeCls.subject} reviews will appear here after release.`,
          `<a class="button secondary" href="#class">Back to class</a>`
        )}</div>`;
      return;
    }

    const ackItems = state.learners
      .map((l) => {
        const pub = state.publishedByLearner[l.learner_id];
        const sections = (pub && pub.sections) || [];
        const acknowledged = sections.length > 0 && sections.every((s) => s.acknowledgment?.acknowledged);
        return { learner: l, acknowledged };
      })
      .filter((x) => !x.acknowledged);

    const subj = getAllowedSubjectsInActiveClass()[0] || "student";
    const cards = ackItems
      .map(
        ({ learner }) => `
        <article class="queue-item" data-search="${html(`${learner.display_name} ${learner.learner_id}`.toLowerCase())}">
          <span class="queue-icon" aria-hidden="true">↗</span>
          <div class="queue-content">
            <h3>${html(learner.display_name)} · ${html(scopeTitle(subj))}</h3>
            <p>Read the released Student Review and your ${html(subj)} review, then record your acknowledgment.</p>
            <div class="row-meta">
              <span class="badge amber">Awaiting acknowledgment</span>
              <span>${html(activeCls.display_name)} · v${html(activeCls.latest_release.version_number)}</span>
            </div>
          </div>
          <a class="button secondary" href="${learnerLink(learner.learner_id, subj)}">Open review →</a>
        </article>
      `
      )
      .join("");

    el.main.innerHTML =
      heading("REVIEWS", "Read. Acknowledge. Respond.", "Your acknowledgment records receipt. Your response adds context without changing the approved review.") +
      `<div class="panel">
        <div class="filter-toolbar">
          <input class="search" data-search-input placeholder="Find a learner…" aria-label="Find a learner">
          <span class="muted"><small>${ackItems.length} awaiting acknowledgment</small></span>
        </div>
        ${cards || emptyState("All released reports acknowledged", "You have acknowledged every learner report in this release.", `<a class="button secondary" href="#class">Open class</a>`)}
        <div class="row-count" data-row-count>${ackItems.length} awaiting acknowledgment</div>
      </div>`;
    return;
  }

  // Class teacher queue from /readiness
  const r = state.classReadiness;
  if (!r) return;
  const activeFilter = route().query.get("status") || "unfinished";

  const slots = [];
  for (const l of r.learners || []) {
    for (const sc of r.required_scopes || []) {
      const slot = l.slots[sc];
      if (!slot) continue;
      slots.push({
        learner_id: l.learner_id,
        learner_name: l.display_name,
        scope: sc,
        review_state: slot.review_state,
        pending_findings_count: slot.pending_findings_count || 0,
        text:
          slot.pending_findings_count > 0
            ? `${slot.pending_findings_count} AI candidate finding(s) await teacher adjudication before release.`
            : slot.review_state === "reviewed_incomplete"
            ? slot.missing_evidence_disclosure || slot.evidence_availability?.human_message || "Evidence gap documented."
            : slot.review_state === "needs_clarification"
            ? "Check what is known and record what still needs clarification."
            : slot.review_state === "ready_for_release"
            ? "This section has a teacher decision and is ready for class release."
            : "This section has not been reviewed yet.",
        href: learnerLink(
          l.learner_id,
          sc,
          slot.pending_findings_count > 0 ? "ai" : "review"
        ),
      });
    }
  }

  const filters = [
    ["unfinished", "To finish", slots.filter((s) => !["ready_for_release", "reviewed_incomplete"].includes(s.review_state)).length],
    ["needs_clarification", "Questions", slots.filter((s) => s.review_state === "needs_clarification").length],
    ["incomplete", "Missing information", slots.filter((s) => s.review_state === "reviewed_incomplete").length],
    ["ai_pending", "AI findings pending", slots.filter((s) => s.pending_findings_count > 0).length],
    ["ready_for_release", "Ready", slots.filter((s) => s.review_state === "ready_for_release").length],
  ];

  const matching = slots.filter((s) => {
    if (activeFilter === "unfinished") return !["ready_for_release", "reviewed_incomplete"].includes(s.review_state);
    if (activeFilter === "incomplete") return s.review_state === "reviewed_incomplete";
    if (activeFilter === "ai_pending") return s.pending_findings_count > 0;
    return s.review_state === activeFilter;
  });

  const chipsHtml = `<div class="filter-chips">${filters
    .map(
      ([k, label, count]) =>
        `<a class="filter-chip ${k === activeFilter ? "active" : ""}" href="#queue?status=${encodeURIComponent(k)}">${html(label)}<b>${count}</b></a>`
    )
    .join("")}</div>`;

  const cardsHtml = matching
    .map(
      (item) => `
      <article class="queue-item" data-search="${html(`${item.learner_name} ${item.scope} ${item.text}`.toLowerCase())}">
        <span class="queue-icon ${html(item.review_state)}" aria-hidden="true">${item.review_state === "needs_clarification" ? "?" : "↗"}</span>
        <div class="queue-content">
          <h3>${html(item.learner_name)} · ${html(scopeTitle(item.scope))}</h3>
          <p>${html(item.text)}</p>
          <div class="row-meta">
            ${reviewStateBadge(item.review_state)}
            ${item.pending_findings_count > 0 ? `<span class="badge amber">${item.pending_findings_count} AI finding(s)</span>` : ""}
            <span>${html(activeCls.display_name)}</span>
          </div>
        </div>
        <a class="button secondary" href="${item.href}">Open review →</a>
      </article>
    `
    )
    .join("");

  el.main.innerHTML =
    heading("REVIEWS", "A clear next step.", "Keep unfinished work separate from reviewed evidence gaps and AI candidate findings.") +
    chipsHtml +
    `<div class="panel">
      <div class="filter-toolbar">
        <input class="search" data-search-input placeholder="Find a learner or review…" aria-label="Find a review">
        <span class="muted"><small>${matching.length} in this list</small></span>
      </div>
      ${cardsHtml || emptyState("Nothing in this list", "Choose another category or return to your class.", `<a class="button secondary" href="#class">Open class</a>`)}
      <div class="row-count" data-row-count>${matching.length} matching review section(s)</div>
    </div>`;
}

// ── Page 4: Records ──────────────────────────────────────────────────────────

async function renderRecordsPage() {
  const activeCls = getActiveClass();
  if (!activeCls) {
    el.main.innerHTML = emptyState("No class assigned", "Select a class to inspect source records.");
    return;
  }

  if (state.learners.length === 0) {
    el.main.innerHTML =
      heading(
        "RECORDS",
        "Follow the source.",
        "Assessment results, attendance, observations, and learner reflections.",
        `<button type="button" class="button primary" data-action="open-import">↑ Import marks / report</button>`
      ) +
      `<div class="panel">${emptyState(
        "No learners in this class",
        "Import a class mark sheet or enroll learners before recording or browsing evidence.",
        `<button type="button" class="button primary" data-action="open-import">↑ Import marks / report</button>`
      )}</div>`;
    return;
  }

  el.main.innerHTML =
    heading(
      "RECORDS",
      "Follow the source.",
      "See what was recorded, when it was recorded, and where it came from.",
      `<button type="button" class="button secondary" data-action="open-import">↑ Import marks / report</button> <button type="button" class="button primary" data-action="open-observation">+ Record observation</button>`
    ) + `<div class="panel">${emptyState("Loading source records…", "Fetching role-scoped evidence from the ALLPS backend.")}</div>`;

  const reqSeq = ++state.recordsSeq;
  const reqClassId = state.activeClassId;
  const targetLearners = state.learners.slice();

  // Load evidence for learners in the active class
  try {
    const entries = await Promise.all(
      targetLearners.map(async (l) => {
        if (!state.evidenceByLearner[l.learner_id]) {
          state.evidenceByLearner[l.learner_id] = await api.getEvidence(l.learner_id);
        }
        return state.evidenceByLearner[l.learner_id];
      })
    );
    if (reqSeq !== state.recordsSeq || reqClassId !== state.activeClassId || !state.currentTeacher) {
      return;
    }
    const allRecords = entries.flat();
    drawRecordsList(allRecords);
  } catch (err) {
    if (reqSeq !== state.recordsSeq || reqClassId !== state.activeClassId || !state.currentTeacher) {
      return;
    }
    el.main.innerHTML =
      heading("RECORDS", "Follow the source.", "Assessment results, attendance, observations, and learner reflections.") +
      `<div class="panel">${emptyState("Could not load records", err.message)}</div>`;
  }
}

function drawRecordsList(allRecords) {
  const q = route().query;
  const activeType = q.get("type") || "all";
  const subjectFilter = q.get("subject") || "all";
  const termFilter = q.get("term") || "all";
  const learnerFilter = q.get("learner") || "all";

  const visibleScopes = getVisibleScopesForActiveClass();
  const filtered = allRecords.filter(
    (e) =>
      (activeType === "all" || e.evidence_type === activeType) &&
      (subjectFilter === "all" || (subjectFilter === "student" ? !e.subject : e.subject === subjectFilter)) &&
      (termFilter === "all" || String(e.term) === termFilter) &&
      (learnerFilter === "all" || e.learner_id === learnerFilter)
  );

  const categories = ["all", "assessment", "attendance", "observation", "learner_reflection", "project"].map(
    (t) => ({
      key: t,
      label: t === "all" ? "All records" : typeLabel(t),
      count: allRecords.filter((e) => t === "all" || e.evidence_type === t).length,
      href: `#records?${new URLSearchParams({ ...Object.fromEntries(q), type: t }).toString()}`,
    })
  );

  const chipsHtml = `<div class="filter-chips">${categories
    .map(
      (c) =>
        `<a class="filter-chip ${c.key === activeType ? "active" : ""}" href="${c.href}">${html(c.label)}<b>${c.count}</b></a>`
    )
    .join("")}</div>`;

  const cardsHtml = filtered
    .map((e) => {
      const l = learnerObj(e.learner_id);
      const searchStr = `${l?.display_name || e.learner_id} ${e.subject || "Student"} ${evidenceSummaryText(e)} ${e.source_reference}`.toLowerCase();
      return `
        <div data-search="${html(searchStr)}">
          <article class="record-card">
            <span class="record-icon" aria-hidden="true">${recordIcon(e.evidence_type)}</span>
            <div>
              <h3>${html(l?.display_name || e.learner_id)} · ${html(e.subject || "Student context")}</h3>
              <p>${html(evidenceSummaryText(e))}</p>
              <div class="row-meta">
                <span>${html(typeLabel(e.evidence_type))}</span>
                <span>·</span>
                <span>${html(e.academic_year)} / Term ${html(e.term)}</span>
                <span>·</span>
                <span>${html(e.source_reference)}</span>
              </div>
            </div>
            <button type="button" class="text-link" data-action="source" data-id="${html(e.evidence_id)}">Open source</button>
          </article>
        </div>
      `;
    })
    .join("");

  el.main.innerHTML =
    heading(
      "RECORDS",
      "Follow the source.",
      "See what was recorded, when it was recorded, and where it came from.",
      `<button type="button" class="button secondary" data-action="open-import">↑ Import marks / report</button> <button type="button" class="button primary" data-action="open-observation">+ Record observation</button>`
    ) +
    chipsHtml +
    `<div class="panel">
      <div class="filter-toolbar">
        <input class="search" data-search-input placeholder="Search source records…" aria-label="Search source records">
        ${filterSelect("Learner", "learner", [["all", "All learners in class"], ...state.learners.map((l) => [l.learner_id, l.display_name])], learnerFilter)}
        ${filterSelect("Scope", "subject", [["all", "All my records"], ...visibleScopes.map((s) => [s, scopeTitle(s)])], subjectFilter)}
        ${filterSelect("Term", "term", [["all", "All terms"], ["1", "Term 1"], ["2", "Term 2"], ["3", "Term 3"]], termFilter)}
      </div>
      <div class="records-scroll">
        ${cardsHtml || emptyState("No records match", "No result has been invented or filled in. Try another filter.")}
      </div>
      <div class="row-count" data-row-count>${filtered.length} records shown</div>
    </div>`;
}

// ── Page 5: Updates ──────────────────────────────────────────────────────────

function renderUpdatesPage() {
  const activeCls = getActiveClass();
  const kind = route().query.get("kind") || "all";
  const allChanges = state.classChanges || [];
  const filtered = allChanges.filter((c) => kind === "all" || c.severity === kind);

  const chipsHtml = `<div class="filter-chips">${[
    ["all", "All updates"],
    ["minor", "Small updates"],
    ["major", "Major changes"],
  ]
    .map(
      ([k, label]) =>
        `<a class="filter-chip ${k === kind ? "active" : ""}" href="#updates?kind=${encodeURIComponent(k)}">${html(label)}<b>${allChanges.filter((c) => k === "all" || c.severity === k).length}</b></a>`
    )
    .join("")}</div>`;

  const isCT = isClassTeacherInActiveClass();

  const cardsHtml = filtered
    .map((ch) => {
      const l = learnerObj(ch.learner_id);
      const isMajor = ch.severity === "major";
      const stepsHtml = (ch.progress_steps || [])
        .map(
          (st) =>
            `<span class="progress-step-pill${st.done ? " done" : ""}${st.current ? " current" : ""}">${html(st.label)}</span>`
        )
        .join("");

      const reviewAction =
        isCT && !ch.reviewed_at && !ch.superseded_by_release_id
          ? `<button type="button" class="button primary sm" data-action="review-change" data-class-id="${html(ch.class_id)}" data-change-id="${html(ch.change_id)}">Mark reviewed</button>`
          : "";

      return `
        <article class="update-item">
          <div class="update-top">
            <span class="badge ${isMajor ? "red" : "green"}">${isMajor ? "Major change · review needed" : "Minor update"}</span>
            <span class="muted"><small>${html(formatStamp(ch.detected_at))}</small></span>
          </div>
          <h3>${html(l?.display_name || ch.learner_id)} · ${html(scopeTitle(ch.scope))}</h3>
          <p><strong>${html(ch.headline)}</strong></p>
          <p>${html(ch.explanation)}</p>
          <details class="update-details">
            <summary>Why it matters &amp; comparison</summary>
            <p>${html(ch.why_it_matters)}</p>
          </details>
          <div class="progress-steps-row">${stepsHtml}</div>
          <div class="update-footer">
            <small>${ch.superseded_by_release_id ? `Superseded by v${ch.superseded_version_number}` : ch.reviewed_at ? `Reviewed by class teacher (${formatStamp(ch.reviewed_at)})` : "Active post-release change"}</small>
            <div class="button-group">
              <button type="button" class="button secondary sm" data-action="change-detail" data-id="${html(ch.change_id)}">See comparison</button>
              <a class="button secondary sm" href="${learnerLink(ch.learner_id, ch.scope)}">Open review →</a>
              ${reviewAction}
            </div>
          </div>
        </article>
      `;
    })
    .join("");

  el.main.innerHTML =
    heading(
      "UPDATES",
      "See the change. Keep the context.",
      activeCls
        ? `Post-release evidence changes for ${activeCls.display_name}. Published releases stay frozen until a new class version is released.`
        : "Select a class to inspect post-release changes."
    ) +
    chipsHtml +
    `<div class="stack">
      ${
        cardsHtml ||
        `<div class="panel">${emptyState(
          "No post-release updates",
          activeCls?.latest_release
            ? "No new evidence has diverged from or extended the published release yet."
            : "Post-release updates are tracked once a class handover has been released."
        )}</div>`
      }
    </div>`;
}

// ── Page 6: Learner Review Page ──────────────────────────────────────────────

async function renderLearnerPage(requestedId, requestedScope = "student", recordView = false) {
  const activeCls = getActiveClass();
  if (!activeCls) {
    el.main.innerHTML = emptyState("No class selected", "Select a class first.");
    return;
  }

  const targetId = requestedId || state.activeLearnerId || state.learners[0]?.learner_id;
  const person = learnerObj(targetId);
  if (!person) {
    el.main.innerHTML = emptyState(
      "Learner not in selected class",
      `Choose a learner enrolled in ${activeCls.display_name}.`,
      `<a class="button secondary" href="#class">Open class</a>`
    );
    return;
  }

  if (state.activeLearnerId !== targetId) {
    state.activeLearnerId = targetId;
    if (el.learnerSelect) el.learnerSelect.value = targetId;
  }

  const isCT = isClassTeacherInActiveClass();
  const visibleScopes = getVisibleScopesForActiveClass();
  const scope = visibleScopes.includes(requestedScope) ? requestedScope : visibleScopes[0] || "student";
  const q = route().query;
  const allowedSubViews = isCT ? ["review", "records", "history", "ai"] : ["review", "records", "history"];
  const subView = allowedSubViews.includes(q.get("view")) ? q.get("view") : "review";

  if (!isCT && !activeCls.latest_release) {
    el.main.innerHTML =
      heading(`MY CLASSES / LEARNER`, person.display_name, "Reviews are shared after class release.") +
      `<div class="panel">${emptyState(
        "Waiting for class release",
        `The class teacher is still reviewing ${activeCls.display_name}. Shared Student Reviews and your ${activeCls.subject} reviews will appear here after release.`,
        `<a class="button secondary" href="#records">Browse permitted records →</a>`
      )}</div>`;
    return;
  }

  const reqSeq = ++state.learnerSeq;
  const reqClassId = state.activeClassId;

  el.main.innerHTML = `<div class="panel">${emptyState("Loading learner review…", `Loading ${person.display_name} from ALLPS backend.`)}</div>`;

  try {
    const [evidence, availability, published, reviews, briefRes] = await Promise.all([
      api.getEvidence(targetId),
      api.getLearnerAvailability(targetId),
      api.getPublishedHandover(targetId),
      isCT ? api.getReviews(targetId) : Promise.resolve([]),
      isCT ? api.getLatestBrief(targetId) : Promise.resolve(null),
    ]);

    if (reqSeq !== state.learnerSeq || reqClassId !== state.activeClassId || !state.currentTeacher) {
      return;
    }

    state.evidenceByLearner[targetId] = evidence;
    state.availabilityByLearner[targetId] = availability;
    state.publishedByLearner[targetId] = published;
    state.reviewsByLearner[targetId] = reviews;
    state.briefByLearner[targetId] = briefRes?.brief || null;

    // Record viewing event once when opening a published review
    let freshPublished = published;
    if (published?.release && recordView && subView === "review") {
      const viewKey = `${published.release.release_id}:${targetId}:${scope}:${state.currentTeacher.teacher_id}`;
      if (!state.recordedViews.has(viewKey)) {
        state.recordedViews.add(viewKey);
        try {
          await api.recordReportView(published.release.release_id, targetId, scope);
          freshPublished = await api.getPublishedHandover(targetId);
          if (reqSeq !== state.learnerSeq || reqClassId !== state.activeClassId || !state.currentTeacher) {
            return;
          }
          state.publishedByLearner[targetId] = freshPublished;
          state.workspace = await api.getWorkspace();
          updateSidebarBadges();
        } catch (viewErr) {
          console.warn("Could not log report view:", viewErr);
        }
      }
    }

    if (reqSeq !== state.learnerSeq || reqClassId !== state.activeClassId || !state.currentTeacher) {
      return;
    }
    drawLearnerPage(person, activeCls, scope, subView, evidence, availability, freshPublished, reviews, briefRes?.brief);
  } catch (err) {
    if (reqSeq !== state.learnerSeq || reqClassId !== state.activeClassId || !state.currentTeacher) {
      return;
    }
    el.main.innerHTML =
      heading("MY CLASSES / LEARNER", person.display_name, `${targetId}`) +
      `<div class="panel">${emptyState("Could not load learner", err.message, `<a class="button secondary" href="#class">← Back to class</a>`)}</div>`;
  }
}

function drawLearnerPage(person, activeCls, scope, subView, evidence, availability, published, reviews, latestBrief) {
  const isCT = isClassTeacherInActiveClass();
  const visibleScopes = getVisibleScopesForActiveClass();
  const id = person.learner_id;

  const scopeEvidence = evidence.filter((e) => (scope === "student" ? !e.subject : e.subject === scope));
  const scopeAvail = availability?.scopes?.[scope] || null;
  const readinessSlot = isCT
    ? (state.classReadiness?.learners || []).find((l) => l.learner_id === id)?.slots?.[scope] || null
    : null;
  const pubRelease = published?.release || null;
  const pubSection = (published?.sections || []).find((s) => s.scope === scope) || null;
  const relatedChanges = (published?.changes || []).filter((c) => c.scope === scope && !c.superseded_by_release_id);

  const sectionTabs = `
    <nav class="tabs" aria-label="Learner review sections">
      ${visibleScopes
        .map(
          (s) =>
            `<a class="tab ${s === scope ? "active" : ""}" href="${learnerLink(id, s)}" ${s === scope ? 'aria-current="page"' : ""}>${html(scopeTitle(s))}</a>`
        )
        .join("")}
    </nav>
  `;

  const subViewsList = [
    ["review", "Review"],
    ["records", `Records (${scopeEvidence.length})`],
    ["history", "Activity"],
  ];
  if (isCT) {
    const pendingAiCount = (reviews || []).filter((r) => r.status === "pending").length;
    subViewsList.push(["ai", `AI Synthesis${pendingAiCount ? ` (${pendingAiCount})` : ""}`]);
  }

  const viewSwitcher = `
    <div class="section-heading">
      <div class="main-view-switch" aria-label="Review detail view">
        ${subViewsList
          .map(
            ([k, label]) =>
              `<a class="${subView === k ? "active" : ""}" href="${learnerLink(id, scope, k)}">${html(label)}</a>`
          )
          .join("")}
      </div>
      ${pubRelease ? `<span class="badge green">Released · v${html(pubRelease.version_number)}</span>` : `<span class="badge outline">Pre-release</span>`}
    </div>
  `;

  let mainContent = "";
  if (subView === "records") {
    const cards = scopeEvidence
      .map(
        (e) => `
      <article class="record-card">
        <span class="record-icon" aria-hidden="true">${recordIcon(e.evidence_type)}</span>
        <div>
          <h3>${html(person.display_name)} · ${html(e.subject || "Student context")}</h3>
          <p>${html(evidenceSummaryText(e))}</p>
          <div class="row-meta">
            <span>${html(typeLabel(e.evidence_type))}</span><span>·</span>
            <span>${html(e.academic_year)} / Term ${html(e.term)}</span><span>·</span>
            <span>${html(e.source_reference)}</span>
          </div>
        </div>
        <button type="button" class="text-link" data-action="source" data-id="${html(e.evidence_id)}">Open source</button>
      </article>
    `
      )
      .join("");

    mainContent = `
      <section class="panel">
        <div class="panel-heading">
          <h3>Records behind ${html(scopeTitle(scope))}</h3>
          <div class="button-group">
            <span class="badge">${scopeEvidence.length} record${scopeEvidence.length === 1 ? "" : "s"}</span>
            <button type="button" class="button secondary sm" data-action="open-observation">+ Record observation</button>
          </div>
        </div>
        ${cards || emptyState("No records available", "No result has been recorded or filled in for this section.")}
      </section>
    `;
  } else if (subView === "history") {
    const viewsList = pubSection?.viewing_history || published?.viewing_history || [];
    const receipts = published?.receipts || [];
    mainContent = `
      <section class="review-card">
        <h2>Review activity</h2>
        <p class="intro">Opening a released report and acknowledging receipt are recorded separately.</p>
        <div class="mt">
          ${
            viewsList.length || receipts.some((r) => r.acknowledged_at)
              ? viewsList
                  .slice()
                  .reverse()
                  .map(
                    (v) => `
                  <div class="timeline-row">
                    <h3>${html(v.teacher_name)} · Opened ${html(scopeTitle(v.scope || scope))}</h3>
                    <p>${html(formatStamp(v.viewed_at))}${pubRelease ? ` · Version ${html(pubRelease.version_number)}` : ""}</p>
                  </div>
                `
                  )
                  .join("")
              : emptyState("No activity yet", "Viewing and acknowledgment history starts after class release.")
          }
        </div>
      </section>
    `;
  } else if (subView === "ai" && isCT) {
    mainContent = renderLearnerAiSection(id, scope, reviews, latestBrief);
  } else {
    // Main Review tab
    const marks = scopeEvidence.filter(
      (e) => e.evidence_type === "assessment" && !e.is_missing_outcome && typeof e.score === "number" && e.max_score
    );
    const chartHtml = marks.length
      ? `
        <div class="result-chart" aria-label="Recorded results by term">
          <div class="result-bars">
            ${marks
              .map((e) => {
                const heightPx = Math.max(4, Math.min(82, (e.score / Math.max(1, e.max_score)) * 82));
                return `
                  <button type="button" class="result-column" data-action="source" data-id="${html(e.evidence_id)}" aria-label="Term ${html(e.term)}: ${html(e.score)}/${html(e.max_score)}. Open source.">
                    <span class="result-value">${html(e.score)}/${html(e.max_score)}</span>
                    <span class="result-bar" style="height:${heightPx}px"></span>
                    <span>Term ${html(e.term)}</span>
                  </button>
                `;
              })
              .join("")}
          </div>
          <p class="form-hint">Select a bar to inspect its source record. These are recorded marks, not an automated average.</p>
        </div>
      `
      : "";

    const availabilityBox = scopeAvail
      ? `
        <div class="${scopeAvail.status === "sufficient" ? "followup-card" : "disclosure-note"}">
          <strong>Evidence availability: ${html(scopeAvail.label || scopeAvail.status)}</strong>
          <p>${html(scopeAvail.human_message || "")}</p>
          ${scopeAvail.unmet_conclusion ? `<small>${html(scopeAvail.unmet_conclusion)}</small>` : ""}
        </div>
      `
      : "";

    const publishedSummaryBox = pubSection
      ? `
        <div class="followup-card">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
            <strong>Published ${html(pubSection.section_title)} · v${html(pubRelease.version_number)}</strong>
            ${pubSection.approved_content_hash ? `<span class="hash-chip" title="SHA-256 Snapshot">SHA: ${html(pubSection.approved_content_hash.slice(0, 14))}…</span>` : ""}
          </div>
          <p>${html(pubSection.approved_summary)}</p>
          ${pubSection.teacher_notes ? `<small style="display:block;margin-top:6px;">Teacher note: ${html(pubSection.teacher_notes)}</small>` : ""}
          ${pubSection.missing_evidence_disclosure ? `<small style="display:block;margin-top:4px;color:var(--amber);">Gap disclosure: ${html(pubSection.missing_evidence_disclosure)}</small>` : ""}
          ${
            pubSection.citations && pubSection.citations.length > 0
              ? `<div class="citation-pills" style="margin-top:8px;"><small>Citations:</small>${pubSection.citations
                  .map((cid) => `<button type="button" class="citation" data-action="source" data-id="${html(cid)}">${html(cid.slice(0, 8))}…</button>`)
                  .join("")}</div>`
              : ""
          }
          <small style="display:block;margin-top:6px;">Approved by ${html(pubSection.approved_by_name)} · ${html(formatStamp(pubSection.approved_at))}</small>
        </div>
      `
      : "";

    const draftSummaryBox =
      isCT && readinessSlot && readinessSlot.approved_summary
        ? `
        <div class="followup-card">
          <strong>Current class-teacher draft</strong>
          <p>${html(readinessSlot.approved_summary)}</p>
          ${readinessSlot.missing_evidence_disclosure ? `<small style="display:block;margin-top:4px;color:var(--amber);">Gap disclosure: ${html(readinessSlot.missing_evidence_disclosure)}</small>` : ""}
          ${readinessSlot.teacher_notes ? `<small style="display:block;margin-top:4px;">Notes: ${html(readinessSlot.teacher_notes)}</small>` : ""}
        </div>
      `
        : "";

    const changesBanner = relatedChanges
      .map(
        (ch) => `
      <div class="change-strip ${ch.severity === "major" ? "red" : ""}">
        <div>
          <strong>${ch.severity === "major" ? "Major change — review needed" : "Minor post-release update"}</strong>
          <p>${html(ch.headline)} · ${html(ch.explanation)}</p>
          <div class="button-group" style="margin-top:8px;">
            <button type="button" class="text-link" data-action="change-detail" data-id="${html(ch.change_id)}">Inspect comparison</button>
            ${
              isCT && !ch.reviewed_at
                ? `<button type="button" class="button primary sm" data-action="review-change" data-class-id="${html(ch.class_id)}" data-change-id="${html(ch.change_id)}">Mark reviewed</button>`
                : ""
            }
          </div>
        </div>
      </div>
    `
      )
      .join("");

    const pendingCount = readinessSlot?.pending_findings_count || 0;
    const ctActionBar = isCT
      ? `
        <div class="review-actions">
          <p>
            ${
              pendingCount > 0
                ? `${pendingCount} AI candidate finding(s) must be adjudicated before marking this section ready.`
                : readinessSlot?.review_state === "ready_for_release" || readinessSlot?.review_state === "reviewed_incomplete"
                ? "You can refine this section decision before the next class release."
                : "Inspect the source records and record your section decision."
            }
          </p>
          <div class="button-group">
            ${
              pendingCount > 0
                ? `<a class="button secondary" href="${learnerLink(id, scope, "ai")}">Adjudicate AI findings (${pendingCount}) →</a>`
                : ""
            }
            <button type="button" class="button primary" data-action="edit-section" data-id="${html(id)}" data-section="${html(scope)}">
              ${readinessSlot?.approved_summary ? "Edit review decision" : "Review this section"}
            </button>
          </div>
        </div>
      `
      : "";

    // Subject teacher response thread on their assigned subject section
    const canRespond = !isCT && pubRelease && pubSection && getAllowedSubjectsInActiveClass().includes(scope);
    const responses = pubSection?.responses || [];
    const responseThread =
      scope !== "student" && (responses.length > 0 || canRespond)
        ? `
        <div class="response-thread">
          <div class="eyebrow">ATTACHED TO THIS REVIEW</div>
          ${
            responses.length
              ? responses
                  .map(
                    (resp) => `
                  <article class="response">
                    <div class="response-head">
                      <span class="avatar">${html(initialsOf(resp.teacher_name))}</span>
                      <strong>${html(resp.teacher_name)}</strong>
                      <span class="badge">${html(String(resp.response_type).replaceAll("_", " "))}</span>
                      <small>${html(formatStamp(resp.created_at))}</small>
                    </div>
                    <p>${html(resp.content)}</p>
                  </article>
                `
                  )
                  .join("")
              : `<p class="intro">No subject responses attached yet.</p>`
          }
          ${
            canRespond
              ? `
              <form class="response-form" id="subject-response-form" data-release-id="${html(pubRelease.release_id)}" data-id="${html(id)}" data-subject="${html(scope)}">
                <label for="subject-response-text">Your subject response</label>
                <textarea id="subject-response-text" name="content" required minlength="3" maxlength="3000" placeholder="Add a confirmation, follow-up observation, or question for the class teacher..."></textarea>
                <div class="response-form-footer">
                  <small>Your response stays attached beneath the frozen review without altering it.</small>
                  <div>
                    <select name="response_type" aria-label="Response type">
                      <option value="confirmation">Confirmation</option>
                      <option value="additional_observation">Additional observation</option>
                      <option value="question">Question</option>
                    </select>
                    <button class="button primary" type="submit">Attach response</button>
                  </div>
                </div>
                <p class="field-error" id="response-error" role="alert"></p>
              </form>
              <button type="button" class="text-link mt" data-action="open-observation">+ Record a new observation</button>
            `
              : ""
          }
        </div>
      `
        : "";

    const headerBadge = readinessSlot
      ? reviewStateBadge(readinessSlot.review_state)
      : pubSection
      ? reviewStateBadge(pubSection.review_state)
      : "";

    mainContent = `
      ${changesBanner}
      <article class="review-card">
        <div class="review-card-heading">
          <h2>${html(scopeTitle(scope))}</h2>
          ${headerBadge}
        </div>
        ${publishedSummaryBox}
        ${!pubSection || isCT ? draftSummaryBox : ""}
        ${chartHtml}
        ${availabilityBox}
        <div class="parent-footer">
          <span>${pubRelease ? `Published handover v${pubRelease.version_number}` : "Pre-release workspace"}</span>
          <a class="text-link" href="${learnerLink(id, scope, "records")}">See ${scopeEvidence.length} source record${scopeEvidence.length === 1 ? "" : "s"} →</a>
        </div>
        ${ctActionBar}
        ${responseThread}
      </article>
    `;
  }

  // Right-hand side panels
  const lastOpened = pubSection?.last_opened;
  const ackInfo = pubSection?.acknowledgment;
  const allReceipts = published?.receipts || [];
  const canAck = !isCT && pubRelease && !(ackInfo && ackInfo.acknowledged);
  const canExport = Boolean(pubRelease);

  const accountabilityHtml = `
    <section class="panel side-panel">
      <div class="eyebrow">ACCOUNTABILITY</div>
      <h3>${pubRelease ? "Who has opened this?" : "Not released yet"}</h3>
      <p>${
        lastOpened
          ? html(lastOpened.display)
          : pubRelease
          ? "No subject teacher open recorded for this section yet."
          : "Viewing history and receipt acknowledgments begin after class release."
      }</p>
      ${
        !isCT && pubRelease
          ? `
          <div class="mt">
            <span class="badge ${ackInfo?.acknowledged ? "green" : "outline"}">${html(ackInfo?.display || "Not acknowledged")}</span>
          </div>
          <button type="button" class="button ${ackInfo?.acknowledged ? "secondary" : "primary"} mt" data-action="ack-report" data-release-id="${html(pubRelease.release_id)}" data-id="${html(id)}" ${canAck ? "" : "disabled"}>
            ${ackInfo?.acknowledged ? "Receipt acknowledged" : "Acknowledge receipt"}
          </button>
        `
          : ""
      }
      ${
        isCT && pubRelease
          ? `
          <div class="mt">
            ${
              allReceipts.length
                ? allReceipts
                    .map(
                      (rc) => `
                    <div class="history-item">
                      <strong>${html(rc.teacher_name)} (${html(rc.subject || "Subject")})</strong>
                      <small>${rc.acknowledged_at ? `Acknowledged ${html(formatStamp(rc.acknowledged_at))}` : rc.first_viewed_at ? `Opened ${html(formatStamp(rc.first_viewed_at))}` : "Not yet opened"}</small>
                    </div>
                  `
                    )
                    .join("")
                : `<p class="form-hint">No subject teacher receipts tracked.</p>`
            }
          </div>
        `
          : ""
      }
      <a class="text-link mt" style="display:inline-block;" href="${learnerLink(id, scope, "history")}">See activity →</a>
    </section>
  `;

  const visibilityHtml = `
    <section class="panel side-panel">
      <div class="eyebrow">WHO CAN READ THIS?</div>
      <h3>${scope === "student" ? "Teachers in this class" : "Class & assigned subject teacher"}</h3>
      <p>${
        scope === "student"
          ? "After release, Student Review is visible to the class teacher and subject teachers assigned to this class."
          : `Only the class teacher and the assigned ${scope} teacher can read this section, its source records, and attached responses.`
      }</p>
    </section>
  `;

  const quickLinksHtml = `
    <section class="panel side-panel">
      <div class="eyebrow">QUICK LINKS &amp; EXPORT</div>
      <div class="stack" style="gap:8px;">
        <a class="text-link" href="#records?learner=${encodeURIComponent(id)}&subject=${encodeURIComponent(scope)}">Browse source records →</a>
        <a class="text-link" href="#updates">View post-release changes →</a>
        ${isCT ? `<a class="text-link" href="#queue">Continue class reviews →</a>` : ""}
        ${
          canExport
            ? `<a class="button secondary sm" href="/api/learners/${encodeURIComponent(id)}/handover/export?format=html&download=false" target="_blank" rel="noopener">Printable view</a>
               <a class="button primary sm" href="/api/learners/${encodeURIComponent(id)}/handover/export?format=pdf&download=true">Export PDF</a>`
            : `<small class="muted">PDF &amp; printable export unlock after release/approval.</small>`
        }
      </div>
    </section>
  `;

  el.main.innerHTML = `
    <div id="teacher-workspace-strip" hidden></div>
    <div id="view-class-handover">
      <div class="page-heading learner-heading">
        <div class="learner-title">
          <span class="avatar">${html(id.slice(-2))}</span>
          <div>
            <div class="eyebrow">${html(activeCls.display_name.toUpperCase())} / LEARNER</div>
            <h1>${html(person.display_name)}</h1>
            <p class="intro">${html(id)} · Term ${html(activeCls.term)}, ${html(activeCls.academic_year)}</p>
          </div>
        </div>
        <div class="heading-actions">
          <button type="button" class="button secondary" data-action="open-observation">+ Record observation</button>
          <a class="button secondary" href="#class">← Back to class</a>
        </div>
      </div>
      ${sectionTabs}
      <div class="learner-grid">
        <div>${viewSwitcher}${mainContent}</div>
        <aside class="learner-aside">
          ${accountabilityHtml}
          ${visibilityHtml}
          ${quickLinksHtml}
        </aside>
      </div>
    </div>
  `;
}

// ── AI Synthesis & Sovereign Candidate Findings (Class Teacher Only) ─────────

function renderLearnerAiSection(learnerId, scope, reviews, latestBrief) {
  const defaultMode = state.config?.default_mode || "auto";
  const isHosted = Boolean(state.config?.hosted);
  const genRes = state.generationResultByLearner[learnerId] || null;
  const activeBrief = genRes?.brief || latestBrief || null;

  let briefHtml = "";
  if (genRes && genRes.status === "validation_failed") {
    briefHtml = `
      <div class="callout">
        <strong>Deterministic policy gate rejected LLM draft</strong>
        <p>${html((genRes.errors || []).join(" · "))}</p>
      </div>
    `;
  } else if (genRes && genRes.status === "inference_failed") {
    briefHtml = `
      <div class="disclosure-note">
        <strong>Inference failed</strong>
        <p>${html((genRes.errors || []).join(" · "))}</p>
      </div>
    `;
  } else if (activeBrief && (activeBrief.status === "abstained" || genRes?.status === "abstained")) {
    briefHtml = `
      <div class="followup-card">
        <strong>AI safely abstained</strong>
        <p>${html(activeBrief.abstention_reason || "Insufficient comparable longitudinal evidence.")}</p>
      </div>
    `;
  } else if (activeBrief) {
    const findingsHtml = (activeBrief.findings || [])
      .map((f, idx) => {
        const cites = (f.supporting_evidence_ids || [])
          .map((eid) => `<button type="button" class="citation" data-action="source" data-id="${html(eid)}">${html(eid.slice(0, 8))}…</button>`)
          .join("");
        return `
          <div class="finding-card">
            <div><strong>Finding ${idx + 1}:</strong> ${html(f.observation)}</div>
            ${cites ? `<div class="citation-pills"><small>Citations:</small>${cites}</div>` : ""}
          </div>
        `;
      })
      .join("");

    briefHtml = `
      <div class="callout" style="margin-top:14px;">
        <strong>Candidate synthesis — not approved. Requires teacher adjudication below.</strong>
        <p>${html(activeBrief.summary)}</p>
        ${activeBrief.limitations?.length ? `<p><small>Limitations: ${html(activeBrief.limitations.join("; "))}</small></p>` : ""}
      </div>
      ${findingsHtml}
    `;
  }

  const reviewCards = (reviews || [])
    .map((rev) => {
      const currentRev = rev.revision ?? 0;
      const isPending = rev.status === "pending";
      const cites = (rev.supporting_evidence_ids || [])
        .map((eid) => `<button type="button" class="citation" data-action="source" data-id="${html(eid)}">${html(eid.slice(0, 8))}…</button>`)
        .join("");
      const statusBadge =
        rev.status === "accepted"
          ? `<span class="badge green">ACCEPTED</span>`
          : rev.status === "rejected"
          ? `<span class="badge red">REJECTED</span>`
          : rev.status === "needs_context"
          ? `<span class="badge amber">NEEDS CONTEXT</span>`
          : `<span class="badge amber">PENDING</span>`;

      return `
        <article class="finding-card" data-review-card="${html(rev.review_id || "")}">
          <div class="finding-card-head">
            <div class="button-group">
              <span class="badge">${html(String(rev.pattern_type || "").toUpperCase())}</span>
              <span class="badge outline">Decision Rev ${html(currentRev)}</span>
              ${statusBadge}
            </div>
            <small class="muted">${html(formatStamp(rev.generated_at))}</small>
          </div>
          <div class="review-copy">${html(rev.summary)}</div>
          ${rev.limitations?.length ? `<div class="disclosure-note"><strong>Limitations</strong><p>${html(rev.limitations.join("; "))}</p></div>` : ""}
          <div class="citation-pills"><small>Citations:</small>${cites || "<small class='muted'>None</small>"}</div>
          ${
            isPending && rev.review_id
              ? `
              <div class="adjudication-box">
                <label class="form-hint" for="notes-${html(rev.review_id)}">Teacher adjudication rationale (optional)</label>
                <textarea id="notes-${html(rev.review_id)}" rows="2" placeholder="Record teacher rationale...">${html(rev.teacher_notes || "")}</textarea>
                <div class="button-group">
                  <button type="button" class="button primary sm" data-action="decide-review" data-review-id="${html(rev.review_id)}" data-status="accepted" data-revision="${html(currentRev)}" data-correction="false">✓ Accept finding</button>
                  <button type="button" class="button secondary sm" data-action="decide-review" data-review-id="${html(rev.review_id)}" data-status="rejected" data-revision="${html(currentRev)}" data-correction="false">✕ Reject</button>
                  <button type="button" class="button secondary sm" data-action="decide-review" data-review-id="${html(rev.review_id)}" data-status="needs_context" data-revision="${html(currentRev)}" data-correction="false">? Needs context</button>
                </div>
              </div>
            `
              : `
              <div class="adjudication-box">
                <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
                  <small>Decision: <strong>${html(rev.status.toUpperCase())}</strong> by ${html(rev.reviewer_id || "Teacher")}</small>
                  ${rev.approved_content_hash ? `<span class="hash-chip">SHA: ${html(rev.approved_content_hash.slice(0, 14))}…</span>` : ""}
                </div>
                ${rev.teacher_notes ? `<small class="muted">Notes: “${html(rev.teacher_notes)}”</small>` : ""}
                ${
                  rev.review_id
                    ? `<button type="button" class="text-link" style="align-self:flex-start;" data-action="toggle-correction" data-review-id="${html(rev.review_id)}">Correct decision</button>
                       <div class="correction-area" id="corr-${html(rev.review_id)}" hidden>
                         <textarea id="corr-notes-${html(rev.review_id)}" rows="2" placeholder="Document pedagogical rationale for correcting this decision...">${html(rev.teacher_notes || "")}</textarea>
                         <div class="button-group" style="margin-top:8px;">
                           <button type="button" class="button primary sm" data-action="decide-review" data-review-id="${html(rev.review_id)}" data-status="accepted" data-revision="${html(currentRev)}" data-correction="true">✓ Correct to Accepted</button>
                           <button type="button" class="button secondary sm" data-action="decide-review" data-review-id="${html(rev.review_id)}" data-status="rejected" data-revision="${html(currentRev)}" data-correction="true">✕ Correct to Rejected</button>
                           <button type="button" class="button secondary sm" data-action="decide-review" data-review-id="${html(rev.review_id)}" data-status="needs_context" data-revision="${html(currentRev)}" data-correction="true">? Correct to Needs Context</button>
                         </div>
                       </div>`
                    : ""
                }
              </div>
            `
          }
        </article>
      `;
    })
    .join("");

  return `
    <section class="review-card">
      <div class="review-card-heading">
        <div>
          <h2>Bounded AI Transition Synthesis</h2>
          <p class="form-hint">Deterministic 9-key comparability bounding, citation verification, and sovereign teacher adjudication.</p>
        </div>
        <div class="synthesis-controls">
          <select id="ai-subject-select" aria-label="Synthesis subject">
            <option value="">All subjects</option>
            <option value="Mathematics" ${scope === "Mathematics" ? "selected" : ""}>Mathematics</option>
            <option value="English" ${scope === "English" ? "selected" : ""}>English</option>
            <option value="Science" ${scope === "Science" ? "selected" : ""}>Science</option>
          </select>
          <select id="ai-mode-select" aria-label="Inference mode" ${isHosted ? "disabled" : ""}>
            <option value="auto" ${defaultMode === "auto" ? "selected" : ""}>Mode: AUTO</option>
            <option value="live" ${defaultMode === "live" ? "selected" : ""}>Mode: LIVE</option>
            <option value="deterministic" ${defaultMode === "deterministic" ? "selected" : ""}>Mode: DETERMINISTIC</option>
            <option value="mock" ${defaultMode === "mock" ? "selected" : ""}>Mode: MOCK</option>
          </select>
          <button type="button" class="button primary sm" data-action="generate-brief" data-id="${html(learnerId)}" ${state.isGenerating ? "disabled" : ""}>
            ${state.isGenerating ? "Synthesizing…" : "Generate candidate handover"}
          </button>
        </div>
      </div>
      ${briefHtml}
      <div class="mt">
        <div class="eyebrow">SAVED CANDIDATE FINDINGS (${(reviews || []).length})</div>
        ${reviewCards || emptyState("No candidate findings yet", "Generate a candidate handover above to synthesize comparable evidence patterns.")}
      </div>
    </section>
  `;
}

// ── Modals: Source Inspection, Section Review, Release, Observation ──────────

function showDetailModal(title, bodyHtml) {
  if (!el.detailDialog || !el.detailContent) return;
  el.detailContent.innerHTML = `<h2 id="detail-title">${html(title)}</h2>${bodyHtml}`;
  el.detailDialog.showModal();
}

async function openSourceModal(evidenceId) {
  showDetailModal("Source record", `<p class="muted">Loading evidence record ${html(evidenceId)}…</p>`);
  try {
    const r = await api.getEvidenceDetail(evidenceId);
    const l = learnerObj(r.learner_id);
    const body = `
      <p class="detail-subtitle">${html(l?.display_name || r.learner_id)} · ${html(r.subject || "Whole-learner context")}</p>
      <div class="followup-card">
        <strong>${html(typeLabel(r.evidence_type))}</strong>
        <p>${html(evidenceSummaryText(r))}</p>
      </div>
      <div class="source-definition">
        <dl>
          <dt>Learner</dt><dd>${html(l?.display_name || r.learner_id)} (${html(r.learner_id)})</dd>
          <dt>Subject</dt><dd>${html(r.subject || "Whole-learner context")}</dd>
          <dt>Year / term</dt><dd>${html(r.academic_year)} / Term ${html(r.term)}</dd>
          <dt>Recorded by</dt><dd>${html(r.source_reference)} (${html(r.source_type)})</dd>
          <dt>Source system</dt><dd>${html(r.source_system)} (${html(r.ingestion_method)})</dd>
          <dt>Observed</dt><dd>${html(formatStamp(r.observed_at))}</dd>
          <dt>Record ID</dt><dd style="font-family:var(--mono);font-size:11px;">${html(r.evidence_id)}</dd>
        </dl>
      </div>
      <pre class="source-payload">${html(JSON.stringify(r.content, null, 2))}</pre>
      <div class="dialog-button-row">
        <button type="button" class="button secondary" data-action="close-detail">Close source</button>
        <a class="button primary" href="${learnerLink(r.learner_id, r.subject || "student")}" data-close-detail>Open learner review</a>
      </div>
    `;
    showDetailModal("Source record", body);
  } catch (err) {
    showDetailModal(
      "Source unavailable",
      `<p class="field-error">${html(err.message)}</p><div class="dialog-button-row"><button type="button" class="button secondary" data-action="close-detail">Close</button></div>`
    );
  }
}

function openSectionReviewModal(learnerId, scope) {
  const r = state.classReadiness;
  if (!r || !isClassTeacherInActiveClass()) return;
  const learnerRow = (r.learners || []).find((l) => l.learner_id === learnerId);
  const slot = learnerRow?.slots?.[scope];
  if (!slot) return;

  const avail = slot.evidence_availability || {};
  const scopeEvidence = (state.evidenceByLearner[learnerId] || []).filter((e) =>
    scope === "student" ? !e.subject : e.subject === scope
  );
  const hasRecords = scopeEvidence.length > 0;
  const existingCitations = new Set(slot.citations || []);

  const options = [
    ["ready_for_release", "Reviewed and ready", "The available evidence supports this section."],
    ["reviewed_incomplete", "Reviewed — evidence incomplete", "Keep a factual missing-information disclosure."],
    ["needs_clarification", "Needs clarification", "A teacher question or verification step is still outstanding."],
  ];

  const defaultSummary =
    slot.approved_summary ||
    (!hasRecords ? avail.human_message || `No ${scopeTitle(scope)} records available in the current source set.` : "");

  const citationChecks = scopeEvidence.length
    ? `
      <div class="form-field">
        <label>Supporting citations (optional, scoped to ${html(scopeTitle(scope))})</label>
        <div class="citation-checklist">
          ${scopeEvidence
            .map(
              (ev) => `
              <label class="citation-check-item">
                <input type="checkbox" name="citations" value="${html(ev.evidence_id)}" ${existingCitations.has(ev.evidence_id) ? "checked" : ""}>
                <span><strong>${html(typeLabel(ev.evidence_type))}</strong> (${html(ev.academic_year)} T${html(ev.term)}): ${html(evidenceSummaryText(ev))}</span>
              </label>
            `
            )
            .join("")}
        </div>
      </div>
    `
    : "";

  showDetailModal(
    `Review ${scope === "student" ? "student context" : scope}`,
    `
      <p class="detail-subtitle">${html(learnerRow.display_name)} (${html(learnerId)}) · ${scopeEvidence.length} source record${scopeEvidence.length === 1 ? "" : "s"}</p>
      <form id="section-review-form" data-class-id="${html(r.school_class.class_id)}" data-id="${html(learnerId)}" data-section="${html(scope)}">
        <fieldset class="decision-list">
          <legend class="form-hint">Choose a review decision</legend>
          ${options
            .map(([val, title, desc]) => {
              const checked =
                val === slot.review_state ||
                (slot.review_state === "not_reviewed" && val === (hasRecords ? "ready_for_release" : "reviewed_incomplete"));
              return `
                <label class="decision-option">
                  <input type="radio" name="review_state" value="${val}" ${checked ? "checked" : ""}>
                  <span>${html(title)}<small>${html(desc)}</small></span>
                </label>
              `;
            })
            .join("")}
        </fieldset>
        <div class="form-field">
          <label for="slot-approved-summary">Approved summary *</label>
          <textarea id="slot-approved-summary" name="approved_summary" maxlength="5000" required placeholder="Write a factual, non-deficit longitudinal summary...">${html(defaultSummary)}</textarea>
          ${scope === "student" ? `<p>Student Review summarizes whole-learner context without embedding subject mark tables.</p>` : ""}
        </div>
        <div class="form-field">
          <label for="slot-missing-disclosure">Missing-evidence disclosure (required if incomplete)</label>
          <input type="text" id="slot-missing-disclosure" name="missing_evidence_disclosure" maxlength="2000" value="${html(slot.missing_evidence_disclosure || (!hasRecords ? avail.human_message || "" : ""))}" placeholder="State exactly what is missing without guessing...">
        </div>
        <div class="form-field">
          <label for="slot-teacher-notes">Teacher notes (optional)</label>
          <input type="text" id="slot-teacher-notes" name="teacher_notes" maxlength="5000" value="${html(slot.teacher_notes || "")}">
        </div>
        ${citationChecks}
        <p class="field-error" id="section-review-error" role="alert"></p>
        <div class="dialog-button-row">
          <button type="button" class="button secondary" data-action="close-detail">Cancel</button>
          <button type="submit" class="button primary" id="btn-save-section-review">Save review decision</button>
        </div>
      </form>
    `
  );
}

function openReleaseModal() {
  const r = state.classReadiness;
  if (!r || !isClassTeacherInActiveClass() || !r.can_release) return;
  const learners = r.learners || [];
  const scopes = r.required_scopes || [];
  let incompleteCount = 0;
  learners.forEach((l) => {
    scopes.forEach((sc) => {
      if (l.slots[sc]?.review_state === "reviewed_incomplete") incompleteCount += 1;
    });
  });

  if (el.releaseSummary) {
    el.releaseSummary.innerHTML = `
      <strong>${learners.length} learners · ${scopes.length} sections each (${learners.length * scopes.length} total)</strong>
      <ul class="release-checklist">
        <li><span>✓</span> Every required section has a class-teacher decision.</li>
        <li><span>✓</span> ${incompleteCount} section${incompleteCount === 1 ? "" : "s"} keep an explicit missing-information disclosure.</li>
        <li><span>✓</span> Subject teachers receive Student Review + their assigned subject only.</li>
      </ul>
    `;
  }
  if (el.releaseNotesInput) el.releaseNotesInput.value = "";
  if (el.releaseDialog) el.releaseDialog.showModal();
}

function openChangeDetailModal(changeId) {
  const ch = (state.classChanges || []).find((c) => c.change_id === changeId);
  if (!ch) return;
  const l = learnerObj(ch.learner_id);
  const comp = ch.comparison || {};
  const newResults = (comp.new_results || [])
    .map((nr) => `<li>${html(nr.evidence_type)} (${html(nr.academic_year)} T${html(nr.term)}): ${html(nr.score !== undefined ? `${nr.score}/${nr.max_score}` : nr.text || nr.missing_status || "Recorded")}</li>`)
    .join("");

  showDetailModal(
    ch.severity === "major" ? "Major change — review needed" : "Minor post-release update",
    `
      <p class="detail-subtitle">${html(l?.display_name || ch.learner_id)} · ${html(scopeTitle(ch.scope))}</p>
      <div class="compare-grid">
        <div class="compare-box">
          <div class="eyebrow">PUBLISHED SNAPSHOT</div>
          <p>${html(comp.published_conclusion || "Approved snapshot remains frozen and unchanged.")}</p>
        </div>
        <div class="compare-box changed">
          <div class="eyebrow">CURRENT EVALUATION</div>
          <p>${html(comp.current_conclusion || ch.headline)}</p>
        </div>
      </div>
      <p>${html(ch.why_it_matters)}</p>
      ${newResults ? `<ul class="mt" style="padding-left:18px;font-size:12px;">${newResults}</ul>` : ""}
      <div class="dialog-button-row">
        <button type="button" class="button secondary" data-action="close-detail">Close</button>
        <a class="button primary" href="${learnerLink(ch.learner_id, ch.scope)}" data-close-detail>Open review →</a>
      </div>
    `
  );
}

// ── Observation Entry & 2-Step Preview ───────────────────────────────────────

function openObservationDialog() {
  if (!state.activeLearnerId) {
    toast("Select a learner first before recording an observation.");
    return;
  }
  if (el.obsErrorAlert) el.obsErrorAlert.hidden = true;

  // Scope subject dropdown based on teacher role in active class
  if (el.obsSubject) {
    const isCT = isClassTeacherInActiveClass();
    const allowed = getAllowedSubjectsInActiveClass();
    el.obsSubject.innerHTML = `<option value="">General / Student context</option>`;
    const subjectList = isCT ? ["Mathematics", "English", "Science"] : allowed;
    subjectList.forEach((subj) => {
      const opt = document.createElement("option");
      opt.value = subj;
      opt.textContent = subj;
      el.obsSubject.appendChild(opt);
    });
    if (!isCT && allowed.length === 1 && !state.observationDraft.subject) {
      state.observationDraft.subject = allowed[0];
    }
    el.obsSubject.value = state.observationDraft.subject || "";
  }

  if (el.obsYear) el.obsYear.value = state.observationDraft.academic_year;
  if (el.obsTerm) el.obsTerm.value = state.observationDraft.term;
  if (el.obsSourceRef) el.obsSourceRef.value = state.observationDraft.source_reference || state.currentTeacher?.display_name || "";
  if (el.obsDatetime) el.obsDatetime.value = state.observationDraft.event_datetime;
  if (el.obsText) el.obsText.value = state.observationDraft.observation;
  if (el.obsContext) el.obsContext.value = state.observationDraft.context;

  if (el.observationDialog) el.observationDialog.showModal();
}

function showObsError(msg) {
  if (!el.obsErrorAlert) return;
  el.obsErrorAlert.textContent = msg;
  el.obsErrorAlert.hidden = false;
}

function handleObservationPreview() {
  state.observationDraft.academic_year = parseInt(el.obsYear.value, 10);
  state.observationDraft.term = parseInt(el.obsTerm.value, 10);
  state.observationDraft.subject = el.obsSubject.value;
  state.observationDraft.source_reference = el.obsSourceRef.value.trim();
  state.observationDraft.event_datetime = el.obsDatetime.value;
  state.observationDraft.observation = el.obsText.value.trim();
  state.observationDraft.context = el.obsContext.value.trim();

  if (!state.observationDraft.observation || state.observationDraft.observation.length < 3) {
    showObsError("Observation text is required (at least 3 characters).");
    return;
  }
  if (labelPattern.test(state.observationDraft.observation) || labelPattern.test(state.observationDraft.context)) {
    showObsError("Use factual observations without diagnostic or deficit labels.");
    return;
  }
  if (!state.observationDraft.source_reference) {
    showObsError("Attributed educator name is required.");
    return;
  }
  if (!state.observationDraft.event_datetime) {
    showObsError("Observed date and time is required.");
    return;
  }

  if (el.obsErrorAlert) el.obsErrorAlert.hidden = true;
  const l = learnerObj(state.activeLearnerId);
  if (el.previewContent) {
    el.previewContent.innerHTML = `
      <dl>
        <dt>Learner</dt><dd>${html(l?.display_name || state.activeLearnerId)} (${html(state.activeLearnerId)})</dd>
        <dt>Academic time</dt><dd>Year ${html(state.observationDraft.academic_year)} · Term ${html(state.observationDraft.term)}</dd>
        <dt>Subject</dt><dd>${html(state.observationDraft.subject || "General / Student context")}</dd>
        <dt>Observed time</dt><dd>${html(state.observationDraft.event_datetime)}</dd>
        <dt>Educator</dt><dd>${html(state.observationDraft.source_reference)}</dd>
        <dt>Observation</dt><dd>${html(state.observationDraft.observation)}</dd>
        ${state.observationDraft.context ? `<dt>Context</dt><dd>${html(state.observationDraft.context)}</dd>` : ""}
        <dt>Event ID</dt><dd style="font-family:var(--mono);font-size:11px;">${html(state.observationDraft.source_event_id)}</dd>
      </dl>
    `;
  }

  el.observationDialog.close();
  el.previewDialog.showModal();
}

async function handleSaveObservation() {
  if (!state.activeLearnerId) return;
  el.btnConfirmSaveObservation.disabled = true;
  el.btnConfirmSaveObservation.textContent = "Saving…";

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
    el.previewDialog.close();
    state.observationDraft = makeEmptyObservationDraft(state.currentTeacher?.display_name || "");
    await refreshWorkspaceFromServer();
    toast(`Observation saved for ${state.activeLearnerId}.`);
  } catch (err) {
    el.previewDialog.close();
    el.observationDialog.showModal();
    showObsError(`Save failed: ${err.message}`);
  } finally {
    el.btnConfirmSaveObservation.disabled = false;
    el.btnConfirmSaveObservation.textContent = "Confirm & save";
  }
}

// ── School Report / Marks Import Modal ───────────────────────────────────────

function showImportError(msg) {
  if (!el.importErrorAlert) return;
  el.importErrorAlert.textContent = msg;
  el.importErrorAlert.hidden = false;
  el.importErrorAlert.focus();
}

function clearImportFeedback() {
  if (el.importErrorAlert) {
    el.importErrorAlert.hidden = true;
    el.importErrorAlert.textContent = "";
  }
  if (el.importResultSummary) {
    el.importResultSummary.hidden = true;
    el.importResultSummary.innerHTML = "";
    el.importResultSummary.classList.remove("has-errors");
  }
  if (el.importFile) el.importFile.removeAttribute("aria-invalid");
  if (el.importSourceSystem) el.importSourceSystem.removeAttribute("aria-invalid");
}

function openImportDialog() {
  const activeCls = getActiveClass();
  if (!activeCls) {
    toast("Select an assigned class before importing a report file.");
    return;
  }
  clearImportFeedback();
  if (el.importForm) el.importForm.reset();

  const isCT = isClassTeacherInActiveClass();
  const allowed = getAllowedSubjectsInActiveClass();
  if (el.importClassContext) {
    const scopeNote = isCT
      ? "All subjects for this class (class teacher)."
      : `Scoped to your assigned subject(s): ${allowed.join(", ") || "none"}.`;
    el.importClassContext.textContent = `Target class: ${activeCls.display_name} (${activeCls.class_id}). ${scopeNote}`;
  }

  if (el.importSourceSystem) el.importSourceSystem.value = "school_report_csv";
  if (el.importYear && activeCls.academic_year) el.importYear.value = String(activeCls.academic_year);
  if (el.importTerm && activeCls.term) el.importTerm.value = String(activeCls.term);
  if (el.importGrade && activeCls.grade) el.importGrade.value = activeCls.grade;
  if (el.importObservedAt && !el.importObservedAt.value) {
    el.importObservedAt.value = new Date().toISOString().slice(0, 10);
  }
  if (el.importMaxScore && !el.importMaxScore.value) el.importMaxScore.value = "100";

  if (el.importDialog) el.importDialog.showModal();
}

function renderImportSummary(summary) {
  if (!el.importResultSummary) return;
  const manifest = summary.manifest || {};
  const accepted = manifest.accepted_count ?? 0;
  const dupes = manifest.duplicate_count ?? 0;
  const rejected = manifest.rejected_count ?? 0;
  const errors = Array.isArray(summary.errors) ? summary.errors : [];

  el.importResultSummary.classList.toggle("has-errors", rejected > 0);
  const errorItems = errors
    .slice(0, 20)
    .map((err) => {
      const prefix = [err.learner_id, err.subject].filter(Boolean).join(" · ");
      return `<li>${prefix ? `<strong>${html(prefix)}:</strong> ` : ""}${html(err.error)}</li>`;
    })
    .join("");
  const extraCount = errors.length > 20 ? `<li>…and ${errors.length - 20} more row error(s).</li>` : "";

  el.importResultSummary.innerHTML = `
    <div><strong>Import completed</strong> (${html(manifest.file_name || "file")})</div>
    <div class="import-summary-counts">
      <span>Accepted: ${html(accepted)}</span>
      <span>Duplicates skipped: ${html(dupes)}</span>
      <span>Rejected: ${html(rejected)}</span>
    </div>
    ${errors.length ? `<ul class="import-errors-list">${errorItems}${extraCount}</ul>` : ""}
  `;
  el.importResultSummary.hidden = false;
}

async function handleImportSubmit(e) {
  e.preventDefault();
  clearImportFeedback();

  const activeCls = getActiveClass();
  if (!activeCls) {
    showImportError("No active class selected.");
    return;
  }

  const file = el.importFile?.files?.[0];
  if (!file) {
    if (el.importFile) {
      el.importFile.setAttribute("aria-invalid", "true");
      el.importFile.focus();
    }
    showImportError("Choose a .csv or .json report file to import.");
    return;
  }

  const sourceSystem = el.importSourceSystem?.value.trim() || "";
  if (!sourceSystem) {
    if (el.importSourceSystem) {
      el.importSourceSystem.setAttribute("aria-invalid", "true");
      el.importSourceSystem.focus();
    }
    showImportError("Source system is required.");
    return;
  }

  const formData = new FormData();
  formData.append("file", file);
  formData.append("source_system", sourceSystem);

  const optionalFields = [
    ["academic_year", el.importYear?.value],
    ["term", el.importTerm?.value],
    ["observed_at", el.importObservedAt?.value],
    ["max_score", el.importMaxScore?.value],
    ["grade", el.importGrade?.value],
    ["assessment_stage", el.importStage?.value],
    ["form", el.importFormName?.value],
    ["form_version", el.importFormVersion?.value],
    ["language", el.importLanguage?.value],
    ["notes", el.importNotes?.value],
  ];
  for (const [key, rawVal] of optionalFields) {
    const cleaned = typeof rawVal === "string" ? rawVal.trim() : "";
    if (cleaned) formData.append(key, cleaned);
  }
  if (el.importComparisonAuthorized?.checked) {
    formData.append("comparison_authorized", "true");
  }

  if (el.btnSubmitImport) {
    el.btnSubmitImport.disabled = true;
    el.btnSubmitImport.textContent = "Importing…";
  }

  try {
    const summary = await api.importClassFile(activeCls.class_id, formData);
    renderImportSummary(summary);
    const accepted = summary.manifest?.accepted_count ?? 0;
    const rejected = summary.manifest?.rejected_count ?? 0;
    if (accepted > 0) {
      await refreshWorkspaceFromServer();
      toast(`Imported ${accepted} record${accepted === 1 ? "" : "s"} into ${activeCls.display_name}.`);
    } else if (rejected > 0) {
      showImportError("No records were imported. Review the row errors below and retry.");
    } else {
      toast("All rows in this file were already recorded (duplicates skipped).");
    }
  } catch (err) {
    showImportError(err.message);
  } finally {
    if (el.btnSubmitImport) {
      el.btnSubmitImport.disabled = false;
      el.btnSubmitImport.textContent = "Import file";
    }
  }
}

function downloadWideCsvTemplate() {
  const activeCls = getActiveClass();
  const isCT = isClassTeacherInActiveClass();
  const allowed = getAllowedSubjectsInActiveClass();
  const subjects = isCT || allowed.length === 0 ? ["Mathematics", "English", "Science"] : allowed;
  const subjHeaders = subjects.map((s) => `${s} (100)`).join(",");
  const year = activeCls?.academic_year || 2026;
  const term = activeCls?.term || 1;
  const grade = activeCls?.grade || "Grade 3";
  const today = new Date().toISOString().slice(0, 10);
  const sampleScores = subjects.map((_, idx) => (idx === 0 ? "78" : idx === 1 ? "84" : "absent")).join(",");
  const sampleScores2 = subjects.map((_, idx) => (idx === 0 ? "65/100" : "72")).join(",");
  const csv = [
    `learner_id,learner_name,grade,academic_year,term,observed_at,${subjHeaders}`,
    `LRN-101,Amina Hassan,${grade},${year},${term},${today},${sampleScores}`,
    `LRN-102,Brian Otieno,${grade},${year},${term},${today},${sampleScores2}`,
  ].join("\n");

  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `allps_marksheet_template_${activeCls?.class_id || "class"}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

// ── Class Switcher, DB Demo Sync & Global Event Bindings ─────────────────────

async function switchActiveClass(classId) {
  state.activeClassId = classId || null;
  state.activeLearnerId = null;
  state.learners = [];
  state.classReadiness = null;
  state.classChanges = [];
  state.publishedByLearner = {};
  if (el.learnerSelect) {
    el.learnerSelect.innerHTML = `<option value="">Loading learners…</option>`;
    el.learnerSelect.disabled = true;
  }
  try {
    return await loadActiveClassContext({ loadDb: false });
  } catch (err) {
    if (state.currentTeacher) {
      showWorkspaceStatus("error", `Could not load class data: ${err.message}`);
    }
    renderLearnerSelector();
    return false;
  }
}

async function handleReseed(mode = "merge") {
  if (state.isDbBusy) return;
  state.isDbBusy = true;
  try {
    const res = await api.reseedDatabase(mode);
    await bootstrapAuthenticatedSession();
    showWorkspaceStatus("success", res.message || `Database ${mode} completed.`);
  } catch (err) {
    showWorkspaceStatus("error", err.message);
  } finally {
    state.isDbBusy = false;
  }
}

function setupDialogLightDismiss(dialog) {
  if (!dialog || "closedBy" in HTMLDialogElement.prototype) return;
  const outside = (e) => {
    const r = dialog.getBoundingClientRect();
    return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
  };
  let pressedOutside = false;
  dialog.addEventListener("pointerdown", (e) => {
    pressedOutside = outside(e);
  });
  dialog.addEventListener("pointerup", (e) => {
    if (pressedOutside && outside(e)) dialog.close();
  });
}

function bindStaticEvents() {
  if (el.loginForm) el.loginForm.addEventListener("submit", handleLoginSubmit);
  if (el.btnTogglePin) el.btnTogglePin.addEventListener("click", handleTogglePinVisibility);
  if (el.btnRetryConnection) el.btnRetryConnection.addEventListener("click", checkSessionAndStart);
  if (el.loginTeacherId) el.loginTeacherId.addEventListener("input", clearLoginError);
  if (el.loginPin) el.loginPin.addEventListener("input", clearLoginError);
  if (el.btnAuthAction) el.btnAuthAction.addEventListener("click", handleLogout);

  if (el.sidebarToggle) {
    el.sidebarToggle.addEventListener("click", () =>
      toggleNavigation(!document.body.classList.contains("nav-open"))
    );
  }
  if (el.navOverlay) el.navOverlay.addEventListener("click", () => toggleNavigation(false));

  if (el.classSelect) {
    el.classSelect.addEventListener("change", async (e) => {
      const committed = await switchActiveClass(e.target.value);
      if (!committed) return;
      const [page] = route().parts;
      if (page === "learner") {
        if (state.activeLearnerId) {
          navigate(learnerLink(state.activeLearnerId, "student"));
        } else {
          navigate("#class");
        }
      } else {
        renderCurrentRoute(false);
      }
    });
  }

  if (el.learnerSelect) {
    el.learnerSelect.addEventListener("change", (e) => {
      state.activeLearnerId = e.target.value || null;
      const [page, , scope] = route().parts;
      if (page === "learner" && state.activeLearnerId) {
        navigate(learnerLink(state.activeLearnerId, scope || "student"));
      } else {
        renderCurrentRoute(false);
      }
    });
  }

  if (el.btnDismissWorkspaceStatus) {
    el.btnDismissWorkspaceStatus.addEventListener("click", clearWorkspaceStatus);
  }
  if (el.btnRefreshData) {
    el.btnRefreshData.addEventListener("click", () => refreshWorkspaceFromServer({ showToast: true }));
  }
  if (el.btnSeedMerge) {
    el.btnSeedMerge.addEventListener("click", () => handleReseed("merge"));
  }
  if (!("commandForElement" in HTMLButtonElement.prototype) && el.btnOpenResetDialog && el.resetDbDialog) {
    el.btnOpenResetDialog.addEventListener("click", () => el.resetDbDialog.showModal());
  }
  if (el.resetDbDialog) {
    el.resetDbDialog.addEventListener("close", () => {
      const rv = el.resetDbDialog.returnValue;
      el.resetDbDialog.returnValue = "";
      if (rv === "confirm") handleReseed("reset");
    });
  }

  if (el.cancelRelease) el.cancelRelease.addEventListener("click", () => el.releaseDialog.close());
  if (el.confirmRelease) {
    el.confirmRelease.addEventListener("click", async () => {
      if (!state.activeClassId) return;
      el.confirmRelease.disabled = true;
      try {
        const notes = el.releaseNotesInput?.value || null;
        const res = await api.releaseClass(state.activeClassId, notes);
        el.releaseDialog.close();
        state.recordedViews.clear();
        await refreshWorkspaceFromServer();
        toast(`Class handover v${res.release.version_number} released.`);
      } catch (err) {
        showWorkspaceStatus("error", err.message);
      } finally {
        el.confirmRelease.disabled = false;
      }
    });
  }

  if (el.btnCloseObservation) el.btnCloseObservation.addEventListener("click", () => el.observationDialog.close());
  if (el.btnCancelObservation) el.btnCancelObservation.addEventListener("click", () => el.observationDialog.close());
  if (el.btnPreviewObservation) el.btnPreviewObservation.addEventListener("click", handleObservationPreview);
  if (el.btnBackToEditObservation) {
    el.btnBackToEditObservation.addEventListener("click", () => {
      el.previewDialog.close();
      el.observationDialog.showModal();
    });
  }
  if (el.btnConfirmSaveObservation) el.btnConfirmSaveObservation.addEventListener("click", handleSaveObservation);

  if (el.btnCloseImport) el.btnCloseImport.addEventListener("click", () => el.importDialog.close());
  if (el.btnCancelImport) el.btnCancelImport.addEventListener("click", () => el.importDialog.close());
  if (el.importForm) el.importForm.addEventListener("submit", handleImportSubmit);
  if (el.importFile) el.importFile.addEventListener("change", clearImportFeedback);

  [el.detailDialog, el.releaseDialog, el.observationDialog, el.previewDialog, el.resetDbDialog, el.importDialog].forEach(
    setupDialogLightDismiss
  );

  window.addEventListener("hashchange", () => {
    if (el.detailDialog?.open) el.detailDialog.close();
    toggleNavigation(false);
    renderCurrentRoute(true);
    if (el.main) el.main.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: "instant" });
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") toggleNavigation(false);
  });

  document.addEventListener("change", (e) => {
    const key = e.target.dataset?.filter;
    if (!key) return;
    const cur = route();
    const q = cur.query;
    if (e.target.value === "all") q.delete(key);
    else q.set(key, e.target.value);
    navigate(`#${cur.parts.join("/")}${q.size ? `?${q}` : ""}`);
  });

  document.addEventListener("input", (e) => {
    if (!e.target.hasAttribute("data-search-input")) return;
    const query = e.target.value.trim().toLowerCase();
    let count = 0;
    document.querySelectorAll("[data-search]").forEach((row) => {
      const match = row.dataset.search.includes(query);
      row.hidden = !match;
      if (match) count += 1;
    });
    const counter = document.querySelector("[data-row-count]");
    if (counter) {
      const [page] = route().parts;
      const noun = page === "records" ? "records" : page === "class" ? "learners" : "reviews";
      counter.textContent = `${count} ${noun} shown${query ? ` for “${e.target.value.trim()}”` : ""}`;
    }
  });

  document.addEventListener("click", async (e) => {
    if (e.target.closest("[data-close-detail]") && el.detailDialog?.open) {
      el.detailDialog.close();
    }
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const { action, id, section, releaseId, classId, changeId, reviewId, status, revision, correction } = btn.dataset;

    if (action === "close-detail") {
      if (el.detailDialog?.open) el.detailDialog.close();
    } else if (action === "source") {
      await openSourceModal(id);
    } else if (action === "open-observation") {
      openObservationDialog();
    } else if (action === "open-import") {
      openImportDialog();
    } else if (action === "download-wide-csv-template") {
      downloadWideCsvTemplate();
    } else if (action === "release") {
      openReleaseModal();
    } else if (action === "edit-section") {
      openSectionReviewModal(id, section);
    } else if (action === "change-detail") {
      openChangeDetailModal(id);
    } else if (action === "ack-report") {
      btn.disabled = true;
      try {
        await api.acknowledgeReport(releaseId, id);
        toast("Receipt acknowledged separately from viewing.");
        await refreshWorkspaceFromServer();
      } catch (err) {
        showWorkspaceStatus("error", err.message);
        btn.disabled = false;
      }
    } else if (action === "review-change") {
      btn.disabled = true;
      try {
        await api.markChangeReviewed(classId, changeId);
        toast("Post-release change marked as reviewed.");
        await refreshWorkspaceFromServer();
      } catch (err) {
        showWorkspaceStatus("error", err.message);
        btn.disabled = false;
      }
    } else if (action === "generate-brief") {
      if (state.isGenerating) return;
      state.isGenerating = true;
      const subj = document.getElementById("ai-subject-select")?.value || null;
      const mode = document.getElementById("ai-mode-select")?.value || "auto";
      renderCurrentRoute(false);
      try {
        const res = await api.generateHandover(id, subj, mode);
        state.generationResultByLearner[id] = res;
        await refreshWorkspaceFromServer();
        toast("Candidate handover synthesis completed.");
      } catch (err) {
        showWorkspaceStatus("error", err.message);
      } finally {
        state.isGenerating = false;
        renderCurrentRoute(false);
      }
    } else if (action === "toggle-correction") {
      const box = document.getElementById(`corr-${reviewId}`);
      if (box) box.hidden = !box.hidden;
    } else if (action === "decide-review") {
      const isCorrection = correction === "true";
      const notesEl = isCorrection
        ? document.getElementById(`corr-notes-${reviewId}`)
        : document.getElementById(`notes-${reviewId}`);
      const notes = notesEl ? notesEl.value : "";
      btn.disabled = true;
      try {
        await api.postReviewDecision(reviewId, status, notes, parseInt(revision || "0", 10), isCorrection);
        toast(isCorrection ? "Correction recorded." : "Teacher decision recorded.");
        await refreshWorkspaceFromServer();
      } catch (err) {
        if (err.status === 409) {
          showWorkspaceStatus("conflict", `Concurrency conflict: ${err.message} Reloaded latest revision.`);
          await refreshWorkspaceFromServer();
        } else {
          showWorkspaceStatus("error", err.message);
          btn.disabled = false;
        }
      }
    }
  });

  document.addEventListener("submit", async (e) => {
    const form = e.target;
    if (form.id === "section-review-form") {
      e.preventDefault();
      const { classId, id, section } = form.dataset;
      const reviewState = form.elements.review_state.value;
      const summary = form.elements.approved_summary.value.trim();
      const disclosure = form.elements.missing_evidence_disclosure.value.trim();
      const notes = form.elements.teacher_notes.value.trim();
      const errEl = document.getElementById("section-review-error");

      if (!validateSafeText(summary, errEl, true)) return;
      if (disclosure && !validateSafeText(disclosure, errEl, false)) return;
      if (notes && !validateSafeText(notes, errEl, false)) return;

      const citations = Array.from(form.querySelectorAll('input[name="citations"]:checked')).map(
        (cb) => cb.value
      );

      const submitBtn = document.getElementById("btn-save-section-review");
      if (submitBtn) submitBtn.disabled = true;
      try {
        await api.updateSectionReview(classId, id, section, {
          review_state: reviewState,
          approved_summary: summary,
          missing_evidence_disclosure: disclosure || null,
          teacher_notes: notes || null,
          citations,
        });
        if (el.detailDialog?.open) el.detailDialog.close();
        await refreshWorkspaceFromServer();
        toast("Section review decision saved.");
      } catch (err) {
        if (errEl) errEl.textContent = err.message;
        if (submitBtn) submitBtn.disabled = false;
      }
    } else if (form.id === "subject-response-form") {
      e.preventDefault();
      const { releaseId, id, subject } = form.dataset;
      const content = form.elements.content.value.trim();
      const responseType = form.elements.response_type.value;
      const errEl = document.getElementById("response-error");
      if (!validateSafeText(content, errEl, true)) return;

      try {
        await api.addSubjectResponse(releaseId, id, {
          subject,
          response_type: responseType,
          content,
        });
        await refreshWorkspaceFromServer();
        toast("Subject response attached beneath the approved review.");
      } catch (err) {
        if (errEl) errEl.textContent = err.message;
      }
    }
  });
}

document.addEventListener("DOMContentLoaded", init);
