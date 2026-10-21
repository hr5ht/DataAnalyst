const uploadView = document.getElementById("upload-view");
const workspace = document.getElementById("workspace");
const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file");
const uploadStatus = document.getElementById("upload-status");
const chatForm = document.getElementById("chat-form");
const questionInput = document.getElementById("question");
const sendButton = document.getElementById("send");
const messagesEl = document.getElementById("messages");
const charCount = document.getElementById("char-count");

const BADGES = {
  empty: "No matching rows",
  clarify: "Needs more detail",
  unsupported: "Not supported",
  error: "Could not answer",
};

const settings = { maxUploadMb: 4, chatEnabled: true };
let current = null;
let pendingClarify = null;
let busy = false;

loadSettings();

fileInput.addEventListener("change", () => {
  if (fileInput.files[0]) startUpload(fileInput.files[0]);
  fileInput.value = "";
});

for (const type of ["dragenter", "dragover"]) {
  dropzone.addEventListener(type, (event) => {
    event.preventDefault();
    dropzone.classList.add("dragging");
  });
}
for (const type of ["dragleave", "drop"]) {
  dropzone.addEventListener(type, () => dropzone.classList.remove("dragging"));
}
dropzone.addEventListener("drop", (event) => {
  event.preventDefault();
  const file = event.dataTransfer.files[0];
  if (file) startUpload(file);
});

document.getElementById("sample-button").addEventListener("click", async () => {
  try {
    const response = await fetch("/sample.csv");
    if (!response.ok) throw new Error("The sample file could not be loaded.");
    startUpload(new File([await response.blob()], "sample-sales.csv", { type: "text/csv" }));
  } catch (error) {
    setStatus(uploadStatus, readableError(error), true);
  }
});

document.getElementById("new-file").addEventListener("click", () => {
  current = null;
  workspace.hidden = true;
  uploadView.hidden = false;
  document.getElementById("dataset-chip").hidden = true;
  setStatus(uploadStatus, "");
  fileInput.focus();
});

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  sendQuestion(questionInput.value);
});

questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

questionInput.addEventListener("input", () => {
  charCount.textContent = `${questionInput.value.length}/500`;
  questionInput.style.height = "auto";
  questionInput.style.height = `${questionInput.scrollHeight}px`;
});

async function loadSettings() {
  try {
    const health = await request("/health");
    settings.maxUploadMb = health.max_upload_mb;
    settings.chatEnabled = health.llm_configured;
  } catch {
    return;
  }
  document.getElementById("limits").textContent =
    `Comma-separated, UTF-8, with a header row · up to ${formatNumber(settings.maxUploadMb)} MB`;
}

async function startUpload(file) {
  if (!/\.csv$/i.test(file.name)) {
    setStatus(uploadStatus, "Choose a .csv file.", true);
    return;
  }
  if (file.size > settings.maxUploadMb * 1024 * 1024) {
    setStatus(uploadStatus, `${file.name} is larger than ${formatNumber(settings.maxUploadMb)} MB.`, true);
    return;
  }

  dropzone.classList.add("busy");
  setStatus(uploadStatus, `Uploading and profiling ${file.name}...`);
  try {
    const data = await uploadFile(file);
    current = { file, filename: data.filename, datasetId: data.dataset_id, profile: data.profile };
    showWorkspace();
    setStatus(uploadStatus, "");
  } catch (error) {
    setStatus(uploadStatus, readableError(error), true);
  } finally {
    dropzone.classList.remove("busy");
  }
}

async function uploadFile(file) {
  const body = new FormData();
  body.append("file", file);
  return request("/datasets", { method: "POST", body });
}

function showWorkspace() {
  const { profile, filename } = current;
  document.getElementById("dataset-name").textContent = filename;
  document.getElementById("dataset-size").textContent =
    `${formatNumber(profile.rows)} rows · ${formatNumber(profile.columns)} columns`;
  document.getElementById("dataset-chip").hidden = false;

  renderStats(profile);
  renderQuality(profile);
  renderColumns(profile);
  renderSample(profile);
  resetChat(profile, filename);

  uploadView.hidden = true;
  workspace.hidden = false;
  window.scrollTo({ top: 0 });
  if (settings.chatEnabled) questionInput.focus();
}

