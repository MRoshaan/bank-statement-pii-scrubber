const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const state = {
  files: [],
  batch: null,
  fileDetails: [],
  analysis: null,
  sessionId: null,
  chatVersion: 0,
  chatPending: false,
};

const SUGGESTIONS = [
  "How much did I spend on food?",
  "Which merchant did I pay most often?",
  "What were my largest cash withdrawals?",
  "How much did I spend in total?",
  "What fees did the bank charge?",
];

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function clear(node) {
  node.replaceChildren();
}

function shortId(value) {
  return value ? `${String(value).slice(0, 8)}…` : "—";
}

function formatNumber(value) {
  const number = Number(value ?? 0);
  if (!Number.isFinite(number)) return "—";
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(number);
}

const CURRENCY_SIGNS = {
  PKR: "₨",
  USD: "$",
  GBP: "£",
  EUR: "€",
  INR: "₹",
  CAD: "C$",
  AUD: "A$",
  AED: "د.إ",
  SAR: "﷼",
};

function formatMoney(value, currency) {
  const code = String(currency || "").toUpperCase();
  const sign = CURRENCY_SIGNS[code];
  return sign ? `${sign}${formatNumber(value)}` : `${formatNumber(value)}${code ? ` ${code}` : ""}`;
}

function currencyDisplay(currency) {
  const code = String(currency || "").toUpperCase();
  const sign = CURRENCY_SIGNS[code];
  return sign ? `${sign} ${code}` : code || "—";
}

function displayText(value) {
  // The database and LLM keep ISO codes for precision. The UI renders the
  // Pakistani rupee with its currency sign, in either "PKR 1,000" or
  // "1,000 PKR" form.
  return String(value ?? "")
    .replace(/\bPKR\s*([\d,.]+)/g, "₨$1")
    .replace(/([\d,.]*)\s*\bPKR\b/g, (match, amount) => (amount ? `₨${amount}` : "₨"))
    .replace(/\bPKR\b/g, "₨");
}

function showAlert(message, type = "error") {
  const alert = $("#alert");
  alert.textContent = message;
  alert.className = `alert ${type}`;
  alert.classList.remove("hidden");
  window.clearTimeout(showAlert._timer);
  showAlert._timer = window.setTimeout(() => alert.classList.add("hidden"), 9000);
}

function setBusy(button, busy, label) {
  if (!button) return;
  if (busy) {
    if (!button.dataset.originalLabel) button.dataset.originalLabel = button.textContent;
    button.disabled = true;
    const spinner = el("span", "spinner");
    button.replaceChildren(spinner, document.createTextNode(label || "Working…"));
  } else {
    button.disabled = false;
    button.textContent = button.dataset.originalLabel || button.textContent;
  }
}

function badge(text, kind = "info") {
  return el("span", `badge ${kind}`, text);
}

function chips(counts) {
  const wrap = el("div", "count-chips");
  const entries = Object.entries(counts || {}).sort((a, b) => b[1] - a[1]);
  if (!entries.length) {
    wrap.append(el("span", "chip", "No redactions"));
    return wrap;
  }
  for (const [key, value] of entries) {
    const chip = el("span", "chip");
    chip.append(document.createTextNode(key));
    chip.append(el("strong", "", value));
    wrap.append(chip);
  }
  return wrap;
}

function table(headers, rows, numericIndexes = []) {
  const wrap = el("div", "table-wrap");
  const tableNode = el("table");
  const thead = el("thead");
  const headRow = el("tr");
  headers.forEach((header, index) => {
    const th = el("th", numericIndexes.includes(index) ? "num" : "", header);
    headRow.append(th);
  });
  thead.append(headRow);
  const tbody = el("tbody");
  for (const row of rows) {
    const tr = el("tr");
    row.forEach((cell, index) => {
      const td = el("td", numericIndexes.includes(index) ? "num" : "");
      if (cell instanceof Node) td.append(cell);
      else td.textContent = cell === null || cell === undefined ? "—" : String(cell);
      tr.append(td);
    });
    tbody.append(tr);
  }
  tableNode.append(thead, tbody);
  wrap.append(tableNode);
  return wrap;
}

