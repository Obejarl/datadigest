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
};

function icon(name) {
  const tpl = document.createElement("template");
  tpl.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</svg>`;
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
  for (const child of children) if (child !== null && child !== undefined) node.append(child);
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
  const box = el("div", { class: "toast", text: message, style: { "--c": color } });
  box.style.setProperty("--c", color);
  document.getElementById("toasts").append(box);
  setTimeout(() => box.remove(), 4500);
}

function badge(status) {
  return el("span", { class: `badge ${status}` }, el("i"), status);
}

function meter(pct, color) {
  const bar = el("b");
  bar.style.setProperty("--c", color);
  requestAnimationFrame(() => requestAnimationFrame(() => { bar.style.width = `${Math.max(0, Math.min(100, pct))}%`; }));
  return el("div", { class: "meter" }, bar);
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

async function refreshStatus() {
  const pills = document.getElementById("pills");
  let ready = false;
  let stats = null;
  try { ready = (await fetch("/readyz")).ok; } catch {}
  try { stats = await api("/api/stats"); } catch {}

  const pill = (cls, text, opt) => el("span", { class: `pill ${cls}${opt ? " opt" : ""}` }, el("i"), text);
  const items = [pill(ready ? "ok live" : "bad", ready ? "API ready" : "API degraded")];
  if (stats) {
    items.push(pill(stats.mode === "worker" ? "ok" : "warn", stats.mode === "worker" ? "Worker mode" : "Inline mode", true));
    if (stats.queue_depth !== null) items.push(pill(stats.queue_depth ? "warn" : "ok", `Queue ${stats.queue_depth}`, true));
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

let allDatasets = [];

function renderTable() {
  const body = document.getElementById("datasets");
  const query = document.getElementById("search").value.trim().toLowerCase();
  const rows = allDatasets.filter((d) => d.filename.toLowerCase().includes(query));
  body.replaceChildren();
  if (!rows.length) {
    const msg = allDatasets.length ? "No datasets match this filter." : "No datasets yet. Drop a CSV above to get started.";
    body.append(el("tr", {}, el("td", { class: "empty", colspan: "8", text: msg })));
    return;
  }
  for (const d of rows) {
    let quality = el("span", { class: "muted", text: "–" });
    if (d.quality_score !== null) {
      const g = gradeOf(d.quality_score);
      const cell = el("div", { class: "qcell" }, el("span", { class: "g", text: `${g} ${d.quality_score}` }), meter(d.quality_score, GRADE[g].c));
      cell.style.setProperty("--c", GRADE[g].c);
      quality = cell;
    }
    body.append(el("tr", {},
      el("td", { class: "name" }, el("a", { href: `/datasets/${d.id}`, text: d.filename })),
      el("td", {}, badge(d.status)),
      el("td", {}, quality),
      el("td", {}, el("span", { class: "num", text: fmtNumber(d.rows) })),
      el("td", {}, el("span", { class: "num", text: fmtNumber(d.cols) })),
      el("td", {}, el("span", { class: "num", text: fmtNumber(d.warnings_count) })),
      el("td", {}, el("span", { class: "num", text: fmtBytes(d.size_bytes) })),
      el("td", { class: "muted", text: fmtAgo(d.created_at) }),
    ));
  }
}

async function refreshIndex() {
  const [datasets, stats] = await Promise.all([api("/api/datasets"), refreshStatus()]);
  allDatasets = datasets;
  renderTable();
  renderKpis(stats);
  if (datasets.some((d) => d.status === "queued" || d.status === "processing")) setTimeout(refreshIndex, POLL_MS);
}

function uploadFile(file) {
  const bar = document.getElementById("progress");
  const fill = bar.firstElementChild;
  bar.hidden = false;
  fill.style.width = "0%";
  const form = new FormData();
  form.append("file", file);

  // XMLHttpRequest instead of fetch: it reports upload progress.
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/datasets");
  xhr.upload.onprogress = (e) => { if (e.lengthComputable) fill.style.width = `${(100 * e.loaded) / e.total}%`; };
  xhr.onload = () => {
    let data = {};
    try { data = JSON.parse(xhr.responseText); } catch {}
    if (xhr.status === 202) {
      location.href = `/datasets/${data.id}`;
    } else {
      bar.hidden = true;
      toast(`Upload failed: ${data.detail || xhr.statusText}`, COLORS.red);
    }
  };
  xhr.onerror = () => { bar.hidden = true; toast("Upload failed: network error", COLORS.red); };
  xhr.send(form);
}

function initIndex() {
  const drop = document.getElementById("drop");
  const input = document.getElementById("file");
  input.addEventListener("change", () => input.files[0] && uploadFile(input.files[0]));
  document.getElementById("top-upload").addEventListener("click", () => input.click());
  for (const type of ["dragenter", "dragover"]) drop.addEventListener(type, (e) => { e.preventDefault(); drop.classList.add("over"); });
  for (const type of ["dragleave", "drop"]) drop.addEventListener(type, (e) => { e.preventDefault(); drop.classList.remove("over"); });
  drop.addEventListener("drop", (e) => e.dataTransfer.files[0] && uploadFile(e.dataTransfer.files[0]));
  document.getElementById("search").addEventListener("input", renderTable);
  if (location.hash === "#upload") {
    drop.scrollIntoView({ block: "center" });
    drop.classList.add("over");
    setTimeout(() => drop.classList.remove("over"), 1600);
  }
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

function ring(score, color) {
  const r = 46;
  const length = 2 * Math.PI * r;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 104 104");
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
  const box = el("div", { class: "ring" }, svg,
    el("div", { class: "inner" }, el("div", { class: "score mono", text: String(score) }), el("div", { class: "grade", text: "OF 100" })));
  box.style.setProperty("--c", color);
  return box;
}

function kindSplit(kinds) {
  const total = Object.values(kinds).reduce((a, b) => a + b, 0) || 1;
  const split = el("div", { class: "split" });
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

function renderTiles(profile) {
  const s = profile.summary;
  const q = s.quality;  // absent on datasets profiled before the score existed
  const g = q ? GRADE[q.grade] : { c: COLORS.sub, label: "" };
  const [split, legend] = kindSplit(s.kinds);
  const headline = q ? `Grade ${q.grade} · ${g.label}` : "No score (profiled by an older version)";
  const quality = el("div", { class: "tile span2" },
    el("div", { class: "lbl" }, icon("gauge"), "Quality score"),
    el("div", { class: "quality" }, q ? ring(q.score, g.c) : null,
      el("div", { class: "facts" },
        el("div", { style: { fontSize: "20px", fontWeight: "700" }, text: headline }),
        el("div", { class: "muted", style: { fontSize: "13px", marginTop: "2px" }, text: `${profile.warnings.length} warnings · ${s.missing_cells_pct}% missing · ${s.duplicate_rows} duplicates` }),
        split, legend)));
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
    tile({ label: "Warnings", iconName: "alert", value: String(profile.warnings.length), sub: profile.warnings.length ? "See the overview tab" : "Nothing to flag",
           color: COLORS.amber, tint: "rgba(255,200,87,.16)" }),
    tile({ label: "Memory", iconName: "memory", value: fmtBytes(s.memory_bytes), sub: "In-memory size while profiling", color: COLORS.green, tint: "rgba(16,227,154,.16)" }),
  );
}

function renderOverview(profile, charts) {
  const s = profile.summary;
  document.getElementById("warn-count").textContent = String(profile.warnings.length);
  const warnings = profile.warnings.map((w) => {
    const style = WARNING_STYLE[w.type] || { c: COLORS.amber, icon: "alert", label: w.type };
    const node = el("div", { class: "issue" }, icon(style.icon),
      el("div", {}, el("div", { class: "m", text: w.message }), el("div", { class: "t", text: style.label })));
    node.style.setProperty("--c", style.c);
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
  const cards = profile.columns.map((c) => {
    const card = el("article", { class: "col", "data-kind": c.kind, "data-name": c.name.toLowerCase() },
      el("div", { class: "col-h" }, el("h3", { text: c.name }), el("span", { class: `kind ${c.kind}`, text: c.kind })),
      el("div", { class: "col-stats" }, ...columnStats(c).map(([k, v]) => el("div", {}, el("div", { class: "k", text: k }), el("div", { class: "v", text: v, title: v })))),
      el("div", { class: "sum", text: columnSummary(c) }));
    const chart = byColumn.get(c.name);
    if (chart) { const box = el("div", { class: "mini" }); card.append(box); chartInto(box, chart, true); }
    return card;
  });
  grid.replaceChildren(...cards);
  document.getElementById("col-count").textContent = String(profile.columns.length);

  const counts = {};
  for (const c of profile.columns) counts[c.kind] = (counts[c.kind] || 0) + 1;
  const filters = document.getElementById("filters");
  const search = document.getElementById("col-search");
  let active = "all";
  const apply = () => {
    const q = search.value.trim().toLowerCase();
    for (const card of cards) {
      card.hidden = !((active === "all" || card.dataset.kind === active) && card.dataset.name.includes(q));
    }
  };
  const chips = [["all", profile.columns.length], ...Object.entries(counts)].map(([kind, n]) => {
    const chip = el("button", { class: kind === "all" ? "fchip active" : "fchip", type: "button" }, kind === "all" ? "All" : kind, el("span", { text: String(n) }));
    chip.addEventListener("click", () => {
      active = kind;
      for (const other of filters.querySelectorAll(".fchip")) other.classList.toggle("active", other === chip);
      apply();
    });
    return chip;
  });
  filters.replaceChildren(...chips, search);
  search.addEventListener("input", apply);
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

function initTabs() {
  const tabs = [...document.querySelectorAll(".tab")];
  const show = (name) => {
    for (const t of tabs) t.classList.toggle("active", t.dataset.tab === name);
    for (const p of document.querySelectorAll(".pane")) p.classList.toggle("active", p.id === `pane-${name}`);
    history.replaceState(null, "", name === "overview" ? location.pathname : `#${name}`);  // shareable links
  };
  for (const t of tabs) t.addEventListener("click", () => show(t.dataset.tab));
  const fromHash = location.hash.slice(1);
  if (tabs.some((t) => t.dataset.tab === fromHash)) show(fromHash);
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea") || e.metaKey || e.ctrlKey || e.altKey) return;
    const tab = tabs[Number(e.key) - 1];
    if (tab && !document.getElementById("result").hidden) show(tab.dataset.tab);
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
    ? "A worker picked this job from the Redis queue. This page updates by itself."
    : "The API is profiling the file in the background (inline mode). This page updates by itself.";
}

