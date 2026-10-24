// Operations-research pages: /optimize (choose a problem, configure, run), /optimizations/{id}
// (result) and /capacity (worker sizing). Shared helpers (el, api, icon, toast, tile, meter,
// chartInto, confirmDialog, refreshStatus, fmt*) come from app.js, which is loaded first.

Object.assign(ICONS, {
  factory: '<path d="M3 21V9l6 4V9l6 4V5l6 4v12z"/><path d="M7 17h2M12 17h2M17 17h2"/>',
  truck: '<path d="M3 6h11v10H3zM14 9h4l3 3v4h-7"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2 20c0-3.3 3.1-6 7-6s7 2.7 7 6"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14c2.4.7 4 2.9 4 6"/>',
  briefcase: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 13h18"/>',
  sigma: '<path d="M18 4H6l6 8-6 8h12"/>',
  trend: '<path d="m3 17 6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
  bulb: '<path d="M9 18h6M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z"/>',
});

const KIND_STYLE = {
  production: { icon: "factory", c: COLORS.cyan },
  transport: { icon: "truck", c: COLORS.violet },
  assignment: { icon: "users", c: COLORS.green },
  knapsack: { icon: "briefcase", c: COLORS.amber },
};
const TONE = { cyan: COLORS.cyan, green: COLORS.green, amber: COLORS.amber, violet: COLORS.violet, red: COLORS.red };
const KPI_ICONS = ["sigma", "trend", "target", "layers"];

