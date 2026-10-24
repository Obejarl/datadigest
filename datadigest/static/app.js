// DataDigest dashboard. No framework: fetch the JSON API and build the DOM.
// Everything that comes from an uploaded file is written with textContent, never innerHTML.

const POLL_MS = 1500;
const STATUS_MS = 10000;

const COLORS = { cyan: "#22D3EE", violet: "#A78BFA", green: "#10E39A", amber: "#FFC857", red: "#FF4D6D", sub: "#93A1B4" };
const KIND_COLOR = { numeric: COLORS.cyan, categorical: COLORS.violet, datetime: COLORS.green, boolean: COLORS.amber, text: "#64748B" };
const GRADE = {
  A: { c: COLORS.green, label: "Clean" },
  B: { c: COLORS.cyan, label: "Good" },
  C: { c: COLORS.amber, label: "Needs attention" },
  D: { c: COLORS.red, label: "Poor" },
};
const gradeOf = (score) => (score >= 90 ? "A" : score >= 75 ? "B" : score >= 60 ? "C" : "D");

// Icons are constant markup written by us, never user data.
const ICONS = {
  db: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  rows: '<path d="M3 6h18M3 12h18M3 18h18"/>',
  cols: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16M15 4v16"/>',
  gauge: '<path d="M12 14l4-4"/><path d="M3.3 17a9 9 0 1 1 17.4 0"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>',
  check: '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
  hole: '<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>',
  memory: '<rect x="4" y="6" width="16" height="12" rx="2"/><path d="M8 10v4M12 10v4M16 10v4"/>',
  trash: '<path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/>',
  retry: '<path d="M3 12a9 9 0 0 1 15.5-6.2L21 8M21 3v5h-5M21 12a9 9 0 0 1-15.5 6.2L3 16M3 21v-5h5"/>',
};

function icon(name) {
  const tpl = document.createElement("template");
  tpl.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;
  return tpl.content.firstChild;
}

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "style") Object.assign(node.style, value);
    else node.setAttribute(key, value);
  }
  for (const child of children) if (child !== null && child !== undefined && child !== false) node.append(child);
  return node;
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

// Keyboard shortcuts must not fire while the user types in a field.
const isTyping = (e) => e.target instanceof Element && e.target.closest("input, textarea, select, [contenteditable]");

// ---------------------------------------------------------------- formatting

const fmtNumber = (n) => (n === null || n === undefined ? "–" : Number(n).toLocaleString("en-US"));
// Compact only where it helps: "1K" for 1,005 rows hides information.
const fmtCompact = (n) => (Math.abs(n || 0) < 10000 ? fmtNumber(n || 0)
  : new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n));

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

function fmtStat(v) {
  if (v === null || v === undefined) return "–";
  const abs = Math.abs(v);
  if (abs >= 1e6 || (abs > 0 && abs < 0.01)) return Number(v).toExponential(2);
  return Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 });
}

// ---------------------------------------------------------------- shared UI

function toast(message, color = COLORS.cyan) {
  const box = el("div", { class: "toast", text: message, role: "status" });
  box.style.setProperty("--c", color);
  document.getElementById("toasts").append(box);
  setTimeout(() => box.remove(), 4500);
}

/** A styled replacement for window.confirm(). Resolves to true when confirmed. */
function confirmDialog({ title, body, confirmText = "Confirm", danger = false }) {
  const dialog = el("dialog", { class: "modal", "aria-labelledby": "modal-title" });
  const cancel = el("button", { class: "btn", type: "button", text: "Cancel" });
  const ok = el("button", { class: danger ? "btn solid-danger" : "btn primary", type: "submit", value: "ok", text: confirmText });
  dialog.append(el("form", { method: "dialog" },
    el("h2", { id: "modal-title", text: title }), el("p", { text: body }), el("div", { class: "row" }, cancel, ok)));
  document.body.append(dialog);
  return new Promise((resolve) => {
    cancel.addEventListener("click", () => dialog.close("cancel"));
    dialog.addEventListener("close", () => { resolve(dialog.returnValue === "ok"); dialog.remove(); });
    dialog.showModal();
    ok.focus();
  });
}

async function deleteDataset(dataset) {
  const sure = await confirmDialog({
    title: "Delete this dataset?",
    body: `“${dataset.filename}”, its report and any optimization runs on it will be removed permanently.`,
    confirmText: "Delete",
    danger: true,
  });
  if (!sure) return false;
  await api(`/api/datasets/${dataset.id}`, { method: "DELETE" });
  toast(`Deleted ${dataset.filename}`, COLORS.green);
  return true;
}

const rerun = (id) => api(`/api/datasets/${id}/reprocess`, { method: "POST" });

function badge(status) {
  return el("span", { class: `badge ${status}` }, el("i"), status);
}

