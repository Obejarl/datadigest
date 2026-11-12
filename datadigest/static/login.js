// The sign-in page: one shared token, or an email and a password, depending on how the server is set up.

// Only same-site paths are valid "next" targets: "//evil.example" and "/\evil.example" are not.
function safeNext(value) {
  return value && value.startsWith("/") && !value.startsWith("//") && !value.includes("\\") ? value : "/";
}

async function initLogin() {
  const form = document.getElementById("login-form");
  const error = document.getElementById("login-error");
  const submit = document.getElementById("login-submit");
  const next = safeNext(new URLSearchParams(location.search).get("next"));

  let accounts = false;
  try {
    const status = await api("/api/auth/status");
    if (status.authenticated) { location.href = next; return; }
    accounts = status.mode === "accounts";
  } catch {}
  // Fields of the other mode are disabled, so "required" and the password manager ignore them.
  for (const [id, on] of [["token-fields", !accounts], ["account-fields", accounts]]) {
    const box = document.getElementById(id);
    box.hidden = !on;
    for (const input of box.querySelectorAll("input")) input.disabled = !on;
  }
  const first = document.getElementById(accounts ? "email" : "token");
  first.focus();

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.hidden = true;
    submit.disabled = true;
    const body = accounts
      ? { email: document.getElementById("email").value, password: document.getElementById("password").value }
      : { token: document.getElementById("token").value };
    try {
      await api("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      location.href = next;
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
      submit.disabled = false;
      document.getElementById(accounts ? "password" : "token").select();
    }
  });
}

if (document.body.dataset.page === "login") initLogin();