function renderStats(profile) {
  const missing = profile.column_profiles.reduce((total, column) => total + column.missing, 0);
  const cells = profile.rows * profile.columns;
  const stats = [
    ["Rows", formatNumber(profile.rows)],
    ["Columns", formatNumber(profile.columns), typeSummary(profile.column_profiles)],
    ["Missing cells", formatNumber(missing), cells ? `${percent(missing, cells)} of all cells` : ""],
    ["Duplicate rows", formatNumber(profile.duplicate_rows), profile.duplicate_rows ? `${percent(profile.duplicate_rows, profile.rows)} of rows` : ""],
  ];
  document.getElementById("stats").replaceChildren(
    ...stats.map(([label, value, note]) => {
      const card = element("div", "stat");
      card.append(element("span", "", label), element("strong", "", value));
      if (note) card.append(element("small", "", note));
      return card;
    }),
  );
  document.getElementById("type-summary").textContent = typeSummary(profile.column_profiles);
}

function typeSummary(columns) {
  const names = { numeric: "numeric", text: "text", datetime: "date", boolean: "true/false" };
  const counts = {};
  for (const column of columns) counts[column.kind] = (counts[column.kind] ?? 0) + 1;
  return Object.entries(counts)
    .map(([kind, count]) => `${count} ${names[kind] ?? kind}`)
    .join(" · ");
}

function renderQuality(profile) {
  const notes = [];
  const columns = profile.column_profiles;
  const missing = columns.filter((c) => c.missing).sort((a, b) => b.missing - a.missing);
  const cells = profile.rows * profile.columns;

  if (missing.length) {
    const total = missing.reduce((sum, c) => sum + c.missing, 0);
    const worst = missing.slice(0, 4).map((c) => `${c.name} (${percent(c.missing, profile.rows)})`).join(", ");
    notes.push(["warn", `${formatNumber(total)} of ${formatNumber(cells)} cells are empty. Most gaps: ${worst}.`]);
  } else {
    notes.push(["ok", "No missing values."]);
  }

  if (profile.duplicate_rows) {
    const verb = profile.duplicate_rows === 1 ? "repeats" : "repeat";
    notes.push(["warn", `${plural(profile.duplicate_rows, "row")} ${verb} an earlier row exactly. Counts and totals include them.`]);
  } else {
    notes.push(["ok", "No duplicate rows."]);
  }

  for (const column of columns) {
    if (profile.rows && column.missing === profile.rows) notes.push(["warn", `${column.name} is empty in every row.`]);
    else if (column.unique === 1) notes.push(["info", `${column.name} has the same value in every row.`]);
    else if (profile.rows > 1 && column.unique === profile.rows && column.kind !== "datetime") {
      notes.push(["info", `${column.name} is different in every row, so it looks like an ID.`]);
    }
  }

  const dates = columns.filter((c) => c.kind === "datetime").map((c) => c.name);
  notes.push(
    dates.length
      ? ["ok", `${dates.join(", ")} ${dates.length === 1 ? "was read as a date" : "were read as dates"}, so trends over time are available.`]
      : ["info", "No date columns found. Dates must look like YYYY-MM-DD to be used for trends."],
  );

  document.getElementById("quality").replaceChildren(...notes.map(([level, text]) => element("li", level, text)));
}

function renderColumns(profile) {
  const headers = ["Column", "Type", ...["Missing", "Unique", "Min", "Mean", "Median", "Max"].map(numberHeader), "Example"];
  const rows = profile.column_profiles.map((column) => [
    element("strong", "", column.name),
    element("span", `type ${column.kind}`, column.kind === "datetime" ? "date" : column.kind),
    { node: missingCell(column.missing, profile.rows), className: "number" },
    { value: formatNumber(column.unique), className: "number" },
    { value: formatNumber(column.numeric?.min), className: "number" },
    { value: formatNumber(column.numeric?.mean), className: "number" },
    { value: formatNumber(column.numeric?.median), className: "number" },
    { value: formatNumber(column.numeric?.max), className: "number" },
    exampleValue(profile.sample, column.name),
  ]);
  renderTable(document.getElementById("columns"), headers, rows);
}

