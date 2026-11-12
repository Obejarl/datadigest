// The Statistics tab of a dataset: distributions, associations, consistency, sensitivity.

const statNum = (v, d = 3) => {
  if (v === null || v === undefined) return "–";
  if (v !== 0 && (Math.abs(v) >= 1e7 || Math.abs(v) < 1e-3)) return v.toExponential(2);
  return Number(v.toFixed(d)).toLocaleString("en-US", { maximumFractionDigits: d });
};
const pv = (p) => (p === null || p === undefined ? "–" : p < 0.001 ? "<0.001" : p.toFixed(3));
const share = (v, d = 0) => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(d)}%`);
const STRENGTH_TONE = { negligible: "dim", weak: "dim", small: "dim", moderate: "warn", medium: "warn", strong: "good", large: "good", "very strong": "good" };

function tag(text, tone = "dim", title = "") {
  return el("span", { class: `tag ${tone}`, text, title });
}

/** Adjusted p-value as a tag. Green only when the result is significant AND its effect is not small:
 *  a tiny effect that passes the test is marked amber, so it is not read as a finding. */
const SMALL_EFFECTS = new Set(["negligible", "weak", "small"]);
function sig(p, strength) {
  if (p === null || p === undefined || p >= 0.05) return tag(pv(p), "dim", "Not significant after adjusting for the number of tests");
  if (SMALL_EFFECTS.has(strength)) return tag(`${pv(p)} · small`, "warn", "Passes the test, but the effect is small: with many rows almost any difference does");
  return tag(pv(p), "good", "Significant after adjusting for the number of tests, and not small");
}

const HIGHLIGHT = { finding: ["check", COLORS.green], caution: ["alert", COLORS.amber], info: ["info", COLORS.cyan] };

/** The plain-language summary and the reading guide shown above the tables. */
function statsSummary(adv) {
  const items = (adv.highlights || []).map((h) => {
    const [iconName, color] = HIGHLIGHT[h.kind] || HIGHLIGHT.info;
    const row = el("div", { class: "insight" }, icon(iconName), el("div", { text: h.text }));
    row.style.setProperty("--c", color);
    return row;
  });
  const tests = adv.tests_run || 0;
  const byChance = Math.round(tests * 0.05);
  const guide = el("details", { class: "guide" },
    el("summary", { text: "How to read these numbers" }),
    el("ul", { class: "notes" },
      el("li", { text: "Start with the effect size (strength, V, η², δ), then look at the p-value. The p-value says how sure we are that an effect exists, not how big or how important it is." }),
      el("li", { text: tests ? `${fmtNumber(tests)} tests were run on this file. Unadjusted, about ${byChance} would look significant by chance alone; that is why the tables show adjusted p-values.` : "No tests could be run on this file." }),
      el("li", { text: "A relation between two columns does not say that one causes the other." }),
      el("li", { text: "These statistics explore the data. A decision that matters deserves a question fixed in advance and a test chosen for it." })));
  return el("section", { class: "card stats-summary" },
    el("div", { class: "card-h" }, el("h2", { class: "card-t", text: "What stands out" }), el("span", { class: "chip", text: "in plain words" })),
    el("div", { class: "insights" }, ...items), guide);
}

function statTable(head, rows) {
  const body = rows.length
    ? rows.map((r) => el("tr", {}, ...r.map((c) => (c instanceof Node ? el("td", {}, c) : el("td", { text: String(c) })))))
    : [el("tr", {}, el("td", { class: "empty", colspan: String(head.length), text: "Nothing to show for this file." }))];
  return el("div", { class: "table-wrap stat-wrap" }, el("table", { class: "preview stat" },
    el("thead", {}, el("tr", {}, ...head.map((h) => el("th", { text: h })))), el("tbody", {}, ...body)));
}

function statCard(title, hint, ...children) {
  return el("section", { class: "card" }, el("div", { class: "card-h" }, el("h2", { class: "card-t", text: title }), hint ? el("span", { class: "chip", text: hint }) : ""), ...children);
}

function statsDistributions(adv) {
  const rows = adv.distributions.map((d) => {
    const n = d.normality;
    const shapiro = n && n.shapiro ? n.shapiro.p : null;
    return [d.name, fmtNumber(d.n), statNum(d.mean), statNum(d.median), statNum(d.mode), statNum(d.variance), statNum(d.std), statNum(d.cv), statNum(d.skew, 2), statNum(d.kurtosis, 2),
      `${statNum(d.ci95_mean[0])} … ${statNum(d.ci95_mean[1])}`,
      n ? tag(n.rejected ? "not normal" : "normal", n.rejected ? "warn" : "good", `Shapiro p = ${pv(shapiro)}; rejected only when the tests agree`) : "–",
      tag(d.shape, "dim")];
  });
  const fits = adv.distributions.filter((d) => d.fits.length).map((d) => [d.name,
    ...[0, 1, 2].map((i) => (d.fits[i] ? `${d.fits[i].dist} · D ${statNum(d.fits[i].ks_stat, 3)}` : "–")),
    tag(d.best_fit, "good")]);
  const spread = adv.distributions.map((d) => [d.name, statNum(d.min), statNum(d.p1), statNum(d.p5), statNum(d.iqr), statNum(d.p95), statNum(d.p99), statNum(d.max), statNum(d.range), statNum(d.mad), statNum(d.robust_cv), statNum(d.trimmed_mean), statNum(d.sem)]);
  return [
    statCard("Location, spread and shape", "numeric columns",
      statTable(["Column", "n", "Mean", "Median", "Mode", "Variance", "Std", "CV", "Skew", "Excess kurtosis", "95% CI of mean", "Normality", "Shape"], rows)),
    statCard("Spread and robust measures", "",
      statTable(["Column", "Min", "P1", "P5", "IQR", "P95", "P99", "Max", "Range", "MAD", "Robust CV", "10% trimmed mean", "Std. error"], spread)),
    statCard("Kolmogorov–Smirnov distribution fit", "lower D = closer",
      statTable(["Column", "Closest", "Second", "Third", "Best fit"], fits),
      el("p", { class: "muted fine", text: "Candidates: normal, log-normal, exponential, uniform, gamma, Weibull; fitted by maximum likelihood on up to 5,000 values. Skipped for columns with 10 or fewer distinct values." })),
  ];
}

function statsAssociations(adv) {
  const a = adv.associations;
  const numeric = a.numeric.map((r) => [r.a, r.b, fmtNumber(r.n), statNum(r.pearson), statNum(r.spearman), statNum(r.kendall), sig(r.p_adj, r.strength),
    tag(r.strength, STRENGTH_TONE[r.strength] || "dim"), r.nonlinear_hint ? tag("non-linear?", "warn", "Spearman and Pearson disagree: curved relation or a few extreme points") : ""]);
  const categorical = a.categorical.map((r) => [r.a, r.b, statNum(r.chi2, 2), String(r.dof), sig(r.p_adj, r.strength), statNum(r.cramers_v), statNum(r.contingency_c),
    tag(r.strength, STRENGTH_TONE[r.strength] || "dim"), r.reliable ? "" : tag("few cases per cell", "warn", `${statNum(r.low_expected_pct, 0)}% of cells expect fewer than 5`)]);
  const ordinal = a.ordinal.map((r) => [r.a, r.b, fmtNumber(r.n), statNum(r.gamma), statNum(r.kendall_tau_b), statNum(r.somers_d_b_on_a), statNum(r.somers_d_a_on_b), sig(r.p_adj, r.strength), tag(r.strength, STRENGTH_TONE[r.strength] || "dim")]);
  const groups = a.by_group.map((r) => [r.numeric, r.group, String(r.groups), statNum(r.f, 2), sig(r.p_adj, r.effect), statNum(r.eta_squared), tag(r.effect, STRENGTH_TONE[r.effect] || "dim"),
    pv(r.p_kruskal), pv(r.p_levene), r.cohens_d === undefined ? "" : statNum(r.cohens_d, 2), r.cliffs_delta === undefined ? "" : statNum(r.cliffs_delta, 2)]);
  return [
    statCard("Numeric pairs", "Pearson · Spearman · Kendall",
      statTable(["A", "B", "n", "Pearson r", "Spearman ρ", "Kendall τ", "p (adj.)", "Strength", ""], numeric)),
    statCard("Categorical pairs", "χ² test of independence",
      statTable(["A", "B", "χ²", "df", "p (adj.)", "Cramér's V", "Contingency C", "Strength", ""], categorical)),
    statCard("Ordinal pairs", "gamma · Somers' d",
      statTable(["A", "B", "n", "Goodman–Kruskal γ", "Kendall τ-b", "Somers' d (B on A)", "Somers' d (A on B)", "p (adj.)", "Strength"], ordinal),
      el("p", { class: "muted fine", text: "Columns with 10 or fewer values are treated as ordered scales; continuous columns are cut into quintiles. Ties are ignored by γ." })),
    statCard("Numeric by group", "ANOVA · Kruskal–Wallis · Levene",
      statTable(["Numeric", "Group", "Groups", "F", "p (adj.)", "η²", "Effect", "Kruskal p", "Levene p", "Cohen's d", "Cliff's δ"], groups),
      el("p", { class: "muted fine", text: "Cohen's d and Cliff's δ are shown when the group column has exactly two levels. Levene's test (median-centred) compares variances." })),
  ];
}

function statsConsistency(adv) {
  const c = adv.consistency;
  const rows = c.columns.map((col) => [col.name, tag(col.kind || "?", "dim"), share(col.completeness, 1), share(col.validity, 1), share(col.uniqueness, 1),
    col.format ? `${share(col.format.share)} · ${col.format.dominant}` : "–",
    col.label_variants && col.label_variants.groups ? tag(`${col.label_variants.groups} clash`, "warn", col.label_variants.examples.join("; ")) : (col.label_variants ? "none" : "–"),
    tag(statNum(col.degree, 1), col.degree >= 90 ? "good" : col.degree >= 75 ? "warn" : "bad")]);
  const out = [statCard("Degree of consistency", `${c.grade} · ${statNum(c.score, 1)} / 100`,
    statTable(["Column", "Kind", "Completeness", "Validity", "Uniqueness", "Format (dominant pattern)", "Label variants", "Degree"], rows),
    el("p", { class: "muted fine", text: "Completeness: non-empty share. Validity: share of values readable as the column's type. Format: share of values with the most common character pattern (9 = digit, a = letter). Label variants: spellings that differ only in case or spaces." }))];
  if (c.key_conflicts) {
    const k = c.key_conflicts;
    out.push(statCard("Duplicate keys", k.key, el("p", { text: k.repeated_keys
      ? `${k.repeated_keys} value(s) of ${k.key} appear more than once; ${k.conflicting_keys} of them have rows that disagree on other columns.`
      : `Every value of ${k.key} is unique.` })));
  }
  if (c.cronbach) {
    const a = c.cronbach;
    out.push(statCard("Internal consistency (Cronbach's α)", a.label,
      el("p", { text: `α = ${statNum(a.alpha)} (standardized ${statNum(a.alpha_standardized)}), mean inter-item r = ${statNum(a.mean_inter_item_r)}, ${a.items} columns, ${fmtNumber(a.n)} complete rows.` }),
      statTable(["Column", "Item-total r", "α if deleted"], a.item_stats.map((i) => [i.name, statNum(i.item_total_r), statNum(i.alpha_if_deleted)])),
      el("p", { class: "muted fine", text: a.note })));
  }
  return out;
}

function statsSensitivity(adv) {
  const s = adv.sensitivity;
  const tone = { robust: "good", moderate: "warn", sensitive: "bad" };
  const rows = s.columns.map((r) => [r.name, fmtNumber(r.outliers_removed), statNum(r.mean), statNum(r.mean_without_outliers), `${statNum(r.mean_shift_pct, 1)}%`, `${statNum(r.median_shift_pct, 1)}%`, `${statNum(r.std_shift_pct, 1)}%`,
    statNum(r.winsorized_mean), `${statNum(r.bootstrap_mean_ci[0])} … ${statNum(r.bootstrap_mean_ci[1])}`, `${statNum(r.bootstrap_median_ci[0])} … ${statNum(r.bootstrap_median_ci[1])}`, tag(r.robustness, tone[r.robustness] || "dim")]);
  const corr = s.correlations.map((r) => [r.a, r.b, statNum(r.pearson), statNum(r.pearson_without_outliers), statNum(r.delta), fmtNumber(r.rows_dropped), r.fragile ? tag("fragile", "bad", "The correlation changes a lot, or flips sign, without the extreme rows") : tag("stable", "good")]);
  return [
    statCard("How much do outliers move the statistics?", "IQR rule",
      statTable(["Column", "Outliers", "Mean", "Mean without", "Δ mean", "Δ median", "Δ std", "Winsorized mean (5%)", "Bootstrap 95% CI, mean", "Bootstrap 95% CI, median", "Verdict"], rows),
      el("p", { class: "muted fine", text: "Sensitive: dropping the outliers changes the mean or the standard deviation by 10% or more. Bootstrap intervals use 300 resamples of up to 5,000 values." })),
    statCard("Which correlations depend on the outliers?", "Pearson",
      statTable(["A", "B", "r", "r without outliers", "Δ r", "Rows dropped", ""], corr)),
  ];
}

function renderStats(profile) {
  const adv = profile.advanced;
  const nav = document.getElementById("stats-nav");
  const body = document.getElementById("stats-body");
  if (!adv) {
    nav.hidden = true;
    body.replaceChildren(el("p", { class: "muted", text: "This dataset was analysed before statistics existed. Use Re-run to add them." }));
    return;
  }
  const sections = [["Distributions", statsDistributions], ["Associations", statsAssociations], ["Consistency", statsConsistency], ["Sensitivity", statsSensitivity]];
  const panels = sections.map(([, build]) => el("div", { class: "stats-section", hidden: true }, ...build(adv)));
  const buttons = sections.map(([label], i) => {
    const b = el("button", { class: "seg-b", type: "button", text: label });
    b.addEventListener("click", () => select(i));
    return b;
  });
  const select = (i) => {
    buttons.forEach((b, j) => b.classList.toggle("active", i === j));
    panels.forEach((p, j) => { p.hidden = i !== j; });
  };
  const sample = adv.sample;
  const notes = el("ul", { class: "notes" }, ...adv.notes.map((n) => el("li", { text: n })));
  nav.replaceChildren(...buttons, el("span", { class: "chip", text: sample.sampled ? `sample of ${fmtNumber(sample.rows)} / ${fmtNumber(sample.of)} rows` : `${fmtNumber(sample.rows)} rows` }));
  body.replaceChildren(statsSummary(adv), ...panels, notes);
  select(0);
}
