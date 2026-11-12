// One dataset: quality tiles, warnings, column cards, correlations, preview and tabs.
// The Statistics tab is drawn by stats.js (renderStats).

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
    ["Rows × columns", `${fmtNumber(s.rows)} × ${s.columns}`], [s.engine === "spark" ? "Size on disk" : "Memory", fmtBytes(s.memory_bytes)],
    ["Engine", s.engine || "pandas"],
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
  const chips = [fmtBytes(dataset.size_bytes), `${dataset.source_path ? "registered" : "uploaded"} ${fmtAgo(dataset.created_at)}`];
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
    el("span", { class: "chip", text: `sep ${s.delimiter === "\t" ? "TAB" : s.delimiter}` }),
    el("span", { class: s.engine === "spark" ? "chip eng-spark" : "chip", text: s.engine === "spark" ? "⚡ engine spark" : `engine ${s.engine || "pandas"}` }));

  document.getElementById("result").hidden = false;  // before charts: they measure their containers
  renderTiles(profile, dataset);
  renderOverview(profile, charts);
  renderColumns(profile, charts);
  renderCorrelations(profile, charts);
  renderPreview(profile);
  renderStats(profile);
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

if (document.body.dataset.page === "dataset") initDataset();
