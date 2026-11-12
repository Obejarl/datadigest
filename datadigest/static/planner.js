// Shared by the Optimize pages and the capacity planner: draws any result that has the
// planner shape (KPI tiles, insights, charts, tables; see datadigest/envelope.py), so a new
// solver needs no new UI code. Helpers (el, icon, tile, chartInto) come from core.js.

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