function fmtCell(v) {
  if (v === null || v === undefined) return "–";
  if (typeof v === "number") {
    return Number.isInteger(v) ? v.toLocaleString("en-US") : v.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
  return String(v);
}

async function loadKinds() {
  const kinds = await api("/api/optimize/kinds");
  return new Map(kinds.map((k) => [k.key, k]));
}

// ------------------------------------------------------------ generic result

/** Draw any solver envelope: KPI tiles, insights, charts and tables. Used for all four
 *  problem types and the capacity planner, so a new solver needs no new UI code. */
function renderEnvelope(container, r) {
  const tiles = el("div", { class: "bento" }, ...r.kpis.map((k, i) => tile({
    label: k.label, iconName: KPI_ICONS[i % KPI_ICONS.length], value: String(k.value ?? "–"), unit: k.unit, sub: k.sub,
    color: TONE[k.tone] || COLORS.cyan, tint: (TONE[k.tone] || COLORS.cyan) + "33",
  })));

  const insights = el("div", { class: "insights" }, ...r.insights.map((text, i) => {
    const color = r.status !== "optimal" ? COLORS.red : i === 0 ? COLORS.green : COLORS.cyan;
    const row = el("div", { class: "insight" }, icon(r.status !== "optimal" ? "alert" : i === 0 ? "check" : "bulb"), el("div", { text }));
    row.style.setProperty("--c", color);
    return row;
  }));
  const insightCard = el("section", { class: "card" },
    el("div", { class: "card-h" }, el("h2", { class: "card-t", text: "What the optimum tells you" })), insights);

  const charts = el("div", { class: "charts" });
  for (const c of r.charts) {
    const box = el("div");
    charts.append(el("div", { class: c.wide ? "chart wide" : "chart" }, el("div", { class: "ct", text: c.title }), box));
    chartInto(box, c);
  }

  const tables = r.tables.map((t) => {
    const numericCol = t.columns.map((_, j) => t.rows.length > 0 && t.rows.every((row) => row[j] === null || typeof row[j] === "number"));
    return el("section", { class: "card" },
      el("div", { class: "card-h" }, el("h2", { class: "card-t", text: t.title }), el("span", { class: "chip", text: `${t.rows.length} rows` })),
      el("div", { class: "table-wrap" }, el("table", {},
        el("thead", {}, el("tr", {}, ...t.columns.map((c, j) => el("th", { class: numericCol[j] ? "n" : null, text: c })))),
        el("tbody", {}, ...t.rows.map((row) => el("tr", {}, ...row.map((v, j) => el("td", { class: numericCol[j] ? "n" : null, text: fmtCell(v) }))))))));
  });

  container.replaceChildren(tiles, insightCard, ...(r.charts.length ? [charts] : []), ...tables);
}

function resultStatus(status) {
  const labels = { optimal: "optimal", infeasible: "infeasible", unbounded: "unbounded", time_limit: "time limit" };
  return el("span", { class: `result-status ${status}`, text: labels[status] || status || "–" });
}

// ------------------------------------------------------------ form fields

function field(label, control, hint, wide = false) {
  return el("label", { class: wide ? "field wide" : "field" }, label, control, hint ? el("span", { class: "hint", text: hint }) : null);
}

function selectField(label, names, value, hint, { optional = false } = {}) {
  const select = el("select", { class: "search" });
  if (optional) select.append(el("option", { value: "", text: "— none —" }));
  for (const n of names) select.append(el("option", { value: n, text: n }));
  select.value = value ?? (optional ? "" : names[0] ?? "");
  return { node: field(label, select, hint), get: () => select.value || null, set: (v) => { select.value = v ?? ""; }, el: select };
}

function numberField(label, value, hint, attrs = {}) {
  const input = el("input", { type: "number", value: value ?? "", ...attrs });
  return { node: field(label, input, hint), get: () => (input.value === "" ? null : Number(input.value)), set: (v) => { input.value = v ?? ""; } };
}

function textField(label, value, hint) {
  const input = el("input", { type: "text", value });
  return { node: field(label, input, hint), get: () => input.value.trim(), set: (v) => { input.value = v ?? ""; } };
}

function checkField(label, checked, hint) {
  const box = el("input", { type: "checkbox" });
  box.checked = checked;
  return { node: field("", el("span", { class: "check" }, box, label), hint), get: () => box.checked, set: (v) => { box.checked = !!v; } };
}

/** Pick numeric columns as constrained resources/budgets, each with a capacity. */
function capacityField(label, columns, estimate, isDefault, hint) {
  const list = el("div", { class: "res-list" });
  const items = columns.map((c) => {
    const box = el("input", { type: "checkbox" });
    box.checked = isDefault(c.name);
    const cap = el("input", { type: "number", value: estimate(c.name), min: "0", "aria-label": `Capacity of ${c.name}` });
    cap.disabled = !box.checked;
    box.addEventListener("change", () => { cap.disabled = !box.checked; });
    list.append(el("div", { class: "res-row" }, el("span", { class: "check" }, box, c.name), cap));
    return { name: c.name, box, cap };
  });
  return {
    node: field(label, list, hint, true),
    get: () => items.filter((i) => i.box.checked).map((i) => ({ column: i.name, capacity: Number(i.cap.value) })),
    set: (chosen) => {
      const byName = new Map((chosen || []).map((r) => [r.column, r.capacity]));
      for (const i of items) {
        i.box.checked = byName.has(i.name);
        i.cap.disabled = !i.box.checked;
        if (byName.has(i.name)) i.cap.value = byName.get(i.name);
      }
    },
  };
}

/** Column values from the profile preview (the whole file for small datasets), scaled to all rows. */
function columnValues(profile) {
  const { columns, rows } = profile.preview || { columns: [], rows: [] };
  const scale = rows.length ? profile.summary.rows / rows.length : 1;
  const values = (name) => {
    const j = columns.indexOf(name);
    return j < 0 ? [] : rows.map((r) => (r[j] === null ? NaN : Number(String(r[j]).replace(",", "."))));
  };
  const sum = (xs) => xs.reduce((a, x) => a + (Number.isFinite(x) ? x : 0), 0);
  return { values, sum, scale };
}

const nice = (x) => (x >= 100 ? Math.round(x) : Math.round(x * 10) / 10);

/** Choose which numeric columns take part (tasks, destinations). */
function columnsField(label, columns, isDefault, hint) {
  const list = el("div", { class: "res-list cols-list" });
  const items = columns.map((c) => {
    const box = el("input", { type: "checkbox" });
    box.checked = isDefault(c.name);
    list.append(el("label", { class: "check" }, box, c.name));
    return { name: c.name, box };
  });
  return {
    node: field(label, list, hint, true),
    get: () => { const chosen = items.filter((i) => i.box.checked).map((i) => i.name); return chosen.length ? chosen : null; },
    set: (names) => { if (names) for (const i of items) i.box.checked = names.includes(i.name); },
  };
}

const ID_LIKE = /(^|_)id$|^index$|^#$|^no$/i;

const pick = (cols, pattern, fallback) => (cols.find((c) => pattern.test(c.name)) || fallback || cols[0] || {}).name;

/** Build the form for one problem type from a dataset profile. Returns {nodes, collect}. */
function buildForm(kind, profile) {
  const all = profile.columns;
  const num = all.filter((c) => c.kind === "numeric");
  const text = all.filter((c) => c.kind !== "numeric");
  const names = (cols) => cols.map((c) => c.name);
  const nameGuess = (text[0] || all[0] || {}).name;

  if (kind === "production") {
    const objective = selectField("Objective (profit or output per unit)", names(num), pick(num, /profit|margin|output|value|revenue|return/i), "Maximised");
    const minCol = selectField("Minimum quantity (optional)", names(num), pick(num, /^min|minimum/i, {}) || null, "Contracts you must fulfil", { optional: true });
    const maxCol = selectField("Maximum quantity (optional)", names(num), pick(num, /^max|maximum|demand/i, {}) || null, "Market demand per product", { optional: true });
    const skip = /profit|margin|output|value|revenue|return|^min|^max|minimum|maximum|demand|_id$|^id$/i;
    // Enough capacity for the minimum quantities (+10%), and about 60% of what full demand would use,
    // so the plan is feasible but the resources still bind. Without a max, assume ten units of each.
    const { values, sum, scale } = columnValues(profile);
    const lo = minCol.get() ? values(minCol.get()) : [];
    const hi = maxCol.get() ? values(maxCol.get()) : [];
    const estimate = (name) => {
      const use = values(name);
      const need = sum(use.map((u, i) => u * (lo[i] || 0)));
      const full = sum(use.map((u, i) => u * (Number.isFinite(hi[i]) ? hi[i] : 10)));
      return nice(Math.max(1.1 * need, 0.6 * full) * scale) || 100;
    };
    const fields = {
      name_column: selectField("Product names", names(all), nameGuess),
      objective_column: objective,
      resources: capacityField("Resources used per unit, and how much of each you have", num, estimate, (n) => !skip.test(n),
        "Tick a column to make it a constraint; set the available capacity."),
      min_column: minCol,
      max_column: maxCol,
      integer: checkField("Whole units only (integer programming)", true, "Turn off for divisible goods; also gives exact shadow prices"),
    };
    return form(fields);
  }
  if (kind === "transport") {
    const supply = pick(num, /supply|capacity|stock|available/i);
    return form({
      source_column: selectField("Source names (factories, warehouses)", names(text.length ? text : all), nameGuess),
      supply_column: selectField("Supply column", names(num), supply, "Units each source can ship"),
      demand_label: textField("Label of the demand row", "demand",
        "One row with this label holds each destination's demand."),
      destination_columns: columnsField("Destinations (unit cost columns)", num, (n) => n !== supply && !ID_LIKE.test(n),
        "Each ticked column is a destination; cells are the cost per unit, empty = no route."),
    });
  }
  if (kind === "assignment") {
    const sense = selectField("Goal", ["max", "min"], "max", "max for scores or profit, min for cost or time");
    sense.el.options[0].textContent = "Maximise the total (scores, profit)";
    sense.el.options[1].textContent = "Minimise the total (cost, time)";
    return form({
      agent_column: selectField("Agent names (people, machines)", names(text.length ? text : all), nameGuess),
      sense,
      task_columns: columnsField("Tasks (score or cost columns)", num, (n) => !ID_LIKE.test(n),
        "Each ticked column is a task; empty cells mean the pairing is not allowed."),
    });
  }
  const value = selectField("Value of choosing an item", names(num), pick(num, /return|value|profit|benefit|npv|score/i), "Maximised");
  // A budget that covers about 40% of all candidates forces a real choice.
  const { values, sum, scale } = columnValues(profile);
  return form({
    name_column: selectField("Item names", names(all), nameGuess),
    value_column: value,
    budgets: capacityField("Costs and the budget for each", num, (n) => nice(0.4 * sum(values(n)) * scale) || 100,
      (n) => /cost|capex|budget|engineer|staff|hour|people|time/i.test(n),
      "Tick a cost column and set its budget."),
    max_items: numberField("Max number of items (optional)", null, "Leave empty for no limit", { min: "1", step: "1" }),
  });
}

function form(fields) {
  return {
    nodes: Object.values(fields).map((f) => f.node),
    collect: () => Object.fromEntries(Object.entries(fields).map(([k, f]) => [k, f.get()]).filter(([, v]) => v !== null && v !== "")),
    apply: (params) => { for (const [k, v] of Object.entries(params)) if (fields[k] && fields[k].set) fields[k].set(v); },
  };
}

// ------------------------------------------------------------ /optimize

let currentForm = null;
let currentKind = null;
let currentKinds = null;
let pendingPrefill = null;  // params of an earlier run, applied once its form is built

async function openConfig(kind, kinds, datasets, datasetId) {
  currentKind = kind;
  currentKinds = kinds;
  const spec = kinds.get(kind);
  for (const card of document.querySelectorAll(".kind-card")) card.classList.toggle("selected", card.dataset.kind === kind);
  const config = document.getElementById("config");
  document.getElementById("config-title").textContent = `${spec.title} on your data`;
  document.getElementById("config-help").textContent = `${spec.summary} Method: ${spec.method}.`;
  document.getElementById("config-error").hidden = true;
  const select = document.getElementById("config-dataset");
  select.replaceChildren(...datasets.map((d) => el("option", { value: d.id, text: `${d.filename} · ${fmtNumber(d.rows)} rows` })));
  if (!datasets.length) {
    select.append(el("option", { value: "", text: "No profiled datasets yet: upload a CSV or run an example" }));
  }
  if (datasetId && datasets.some((d) => d.id === datasetId)) select.value = datasetId;
  config.hidden = false;
  config.scrollIntoView({ behavior: "smooth", block: "start" });
  await rebuildForm();
}

async function rebuildForm() {
  const box = document.getElementById("config-fields");
  const id = document.getElementById("config-dataset").value;
  currentForm = null;
  if (!id) { box.replaceChildren(); return; }
  box.replaceChildren(el("div", { class: "skel", style: { height: "70px" } }));
  try {
    const profile = await api(`/api/datasets/${id}/profile`);
    currentForm = buildForm(currentKind, profile);
    const spec = currentKinds && currentKinds.get(currentKind);
    const filename = document.getElementById("config-dataset").selectedOptions[0]?.textContent.split(" · ")[0];
    if (spec && filename === spec.sample) currentForm.apply(spec.example);  // known-good inputs for the demo file
    if (pendingPrefill) { currentForm.apply(pendingPrefill); pendingPrefill = null; }
    box.replaceChildren(...currentForm.nodes);
  } catch (err) {
    box.replaceChildren(el("p", { class: "muted", text: `Could not read the columns: ${err.message}` }));
  }
}

async function solve() {
  const error = document.getElementById("config-error");
  error.hidden = true;
  const datasetId = document.getElementById("config-dataset").value;
  if (!currentForm || !datasetId) return;
  const button = document.getElementById("config-solve");
  button.disabled = true;
  try {
    const opt = await api("/api/optimizations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dataset_id: datasetId, kind: currentKind, params: currentForm.collect() }),
    });
    location.href = `/optimizations/${opt.id}`;
  } catch (err) {
    error.textContent = err.message;
    error.hidden = false;
    button.disabled = false;
  }
}