function meter(pct, color) {
  const bar = el("b");
  bar.style.setProperty("--c", color);
  requestAnimationFrame(() => requestAnimationFrame(() => { bar.style.width = `${Math.max(0, Math.min(100, pct))}%`; }));
  return el("div", { class: "meter", role: "presentation" }, bar);
}

function tile({ label, iconName, value, unit, sub, tint, color, extra, span2 }) {
  const lbl = el("div", { class: "lbl" }, icon(iconName), label);
  lbl.style.setProperty("--tc", color || COLORS.cyan);
  const v = el("div", { class: "v", text: value });
  if (unit) v.append(el("small", { text: unit }));
  const node = el("div", { class: span2 ? "tile span2" : "tile" }, lbl, v, sub ? el("div", { class: "s", text: sub }) : null, extra);
  node.style.setProperty("--tint", tint || "rgba(34,211,238,.2)");
  return node;
}

function skeletonTiles(n) {
  return Array.from({ length: n }, () => el("div", { class: "tile" },
    el("div", { class: "skel", style: { width: "45%", height: "12px" } }),
    el("div", { class: "skel", style: { width: "60%", height: "30px", marginTop: "14px" } }),
    el("div", { class: "skel", style: { width: "75%", height: "12px", marginTop: "12px" } })));
}

async function refreshStatus() {
  const pills = document.getElementById("pills");
  let ready = false;
  let stats = null;
  try { ready = (await fetch("/readyz")).ok; } catch {}
  try { stats = await api("/api/stats"); } catch {}

  const pill = (cls, text, opt, title) => el("span", { class: `pill ${cls}${opt ? " opt" : ""}`, title }, el("i"), text);
  const items = [pill(ready ? "ok live" : "bad", ready ? "API ready" : "API degraded", false, "Database and queue reachable")];
  if (stats) {
    items.push(stats.mode === "worker"
      ? pill("ok", "Worker mode", true, "Uploads are queued in Redis and profiled by worker processes")
      : pill("warn", "Inline mode", true, "No Redis configured: the API profiles uploads itself"));
    if (stats.queue_depth !== null) items.push(pill(stats.queue_depth ? "warn" : "ok", `Queue ${stats.queue_depth}`, true, "Jobs waiting for a worker"));
    if (stats.queue_dead) items.push(pill("bad", `Dead letters ${stats.queue_dead}`, true, "Jobs that failed every retry; their datasets or runs are marked failed"));
  }
  pills.replaceChildren(...items);
  return stats;
}

// Charts are drawn when their container scrolls into view. A hidden tab has no size,
// and Plotly would fall back to a 700px default, so drawing late is also drawing right.
const pendingCharts = new Map();
const chartObserver = "IntersectionObserver" in window
  ? new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const draw = pendingCharts.get(entry.target);
        chartObserver.unobserve(entry.target);
        pendingCharts.delete(entry.target);
        if (draw) draw();
      }
    }, { rootMargin: "200px" })
  : null;

function themedLayout(layout, compact) {
  const axis = (a = {}) => ({ ...a, gridcolor: "rgba(148,163,184,0.10)", zerolinecolor: "rgba(148,163,184,0.18)", linecolor: "rgba(148,163,184,0.18)" });
  const out = {
    ...layout,
    title: undefined,
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "Inter, system-ui, sans-serif", size: 12, color: COLORS.sub },
    xaxis: axis(layout.xaxis),
    yaxis: axis(layout.yaxis),
    hoverlabel: { bgcolor: "#0f1626", bordercolor: COLORS.cyan, font: { family: "Roboto Mono, monospace", color: "#E6EDF3" } },
    margin: { ...(layout.margin || {}), t: 8 },
  };
  if (compact) {
    out.height = 200;
    out.margin = { l: (layout.margin && layout.margin.l > 60) ? 110 : 44, r: 8, t: 6, b: 30 };
  }
  return out;
}

function chartInto(container, chart, compact = false) {
  const draw = () => {
    if (!window.Plotly) { container.textContent = "Charts need plotly.js, which could not be loaded."; return; }
    Plotly.newPlot(container, chart.figure.data, themedLayout(chart.figure.layout, compact),
                   { responsive: true, displaylogo: false, displayModeBar: false });
  };
  if (chartObserver) { pendingCharts.set(container, draw); chartObserver.observe(container); } else { draw(); }
}

function okState(text) {
  return el("div", { class: "ok-state" }, icon("check"), text);
}

// ---------------------------------------------------------------- index page