function refs(list) {
  const wrap = el("div", "refs");
  for (const ref of list || []) {
    wrap.append(el("span", "ref-chip", ref));
  }
  if (!wrap.children.length) wrap.append(el("span", "muted", "No direct citation"));
  return wrap;
}

function totalRedactions(counts) {
  return Object.values(counts || {}).reduce((sum, value) => sum + Number(value || 0), 0);
}

/* ---------------- upload ---------------- */

function renderSelectedFiles() {
  const list = $("#selected-files");
  clear(list);
  $("#file-count-label").textContent = state.files.length
    ? `${state.files.length} file${state.files.length === 1 ? "" : "s"} selected`
    : "No files selected";
  for (const file of state.files) {
    const row = el("div", "file-row");
    const name = el("span", "name", file.name);
    const meta = el("span", "meta", `${(file.size / 1024).toFixed(1)} KB`);
    row.append(name, meta);
    list.append(row);
  }
}

function acceptFiles(fileList) {
  state.files = Array.from(fileList || []).filter((file) => {
    const allowed = /\.(pdf|docx|csv|txt|text|zip)$/i.test(file.name);
    if (!allowed) showAlert(`${file.name} is not a supported statement format.`, "warn");
    return allowed;
  });
  renderSelectedFiles();
}

$("#file-input").addEventListener("change", (event) => acceptFiles(event.target.files));

const dropzone = $("#dropzone");
for (const eventName of ["dragenter", "dragover"]) {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.add("dragover");
  });
}
for (const eventName of ["dragleave", "drop"]) {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.remove("dragover");
  });
}
dropzone.addEventListener("drop", (event) => acceptFiles(event.dataTransfer.files));

async function readError(response) {
  try {
    const data = await response.json();
    if (typeof data.detail === "string") return data.detail;
    return JSON.stringify(data.detail || data);
  } catch {
    return response.statusText || `HTTP ${response.status}`;
  }
}

$("#scrub-btn").addEventListener("click", async () => {
  if (!state.files.length) {
    showAlert("Select at least one statement file first.", "warn");
    return;
  }
  const button = $("#scrub-btn");
  setBusy(button, true, "Scrubbing…");
  const form = new FormData();
  for (const file of state.files) form.append("files", file, file.name);
  const name = $("#batch-name").value.trim();
  if (name) form.append("name", name);

  try {
    const response = await fetch("/api/v1/batches", { method: "POST", body: form });
    if (!response.ok) throw new Error(await readError(response));
    const data = await response.json();
    state.batch = data.batch;
    state.fileDetails = data.files || [];
    state.analysis = null;
    state.sessionId = null;
    state.chatVersion += 1;
    renderBatch();
    showAlert(`Scrubbed ${data.batch.file_count} files and stored batch ${shortId(data.batch.id)}.`, "success");
    $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showAlert(error.message || "Upload failed.");
  } finally {
    setBusy(button, false);
  }
});

/* ---------------- results ---------------- */