async function runExample(kind, button) {
  button.disabled = true;
  try {
    const opt = await api(`/api/optimize/examples/${kind}`, { method: "POST" });
    location.href = `/optimizations/${opt.id}`;
  } catch (err) {
    button.disabled = false;
    toast(err.message, COLORS.red);
  }
}

let runsPoll = null;
async function refreshRuns(kinds) {
  clearTimeout(runsPoll);
  const runs = await api("/api/optimizations");
  const body = document.getElementById("runs");
  if (!runs.length) {
    body.replaceChildren(el("tr", {}, el("td", { class: "empty", colspan: "7", text: "No runs yet. Try an example above: one click, about a second." })));
    return;
  }
  body.replaceChildren(...runs.map((o) => {
    const del = el("button", { class: "icon-btn danger", type: "button", title: "Delete", "aria-label": `Delete ${o.name}` }, icon("trash"));
    del.addEventListener("click", async () => {
      if (!(await confirmDialog({ title: "Delete this run?", body: `“${o.name}” will be removed.`, confirmText: "Delete", danger: true }))) return;
      try { await api(`/api/optimizations/${o.id}`, { method: "DELETE" }); refreshRuns(kinds); } catch (err) { toast(err.message, COLORS.red); }
    });
    const seconds = o.started_at && o.finished_at ? ((new Date(o.finished_at) - new Date(o.started_at)) / 1000).toFixed(2) + " s" : "–";
    const style = KIND_STYLE[o.kind] || { icon: "sigma", c: COLORS.cyan };
    const kindIcon = icon(style.icon);
    kindIcon.style.cssText = `width:16px;height:16px;vertical-align:-3px;margin-right:8px;color:${style.c}`;
    return el("tr", {},
      el("td", { class: "name" }, kindIcon, el("a", { href: `/optimizations/${o.id}`, text: o.name })),
      el("td", { title: o.error || "" }, badge(o.status)),
      el("td", {}, o.status === "done" ? el("span", {}, resultStatus(o.result_status), el("span", { class: "num", text: ` ${fmtCell(o.objective)}` })) : "–"),
      el("td", {}, el("span", { class: "num", text: o.uplift_pct === null ? "–" : `+${o.uplift_pct.toFixed(1)}%` })),
      el("td", {}, el("span", { class: "num", text: seconds })),
      el("td", { class: "muted", text: fmtAgo(o.created_at) }),
      el("td", {}, el("div", { class: "row-actions" }, del)));
  }));
  if (runs.some((o) => o.status === "queued" || o.status === "processing")) runsPoll = setTimeout(() => refreshRuns(kinds), POLL_MS);
}

