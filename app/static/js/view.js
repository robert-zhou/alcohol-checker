import { state } from "/static/js/state.js";
import { escapeHtml, formatFieldStatusLabel, formatOverallLabel, formatValue, getBatchJobUrl, getFullPath } from "/static/js/utils.js";

function renderEmptyState() {
  if (state.loading) {
    return `
      <div class="results-loading-state">
        <div class="results-loading-spinner"></div>
        <div style="font-size: 1.1rem; font-weight: 700; margin-bottom: 6px;">Verifying case...</div>
        <div>This can take a few seconds while the label image is analyzed.</div>
      </div>
    `;
  }

  return `
    <div style="color: #5a6d88; text-align: center; padding-top: 120px;">
      <div style="font-size: 2.4rem; margin-bottom: 8px;">Receipt</div>
      <div style="font-size: 1.1rem; font-weight: 700; margin-bottom: 6px;">No case reviewed yet</div>
      <div>Upload an application PDF and a label image to start the review.</div>
    </div>
  `;
}

function renderStatus() {
  const type = state.status.type === "error" ? "error" : state.status.type === "success" ? "success" : "";
  return `<div class="status ${type}">${state.status.message}</div>`;
}

function renderBatchStatus() {
  if (!state.batchJobId && !state.batchStatus && !state.batchResults) {
    return "";
  }

  const total = state.batchProgress.total || 0;
  const completed = state.batchProgress.completed || 0;
  const percent = total > 0 ? Math.round((completed / total) * 100) : 0;
  const summary = state.batchResults?.summary || null;

  return `
    <div class="batch-status-panel">
      <div class="batch-status-header">
        <div>
          <div class="batch-status-label">Batch progress</div>
          <div class="batch-status-title">${state.batchStatus || "queued"}</div>
        </div>
        <span class="batch-pill">${percent}%</span>
      </div>

      <div class="batch-progress-bar">
        <span style="width: ${Math.min(100, percent)}%"></span>
      </div>

      <div class="batch-metrics">
        <div>
          <div class="batch-mini-label">Job ID</div>
          <div class="batch-mini-value">${state.batchJobId || "n/a"}</div>
        </div>
        <div>
          <div class="batch-mini-label">Processed</div>
          <div class="batch-mini-value">${completed} / ${total || summary?.processed || 0}</div>
        </div>
        <div>
          <div class="batch-mini-label">Total files</div>
          <div class="batch-mini-value">${summary?.label_count || total || 0}</div>
        </div>
      </div>

      ${state.batchJobId ? `
        <div class="batch-link-row">
          <span>Job link</span>
          <a href="${getBatchJobUrl(state.batchJobId)}" target="_blank" rel="noreferrer">${state.batchJobId}</a>
        </div>
      ` : ""}

      ${summary ? `<div class="batch-summary">${summary.processed || 0} case(s) completed</div>` : ""}
    </div>
  `;
}

function categorizeReason(detailText, isManualOverride) {
  const detail = String(detailText || "").trim();
  if (isManualOverride) {
    return { category: "Others", detail: detail || "Manual override applied by reviewer." };
  }
  const lowered = detail.toLowerCase();
  const formatMarkers = [
    "local policy",
    "format",
    "upper case",
    "boldness",
    "case-exact",
    "does not start with",
    "tiny text",
    "legibility",
  ];
  if (formatMarkers.some((marker) => lowered.includes(marker))) {
    return { category: "Label format error", detail: detail || "Label formatting or compliance rule did not pass." };
  }
  const mismatchMarkers = [
    "differs",
    "mismatch",
    "close but not exact",
    "similar but not exact",
    "reasonably close but not exact",
  ];
  if (mismatchMarkers.some((marker) => lowered.includes(marker))) {
    return { category: "Mismatch between application and label", detail: detail || "Extracted label value does not match application data." };
  }
  return { category: "Others", detail: detail || "Additional review context provided." };
}

function renderReasonCell(status, entry, isManualOverride) {
  if (status === "pass") {
    return "-";
  }

  const detail = isManualOverride
    ? (entry.comment ? `Manual override: ${entry.comment}` : "Manual override applied.")
    : (entry.reason || "No reason supplied.");
  const categorized = categorizeReason(detail, isManualOverride);
  return `<strong>${escapeHtml(categorized.category)}:</strong> ${escapeHtml(categorized.detail)}`;
}

