import { initialJson, state } from "/static/js/state.js";
import { flagUnauthorizedIfNeeded, hydrateBatchJobFromUrl, loadAuthStatus, pollBatchJob, readJsonResponse } from "/static/js/services.js";
import { renderApp } from "/static/js/view.js";
import { getFullPath, safeRevoke } from "/static/js/utils.js";

const root = document.getElementById("root");

function render() {
  root.innerHTML = renderApp();
}

function revokeBatchPreviewUrls(urlMap) {
  Object.values(urlMap || {}).forEach((url) => safeRevoke(url));
}

function clearStateAndUrls() {
  safeRevoke(state.applicationPreviewUrl);
  safeRevoke(state.applicationSourceUrl);
  safeRevoke(state.labelPreviewUrl);
  revokeBatchPreviewUrls(state.batchApplicationPreviewUrls);
  revokeBatchPreviewUrls(state.batchLabelPreviewUrls);

  state.batchRunToken = Date.now();
  state.applicationFile = null;
  state.applicationFilePath = "";
  state.applicationFileDisplay = "";
  state.labelFile = null;
  state.labelFilePath = "";
  state.labelFileDisplay = "";
  state.applicationJson = initialJson;
  state.labelPreviewUrl = "";
  state.applicationPreviewUrl = "";
  state.applicationSourceUrl = "";
  state.batchApplicationFiles = [];
  state.batchApplicationFileDisplay = "";
  state.batchApplicationPreviewUrls = {};
  state.batchLabelFiles = [];
  state.batchLabelFileDisplay = "";
  state.batchLabelPreviewUrls = {};
  state.batchMappingFile = null;
  state.batchMappingFileDisplay = "";
  state.batchJobId = null;
  state.batchStatus = null;
  state.batchProgress = { completed: 0, total: 0 };
  state.batchResults = null;
  state.batchSelectedItem = null;
  state.result = null;

  const url = new URL(window.location.href);
  url.searchParams.delete("batch_job_id");
  window.history.replaceState({}, "", url);
  state.status = { type: "idle", message: "Form cleared. Ready for a new check." };
}

async function submitBatchJob() {
  if (!state.batchApplicationFiles.length || !state.batchLabelFiles.length) {
    state.status = { type: "error", message: "Select one or more application PDFs and one or more label images to start a batch job." };
    render();
    return;
  }

  state.batchRunToken = Date.now();
  const activeToken = state.batchRunToken;
  state.batchJobId = null;
  state.batchStatus = null;
  state.batchProgress = { completed: 0, total: 0 };
  state.batchResults = null;
  state.batchSelectedItem = null;
  state.loading = true;
  state.status = { type: "idle", message: "Starting batch job..." };
  render();

  try {
    const formData = new FormData();
    state.batchApplicationFiles.forEach((file) => {
      formData.append("application_files", file, file.name);
    });
    state.batchLabelFiles.forEach((file) => {
      formData.append("label_files", file, file.name);
    });
    if (state.batchMappingFile) {
      formData.append("mapping_file", state.batchMappingFile, state.batchMappingFile.name);
    }

    const response = await fetch("/api/batch", { method: "POST", body: formData });
    const data = await readJsonResponse(response);
    if (!response.ok || data.error) {
      flagUnauthorizedIfNeeded(response);
      throw new Error(data.detail || data.error || "Batch job failed");
    }

    state.batchJobId = data.job_id;
    state.batchStatus = data.status;
    state.batchProgress = data.progress || { completed: 0, total: 0 };
    state.status = { type: "success", message: "Batch job started. Polling for status..." };
    render();
    await pollBatchJob(data.job_id, activeToken, render);
  } catch (error) {
    state.loading = false;
    state.status = { type: "error", message: error.message || "Batch job failed." };
    render();
  }
}

async function verifyCase() {
  state.result = null;

  if (!state.labelFile) {
    state.status = { type: "error", message: "Please select the label image." };
    render();
    return;
  }
  if (!state.applicationFile && !state.applicationJson.trim()) {
    state.status = { type: "error", message: "Please provide application data or upload an application PDF file." };
    render();
    return;
  }

  state.loading = true;
  state.status = { type: "idle", message: "Verifying label against application data..." };
  render();

  try {
    const formData = new FormData();
    if (state.applicationFile) {
      formData.append("application_file", state.applicationFile, state.applicationFile.name);
    } else {
      formData.append("application", state.applicationJson);
    }
    formData.append("file", state.labelFile, state.labelFile.name);

    const response = await fetch("/api/verify", { method: "POST", body: formData });
    const data = await readJsonResponse(response);

    if (!response.ok || data.error) {
      flagUnauthorizedIfNeeded(response);
      throw new Error(data.detail || data.error || "Verification failed");
    }

    state.result = data;
    state.status = {
      type: "success",
      message: data.status === "llm_review_pending" || data.status === "llm_review_in_progress"
        ? "Verification completed with LLM review requested."
        : "Verification complete.",
    };
  } catch (error) {
    state.status = { type: "error", message: error.message || "Verification failed." };
  } finally {
    state.loading = false;
    render();
  }
}

