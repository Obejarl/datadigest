// DataDigest dashboard, shared part. No framework: fetch the JSON API and build the DOM.
// Everything that comes from an uploaded file is written with textContent, never innerHTML.
// Scripts are plain (not modules) and share one scope: core.js is loaded first, then the
// script of the page (index.js, dataset.js + stats.js, capacity.js, login.js).

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
  setTimeout(() => { box.classList.add("out"); setTimeout(() => box.remove(), 300); }, 4500);
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
    if (stats.queue_dead) items.push(pill("bad", `Dead letters ${stats.queue_dead}`, true, "Jobs that failed every retry; their datasets are marked failed"));
  }
  pills.replaceChildren(...items);
  try {
    const auth = await api("/api/auth/status");
    if (auth.required && auth.authenticated) {
      if (auth.user) {
        pills.append(el("a", { class: "pill opt who", href: "/account", title: `Signed in as ${auth.user.email} (${auth.user.role}). Open your account.` }, auth.user.email));
      }
      const out = el("button", { class: "pill opt signout", type: "button", title: "Sign out of DataDigest" }, "Sign out");
      out.addEventListener("click", async () => { await api("/api/logout", { method: "POST" }); location.href = "/login"; });
      pills.append(out);
    }
  } catch {}
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