function renderResults(resultData = state.result, context = {}) {
  if (!resultData) return renderEmptyState();

  const result = resultData;
  const parsed = result.parsed || {};
  const comparisons = result.comparisons || {};
  const rows = [
    ["brand", "Brand"],
    ["producer", "Producer"],
    ["class", "Class"],
    ["abv", "ABV"],
    ["net_contents", "Net contents"],
    ["government_warning", "Government warning"],
    ["country_of_origin", "Country of origin"],
  ];
  const applicationSource = context.applicationSource || result.source_files?.application || "Application data provided";
  const labelSource = context.labelSource || result.source_files?.label || "Label image attached";
  const applicationLink = context.applicationTargetUrl || (context.isBatchDetail ? "" : (state.applicationPreviewUrl || state.applicationSourceUrl)) || "#";
  const labelPreview = context.labelTargetUrl || (context.isBatchDetail ? "" : state.labelPreviewUrl) || "";
  const caseResult = result.case_result || { status: result.overall || "need_review", confidence: result.overall_confidence };
  const caseStatusLabel = formatOverallLabel(caseResult.status || result.overall || "need_review");

  return `
    <div class="top-case-hero ${caseResult.status || "need_review"}">
      <div class="top-case-main">${caseStatusLabel}</div>
      <div class="top-case-sub">Case confidence: ${caseResult.confidence === null || caseResult.confidence === undefined ? "n/a" : `${Number(caseResult.confidence).toFixed(0)}%`}</div>
    </div>

    <div class="summary-card">
      <div style="display: flex; justify-content: space-between; align-items: center; gap: 12px;">
        <div>
          <div style="color: #5a6d88; font-size: 0.75rem; letter-spacing: 0.08em; text-transform: uppercase;">Case summary</div>
          <div style="font-size: 1.2rem; font-weight: 800; margin-top: 6px;">${result.filename || "Uploaded label"}</div>
        </div>
        <span class="badge ${caseResult.status || "need_review"}">${caseStatusLabel}</span>
      </div>

      <div class="file-rail">
        <div class="source-card">
          <div class="source-title">Application file</div>
          ${applicationLink && applicationLink !== "#" ?
            `<a href="${applicationLink}" target="_blank" rel="noreferrer">${applicationSource}</a>` :
            `<div class="source-value">${applicationSource}</div>`}
          <div class="source-meta">Type: ${result.application_source_type || "pdf"}</div>
        </div>
        <div class="source-card">
          <div class="source-title">Label image</div>
          ${labelPreview ?
            `<a href="${labelPreview}" target="_blank" rel="noreferrer"><img src="${labelPreview}" alt="Uploaded label preview" class="label-preview" /></a>` :
            `<div class="source-value">${labelSource}</div>`}
        </div>
      </div>
    </div>

    <table>
      <thead>
        <tr>
          <th>Field</th>
          <th>Label value</th>
          <th>Application value</th>
          <th>Result</th>
          <th>Confidence</th>
          <th>Reason</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(([key, label]) => {
          const entry = comparisons[key] || {};
          const status = entry.status || "unknown";
          const confidence = entry.confidence ?? "n/a";
          const overrideValue = entry.override_value ?? "";
          const isManualOverride = Boolean(overrideValue && entry.review_decision !== undefined);
          const appValue = formatValue(entry.app ?? entry.app_ml ?? "-");
          const labelValue = formatValue(entry.label ?? entry.label_ml ?? "-");
          const statusLabel = formatFieldStatusLabel(status);
          const resultDisplay = isManualOverride ? `${statusLabel} / ${overrideValue}` : statusLabel;
          const reason = renderReasonCell(status, entry, isManualOverride);
          const rowClass = status === "failure" ? "failure-row" : status === "need_review" ? "review-row" : "pass-row";
          const labelCell = labelValue === "-" ? "-" : (labelPreview ? `<a href="${labelPreview}" target="_blank" rel="noreferrer" class="inline-link">${labelValue}</a>` : labelValue);
          const applicationCell = appValue === "-" ? "-" : (applicationLink !== "#" ? `<a href="${applicationLink}" target="_blank" rel="noreferrer" class="inline-link">${appValue}</a>` : appValue);
          const overrideSuffix = isManualOverride ? '<span class="override-pill">manual</span>' : "";
          return `<tr class="${rowClass}"><td>${label}</td><td>${labelCell}</td><td>${applicationCell}${overrideSuffix}</td><td><span class="badge ${status}">${resultDisplay}</span></td><td>${String(confidence)}</td><td class="reason">${reason}</td><td><button type="button" class="secondary manual-override" data-field="${key}">Manual override</button></td></tr>`;
        }).join("")}
      </tbody>
    </table>

    <div class="final-decision-panel">
      ${result.debug ? `
        <details>
          <summary>Parsed extraction details</summary>
          <pre>${escapeHtml(JSON.stringify(parsed, null, 2))}</pre>
        </details>
      ` : ""}
    </div>
  `;
}

