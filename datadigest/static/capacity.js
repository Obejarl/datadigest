// /capacity: size the worker pool. core.js and planner.js are loaded first.

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