async function saveOverride() {
  if (!state.result || !(state.result.result_id || state.result.application_id) || !state.overrideModal) {
    return;
  }

  const fieldName = state.overrideModal.field;
  const decisionInputs = document.querySelectorAll('input[name="overrideDecision"]:checked');
  const selectedDecision = decisionInputs.length ? decisionInputs[0].value : "match";
  const overrideValue = document.getElementById("overrideValueInput")?.value || "";
  const comment = document.getElementById("overrideCommentInput")?.value || "";

  const resultId = state.result.result_id || state.result.application_id;
  const formData = new FormData();
  formData.append("field_name", fieldName);
  formData.append("decision", selectedDecision === "match" ? "approve" : "disapprove");
  formData.append("override_value", overrideValue);
  formData.append("comment", comment);

  state.status = { type: "idle", message: `Saving ${fieldName} override...` };
  state.overrideModal = null;
  render();

  try {
    const response = await fetch(`/api/results/${resultId}/review`, { method: "POST", body: formData });
    const data = await readJsonResponse(response);
    if (!response.ok || data.error) {
      flagUnauthorizedIfNeeded(response);
      throw new Error(data.detail || data.error || "Override save failed");
    }
    state.result = data;
    state.status = { type: "success", message: `Manual override saved for ${fieldName}.` };
  } catch (error) {
    state.status = { type: "error", message: error.message || "Override save failed." };
  } finally {
    render();
  }
}

async function loginUser() {
  const usernameInput = document.getElementById("loginUsername");
  const passwordInput = document.getElementById("loginPassword");
  const username = usernameInput ? usernameInput.value : "";
  const password = passwordInput ? passwordInput.value : "";

  if (!username.trim() || !password) {
    state.loginError = "Enter both a username and password.";
    render();
    return;
  }

  state.loginLoading = true;
  state.loginError = "";
  render();

  try {
    const formData = new FormData();
    formData.append("username", username);
    formData.append("password", password);
    const response = await fetch("/api/login", { method: "POST", body: formData });
    const data = await readJsonResponse(response);
    if (!response.ok || data.error) {
      throw new Error(data.detail || data.error || "Login failed.");
    }
    state.auth.authenticated = true;
    state.auth.user = data.user || null;
    state.loginError = "";
  } catch (error) {
    state.loginError = error.message || "Login failed.";
  } finally {
    state.loginLoading = false;
    render();
  }
}

async function logoutUser() {
  try {
    await fetch("/api/logout", { method: "POST" });
  } catch {
    // Ignore network errors on logout; clear local auth state regardless.
  }
  state.auth.authenticated = false;
  state.auth.user = null;
  clearStateAndUrls();
  render();
}

function handleChange(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;

  if (target.id === "applicationFile") {
    const input = target;
    const file = input.files && input.files[0];
    if (!file) return;

    const lowerName = file.name.toLowerCase();
    if (!lowerName.endsWith(".pdf") && file.type !== "application/pdf") {
      state.status = { type: "error", message: "Only PDF application files are supported at this time." };
      input.value = "";
      render();
      return;
    }

    safeRevoke(state.applicationPreviewUrl);
    safeRevoke(state.applicationSourceUrl);

    const selectedPath = input.value || file.name || "";
    state.applicationFile = file;
    state.applicationFilePath = selectedPath;
    state.applicationFileDisplay = `Selected: ${file.name || selectedPath}`;
    state.applicationJson = "";
    state.applicationPreviewUrl = URL.createObjectURL(file);
    state.applicationSourceUrl = state.applicationPreviewUrl;
    state.status = { type: "success", message: `Loaded ${selectedPath}. PDF application detected; the server will extract the required fields.` };
    render();
    return;
  }

  if (target.id === "labelFile") {
    const input = target;
    const file = input.files && input.files[0];
    if (!file) return;

    safeRevoke(state.labelPreviewUrl);
    const selectedPath = input.value || file.name || "";
    state.labelFile = file;
    state.labelFilePath = selectedPath;
    state.labelFileDisplay = `Selected: ${file.name || selectedPath}`;
    state.labelPreviewUrl = URL.createObjectURL(file);
    state.status = { type: "success", message: `Label selected: ${selectedPath}.` };
    render();
    return;
  }

  if (target.id === "batchApplicationFiles") {
    revokeBatchPreviewUrls(state.batchApplicationPreviewUrls);
    state.batchApplicationFiles = Array.from(target.files || []);
    state.batchApplicationFileDisplay = state.batchApplicationFiles.length
      ? `Selected: ${state.batchApplicationFiles.map((file) => file.name || getFullPath(file, "")).join(", ")}`
      : "";
    state.batchApplicationPreviewUrls = {};
    state.batchApplicationFiles.forEach((file) => {
      if (file.name) state.batchApplicationPreviewUrls[file.name] = URL.createObjectURL(file);
    });
    render();
    return;
  }

  if (target.id === "batchLabelFiles") {
    revokeBatchPreviewUrls(state.batchLabelPreviewUrls);
    state.batchLabelFiles = Array.from(target.files || []);
    state.batchLabelFileDisplay = state.batchLabelFiles.length
      ? `Selected: ${state.batchLabelFiles.map((file) => file.name || getFullPath(file, "")).join(", ")}`
      : "";
    state.batchLabelPreviewUrls = {};
    state.batchLabelFiles.forEach((file) => {
      if (file.name) state.batchLabelPreviewUrls[file.name] = URL.createObjectURL(file);
    });
    render();
    return;
  }

  if (target.id === "batchMappingFile") {
    const file = target.files && target.files[0];
    state.batchMappingFile = file || null;
    state.batchMappingFileDisplay = file ? `Selected: ${file.name || ""}` : "";
    render();
  }
}