function renderKpis(stats) {
  const box = document.getElementById("kpis");
  if (!stats) return;
  const s = stats.by_status;
  const parts = [`${s.done || 0} done`];
  if (s.processing || s.queued) parts.push(`${(s.processing || 0) + (s.queued || 0)} in progress`);
  if (s.failed) parts.push(`${s.failed} failed`);

  const q = stats.avg_quality;
  const qGrade = q === null ? null : gradeOf(q);
  box.replaceChildren(
    tile({ label: "Datasets", iconName: "db", value: fmtNumber(stats.datasets), sub: parts.join(" · ") }),
    tile({ label: "Rows profiled", iconName: "rows", value: fmtCompact(stats.rows_profiled), sub: `${fmtNumber(stats.rows_profiled)} rows in completed datasets`,
           color: COLORS.violet, tint: "rgba(167,139,250,.22)" }),
    tile({ label: "Average quality", iconName: "gauge", value: q === null ? "–" : String(Math.round(q)), unit: q === null ? "" : "/ 100",
           sub: q === null ? "No completed datasets yet" : `Grade ${qGrade} · ${GRADE[qGrade].label}`, color: COLORS.green,
           tint: "rgba(16,227,154,.18)", extra: q === null ? null : meter(q, GRADE[qGrade].c) }),
    tile({ label: "Avg. processing", iconName: "clock", value: stats.avg_seconds === null ? "–" : stats.avg_seconds.toFixed(2), unit: stats.avg_seconds === null ? "" : "s",
           sub: `${fmtNumber(stats.warnings_found)} warnings found so far`, color: COLORS.amber, tint: "rgba(255,200,87,.16)" }),
  );
}

let allDatasets = null;  // null until the first load, so we can show skeleton rows

function skeletonRows(n) {
  return Array.from({ length: n }, () => el("tr", {}, ...Array.from({ length: 9 }, (_, i) =>
    el("td", {}, el("div", { class: "skel", style: { height: "14px", width: i === 0 ? "140px" : "56px" } })))));
}

function rowActions(d) {
  const actions = el("div", { class: "row-actions" });
  if (d.status === "failed" || d.status === "done") {
    const retry = el("button", { class: "icon-btn", type: "button", title: d.status === "failed" ? "Try again" : "Re-run analysis", "aria-label": `Re-run ${d.filename}` }, icon("retry"));
    retry.addEventListener("click", async () => {
      try { await rerun(d.id); toast(`Re-running ${d.filename}`); refreshIndex(); } catch (err) { toast(err.message, COLORS.red); }
    });
    actions.append(retry);
  }
  const del = el("button", { class: "icon-btn danger", type: "button", title: "Delete", "aria-label": `Delete ${d.filename}` }, icon("trash"));
  del.addEventListener("click", async () => {
    try { if (await deleteDataset(d)) refreshIndex(); } catch (err) { toast(err.message, COLORS.red); }
  });
  actions.append(del);
  return actions;
}

function renderTable() {
  const body = document.getElementById("datasets");
  if (allDatasets === null) { body.replaceChildren(...skeletonRows(3)); return; }
  const query = document.getElementById("search").value.trim().toLowerCase();
  const rows = allDatasets.filter((d) => d.filename.toLowerCase().includes(query));
  body.replaceChildren();
  if (!rows.length) {
    const cell = el("td", { class: "empty", colspan: "9" });
    if (allDatasets.length) cell.textContent = "No datasets match this filter.";
    else cell.append("No datasets yet. Drop a CSV above to get started.",
                     el("span", { class: "sample-hint muted", text: "No file at hand? Pick one of the samples above." }));
    body.append(el("tr", {}, cell));
    return;
  }
  for (const d of rows) {
    let quality = el("span", { class: "muted", text: "–" });
    if (d.quality_score !== null) {
      const g = gradeOf(d.quality_score);
      const cell = el("div", { class: "qcell", title: `Quality ${d.quality_score}/100, grade ${g}` },
        el("span", { class: "g", text: `${g} ${d.quality_score}` }), meter(d.quality_score, GRADE[g].c));
      cell.style.setProperty("--c", GRADE[g].c);
      quality = cell;
    }
    body.append(el("tr", {},
      el("td", { class: "name" }, el("a", { href: `/datasets/${d.id}`, text: d.filename })),
      el("td", { title: d.error || "" }, badge(d.status)),
      el("td", {}, quality),
      el("td", {}, el("span", { class: "num", text: fmtNumber(d.rows) })),
      el("td", {}, el("span", { class: "num", text: fmtNumber(d.cols) })),
      el("td", {}, el("span", { class: "num", text: fmtNumber(d.warnings_count) })),
      el("td", {}, el("span", { class: "num", text: fmtBytes(d.size_bytes) })),
      el("td", { class: "muted", text: fmtAgo(d.created_at) }),
      el("td", {}, rowActions(d)),
    ));
  }
}

let indexPoll = null;
async function refreshIndex() {
  clearTimeout(indexPoll);
  const [datasets, stats] = await Promise.all([api("/api/datasets"), refreshStatus()]);
  allDatasets = datasets;
  renderTable();
  renderKpis(stats);
  if (datasets.some((d) => d.status === "queued" || d.status === "processing")) indexPoll = setTimeout(refreshIndex, POLL_MS);
}