async function initOptimize() {
  refreshStatus();
  setInterval(refreshStatus, STATUS_MS);
  const params = new URLSearchParams(location.search);
  const [kinds, datasets] = await Promise.all([loadKinds(), api("/api/datasets?limit=200")]);
  const ready = datasets.filter((d) => d.status === "done");

  document.getElementById("kinds").replaceChildren(...[...kinds.values()].map((k) => {
    const style = KIND_STYLE[k.key];
    const example = el("button", { class: "btn primary", type: "button", text: "Run example" });
    const own = el("button", { class: "btn", type: "button", text: "Use my data" });
    example.addEventListener("click", () => runExample(k.key, example));
    own.addEventListener("click", () => openConfig(k.key, kinds, ready, document.getElementById("config-dataset").value || params.get("dataset")));
    const ico = el("div", { class: "ico" }, icon(style.icon));
    ico.style.setProperty("--tc", style.c);
    const card = el("article", { class: "kind-card", "data-kind": k.key }, ico, el("h3", { text: k.title }), el("p", { text: k.summary }),
      el("div", { class: "method", text: k.method }), el("div", { class: "actions" }, example, own));
    card.style.setProperty("--tint", style.c + "33");
    return card;
  }));

  document.getElementById("config-dataset").addEventListener("change", rebuildForm);
  document.getElementById("config-solve").addEventListener("click", solve);
  document.getElementById("config-close").addEventListener("click", () => {
    document.getElementById("config").hidden = true;
    for (const card of document.querySelectorAll(".kind-card")) card.classList.remove("selected");
  });

  const wantKind = params.get("kind");
  if (params.get("from")) {
    // "Change inputs" on a result page: reopen the form with that run's dataset and parameters.
    try {
      const run = await api(`/api/optimizations/${params.get("from")}`);
      pendingPrefill = run.params;
      const list = ready.some((d) => d.id === run.dataset_id) ? ready : [...ready, ...datasets.filter((d) => d.id === run.dataset_id)];
      await openConfig(run.kind, kinds, list, run.dataset_id);
      toast("Inputs of the earlier run loaded: change them and solve again");
    } catch (err) { toast(err.message, COLORS.red); }
  } else if (wantKind && kinds.has(wantKind)) openConfig(wantKind, kinds, ready, params.get("dataset"));
  else if (params.get("dataset")) {
    const d = ready.find((x) => x.id === params.get("dataset"));
    if (d) toast(`Pick a problem type to run on ${d.filename}`);
  }
  refreshRuns(kinds).catch((err) => toast(err.message, COLORS.red));
}

