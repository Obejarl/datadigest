// The dataset list: totals, upload, samples and server-side files.

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

/** Files too big to upload sit in the server's LARGE_DATA_DIR; offer them when that is configured. */
async function loadServerFiles() {
  const box = document.getElementById("server-files");
  let info;
  try { info = await api("/api/server-files"); } catch { return; }
  if (!info.enabled || !info.files.length) return;
  const label = info.spark ? "Large files on the server (profiled with Spark):" : "Files on the server:";
  box.replaceChildren(el("span", { text: label }), ...info.files.map((f) => {
    const btn = el("button", { class: "sample", type: "button" }, f.name, el("small", { text: fmtBytes(f.size_bytes) }));
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try { location.href = `/datasets/${(await api(`/api/server-files/${encodeURIComponent(f.name)}`, { method: "POST" })).id}`; }
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
  loadServerFiles();
  refreshIndex().catch((err) => toast(err.message, COLORS.red));
  setInterval(() => refreshStatus().then(renderKpis), STATUS_MS);
}

if (document.body.dataset.page === "index") initIndex();
