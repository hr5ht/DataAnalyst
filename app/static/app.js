const form = document.getElementById("upload-form");
const statusEl = document.getElementById("status");
const profileEl = document.getElementById("profile");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = form.elements.file.files[0];
  if (!file) return;

  const button = form.querySelector("button");
  button.disabled = true;
  profileEl.hidden = true;
  setStatus(`Uploading ${file.name}...`);

  try {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch("/datasets", { method: "POST", body });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(errorMessage(data, response.status));
    showProfile(data);
    setStatus("");
  } catch (error) {
    setStatus(error instanceof TypeError ? "Could not reach the server." : error.message, true);
  } finally {
    button.disabled = false;
  }
});

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function errorMessage(data, status) {
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map((item) => item.msg).join(" ");
  if (status === 413) return "The file is too large to upload.";
  return `Upload failed (HTTP ${status}).`;
}

function showProfile({ filename, profile }) {
  const stats = [
    ["File", filename],
    ["Rows", formatNumber(profile.rows)],
    ["Columns", formatNumber(profile.columns)],
    ["Duplicate rows", formatNumber(profile.duplicate_rows)],
  ];
  document.getElementById("stats").replaceChildren(...stats.map(([label, value]) => statCard(label, value)));

  renderTable(
    document.getElementById("columns"),
    ["Column", "Type", ...["Missing", "Unique", "Min", "Mean", "Max"].map((value) => ({ value, className: "number" }))],
    profile.column_profiles.map((column) => [
      column.name,
      column.kind,
      { value: formatNumber(column.missing), className: column.missing ? "number missing" : "number" },
      { value: formatNumber(column.unique), className: "number" },
      { value: formatNumber(column.numeric?.min), className: "number" },
      { value: formatNumber(column.numeric?.mean), className: "number" },
      { value: formatNumber(column.numeric?.max), className: "number" },
    ]),
  );

  const names = profile.column_profiles.map((column) => column.name);
  renderTable(
    document.getElementById("sample"),
    names,
    profile.sample.map((row) => names.map((name) => formatCell(row[name]))),
  );

  profileEl.hidden = false;
}

function statCard(label, value) {
  const card = document.createElement("div");
  card.className = "stat";
  const labelEl = document.createElement("span");
  labelEl.textContent = label;
  const valueEl = document.createElement("strong");
  valueEl.textContent = value;
  valueEl.title = value;
  card.append(labelEl, valueEl);
  return card;
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

function fillCell(element, cell) {
  if (cell && typeof cell === "object") {
    element.textContent = cell.value;
    element.className = cell.className;
  } else {
    element.textContent = cell;
  }
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
