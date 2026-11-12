// /capacity: size the worker pool. Shared helpers (el, api, icon, toast, tile, chartInto,
// refreshStatus) come from core.js, which is loaded first.

Object.assign(ICONS, {
  sigma: '<path d="M18 4H6l6 8-6 8h12"/>',
  trend: '<path d="m3 17 6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
  bulb: '<path d="M9 18h6M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z"/>',
});

const TONE = { cyan: COLORS.cyan, green: COLORS.green, amber: COLORS.amber, violet: COLORS.violet, red: COLORS.red };
const KPI_ICONS = ["sigma", "trend", "target", "layers"];

function fmtCell(v) {
  if (v === null || v === undefined) return "–";
  if (typeof v === "number") {
    return Number.isInteger(v) ? v.toLocaleString("en-US") : v.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
  return String(v);
}

/** Draw a planner result: KPI tiles, insights, charts and tables. */
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

function field(label, control, hint, wide = false) {
  return el("label", { class: wide ? "field wide" : "field" }, label, control, hint ? el("span", { class: "hint", text: hint }) : null);
}

const CAP_FIELDS = [
  ["arrival_per_min", "Arrivals per minute", "Uploads entering the queue", { min: "0.01", step: "0.1" }],
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


if (document.body.dataset.page === "capacity") initCapacity();