async function loadDataset(id, mode) {
  const dataset = await api(`/api/datasets/${id}`);
  document.title = `${dataset.filename} · DataDigest`;
  document.getElementById("title").textContent = dataset.filename;
  document.getElementById("crumb").textContent = dataset.filename;
  const chips = [fmtBytes(dataset.size_bytes), `uploaded ${fmtAgo(dataset.created_at)}`];
  if (dataset.finished_at) {
    const secs = (new Date(dataset.finished_at) - new Date(dataset.created_at)) / 1000;
    chips.push(`profiled in ${secs.toFixed(2)} s`);
  }
  document.getElementById("chips").replaceChildren(badge(dataset.status), ...chips.map((c) => el("span", { class: "chip", text: c })));

  const pending = dataset.status === "queued" || dataset.status === "processing";
  document.getElementById("pending").hidden = !pending;
  document.getElementById("failed").hidden = dataset.status !== "failed";
  if (pending) {
    renderPending(dataset, mode);
    setTimeout(() => loadDataset(id, mode), POLL_MS);
    return;
  }
  document.getElementById("actions").hidden = false;
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
  renderTiles(profile);
  renderOverview(profile, charts);
  renderColumns(profile, charts);
  renderCorrelations(profile, charts);
}

function initDataset() {
  const id = location.pathname.split("/").filter(Boolean).pop();
  initTabs();
  document.getElementById("delete").addEventListener("click", async () => {
    if (!confirm("Delete this dataset and its report?")) return;
    try {
      await api(`/api/datasets/${id}`, { method: "DELETE" });
      location.href = "/";
    } catch (err) {
      toast(`Delete failed: ${err.message}`, COLORS.red);
    }
  });
  refreshStatus()
    .then((stats) => loadDataset(id, stats && stats.mode))
    .catch((err) => {
      document.getElementById("title").textContent = "Dataset not found";
      document.getElementById("crumb").textContent = "not found";
      toast(err.message, COLORS.red);
    });
  setInterval(refreshStatus, STATUS_MS);
}

if (document.body.dataset.page === "index") initIndex();
if (document.body.dataset.page === "dataset") initDataset();