/** Upload one file with progress (XMLHttpRequest reports upload progress, fetch does not). */
function uploadOne(file, onProgress) {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/datasets");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch {}
      if (xhr.status === 202) resolve(data); else reject(new Error(data.detail || xhr.statusText));
    };
    xhr.onerror = () => reject(new Error("network error"));
    xhr.send(form);
  });
}

async function uploadFiles(files) {
  const list = document.getElementById("uploads");
  const results = [];
  for (const file of files) {  // one at a time: predictable progress, no burst on the API
    const fill = el("b");
    const state = el("span", { class: "st", text: fmtBytes(file.size) });
    const row = el("div", { class: "up" }, el("span", { class: "n", text: file.name }), state, el("div", { class: "progress" }, fill));
    list.append(row);
    try {
      const dataset = await uploadOne(file, (p) => { fill.style.width = `${p * 100}%`; });
      fill.style.width = "100%";
      state.className = "st ok";
      state.textContent = "uploaded";
      row.replaceChild(el("a", { class: "n", href: `/datasets/${dataset.id}`, text: file.name }), row.firstChild);
      results.push(dataset);
    } catch (err) {
      state.className = "st err";
      state.textContent = err.message;
    }
  }
  if (files.length === 1 && results.length === 1) { location.href = `/datasets/${results[0].id}`; return; }
  if (results.length) toast(`${results.length} of ${files.length} files uploaded`, COLORS.green);
  setTimeout(() => list.replaceChildren(), 8000);
  refreshIndex();
}

async function loadSamples() {
  const box = document.getElementById("samples");
  let samples = [];
  try { samples = await api("/api/samples"); } catch { return; }
  if (!samples.length) return;
  box.replaceChildren(el("span", { text: "No file at hand? Try a sample:" }), ...samples.map((s) => {
    const btn = el("button", { class: "sample", type: "button" }, s.name, el("small", { text: s.description }));
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try { location.href = `/datasets/${(await api(`/api/samples/${encodeURIComponent(s.name)}`, { method: "POST" })).id}`; }
      catch (err) { btn.disabled = false; toast(err.message, COLORS.red); }
    });
    return btn;
  }));
  box.hidden = false;
}

function initIndex() {
  const drop = document.getElementById("drop");
  const input = document.getElementById("file");
  const search = document.getElementById("search");
  const take = (files) => { if (files && files.length) uploadFiles([...files]); };
  input.addEventListener("change", () => { take(input.files); input.value = ""; });
  document.getElementById("top-upload").addEventListener("click", () => input.click());
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  for (const type of ["dragenter", "dragover"]) drop.addEventListener(type, (e) => { e.preventDefault(); drop.classList.add("over"); });
  for (const type of ["dragleave", "drop"]) drop.addEventListener(type, (e) => { e.preventDefault(); drop.classList.remove("over"); });
  drop.addEventListener("drop", (e) => take(e.dataTransfer.files));
  search.addEventListener("input", renderTable);
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !isTyping(e)) { e.preventDefault(); search.focus(); }
  });
  if (location.hash === "#upload") {
    drop.scrollIntoView({ block: "center" });
    drop.focus();
    drop.classList.add("over");
    setTimeout(() => drop.classList.remove("over"), 1600);
  }
  document.getElementById("kpis").replaceChildren(...skeletonTiles(4));
  renderTable();
  loadSamples();
  refreshIndex().catch((err) => toast(err.message, COLORS.red));
  setInterval(() => refreshStatus().then(renderKpis), STATUS_MS);
}

// -------------------------------------------------------------- dataset page

const WARNING_STYLE = {
  high_missing: { c: COLORS.amber, icon: "alert", label: "missing data" },
  constant: { c: COLORS.amber, icon: "alert", label: "constant column" },
  duplicates: { c: COLORS.amber, icon: "copy", label: "duplicates" },
  outliers: { c: COLORS.violet, icon: "info", label: "outliers" },
  skewed: { c: COLORS.violet, icon: "info", label: "skewed" },
  high_correlation: { c: COLORS.cyan, icon: "info", label: "correlation" },
  unique_id: { c: COLORS.cyan, icon: "info", label: "identifier" },
};

let showTab = () => {};
const columnCards = new Map();  // column name -> card element

function ring(score, color) {
  const r = 46;
  const length = 2 * Math.PI * r;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 104 104");
  svg.setAttribute("aria-hidden", "true");
  for (const cls of ["track", "arc"]) {
    const c = document.createElementNS(ns, "circle");
    c.setAttribute("cx", "52"); c.setAttribute("cy", "52"); c.setAttribute("r", String(r)); c.setAttribute("class", cls);
    if (cls === "arc") {
      c.style.strokeDasharray = String(length);
      c.style.strokeDashoffset = String(length);
      requestAnimationFrame(() => requestAnimationFrame(() => { c.style.strokeDashoffset = String(length * (1 - score / 100)); }));
    }
    svg.append(c);
  }
  const box = el("div", { class: "ring", role: "img", "aria-label": `Quality score ${score} of 100` }, svg,
    el("div", { class: "inner" }, el("div", { class: "score mono", text: String(score) }), el("div", { class: "grade", text: "OF 100" })));
  box.style.setProperty("--c", color);
  return box;
}