async function handleClick(event) {
  const loginButton = event.target.closest("#loginSubmitButton");
  if (loginButton) {
    await loginUser();
    return;
  }

  const logoutButton = event.target.closest("#logoutButton");
  if (logoutButton) {
    await logoutUser();
    return;
  }

  const navButton = event.target.closest(".nav-button");
  if (navButton) {
    state.activeTab = navButton.dataset.tab;
    render();
    return;
  }

  const clearButton = event.target.closest("#clearForm");
  if (clearButton) {
    clearStateAndUrls();
    render();
    return;
  }

  const verifyButton = event.target.closest("#verifyCaseButton");
  if (verifyButton) {
    await verifyCase();
    return;
  }

  const batchButton = event.target.closest("#submitBatchButton");
  if (batchButton) {
    await submitBatchJob();
    return;
  }

  const batchActionButton = event.target.closest("[data-batch-action]");
  if (batchActionButton && state.batchResults) {
    const action = batchActionButton.dataset.batchAction;
    const items = state.batchResults.results || [];

    if (action === "view-details") {
      const index = Number(batchActionButton.dataset.index);
      const selected = items.find((item) => item.index === index) || null;
      if (selected) {
        const selectedResult = selected.result && Object.keys(selected.result).length ? selected.result : null;
        state.batchSelectedItem = selected;
        state.result = selectedResult || {
          filename: selected.label_file || "Batch item",
          application: {},
          parsed: {},
          comparisons: {},
          overall: selected.overall || "need_review",
          status: selected.status || "ready",
          status_message: "No detailed result payload was available for this item.",
          application_source_type: "batch",
          source_files: {
            application: selected.application_file || "Application file",
            label: selected.label_file || "Label file",
          },
        };
      }
      render();
      return;
    }

    if (action === "close-details") {
      state.batchSelectedItem = null;
      render();
      return;
    }
  }

  const manualOverrideButton = event.target.closest(".manual-override");
  if (manualOverrideButton && state.result && (state.result.result_id || state.result.application_id)) {
    const fieldName = manualOverrideButton.dataset.field;
    const fieldEntry = (state.result.comparisons && state.result.comparisons[fieldName]) || {};
    const currentStatus = fieldEntry.status || "need_review";
    const currentOverrideValue = fieldEntry.override_value || fieldEntry.app || fieldEntry.label || "";
    const currentComment = fieldEntry.comment || "";
    state.overrideModal = {
      field: fieldName,
      label: manualOverrideButton.closest("tr")?.children[0]?.textContent || fieldName,
      decision: currentStatus === "pass" ? "match" : "unmatch",
      overrideValue: currentOverrideValue,
      comment: currentComment,
    };
    render();
    return;
  }

  const closeOverride = event.target.closest('[data-action="close-override"]');
  if (closeOverride) {
    state.overrideModal = null;
    render();
    return;
  }

  const saveOverrideButton = event.target.closest(".override-save-btn");
  if (saveOverrideButton) {
    await saveOverride();
  }
}

document.addEventListener("change", handleChange);
document.addEventListener("click", (event) => {
  void handleClick(event);
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  if (target.id === "loginUsername" || target.id === "loginPassword") {
    event.preventDefault();
    void loginUser();
  }
});

render();
void hydrateBatchJobFromUrl(render);
void (async function bootstrapAuth() {
  await loadAuthStatus();
  render();
})();