function renderBatch() {
  const batch = state.batch;
  if (!batch) return;
  $("#postgres-badge").textContent = "Stored in PostgreSQL";
  $("#postgres-badge").className = "badge success";

  const stats = $("#stat-grid");
  clear(stats);
  const statData = [
    ["Files", batch.file_count, batch.status],
    ["Transactions", batch.transaction_count, "Parsed into structured rows"],
    ["Redactions", totalRedactions(batch.redaction_counts), "Identifiers replaced"],
    ["Batch ID", shortId(batch.id), "PostgreSQL UUID"],
  ];
  for (const [label, value, sub] of statData) {
    const card = el("div", "stat");
    card.append(el("div", "label", label));
    card.append(el("div", "value", value));
    card.append(el("div", "sub", sub));
    stats.append(card);
  }

  $("#combined-meta").textContent = `${batch.scrubbed_chars.toLocaleString()} characters · ${batch.warnings.length} warnings`;
  $("#combined-text").textContent = batch.combined_text || "";
  $("#download-combined").href = `/api/v1/batches/${batch.id}/scrubbed`;

  const fileList = $("#per-file-list");
  clear(fileList);
  for (const file of state.fileDetails) {
    const details = el("details", "file-detail");
    const summary = el("summary");
    const left = el("span", "", `${file.filename} · ${file.format.toUpperCase()}`);
    const right = el("span", "chip", `${totalRedactions(file.redaction_counts)} redactions`);
    summary.append(left, right);
    const body = el("div", "detail-body");
    const actions = el("div", "panel-actions");
    actions.append(el("span", "muted", `${file.size_bytes.toLocaleString()} bytes`));
    const download = el("button", "secondary", "Download");
    download.type = "button";
    download.addEventListener("click", () => {
      const blob = new Blob([file.scrubbed_text || ""], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const anchor = el("a");
      anchor.href = url;
      anchor.download = `${file.filename}.scrubbed.txt`;
      anchor.click();
      URL.revokeObjectURL(url);
    });
    actions.append(download);
    body.append(actions);
    body.append(chips(file.redaction_counts));
    if (file.warnings && file.warnings.length) {
      const warning = el("p", "fineprint", `Warnings: ${file.warnings.join("; ")}`);
      body.append(warning);
    }
    const pre = el("pre", "code-block");
    pre.textContent = file.scrubbed_text || "";
    body.append(pre);
    details.append(summary, body);
    fileList.append(details);
  }

  const redactionTable = $("#redaction-table");
  clear(redactionTable);
  const rows = Object.entries(batch.redaction_counts || {})
    .sort((a, b) => b[1] - a[1])
    .map(([entity, count]) => [entity, count]);
  redactionTable.append(table(["Entity type", "Count"], rows, [1]));

  $("#results").classList.remove("hidden");
  $("#empty-state").classList.add("hidden");
  $("#analysis-output").replaceChildren();
  $("#analysis-status").classList.add("hidden");
  $("#chat-messages").replaceChildren();
  $("#chat-meta").textContent = "";
  renderSuggestions();
}

$("#copy-combined").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("#combined-text").textContent || "");
    showAlert("Combined scrubbed output copied.", "success");
  } catch {
    showAlert("Clipboard access was blocked; use the download button.", "warn");
  }
});

for (const tab of $$(".tab")) {
  tab.addEventListener("click", () => {
    $$(".tab").forEach((item) => item.classList.toggle("active", item === tab));
    $$(".tab-panel").forEach((panel) => {
      panel.classList.toggle("hidden", panel.dataset.panel !== tab.dataset.tab);
    });
  });
}

/* ---------------- analysis ---------------- */

$("#analyze-btn").addEventListener("click", async () => {
  if (!state.batch) return;
  const batchId = state.batch.id;
  const button = $("#analyze-btn");
  setBusy(button, true, "Analyzing…");
  $("#analysis-status").classList.remove("hidden");
  $("#analysis-status").replaceChildren(el("p", "muted", "Sending scrubbed facts to Groq…"));
  try {
    const response = await fetch(`/api/v1/batches/${batchId}/analyze`, { method: "POST" });
    if (!response.ok) throw new Error(await readError(response));
    const analysis = await response.json();
    if (state.batch?.id !== batchId) return;
    state.analysis = analysis;
    renderAnalysis(analysis);
    showAlert(analysis.status === "fallback" ? "Analysis generated from deterministic facts." : "Analysis generated and grounded.", "success");
  } catch (error) {
    if (state.batch?.id !== batchId) return;
    $("#analysis-status").replaceChildren(el("p", "fineprint", error.message || "Analysis failed."));
    showAlert(error.message || "Analysis failed.");
  } finally {
    setBusy(button, false);
  }
});