function renderBatchResults() {
  if (!state.batchResults || !Array.isArray(state.batchResults.results) || !state.batchResults.results.length) {
    return '<div class="empty-batch-state">No batch results yet. Upload a batch and run the job to review them.</div>';
  }

  const items = state.batchResults.results;
  const summary = state.batchResults.summary || {};

  return `
    <div class="batch-results-wrap">
      <div class="batch-queue-head">
        <div>
          <div class="section-title" style="margin-bottom: 6px;">Batch review queue</div>
          <div class="batch-queue-meta">Job ID: <strong>${state.batchJobId || "n/a"}</strong></div>
        </div>
      </div>

      <div class="batch-summary-row">
        <span>Requested: ${summary.requested ?? items.length}</span>
        <span>Processed: ${summary.processed ?? items.length}</span>
        <span>Skipped: ${summary.skipped ? (summary.skipped.extra_application_files || 0) + (summary.skipped.extra_label_files || 0) : 0}</span>
      </div>

      <table class="batch-queue-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Application</th>
            <th>App ID</th>
            <th>Label</th>
            <th>Result</th>
            <th>Confidence</th>
            <th>Review state</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          ${items.map((item, index) => {
            const payload = item.result || {};
            const overall = payload.overall || item.overall || "need_review";
            const displayOverall = formatOverallLabel(overall);
            const status = payload.status || item.status || "pending";
            const appId = payload.application_id || item.application_id || "n/a";
            const overallConfidence = (() => {
              const value = payload.overall_confidence ?? (payload.parsed && payload.parsed.vision_quality_score);
              if (value === null || value === undefined || value === "") return "n/a";
              return `${Number(value).toFixed(0)}%`;
            })();
            const rowSelected = state.batchSelectedItem && state.batchSelectedItem.index === item.index ? "selected-row" : "";
            return `
              <tr class="${rowSelected}">
                <td>${index + 1}</td>
                <td>${escapeHtml(item.application_file || "n/a")}</td>
                <td>${escapeHtml(String(appId))}</td>
                <td>${escapeHtml(item.label_file || "n/a")}</td>
                <td><span class="badge ${overall}">${displayOverall}</span></td>
                <td>${escapeHtml(String(overallConfidence))}</td>
                <td>${escapeHtml(String(status))}</td>
                <td>
                  <div class="batch-item-actions">
                    <button type="button" class="secondary" data-batch-action="view-details" data-index="${item.index}">View details</button>
                  </div>
                </td>
              </tr>
            `;
          }).join("")}
        </tbody>
      </table>

      ${state.batchSelectedItem ? `
        <div class="batch-detail-overlay">
          <div class="batch-detail-modal">
            <div class="batch-detail-header">
              <div class="section-title" style="margin: 0;">Selected application details</div>
              <button type="button" class="secondary" data-batch-action="close-details">Close</button>
            </div>
            ${renderResults(state.batchSelectedItem.result, {
              applicationSource: state.batchSelectedItem.application_file || "Application data provided",
              labelSource: state.batchSelectedItem.label_file || "Label image attached",
              applicationTargetUrl: state.batchApplicationPreviewUrls?.[state.batchSelectedItem.application_file] || "",
              labelTargetUrl: state.batchLabelPreviewUrls?.[state.batchSelectedItem.label_file] || "",
              isBatchDetail: true,
            })}
          </div>
        </div>
      ` : ""}
    </div>
  `;
}

