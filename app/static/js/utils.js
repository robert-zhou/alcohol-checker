export function getFullPath(file, filePath) {
  if (filePath) return filePath;
  if (!file) return "";
  return file.path || file.name || "";
}

export function formatValue(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "-";
  return String(value);
}

export function formatOverallLabel(value) {
  const normalized = String(value || "").trim().toLowerCase().replace(/\s+/g, "_");
  if (normalized === "pass" || normalized === "match" || normalized === "approve") return "Pass";
  if (normalized === "fail" || normalized === "failure" || normalized === "mismatch" || normalized === "disapprove" || normalized === "not_match" || normalized === "not-match") return "Failure";
  if (normalized === "review" || normalized === "need_review") return "Need review";
  return "Need review";
}

export function formatFieldStatusLabel(value) {
  const normalized = String(value || "").trim().toLowerCase().replace(/\s+/g, "_");
  if (normalized === "pass" || normalized === "match") return "Pass";
  if (normalized === "failure" || normalized === "fail" || normalized === "mismatch") return "Failure";
  if (normalized === "need_review" || normalized === "review" || normalized === "suspect" || normalized === "missing") return "Need review";
  return normalized ? normalized.replace(/_/g, " ") : "Need review";
}

export function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

export function getBatchJobUrl(jobId) {
  if (!jobId) return "";
  const url = new URL(window.location.href);
  url.searchParams.set("batch_job_id", jobId);
  return url.toString();
}

export function safeRevoke(url) {
  if (url) URL.revokeObjectURL(url);
}
