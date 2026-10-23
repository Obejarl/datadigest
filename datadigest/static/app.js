// DataDigest dashboard. No framework: fetch the JSON API and build the DOM.
// Everything that comes from an uploaded file is written with textContent, never innerHTML.

const POLL_MS = 1500;

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child);
  return node;
}

const fmtNumber = (n) => (n === null || n === undefined ? "–" : Number(n).toLocaleString("en-US"));

function fmtBytes(n) {
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${i ? n.toFixed(1) : n} ${units[i]}`;
}

function fmtAgo(iso) {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

const badge = (status) => el("span", { class: `badge ${status}`, text: status });
const isPending = (status) => status === "queued" || status === "processing";

// ---------------------------------------------------------------- index page

async function uploadFile(file) {
  const errorBox = document.getElementById("upload-error");
  errorBox.hidden = true;
  const form = new FormData();
  form.append("file", file);
  try {
    const dataset = await api("/api/datasets", { method: "POST", body: form });
    location.href = `/datasets/${dataset.id}`;
  } catch (err) {
    errorBox.textContent = `Upload failed: ${err.message}`;
    errorBox.hidden = false;
  }
}

async function refreshList() {
  const body = document.getElementById("datasets");
  const datasets = await api("/api/datasets");
  body.replaceChildren();
  if (!datasets.length) {
    body.append(el("tr", {}, el("td", { class: "empty", colspan: "7", text: "No datasets yet. Upload one above." })));
  }
  for (const d of datasets) {
    body.append(el("tr", {},
      el("td", { class: "name" }, el("a", { href: `/datasets/${d.id}`, text: d.filename })),
      el("td", {}, badge(d.status)),
      el("td", { text: fmtNumber(d.rows) }),
      el("td", { text: fmtNumber(d.cols) }),
      el("td", { text: fmtNumber(d.warnings_count) }),
      el("td", { text: fmtBytes(d.size_bytes) }),
      el("td", { class: "muted", text: fmtAgo(d.created_at) }),
    ));
  }
  if (datasets.some((d) => isPending(d.status))) setTimeout(refreshList, POLL_MS);
}

function initIndex() {
  const drop = document.getElementById("drop");
  const input = document.getElementById("file");
  input.addEventListener("change", () => input.files[0] && uploadFile(input.files[0]));
  for (const type of ["dragenter", "dragover"]) {
    drop.addEventListener(type, (e) => { e.preventDefault(); drop.classList.add("over"); });
  }
  for (const type of ["dragleave", "drop"]) {
    drop.addEventListener(type, (e) => { e.preventDefault(); drop.classList.remove("over"); });
  }
  drop.addEventListener("drop", (e) => e.dataTransfer.files[0] && uploadFile(e.dataTransfer.files[0]));
  refreshList();
}

// -------------------------------------------------------------- dataset page

function columnSummary(c) {
  if (c.kind === "numeric" && c.mean !== undefined) {
    return `min ${fmtNumber(c.min)} · median ${fmtNumber(c.median)} · max ${fmtNumber(c.max)}`;
  }
  if (c.kind === "datetime" && c.min) return `${c.min.slice(0, 10)} → ${c.max.slice(0, 10)}`;
  if (c.top && c.top.length) return c.top.slice(0, 3).map((t) => `${t.value} (${t.count})`).join(", ");
  if (c.kind === "text") return `avg length ${c.avg_length}`;
  return "";
}

function drawChart(container, chart) {
  const css = getComputedStyle(document.documentElement);
  const grid = css.getPropertyValue("--border").trim();
  const layout = {
    ...chart.figure.layout,
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: css.getPropertyValue("--text").trim() },
    xaxis: { gridcolor: grid, zerolinecolor: grid },
    yaxis: { gridcolor: grid, zerolinecolor: grid },
  };
  if (window.Plotly) {
    Plotly.newPlot(container, chart.figure.data, layout, { responsive: true, displaylogo: false });
  } else {
    container.textContent = "Charts need plotly.js, which could not be loaded.";
  }
}

function renderResult(dataset, profile, charts) {
  const s = profile.summary;
  document.getElementById("cards").replaceChildren(
    ...[
      ["Rows", fmtNumber(s.rows)],
      ["Columns", s.columns],
      ["Missing cells", `${s.missing_cells_pct}%`],
      ["Duplicate rows", fmtNumber(s.duplicate_rows)],
      ["Warnings", profile.warnings.length],
    ].map(([k, v]) => el("div", { class: "card" }, el("div", { class: "k", text: k }), el("div", { class: "v", text: String(v) }))),
  );

  const base = `/api/datasets/${dataset.id}`;
  document.getElementById("report-download").href = `${base}/report?download=true`;
  document.getElementById("report-open").href = `${base}/report`;
  document.getElementById("profile-json").href = `${base}/profile`;

  document.getElementById("warnings-title").textContent = `Warnings (${profile.warnings.length})`;
  const warnings = profile.warnings.length
    ? profile.warnings.map((w) => el("div", { class: "warn", text: w.message }))
    : [el("p", { class: "muted", text: "No issues found." })];
  document.getElementById("warnings").replaceChildren(...warnings);

  document.getElementById("columns").replaceChildren(...profile.columns.map((c) => el("tr", {},
    el("td", { class: "name", text: c.name }),
    el("td", {}, el("span", { class: "pill", text: c.kind })),
    el("td", { text: `${c.missing_pct}%` }),
    el("td", { text: fmtNumber(c.unique) }),
    el("td", { class: "muted", text: columnSummary(c) }),
  )));

  // Unhide first: Plotly measures its container, and a hidden one has zero width.
  document.getElementById("result").hidden = false;
  const grid = document.getElementById("charts");
  grid.replaceChildren();
  for (const chart of charts) {
    const box = el("div", { class: chart.id === "correlation" ? "chart wide" : "chart" });
    grid.append(box);
    drawChart(box, chart);
  }
}

async function loadDataset(id) {
  const dataset = await api(`/api/datasets/${id}`);
  document.title = `${dataset.filename} · DataDigest`;
  document.getElementById("title").textContent = dataset.filename;
  const status = document.getElementById("status");
  status.replaceChildren(badge(dataset.status));
  if (isPending(dataset.status)) status.append(el("span", { class: "spinner" }));
  document.getElementById("meta").textContent =
    `${fmtBytes(dataset.size_bytes)} · uploaded ${fmtAgo(dataset.created_at)}`;

  if (isPending(dataset.status)) {
    setTimeout(() => loadDataset(id), POLL_MS);
  } else if (dataset.status === "failed") {
    const box = document.getElementById("error");
    box.textContent = dataset.error || "Processing failed";
    box.hidden = false;
  } else {
    const [profile, charts] = await Promise.all([api(`/api/datasets/${id}/profile`), api(`/api/datasets/${id}/charts`)]);
    renderResult(dataset, profile, charts);
  }
}

function initDataset() {
  const id = location.pathname.split("/").filter(Boolean).pop();
  document.getElementById("delete").addEventListener("click", async () => {
    if (!confirm("Delete this dataset and its report?")) return;
    await api(`/api/datasets/${id}`, { method: "DELETE" });
    location.href = "/";
  });
  loadDataset(id).catch((err) => {
    document.getElementById("title").textContent = "Dataset not found";
    const box = document.getElementById("error");
    box.textContent = err.message;
    box.hidden = false;
  });
}

if (document.body.dataset.page === "index") initIndex();
if (document.body.dataset.page === "dataset") initDataset();