function kindSplit(kinds) {
  const total = Object.values(kinds).reduce((a, b) => a + b, 0) || 1;
  const split = el("div", { class: "split", role: "presentation" });
  const legend = el("div", { class: "legend" });
  for (const [kind, n] of Object.entries(kinds)) {
    const color = KIND_COLOR[kind] || COLORS.sub;
    const part = el("b", { style: { flexGrow: String(n / total), flexBasis: "0" } });
    part.style.setProperty("--c", color);
    split.append(part);
    const item = el("span", { text: `${n} ${kind}` });
    item.style.setProperty("--c", color);
    legend.append(item);
  }
  return [split, legend];
}

function breakdown(penalties) {
  if (!penalties) return null;
  const labels = { missing: "missing", duplicates: "duplicates", warnings: "warnings" };
  const parts = Object.entries(penalties).filter(([, v]) => v > 0)
    .map(([k, v]) => el("span", { title: `Points taken off for ${labels[k] || k}` }, el("b", { text: `−${v}` }), ` ${labels[k] || k}`));
  return el("div", { class: "breakdown" }, ...(parts.length ? parts : [el("span", { text: "no deductions" })]));
}

function renderTiles(profile, dataset) {
  const s = profile.summary;
  const q = s.quality;  // absent on datasets profiled before the score existed
  const g = q ? GRADE[q.grade] : { c: COLORS.sub, label: "" };
  const [split, legend] = kindSplit(s.kinds);
  let headline = el("div", { style: { fontSize: "20px", fontWeight: "700" }, text: q ? `Grade ${q.grade} · ${g.label}` : "No score yet" });
  if (!q) {
    const btn = el("button", { class: "btn", type: "button", style: { marginTop: "6px" }, text: "Re-run to compute it" });
    btn.addEventListener("click", () => rerun(dataset.id).then(() => location.reload()).catch((err) => toast(err.message, COLORS.red)));
    headline = el("div", {}, headline, el("div", { class: "muted", text: "Profiled by an older version of DataDigest." }), btn);
  }
  const quality = el("div", { class: "tile span2" },
    el("div", { class: "lbl" }, icon("gauge"), "Quality score"),
    el("div", { class: "quality" }, q ? ring(q.score, g.c) : null,
      el("div", { class: "facts" }, headline,
        el("div", { class: "muted", style: { fontSize: "13px", marginTop: "2px" }, text: `${profile.warnings.length} warnings · ${s.missing_cells_pct}% missing · ${s.duplicate_rows} duplicates` }),
        q ? breakdown(q.penalties) : null, split, legend)));
  quality.style.setProperty("--tint", g.c + "33");

  const kindsSub = Object.entries(s.kinds).map(([k, n]) => `${n} ${k}`).join(" · ");
  document.getElementById("tiles").replaceChildren(
    quality,
    tile({ label: "Rows", iconName: "rows", value: fmtCompact(s.rows), sub: `${fmtNumber(s.rows)} rows${s.truncated ? " (truncated)" : ""}`, color: COLORS.violet, tint: "rgba(167,139,250,.22)" }),
    tile({ label: "Columns", iconName: "cols", value: String(s.columns), sub: kindsSub }),
    tile({ label: "Missing cells", iconName: "hole", value: String(s.missing_cells_pct), unit: "%", sub: `${fmtNumber(s.missing_cells)} empty cells`,
           color: COLORS.amber, tint: "rgba(255,200,87,.16)", extra: meter(s.missing_cells_pct, COLORS.amber) }),
    tile({ label: "Duplicate rows", iconName: "copy", value: fmtNumber(s.duplicate_rows), sub: `${((100 * s.duplicate_rows) / (s.rows || 1)).toFixed(2)}% of rows`,
           color: COLORS.red, tint: "rgba(255,77,109,.14)" }),
    tile({ label: "Warnings", iconName: "alert", value: String(profile.warnings.length), sub: profile.warnings.length ? "Click one to see its column" : "Nothing to flag",
           color: COLORS.amber, tint: "rgba(255,200,87,.16)" }),
    tile({ label: "Memory", iconName: "memory", value: fmtBytes(s.memory_bytes), sub: "In-memory size while profiling", color: COLORS.green, tint: "rgba(16,227,154,.16)" }),
  );
}

function jumpToColumn(name) {
  const card = columnCards.get(name);
  if (!card) return;
  showTab("columns");
  card.hidden = false;
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  card.classList.remove("flash");
  void card.offsetWidth;  // restart the animation
  card.classList.add("flash");
}