// ------------------------------------------------------------ /optimizations/{id}

async function loadOptimization(id, kinds) {
  const o = await api(`/api/optimizations/${id}`);
  const kind = kinds.get(o.kind);
  document.title = `${o.name} · DataDigest`;
  document.getElementById("title").textContent = o.name;
  document.getElementById("crumb").textContent = o.name;
  const chips = [badge(o.status), el("span", { class: "chip", text: kind ? kind.title : o.kind })];
  const r = o.result;
  if (r) {
    chips.push(el("span", { class: "chip" }, resultStatus(r.status)), el("span", { class: "chip", text: r.solver.name }));
    if (r.solver.seconds !== null && r.solver.seconds !== undefined) chips.push(el("span", { class: "chip", text: `${r.solver.seconds.toFixed(3)} s` }));
    if (r.solver.variables) chips.push(el("span", { class: "chip", text: `${fmtNumber(r.solver.variables)} vars · ${fmtNumber(r.solver.constraints)} constraints` }));
  }
  document.getElementById("chips").replaceChildren(...chips);

  const again = `/optimize?from=${o.id}`;
  document.getElementById("change-inputs").href = again;
  document.getElementById("fix-inputs").href = again;
  document.getElementById("dataset-link").href = `/datasets/${o.dataset_id}`;

  const pending = o.status === "queued" || o.status === "processing";
  document.getElementById("pending").hidden = !pending;
  document.getElementById("failed").hidden = o.status !== "failed";
  document.getElementById("actions").hidden = pending;
  document.getElementById("report-actions").hidden = o.status !== "done";
  if (pending) {
    const steps = ["Queued", "Solving", "Done"];
    const current = o.status === "queued" ? 0 : 1;
    const parts = [];
    steps.forEach((label, i) => {
      if (i) parts.push(el("div", { class: i <= current ? "step-line done" : "step-line" }));
      const state = i < current ? "done" : i === current ? "now" : "";
      parts.push(el("div", { class: `step ${state}` }, el("span", { class: "dot", text: i < current ? "✓" : String(i + 1) }), label));
    });
    document.getElementById("stepper").replaceChildren(...parts);
    document.getElementById("pending-note").textContent = kind ? `Method: ${kind.method}. This page updates by itself.` : "";
    setTimeout(() => loadOptimization(id, kinds), POLL_MS);
    return;
  }
  if (o.status === "failed") {
    document.getElementById("error").textContent = o.error || "The solver failed";
    return;
  }
  const base = `/api/optimizations/${id}`;
  document.getElementById("report-download").href = `${base}/report?download=true`;
  document.getElementById("report-open").href = `${base}/report`;
  document.getElementById("result-json").href = base;
  const result = document.getElementById("result");
  result.hidden = false;  // before charts: they measure their containers
  renderEnvelope(result, r);
}