function renderAnalysis(analysis) {
  const result = analysis.result || {};
  const facts = result.facts || {};
  const validation = analysis.grounding_report || result.validation || {};
  const output = $("#analysis-output");
  clear(output);

  const status = $("#analysis-status");
  clear(status);
  status.classList.remove("hidden");
  const statusRow = el("div", "suggestions");
  statusRow.append(badge(`Model: ${analysis.model}`, "info"));
  statusRow.append(badge(analysis.status === "completed" ? "Grounded" : analysis.status === "fallback" ? "Deterministic fallback" : "Needs review", validation.grounded ? "success" : "warn"));
  if (validation.grounded) statusRow.append(badge("Numbers verified", "success"));
  else statusRow.append(badge("Unsupported figures flagged", "warn"));
  status.append(statusRow);

  const summary = el("section", "analysis-block");
  summary.append(el("h3", "", "Summary"));
  summary.append(el("p", "", displayText(result.summary || "No summary returned.")));
  output.append(summary);

  const currencyRows = Object.entries(facts.by_currency || {}).map(([currency, values]) => [
    currencyDisplay(currency),
    formatMoney(values.spend, currency),
    formatMoney(values.received, currency),
    formatMoney(values.net, currency),
    values.count,
  ]);
  if (currencyRows.length) {
    const block = el("section", "analysis-block");
    block.append(el("h3", "", "Spending by currency"));
    block.append(table(["Currency", "Spend", "Received", "Net", "Transactions"], currencyRows, [1, 2, 3, 4]));
    output.append(block);
  }

  const categoryRows = [];
  for (const [currency, categories] of Object.entries(facts.by_category || {})) {
    for (const [category, values] of Object.entries(categories)) {
      categoryRows.push([currencyDisplay(currency), category, formatMoney(values.spend, currency), values.count]);
    }
  }
  categoryRows.sort((a, b) => String(a[0]).localeCompare(String(b[0])) || Number(b[2].replace(/[^\d.-]/g, "")) - Number(a[2].replace(/[^\d.-]/g, "")));
  if (categoryRows.length) {
    const block = el("section", "analysis-block");
    block.append(el("h3", "", "Top categories"));
    block.append(table(["Currency", "Category", "Spend", "Count"], categoryRows.slice(0, 30), [2, 3]));
    output.append(block);
  }

  const merchantRows = [];
  for (const [currency, merchants] of Object.entries(facts.top_merchants_by_spend || {})) {
    for (const merchant of merchants) {
      merchantRows.push([currencyDisplay(currency), merchant.merchant, formatMoney(merchant.spend, currency), merchant.count]);
    }
  }
  if (merchantRows.length) {
    const block = el("section", "analysis-block");
    block.append(el("h3", "", "Top merchants by spend"));
    block.append(table(["Currency", "Merchant", "Spend", "Count"], merchantRows, [2, 3]));
    output.append(block);
  }

  output.append(insightBlock("Insights", result.insights, "insight"));
  output.append(insightBlock("Anomalies", result.anomalies, "insight anomaly"));
  output.append(insightBlock("Recommendations", result.recommendations, "insight recommendation"));

  const quality = el("section", "analysis-block");
  quality.append(el("h3", "", "Grounding & data quality"));
  const validationText = validation.grounded
    ? `Validated ${validation.checked_numbers?.length || 0} numeric claim(s) and ${validation.checked_refs?.length || 0} citation(s).`
    : `Review needed: ${validation.unsupported_numbers?.length || 0} unsupported number(s), ${validation.invalid_refs?.length || 0} invalid citation(s).`;
  quality.append(el("p", "", validationText));
  for (const note of result.data_quality_notes || []) {
    quality.append(el("p", "fineprint", `• ${note}`));
  }
  const largestRows = (facts.largest_transactions || []).map((item) => [
    item.date || "—",
    item.merchant || "—",
    item.category || "—",
    formatMoney(item.amount, item.currency),
    item.ref || "—",
  ]);
  if (largestRows.length) {
    quality.append(el("h3", "", "Largest transactions"));
    quality.append(table(["Date", "Merchant", "Category", "Amount", "Ref"], largestRows, [3]));
  }
  output.append(quality);
}