function missingCell(missing, rows) {
  const wrap = element("div", "missing-cell");
  wrap.append(element("span", "", missing ? `${formatNumber(missing)} (${percent(missing, rows)})` : "0"));
  const bar = element("div", "bar");
  const fill = element("span");
  fill.style.width = rows ? `${Math.min(100, (missing / rows) * 100)}%` : "0";
  bar.append(fill);
  wrap.append(bar);
  return wrap;
}

function exampleValue(sample, name) {
  const row = sample.find((item) => item[name] !== null && item[name] !== undefined);
  return row ? formatCell(row[name]) : { value: "empty", className: "empty" };
}

function renderSample(profile) {
  const names = profile.column_profiles.map((column) => column.name);
  renderTable(
    document.getElementById("sample"),
    names,
    profile.sample.map((row) => names.map((name) => sampleCell(row[name]))),
  );
  document.getElementById("sample-note").textContent =
    `First ${plural(profile.sample.length, "row")} of ${formatNumber(profile.rows)}`;
}

function sampleCell(value) {
  if (value === null || value === undefined) return { value: "empty", className: "empty" };
  if (typeof value === "number") return { value: formatNumber(value), className: "number" };
  return formatCell(value);
}

function resetChat(profile, filename) {
  pendingClarify = null;
  messagesEl.replaceChildren();
  const welcome = assistantCard();
  if (!settings.chatEnabled) {
    welcome.classList.add("error");
    welcome.querySelector(".answer-text").textContent =
      "Chat is turned off because the server has no GROQ_API_KEY. The overview still works.";
    messagesEl.append(welcome);
    setComposerEnabled(false);
    return;
  }
  welcome.querySelector(".answer-text").textContent =
    `I've loaded ${filename}: ${plural(profile.rows, "row")} and ${plural(profile.columns, "column")}. ` +
    "Ask me anything about it. I pick the analysis, pandas computes it, and I show you the table, chart and steps. Try one of these:";
  const chips = element("div", "chips");
  for (const text of suggestions(profile.column_profiles)) {
    const chip = element("button", "chip", text);
    chip.type = "button";
    chip.addEventListener("click", () => sendQuestion(text));
    chips.append(chip);
  }
  welcome.append(chips);
  messagesEl.append(welcome);
  setComposerEnabled(true);
}

function suggestions(columns) {
  const idLike = (c) => /(id|no|number|code)$/i.test(c.name);
  const category = columns.find((c) => c.kind === "text" && !idLike(c) && c.unique >= 2 && c.unique <= 50);
  const numbers = columns.filter((c) => c.kind === "numeric" && !idLike(c));
  const date = columns.find((c) => c.kind === "datetime");
  const metric = numbers.at(-1);
  const list = ["Give me an overview of this data", "Which columns have missing values?"];
  if (category && metric) list.push(`Which ${category.name} has the highest total ${metric.name}?`);
  if (date && metric) list.push(`How does ${metric.name} change by month?`);
  if (numbers.length >= 2) list.push(`Is ${numbers[0].name} correlated with ${numbers[1].name}?`);
  if (category) list.push(`How many rows are there for each ${category.name}?`);
  return list.slice(0, 5);
}

async function sendQuestion(text) {
  const shown = text.trim();
  if (!shown || busy || !current) return;

  const question = pendingClarify ? `${pendingClarify} (${shown})`.slice(0, 500) : shown;
  pendingClarify = null;
  questionInput.value = "";
  questionInput.dispatchEvent(new Event("input"));

  addUserMessage(shown);
  const pending = addPending();
  setBusy(true);
  try {
    const data = await askQuestion(question);
    pending.remove();
    const card = showAnswer(data);
    if (data.status === "clarify") pendingClarify = question;
    scrollToMessage(card);
  } catch (error) {
    pending.remove();
    scrollToMessage(showError(error, shown));
  } finally {
    setBusy(false);
    questionInput.focus();
  }
}