async function initOptimization() {
  refreshStatus();
  setInterval(refreshStatus, STATUS_MS);
  const id = location.pathname.split("/").filter(Boolean).pop();
  document.getElementById("delete").addEventListener("click", async () => {
    const name = document.getElementById("title").textContent;
    if (!(await confirmDialog({ title: "Delete this run?", body: `“${name}” will be removed.`, confirmText: "Delete", danger: true }))) return;
    try { await api(`/api/optimizations/${id}`, { method: "DELETE" }); location.href = "/optimize"; }
    catch (err) { toast(err.message, COLORS.red); }
  });
  try {
    await loadOptimization(id, await loadKinds());
  } catch (err) {
    document.getElementById("title").textContent = "Run not found";
    document.getElementById("crumb").textContent = "not found";
    toast(err.message, COLORS.red);
  }
}

// ------------------------------------------------------------ /capacity

const CAP_FIELDS = [
  ["arrival_per_min", "Arrivals per minute", "Uploads + solver runs entering the queue", { min: "0.01", step: "0.1" }],
  ["service_seconds", "Service time (s)", "Average time one worker needs per job", { min: "0.01", step: "0.1" }],
  ["target_wait_seconds", "Target mean wait (s)", "How long a job may wait in the queue", { min: "0.1", step: "0.5" }],
  ["worker_cost_per_hour", "Cost per worker per hour", "Cloud cost of one worker pod", { min: "0", step: "0.01" }],
  ["wait_cost_per_hour", "Cost of waiting per hour", "What an hour of user waiting is worth to you", { min: "0", step: "1" }],
  ["peak_factor", "Peak factor", "Peak load ÷ normal load (sets HPA max)", { min: "1", step: "0.5" }],
];