function insightBlock(title, items, className) {
  const block = el("section", "analysis-block");
  block.append(el("h3", "", title));
  if (!items || !items.length) {
    block.append(el("p", "muted", "None flagged."));
    return block;
  }
  for (const item of items) {
    const card = el("div", className);
    card.append(el("h4", "", item.title || title));
    card.append(el("p", "", displayText(item.detail || "")));
    card.append(refs(item.evidence_refs || []));
    if (item.confidence) card.append(el("p", "fineprint", `Confidence: ${item.confidence}`));
    if (item.severity) card.append(el("p", "fineprint", `Severity: ${item.severity}`));
    block.append(card);
  }
  return block;
}

/* ---------------- chat ---------------- */

function renderSuggestions() {
  const wrap = $("#suggestions");
  clear(wrap);
  for (const suggestion of SUGGESTIONS) {
    const button = el("button", "suggestion", suggestion);
    button.type = "button";
    button.addEventListener("click", () => {
      $("#chat-input").value = suggestion;
      $("#chat-form").requestSubmit();
    });
    wrap.append(button);
  }
}

function appendMessage(role, text, meta = {}) {
  const message = el("div", `message ${role}`);
  message.append(el("div", "", displayText(text)));
  const metaRow = el("div", "msg-meta");
  if (meta.grounded !== undefined) {
    metaRow.append(badge(meta.grounded ? "Grounded" : "Unverified", meta.grounded ? "success" : "warn"));
  }
  if (meta.model) metaRow.append(el("span", "", meta.model));
  if (meta.sessionId) metaRow.append(el("span", "", `session ${shortId(meta.sessionId)}`));
  for (const ref of meta.citations || []) {
    metaRow.append(el("span", "ref-chip", ref));
  }
  if (metaRow.children.length) message.append(metaRow);
  $("#chat-messages").append(message);
  message.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return message;
}

$("#chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.batch || state.chatPending) return;
  const batchId = state.batch.id;
  const chatVersion = state.chatVersion;
  const input = $("#chat-input");
  const message = input.value.trim();
  if (!message) return;
  const button = $("#chat-form button");
  state.chatPending = true;
  appendMessage("user", message);
  input.value = "";
  setBusy(button, true, "Thinking…");
  try {
    const response = await fetch(`/api/v1/batches/${batchId}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: state.sessionId }),
    });
    if (!response.ok) throw new Error(await readError(response));
    const data = await response.json();
    if (state.batch?.id !== batchId || state.chatVersion !== chatVersion) return;
    state.sessionId = data.session_id;
    appendMessage("assistant", data.answer, {
      grounded: data.grounded,
      citations: data.citations,
      model: data.model,
      sessionId: data.session_id,
    });
    $("#chat-meta").textContent = data.grounded
      ? "Answer checked against deterministic facts and retrieved transactions."
      : "This answer is not fully grounded; treat it with caution.";
  } catch (error) {
    if (state.batch?.id !== batchId || state.chatVersion !== chatVersion) return;
    appendMessage("assistant", error.message || "Chat failed.");
    showAlert(error.message || "Chat failed.");
  } finally {
    state.chatPending = false;
    setBusy(button, false);
  }
});

$("#new-chat").addEventListener("click", () => {
  state.sessionId = null;
  state.chatVersion += 1;
  $("#chat-messages").replaceChildren();
  $("#chat-meta").textContent = "";
  renderSuggestions();
});

/* ---------------- init ---------------- */

renderSelectedFiles();
renderSuggestions();