export function renderApp() {
  const isSingle = state.activeTab === "single";

  return `
    <div class="page">
      <div class="hero">
        <div>
          <div class="pill">Label audit</div>
          <h1>Alcohol Label Verification</h1>
          <p class="subtitle">Compare uploaded label images against the application record and review mismatches quickly.</p>
        </div>
      </div>

      <div class="workspace-shell">
        <div class="navigation-menu" role="tablist" aria-label="Verification workflow">
          <button type="button" class="nav-button ${isSingle ? "active" : ""}" data-tab="single" role="tab" aria-selected="${isSingle}">Single Case</button>
          <button type="button" class="nav-button ${!isSingle ? "active" : ""}" data-tab="batch" role="tab" aria-selected="${!isSingle}">Batch Case</button>
        </div>

        ${isSingle ? `
          <div class="stack">
            <div class="panel form-panel" id="verifyForm">
              <div class="section-title">Application record</div>
              <div class="upload-box">
                <label for="applicationFile">Upload application PDF</label>
                <input id="applicationFile" type="file" accept="application/pdf,.pdf" />
                <div class="meta">${state.applicationFileDisplay || (state.applicationFile ? `Selected: ${getFullPath(state.applicationFile, state.applicationFilePath)}` : "No application file selected yet.")}</div>
              </div>

              <div class="section-title" style="margin-top: 20px;">Label image</div>
              <div class="upload-box">
                <label for="labelFile">Upload bottle label image</label>
                <input id="labelFile" type="file" accept="image/*" />
                <div class="meta">${state.labelFileDisplay || (state.labelFile ? `Selected: ${getFullPath(state.labelFile, state.labelFilePath)}` : "No label image selected yet.")}</div>
              </div>

              <div class="actions">
                <button type="button" id="verifyCaseButton" ${state.loading ? "disabled" : ""}>${state.loading ? '<span class="button-spinner"></span>Verifying...' : "Verify case"}</button>
                <button type="button" class="secondary" id="clearForm" ${state.loading ? "disabled" : ""}>Clear</button>
              </div>

              ${renderStatus()}
            </div>

            <div class="panel results-panel">
              ${renderResults()}
            </div>
          </div>
        ` : `
          <div class="batch-screen">
            <div class="panel batch-panel">
              <div class="section-title">Batch review</div>
              <div class="upload-box">
                <label for="batchApplicationFiles">Application PDFs</label>
                <input id="batchApplicationFiles" type="file" accept="application/pdf,.pdf" multiple />
                <div class="meta">${state.batchApplicationFileDisplay || (state.batchApplicationFiles.length ? `Selected: ${state.batchApplicationFiles.map(file => getFullPath(file, file.name)).join(", ")}` : "No batch application files selected yet.")}</div>
              </div>
              <div class="upload-box" style="margin-top: 12px;">
                <label for="batchLabelFiles">Label images</label>
                <input id="batchLabelFiles" type="file" accept="image/*" multiple />
                <div class="meta">${state.batchLabelFileDisplay || (state.batchLabelFiles.length ? `Selected: ${state.batchLabelFiles.map(file => getFullPath(file, file.name)).join(", ")}` : "No batch label files selected yet.")}</div>
              </div>
              <div class="upload-box" style="margin-top: 12px;">
                <label for="batchMappingFile">Application-to-label mapping file</label>
                <input id="batchMappingFile" type="file" accept=".json,.txt,.csv" />
                <div class="meta">${state.batchMappingFileDisplay || (state.batchMappingFile ? `Selected: ${state.batchMappingFile.name}` : "Optional: upload a JSON or text mapping file such as app.pdf -> label.png")}</div>
              </div>

              <div class="actions">
                <button type="button" id="submitBatchButton">Run batch job</button>
                <button type="button" class="secondary" id="clearForm">Clear</button>
              </div>

              ${renderBatchStatus()}
              ${renderStatus()}
            </div>

            <div class="panel batch-results-panel">
              <div class="section-title">Batch results</div>
              ${state.batchResults ? renderBatchResults() : '<div class="empty-batch-state">No batch results yet. Upload a batch and run the job to review them.</div>'}
            </div>
          </div>
        `}
      </div>
    </div>

    ${state.overrideModal ? `
      <div class="modal-backdrop" id="overrideModalBackdrop">
        <div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="overrideModalTitle">
          <div class="modal-header">
            <h3 id="overrideModalTitle">Manual override for ${escapeHtml(state.overrideModal.label)}</h3>
            <button type="button" class="modal-close" data-action="close-override">x</button>
          </div>
          <div class="modal-body">
            <div class="override-choice-group">
              <label><input type="radio" name="overrideDecision" value="match" ${state.overrideModal.decision === "match" ? "checked" : ""} /> Pass</label>
              <label><input type="radio" name="overrideDecision" value="unmatch" ${state.overrideModal.decision === "unmatch" ? "checked" : ""} /> Failure</label>
            </div>
            <label class="field-label" for="overrideValueInput">Override value</label>
            <input id="overrideValueInput" type="text" value="${escapeHtml(state.overrideModal.overrideValue || "")}" placeholder="Enter the corrected value" />
            <label class="field-label" for="overrideCommentInput">Comment</label>
            <textarea id="overrideCommentInput" placeholder="Why was this value overridden?">${escapeHtml(state.overrideModal.comment || "")}</textarea>
          </div>
          <div class="modal-footer">
            <button type="button" class="secondary" data-action="close-override">Cancel</button>
            <button type="button" class="override-save-btn" data-field="${escapeHtml(state.overrideModal.field)}">Save override</button>
          </div>
        </div>
      </div>
    ` : ""}
  `;
}