function renderOverview(profile, charts) {
  const s = profile.summary;
  document.getElementById("warn-count").textContent = String(profile.warnings.length);
  const warnings = profile.warnings.map((w) => {
    const style = WARNING_STYLE[w.type] || { c: COLORS.amber, icon: "alert", label: w.type };
    const target = w.columns && w.columns[0];
    const node = el(target ? "button" : "div", { class: target ? "issue link" : "issue", type: target ? "button" : null },
      icon(style.icon),
      el("div", { style: { textAlign: "left" } }, el("div", { class: "m", text: w.message }), el("div", { class: "t", text: style.label })),
      target ? el("span", { class: "go", text: "view column →" }) : null);
    node.style.setProperty("--c", style.c);
    if (target) {
      Object.assign(node.style, { font: "inherit", color: "inherit", width: "100%" });
      node.addEventListener("click", () => jumpToColumn(target));
    }
    return node;
  });
  document.getElementById("warnings").replaceChildren(...(warnings.length ? warnings : [okState("No data-quality issues found")]));

  const missingBox = document.getElementById("missing");
  const missing = charts.find((c) => c.id === "missing");
  missingBox.replaceChildren();
  if (missing) { const box = el("div", { class: "chart" }); missingBox.append(box); chartInto(box, missing); }
  else missingBox.append(okState("Every cell has a value"));

  const facts = [
    ["Encoding", s.encoding], ["Delimiter", s.delimiter === "\t" ? "TAB" : s.delimiter],
    ["Rows × columns", `${fmtNumber(s.rows)} × ${s.columns}`], ["Memory", fmtBytes(s.memory_bytes)],
    ["Duplicate rows", fmtNumber(s.duplicate_rows)], ["Truncated", s.truncated ? "yes (row limit)" : "no"],
  ];
  document.getElementById("facts").replaceChildren(...facts.flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })]));
}

function columnStats(c) {
  const third = {
    numeric: ["Mean", fmtStat(c.mean)],
    categorical: ["Top", c.top && c.top[0] ? c.top[0].value : "–"],
    boolean: ["Top", c.top && c.top[0] ? c.top[0].value : "–"],
    datetime: ["Span", c.span_days === undefined ? "–" : `${fmtNumber(c.span_days)} d`],
    text: ["Avg len", fmtStat(c.avg_length)],
  }[c.kind] || ["–", "–"];
  return [["Missing", `${c.missing_pct}%`], ["Unique", fmtNumber(c.unique)], third];
}

function columnSummary(c) {
  if (c.kind === "numeric" && c.min !== undefined) return `min ${fmtStat(c.min)} · median ${fmtStat(c.median)} · max ${fmtStat(c.max)}`;
  if (c.kind === "datetime" && c.min) return `${c.min.slice(0, 10)} → ${c.max.slice(0, 10)}`;
  if (c.top && c.top.length) return c.top.slice(0, 3).map((t) => `${t.value} (${t.count})`).join(" · ");
  if (c.examples && c.examples.length) return `e.g. ${c.examples[0]}`;
  return "";
}

function renderColumns(profile, charts) {
  const byColumn = new Map(charts.filter((c) => c.column).map((c) => [c.column, c]));
  const grid = document.getElementById("cols");
  columnCards.clear();
  const cards = profile.columns.map((c, index) => {
    const card = el("article", { class: "col", "data-kind": c.kind, "data-name": c.name.toLowerCase() },
      el("div", { class: "col-h" }, el("h3", { text: c.name }), el("span", { class: `kind ${c.kind}`, text: c.kind })),
      el("div", { class: "col-stats" }, ...columnStats(c).map(([k, v]) => el("div", {}, el("div", { class: "k", text: k }), el("div", { class: "v", text: v, title: v })))),
      c.missing_pct > 0 ? meter(c.missing_pct, c.missing_pct >= 20 ? COLORS.amber : COLORS.sub) : null,
      el("div", { class: "sum", text: columnSummary(c) }));
    const chart = byColumn.get(c.name);
    if (chart) { const box = el("div", { class: "mini" }); card.append(box); chartInto(box, chart, true); }
    columnCards.set(c.name, card);
    return { card, c, index };
  });
  grid.replaceChildren(...cards.map((x) => x.card));
  document.getElementById("col-count").textContent = String(profile.columns.length);

  const counts = {};
  for (const c of profile.columns) counts[c.kind] = (counts[c.kind] || 0) + 1;
  const filters = document.getElementById("filters");
  const search = document.getElementById("col-search");
  const sort = document.getElementById("col-sort");
  let active = "all";
  const apply = () => {
    const q = search.value.trim().toLowerCase();
    for (const { card } of cards) {
      card.hidden = !((active === "all" || card.dataset.kind === active) && card.dataset.name.includes(q));
    }
  };
  const order = {
    order: (a, b) => a.index - b.index,
    missing: (a, b) => b.c.missing_pct - a.c.missing_pct || a.index - b.index,
    unique: (a, b) => b.c.unique - a.c.unique || a.index - b.index,
    name: (a, b) => a.c.name.localeCompare(b.c.name),
  };
  // Assigned (not addEventListener) so a re-render after "Re-run" replaces the handlers instead of stacking them.
  sort.value = "order";
  sort.onchange = () => grid.append(...[...cards].sort(order[sort.value]).map((x) => x.card));  // moving nodes keeps charts
  search.value = "";
  search.oninput = apply;
  const chips = [["all", profile.columns.length], ...Object.entries(counts)].map(([kind, n]) => {
    const chip = el("button", { class: kind === "all" ? "fchip active" : "fchip", type: "button", "aria-pressed": String(kind === "all") },
      kind === "all" ? "All" : kind, el("span", { text: String(n) }));
    chip.addEventListener("click", () => {
      active = kind;
      for (const other of filters.querySelectorAll(".fchip")) {
        other.classList.toggle("active", other === chip);
        other.setAttribute("aria-pressed", String(other === chip));
      }
      apply();
    });
    return chip;
  });
  filters.replaceChildren(...chips, search, sort);
}

