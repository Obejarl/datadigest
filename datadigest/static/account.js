// /account: your API token and password and, for administrators, the users.
// Shared helpers (el, api, icon, toast, badge, confirmDialog, refreshStatus, fmt*) come from core.js.

const postJson = (path, body, method = "POST") =>
  api(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function renderMe(me) {
  document.getElementById("me-email").textContent = me.email;
  document.getElementById("me-chips").replaceChildren(
    el("span", { class: me.role === "admin" ? "chip eng-spark" : "chip", text: me.role === "admin" ? "administrator" : "member" }),
    el("span", { class: "chip", text: `${fmtNumber(me.datasets)} dataset${me.datasets === 1 ? "" : "s"}` }),
    el("span", { class: "chip", text: me.has_token ? "API token set" : "no API token" }));
  document.getElementById("token-revoke").hidden = !me.has_token;
  document.getElementById("token-create").textContent = me.has_token ? "Replace the API token" : "Create an API token";
}

async function loadMe() {
  const me = await api("/api/me");
  renderMe(me);
  return me;
}

function initToken() {
  const box = document.getElementById("token-box");
  document.getElementById("token-create").addEventListener("click", async () => {
    try {
      const { token } = await api("/api/me/token", { method: "POST" });
      document.getElementById("token-value").textContent = token;
      document.getElementById("token-usage").textContent = `curl -H "Authorization: Bearer ${token}" ${location.origin}/api/datasets`;
      box.hidden = false;
      await loadMe();
    } catch (err) { toast(err.message, COLORS.red); }
  });
  document.getElementById("token-copy").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(document.getElementById("token-value").textContent); toast("Token copied", COLORS.green); }
    catch { toast("Could not copy; select the text instead", COLORS.amber); }
  });
  document.getElementById("token-revoke").addEventListener("click", async () => {
    if (!(await confirmDialog({ title: "Revoke the API token?", body: "Scripts that use it will stop working.", confirmText: "Revoke", danger: true }))) return;
    try { await api("/api/me/token", { method: "DELETE" }); box.hidden = true; toast("Token revoked", COLORS.green); await loadMe(); }
    catch (err) { toast(err.message, COLORS.red); }
  });
}

function initPassword() {
  const form = document.getElementById("password-form");
  const error = document.getElementById("password-error");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.hidden = true;
    try {
      await postJson("/api/me/password", {
        current_password: document.getElementById("current-password").value,
        new_password: document.getElementById("new-password").value,
      });
      form.reset();
      toast("Password changed", COLORS.green);
    } catch (err) { error.textContent = err.message; error.hidden = false; }
  });
}

async function refreshUsers(me) {
  const users = await api("/api/users");
  document.getElementById("users-count").textContent = `${users.length} user${users.length === 1 ? "" : "s"}`;
  document.getElementById("users").replaceChildren(...users.map((u) => {
    const self = u.id === me.id;
    const change = async (body, done) => {
      try { await postJson(`/api/users/${u.id}`, body, "PATCH"); toast(done, COLORS.green); await refreshUsers(me); }
      catch (err) { toast(err.message, COLORS.red); }
    };
    const role = el("button", { class: "btn small", type: "button", text: u.role === "admin" ? "Make member" : "Make admin" });
    role.addEventListener("click", () => change({ role: u.role === "admin" ? "member" : "admin" }, `${u.email} is now ${u.role === "admin" ? "a member" : "an administrator"}`));
    const active = el("button", { class: "btn small", type: "button", text: u.is_active ? "Disable" : "Enable" });
    active.addEventListener("click", () => change({ is_active: !u.is_active }, `${u.email} ${u.is_active ? "disabled" : "enabled"}`));
    const del = el("button", { class: "icon-btn danger", type: "button", title: "Delete", "aria-label": `Delete ${u.email}` }, icon("trash"));
    del.addEventListener("click", async () => {
      const sure = await confirmDialog({
        title: "Delete this user?",
        body: `${u.email} and their ${fmtNumber(u.datasets)} dataset(s) will be removed permanently.`,
        confirmText: "Delete", danger: true,
      });
      if (!sure) return;
      try { await api(`/api/users/${u.id}`, { method: "DELETE" }); toast(`Deleted ${u.email}`, COLORS.green); await refreshUsers(me); }
      catch (err) { toast(err.message, COLORS.red); }
    });
    return el("tr", {},
      el("td", { class: "name", text: self ? `${u.email} (you)` : u.email }),
      el("td", {}, el("span", { class: u.role === "admin" ? "chip eng-spark" : "chip", text: u.role })),
      el("td", {}, badge(u.is_active ? "done" : "failed")),
      el("td", {}, el("span", { class: "num", text: fmtNumber(u.datasets) })),
      el("td", { class: "muted", text: fmtAgo(u.created_at) }),
      el("td", {}, self ? null : el("div", { class: "row-actions" }, role, active, del)));
  }));
  for (const state of document.querySelectorAll("#users .badge")) state.lastChild.textContent = state.classList.contains("done") ? "active" : "disabled";
}

function initUsers(me) {
  document.getElementById("users-card").hidden = false;
  const form = document.getElementById("user-form");
  const error = document.getElementById("user-error");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.hidden = true;
    try {
      const user = await postJson("/api/users", {
        email: document.getElementById("user-email").value,
        password: document.getElementById("user-password").value,
        role: document.getElementById("user-role").value,
      });
      form.reset();
      toast(`Created ${user.email}`, COLORS.green);
      await refreshUsers(me);
    } catch (err) { error.textContent = err.message; error.hidden = false; }
  });
  return refreshUsers(me);
}

async function initAccount() {
  refreshStatus();
  setInterval(refreshStatus, STATUS_MS);
  try {
    const me = await loadMe();
    document.getElementById("account").hidden = false;
    initToken();
    initPassword();
    if (me.role === "admin") await initUsers(me);
  } catch (err) {
    // Accounts are switched off on this server: there is nothing to manage.
    document.getElementById("no-accounts").hidden = false;
  }
}

if (document.body.dataset.page === "account") initAccount();