async function askQuestion(question) {
  const send = () =>
    request(`/datasets/${current.datasetId}/questions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
  try {
    return await send();
  } catch (error) {
    if (error.status !== 404) throw error;
    const data = await uploadFile(current.file);
    current.datasetId = data.dataset_id;
    return send();
  }
}

function addUserMessage(text) {
  messagesEl.append(element("div", "message user", text));
}

function addPending() {
  const bubble = element("div", "message assistant");
  bubble.setAttribute("aria-label", "Working on it");
  const dots = element("div", "typing");
  dots.append(element("span"), element("span"), element("span"));
  bubble.append(dots);
  messagesEl.append(bubble);
  scrollToMessage(bubble);
  return bubble;
}

function assistantCard() {
  return document.getElementById("assistant-template").content.firstElementChild.cloneNode(true);
}

function showAnswer(data) {
  const card = assistantCard();
  if (data.status !== "answered") {
    const badge = card.querySelector(".badge");
    badge.textContent = BADGES[data.status] ?? data.status;
    badge.dataset.status = data.status;
    badge.hidden = false;
  }
  let text = data.answer;
  if (data.status === "clarify") text += "\n\nReply below and I'll use it with your question.";
  card.querySelector(".answer-text").textContent = text;

  if (data.table && data.table.rows.length) {
    const result = card.querySelector(".result");
    renderTable(
      result.querySelector("table"),
      data.table.columns.map((name, i) => (data.table.rows.some((row) => typeof row[i] === "number") ? numberHeader(name) : name)),
      data.table.rows.map((row) => row.map(sampleCell)),
    );
    const shown = data.table.rows.length;
    result.querySelector(".row-count").textContent =
      shown < data.table.total_rows
        ? `Showing ${formatNumber(shown)} of ${plural(data.table.total_rows, "row")}`
        : plural(data.table.total_rows, "row");
    result.querySelector(".download").addEventListener("click", () => downloadTable(data.table, data.operation?.tool));
    result.hidden = false;
  }

  if (data.warnings.length) {
    const list = card.querySelector(".warnings");
    list.replaceChildren(...data.warnings.map((text) => element("li", "", text)));
    list.hidden = false;
  }

  if (data.operation || data.definitions.length) {
    const trace = card.querySelector(".trace");
    const steps = trace.querySelector(".steps");
    if (data.operation) {
      steps.append(element("li", "", `Chose the ${data.operation.tool.replaceAll("_", " ")} tool: ${data.operation.description}`));
      for (const step of data.operation.steps) {
        const li = element("li");
        li.append(element("code", "", step));
        steps.append(li);
      }
    }
    if (data.definitions.length) {
      const box = trace.querySelector(".definitions");
      box.querySelector("ul").replaceChildren(
        ...data.definitions.map((item) => {
          const li = element("li");
          li.append(
            element("strong", "", item.term),
            ` (${item.kind}): ${item.text} `,
            element("span", "muted", `${item.source}, match ${item.score}`),
          );
          return li;
        }),
      );
      box.hidden = false;
    }
    const meta = [`Request ${data.request_id}`];
    if (data.table) meta.push(`${plural(data.table.total_rows, "row")} returned`);
    meta.push(`from ${current.filename}`);
    trace.querySelector(".trace-meta").textContent = meta.join(" · ");
    trace.hidden = false;
  }

  messagesEl.append(card);
  if (data.chart) renderChart(card.querySelector(".chart"), data.chart);
  return card;
}

function showError(error, question) {
  const card = assistantCard();
  card.classList.add("error");
  const badge = card.querySelector(".badge");
  badge.textContent = BADGES.error;
  badge.dataset.status = "error";
  badge.hidden = false;
  let text = readableError(error);
  if (error.status === 503 && !/try again/i.test(text)) text += " Wait a moment, then try again.";
  card.querySelector(".answer-text").textContent = text;
  const retry = card.querySelector(".retry");
  retry.hidden = false;
  retry.addEventListener("click", () => {
    card.previousElementSibling?.remove();
    card.remove();
    sendQuestion(question);
  });
  messagesEl.append(card);
  return card;
}

function renderChart(container, chart) {
  container.hidden = false;
  if (!window.Plotly) {
    chartNote(container, "The chart library did not load, so only the table is shown.");
    return;
  }
  const trace =
    chart.type === "line"
      ? { type: "scatter", mode: "lines+markers", x: chart.x, y: chart.y, line: { color: "#2563eb", width: 2 } }
      : { type: "bar", x: chart.x, y: chart.y, marker: { color: "#2563eb" } };
  window.Plotly.newPlot(
    container,
    [trace],
    {
      title: { text: chart.title, font: { size: 13 }, x: 0, xanchor: "left" },
      xaxis: { title: { text: chart.x_label }, type: chart.type === "bar" ? "category" : "-", automargin: true },
      yaxis: { title: { text: chart.y_label }, automargin: true, gridcolor: "#e1e4e8" },
      margin: { t: 36, r: 8, b: 36, l: 44 },
      height: 260,
      font: { family: "system-ui, sans-serif", size: 11, color: "#1f2933" },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
    },
    { displayModeBar: false, responsive: true },
  ).catch(() => chartNote(container, "The chart could not be drawn, so only the table is shown."));
}

function chartNote(container, text) {
  container.textContent = text;
  container.className = "muted";
}

function downloadTable(table, tool) {
  const escape = (value) => {
    if (value === null || value === undefined) return "";
    let text = String(value);
    if (typeof value === "string" && /^[=+@]/.test(text)) text = `'${text}`;
    return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  };
  const csv = [table.columns, ...table.rows].map((row) => row.map(escape).join(",")).join("\n");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  link.download = `${tool ?? "result"}.csv`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function scrollToMessage(card) {
  messagesEl.scrollTo({ top: Math.max(0, card.offsetTop - 12), behavior: "smooth" });
}

function setBusy(value) {
  busy = value;
  setComposerEnabled(!value && settings.chatEnabled);
  for (const button of messagesEl.querySelectorAll(".chip, .retry")) button.disabled = value;
}

function setComposerEnabled(enabled) {
  questionInput.disabled = !enabled;
  sendButton.disabled = !enabled;
}

async function request(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    throw new Error("Could not reach the server. Check your connection and try again.");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(errorMessage(data, response.status));
    error.status = response.status;
    throw error;
  }
  return data;
}

