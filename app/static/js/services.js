import { state } from "/static/js/state.js";

export async function readJsonResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  const bodyText = await response.text();
  if (!bodyText) {
    return {};
  }

  const trimmed = bodyText.trim();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      return JSON.parse(trimmed);
    } catch {
      throw new Error(`Server returned invalid JSON: ${trimmed.slice(0, 200)}`);
    }
  }

  if (contentType.includes("application/json")) {
    try {
      return JSON.parse(trimmed);
    } catch {
      throw new Error(`Server returned invalid JSON: ${trimmed.slice(0, 200)}`);
    }
  }

  throw new Error(trimmed.slice(0, 200) || "The server returned an unexpected response.");
}

export async function loadAuthStatus() {
  try {
    const response = await fetch("/api/session");
    const data = await readJsonResponse(response);
    state.auth.required = Boolean(data.auth_required);
    state.auth.authenticated = Boolean(data.authenticated);
    state.auth.user = data.user || null;
  } catch {
    // If the session check itself fails, fail open only when auth isn't required elsewhere.
    state.auth.required = false;
    state.auth.authenticated = true;
  } finally {
    state.auth.checked = true;
  }
}

export function flagUnauthorizedIfNeeded(response) {
  if (response.status === 401 && state.auth.required) {
    state.auth.authenticated = false;
  }
}


export async function pollBatchJob(jobId, runToken, render) {
  try {
    const response = await fetch(`/api/jobs/${jobId}`);
    if (runToken !== state.batchRunToken) return;

    if (!response.ok) {
      const errorData = await readJsonResponse(response).catch(() => ({}));
      state.batchStatus = "not_found";
      state.status = {
        type: "error",
        message: errorData.detail || errorData.error || `Batch job ${jobId} no longer exists.`,
      };
      const url = new URL(window.location.href);
      url.searchParams.delete("batch_job_id");
      window.history.replaceState({}, "", url);
      render();
      return;
    }

    const data = await readJsonResponse(response);
    if (runToken !== state.batchRunToken) return;

    state.batchJobId = jobId;
    state.batchStatus = data.status;
    state.batchProgress = data.progress || { completed: 0, total: 0 };
    state.batchResults = data.result || null;
    state.status = {
      type: data.status === "failed" ? "error" : "success",
      message: data.error ? data.error : `Batch job ${data.status}. ${data.progress ? `${data.progress.completed}/${data.progress.total} processed` : ""}`,
    };

    if (window.location.search.indexOf("batch_job_id=") === -1) {
      const url = new URL(window.location.href);
      url.searchParams.set("batch_job_id", jobId);
      window.history.replaceState({}, "", url);
    }

    if (data.status === "completed" || data.status === "failed") {
      state.loading = false;
      render();
      return;
    }

    render();
    setTimeout(() => pollBatchJob(jobId, runToken, render), 2500);
  } catch (error) {
    if (runToken !== state.batchRunToken) return;
    state.batchStatus = "error";
    state.status = { type: "error", message: error.message || "Unable to reach batch job status." };
    render();
  }
}

export async function hydrateBatchJobFromUrl(render) {
  const params = new URLSearchParams(window.location.search);
  const jobId = params.get("batch_job_id");
  if (!jobId) return;

  state.activeTab = "batch";
  state.batchRunToken = Date.now();
  const activeToken = state.batchRunToken;
  state.batchJobId = jobId;
  state.loading = true;
  state.status = { type: "idle", message: `Loading batch job ${jobId}...` };
  render();
  await pollBatchJob(jobId, activeToken, render);
}