function renderCorrelations(profile, charts) {
  const heat = charts.find((c) => c.id === "correlation");
  const heatBox = document.getElementById("heatmap");
  const pairsBox = document.getElementById("pairs");
  if (!heat) {
    const msg = "Correlations need at least two numeric columns with varying values.";
    heatBox.replaceChildren(el("p", { class: "muted", text: msg }));
    pairsBox.replaceChildren(el("p", { class: "muted", text: "Nothing to compare." }));
    return;
  }
  const box = el("div", { class: "chart" });
  heatBox.replaceChildren(box);
  chartInto(box, heat);

  const { columns, matrix } = profile.correlations;
  const pairs = [];
  for (let i = 0; i < columns.length; i++) {
    for (let j = i + 1; j < columns.length; j++) {
      if (matrix[i][j] !== null) pairs.push([columns[i], columns[j], matrix[i][j]]);
    }
  }
  pairs.sort((a, b) => Math.abs(b[2]) - Math.abs(a[2]));
  pairsBox.replaceChildren(...pairs.slice(0, 10).map(([a, b, r]) => {
    const color = r >= 0 ? COLORS.cyan : COLORS.red;
    const row = el("div", { class: "pair" },
      el("div", { class: "names", text: `${a} × ${b}`, title: `${a} × ${b}` }),
      el("div", { class: "r", text: (r >= 0 ? "+" : "") + r.toFixed(2) }),
      meter(Math.abs(r) * 100, color));
    row.style.setProperty("--c", color);
    return row;
  }));
}

function renderPreview(profile) {
  const preview = profile.preview;
  const head = document.getElementById("preview-head");
  const body = document.getElementById("preview-body");
  const note = document.getElementById("preview-note");
  if (!preview) {
    body.replaceChildren(el("tr", {}, el("td", { class: "empty", text: "No preview: re-run the analysis to add one." })));
    return;
  }
  const kinds = new Map(profile.columns.map((c) => [c.name, c.kind]));
  head.replaceChildren(el("tr", {}, el("th", { class: "rn", text: "#" }),
    ...preview.columns.map((name) => el("th", {}, name, el("span", { class: `kind ${kinds.get(name) || "text"}`, text: kinds.get(name) || "?" })))));
  body.replaceChildren(...preview.rows.map((row, i) => el("tr", {}, el("td", { class: "rn", text: String(i + 1) }),
    ...row.map((v) => (v === null ? el("td", { class: "null", text: "empty" }) : el("td", { text: v, title: v }))))));
  note.textContent = `${preview.rows.length} of ${fmtNumber(profile.summary.rows)} rows`;
}

function initTabs() {
  const tabs = [...document.querySelectorAll(".tab")];
  showTab = (name) => {
    for (const t of tabs) {
      t.classList.toggle("active", t.dataset.tab === name);
      t.setAttribute("aria-selected", String(t.dataset.tab === name));
    }
    for (const p of document.querySelectorAll(".pane")) p.classList.toggle("active", p.id === `pane-${name}`);
    history.replaceState(null, "", name === "overview" ? location.pathname : `#${name}`);  // shareable links
  };
  for (const t of tabs) t.addEventListener("click", () => showTab(t.dataset.tab));
  const fromHash = location.hash.slice(1);
  if (tabs.some((t) => t.dataset.tab === fromHash)) showTab(fromHash);
  document.addEventListener("keydown", (e) => {
    if (isTyping(e) || e.metaKey || e.ctrlKey || e.altKey) return;
    const tab = tabs[Number(e.key) - 1];
    if (tab && !document.getElementById("result").hidden) showTab(tab.dataset.tab);
  });
}