function hpaYaml(hpa) {
  return [
    "apiVersion: autoscaling/v2",
    "kind: HorizontalPodAutoscaler",
    "metadata:",
    "  name: worker",
    "spec:",
    "  scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: worker }",
    `  minReplicas: ${hpa.minReplicas}   # keeps the target wait at normal load`,
    `  maxReplicas: ${hpa.maxReplicas}   # enough for the peak`,
    "  metrics:",
    "    - type: Resource",
    "      resource: { name: cpu, target: { type: Utilization, averageUtilization: 70 } }",
  ].join("\n");
}

async function initCapacity() {
  refreshStatus();
  setInterval(refreshStatus, STATUS_MS);
  const formBox = document.getElementById("cap-form");
  const inputs = Object.fromEntries(CAP_FIELDS.map(([key, label, hint, attrs]) => {
    const input = el("input", { type: "number", ...attrs });
    formBox.append(field(label, input, hint));
    return [key, input];
  }));
  const out = document.getElementById("cap-result");
  let timer = null;

  const render = (r) => {
    for (const [key, input] of Object.entries(inputs)) if (document.activeElement !== input) input.value = +Number(r.inputs[key]).toFixed(3);
    const m = r.measured;
    document.getElementById("measured-chip").textContent = m.service_samples
      ? `measured: ${m.arrival_per_min ? m.arrival_per_min.toFixed(2) : "–"}/min · ${m.service_seconds.toFixed(3)} s from ${m.service_samples} jobs`
      : "no job history yet: using defaults";
    renderEnvelope(out, r);
    document.getElementById("hpa").textContent = hpaYaml(r.hpa);
    document.getElementById("hpa-card").hidden = false;
  };
  const compute = async (useMeasured = false) => {
    const query = new URLSearchParams();
    for (const [key, input] of Object.entries(inputs)) {
      if (useMeasured && (key === "arrival_per_min" || key === "service_seconds")) continue;
      if (input.value !== "" && Number(input.value) > 0) query.set(key, input.value);
    }
    try { render(await api(`/api/capacity?${query}`)); } catch (err) { toast(err.message, COLORS.red); }
    if (!useMeasured) history.replaceState(null, "", `?${query}`);  // the scenario is shareable as a link
  };
  for (const input of Object.values(inputs)) {
    input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => compute(), 400); });
  }
  document.getElementById("cap-measured").addEventListener("click", () => {
    history.replaceState(null, "", location.pathname);
    compute(true);
  });
  document.getElementById("hpa-copy").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(document.getElementById("hpa").textContent); toast("Copied", COLORS.green); }
    catch { toast("Could not copy; select the text instead", COLORS.amber); }
  });
  const shared = new URLSearchParams(location.search);
  for (const [key, input] of Object.entries(inputs)) if (shared.has(key)) input.value = shared.get(key);
  compute(![...shared.keys()].some((k) => k in inputs));
}

if (document.body.dataset.page === "optimize") initOptimize().catch((err) => toast(err.message, COLORS.red));
if (document.body.dataset.page === "optimization") initOptimization();
if (document.body.dataset.page === "capacity") initCapacity();