function errorMessage(data, status) {
  if (typeof data.detail === "string") return data.detail;
  if (status === 413) return "The file is too large to upload.";
  return `The request failed (HTTP ${status}).`;
}

function readableError(error) {
  return error.message || "Something went wrong.";
}

function setStatus(target, message, isError = false) {
  target.textContent = message;
  target.classList.toggle("error", isError);
}

function numberHeader(value) {
  return { value, className: "number" };
}

function renderTable(table, headers, rows) {
  const headRow = document.createElement("tr");
  for (const header of headers) {
    const th = document.createElement("th");
    th.scope = "col";
    fillCell(th, header);
    headRow.append(th);
  }
  const body = document.createElement("tbody");
  for (const row of rows) {
    const tr = document.createElement("tr");
    for (const cell of row) {
      const td = document.createElement("td");
      fillCell(td, cell);
      tr.append(td);
    }
    body.append(tr);
  }
  const head = document.createElement("thead");
  head.append(headRow);
  table.replaceChildren(head, body);
}

function fillCell(target, cell) {
  if (cell instanceof Node) {
    target.append(cell);
  } else if (cell && typeof cell === "object") {
    if (cell.node) target.append(cell.node);
    else target.textContent = cell.value;
    target.className = cell.className ?? "";
  } else {
    target.textContent = cell ?? "";
  }
}

function element(tag, className = "", text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function plural(count, word) {
  return `${formatNumber(count)} ${word}${count === 1 ? "" : "s"}`;
}

function percent(part, whole) {
  if (!whole) return "0%";
  const value = (part / whole) * 100;
  return `${value < 0.1 && value > 0 ? "<0.1" : value.toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
}

function formatNumber(value) {
  if (value === null || value === undefined) return "";
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function formatCell(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)) {
    return value.replace("T", " ").replace(/(\.000)?$/, "").replace(/ 00:00:00$/, "");
  }
  return String(value);
}