function renderPending(dataset, mode) {
  const order = ["uploaded", "queued", "processing", "done"];
  const labels = { uploaded: "Uploaded", queued: "Queued", processing: "Profiling", done: "Ready" };
  const current = order.indexOf(dataset.status);
  const parts = [];
  order.forEach((step, i) => {
    if (i) parts.push(el("div", { class: i <= current ? "step-line done" : "step-line" }));
    const state = i < current ? "done" : i === current ? "now" : "";
    parts.push(el("div", { class: `step ${state}` }, el("span", { class: "dot", text: i < current ? "✓" : String(i + 1) }), labels[step]));
  });
  document.getElementById("stepper").replaceChildren(...parts);
  document.getElementById("pending-note").textContent = mode === "worker"
    ? "A worker picks this job from the Redis queue. This page updates by itself."
    : "The API is profiling the file in the background (inline mode). This page updates by itself.";
}

async function loadDataset(id, mode) {
  const dataset = await api(`/api/datasets/${id}`);
  document.title = `${dataset.filename} · DataDigest`;
  document.getElementById("title").textContent = dataset.filename;
  document.getElementById("crumb").textContent = dataset.filename;
  const chips = [fmtBytes(dataset.size_bytes), `uploaded ${fmtAgo(dataset.created_at)}`];
  if (dataset.finished_at && dataset.status === "done") {
    const started = dataset.queued_at || dataset.created_at;
    chips.push(`profiled in ${((new Date(dataset.finished_at) - new Date(started)) / 1000).toFixed(2)} s`);
  }
  document.getElementById("chips").replaceChildren(badge(dataset.status), ...chips.map((c) => el("span", { class: "chip", text: c })));

  const pending = dataset.status === "queued" || dataset.status === "processing";
  document.getElementById("pending").hidden = !pending;
  document.getElementById("failed").hidden = dataset.status !== "failed";
  document.getElementById("result").hidden = true;
  if (pending) {
    document.getElementById("actions").hidden = true;
    renderPending(dataset, mode);
    setTimeout(() => loadDataset(id, mode), POLL_MS);
    return;
  }
  document.getElementById("actions").hidden = false;
  document.getElementById("optimize-link").href = `/optimize?dataset=${id}`;
  document.getElementById("report-actions").hidden = dataset.status !== "done";
  document.getElementById("rerun").hidden = dataset.status !== "done";
  if (dataset.status === "failed") {
    document.getElementById("error").textContent = dataset.error || "Processing failed";
    return;
  }

  const base = `/api/datasets/${id}`;
  document.getElementById("report-download").href = `${base}/report?download=true`;
  document.getElementById("report-open").href = `${base}/report`;
  document.getElementById("profile-json").href = `${base}/profile`;
  const [profile, charts] = await Promise.all([api(`${base}/profile`), api(`${base}/charts`)]);
  const s = profile.summary;
  document.getElementById("chips").append(
    el("span", { class: "chip", text: s.encoding }),
    el("span", { class: "chip", text: `sep ${s.delimiter === "\t" ? "TAB" : s.delimiter}` }));

  document.getElementById("result").hidden = false;  // before charts: they measure their containers
  renderTiles(profile, dataset);
  renderOverview(profile, charts);
  renderColumns(profile, charts);
  renderCorrelations(profile, charts);
  renderPreview(profile);
}

function initDataset() {
  const id = location.pathname.split("/").filter(Boolean).pop();
  let mode = null;
  initTabs();
  document.getElementById("tiles").replaceChildren(...skeletonTiles(4));

  const startRerun = async () => {
    try {
      await rerun(id);
      toast("Analysis started again");
      loadDataset(id, mode);
    } catch (err) { toast(err.message, COLORS.red); }
  };
  document.getElementById("rerun").addEventListener("click", startRerun);
  document.getElementById("retry").addEventListener("click", startRerun);
  document.getElementById("copy-link").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(location.href); toast("Link copied", COLORS.green); }
    catch { toast("Could not copy; copy the address bar instead", COLORS.amber); }
  });
  document.getElementById("delete").addEventListener("click", async () => {
    try {
      const name = document.getElementById("title").textContent;
      if (await deleteDataset({ id, filename: name })) location.href = "/";
    } catch (err) { toast(`Delete failed: ${err.message}`, COLORS.red); }
  });

  refreshStatus()
    .then((stats) => { mode = stats && stats.mode; return loadDataset(id, mode); })
    .catch((err) => {
      document.getElementById("title").textContent = "Dataset not found";
      document.getElementById("crumb").textContent = "not found";
      document.getElementById("tiles").replaceChildren();
      toast(err.message, COLORS.red);
    });
  setInterval(refreshStatus, STATUS_MS);
}

if (document.body.dataset.page === "index") initIndex();
if (document.body.dataset.page === "dataset") initDataset();
