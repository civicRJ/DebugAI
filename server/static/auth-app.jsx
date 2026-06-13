/* DebugAI auth pages — login / register / account. Mounted via DebugAIAuth(mode). */
(function () {
  const DS = window.DesignSystem_90c6f1 || {};
  const Button = DS.Button || ((p) => React.createElement("button", { className: "btn btn--primary btn--md", ...p }));
  const { useState, useEffect } = React;

  async function post(url, body, method) {
    const r = await fetch(url, {
      method: method || "POST",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = {};
    try { data = await r.json(); } catch (e) { /* no body */ }
    return { ok: r.ok, status: r.status, data };
  }

  function Brand() {
    return (
      <a className="auth-brand" href="/">
        <span className="auth-logo">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12h4l3 8 4-16 3 8h4" /></svg>
        </span>
        <span>Debug<b>AI</b></span>
      </a>
    );
  }

  function Field({ label, type, value, onChange, placeholder, autoComplete }) {
    return (
      <div className="field">
        <label>{label}</label>
        <input type={type || "text"} value={value} onChange={onChange}
          placeholder={placeholder} autoComplete={autoComplete} />
      </div>
    );
  }

  function Login() {
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [err, setErr] = useState(null);
    const [busy, setBusy] = useState(false);
    const submit = async (e) => {
      e.preventDefault(); setBusy(true); setErr(null);
      const r = await post("/api/auth/login", { email, password });
      if (r.ok) { window.location.href = "/dashboard"; return; }
      setErr(r.data.detail || "Sign in failed."); setBusy(false);
    };
    return (
      <div className="auth-card">
        <Brand />
        <div className="auth-title">Sign in</div>
        <div className="auth-sub">Welcome back to DebugAI.</div>
        <form className="auth-form" onSubmit={submit}>
          <Field label="Email" type="email" value={email} autoComplete="email"
            onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" />
          <Field label="Password" type="password" value={password} autoComplete="current-password"
            onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
          {err && <div className="error-banner">{err}</div>}
          <div className="auth-actions">
            <Button type="submit" variant="primary" size="lg" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </Button>
          </div>
        </form>
        <div className="auth-foot">New here? <a href="/register">Create an account</a></div>
      </div>
    );
  }

  function Register() {
    const [f, setF] = useState({ name: "", email: "", password: "" });
    const [err, setErr] = useState(null);
    const [busy, setBusy] = useState(false);
    const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
    const submit = async (e) => {
      e.preventDefault(); setBusy(true); setErr(null);
      const r = await post("/api/auth/register", f);
      if (r.ok) { window.location.href = "/dashboard"; return; }
      setErr(r.data.detail || "Could not create account."); setBusy(false);
    };
    return (
      <div className="auth-card">
        <Brand />
        <div className="auth-title">Create your account</div>
        <div className="auth-sub">Diagnose and fix LLM failures — free.</div>
        <form className="auth-form" onSubmit={submit}>
          <Field label="Name" value={f.name} onChange={set("name")} placeholder="Ada Lovelace" autoComplete="name" />
          <Field label="Email" type="email" value={f.email} onChange={set("email")} placeholder="you@company.com" autoComplete="email" />
          <Field label="Password" type="password" value={f.password} onChange={set("password")} placeholder="at least 8 characters" autoComplete="new-password" />
          {err && <div className="error-banner">{err}</div>}
          <div className="auth-actions">
            <Button type="submit" variant="primary" size="lg" disabled={busy}>
              {busy ? "Creating…" : "Create account"}
            </Button>
          </div>
        </form>
        <div className="auth-foot">Already have an account? <a href="/login">Sign in</a></div>
      </div>
    );
  }

  function Account() {
    const [user, setUser] = useState(null);
    const [f, setF] = useState({ name: "", email: "", new_password: "", current_password: "" });
    const [msg, setMsg] = useState(null);
    const [err, setErr] = useState(null);
    const [busy, setBusy] = useState(false);
    const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

    useEffect(() => {
      post("/api/auth/me", null, "GET").then((r) => {
        if (!r.ok) { window.location.href = "/login"; return; }
        setUser(r.data);
        setF((p) => ({ ...p, name: r.data.name, email: r.data.email }));
      });
    }, []);

    const save = async (e) => {
      e.preventDefault(); setBusy(true); setErr(null); setMsg(null);
      const r = await post("/api/account", {
        name: f.name, email: f.email,
        new_password: f.new_password || null,
        current_password: f.current_password,
      }, "PATCH");
      setBusy(false);
      if (r.ok) { setMsg("Saved."); setF((p) => ({ ...p, new_password: "", current_password: "" })); setUser(r.data); }
      else setErr(r.data.detail || "Update failed.");
    };
    const logout = async () => { await post("/api/auth/logout"); window.location.href = "/"; };
    const remove = async () => {
      if (!window.confirm("Delete your account and all its data? This cannot be undone.")) return;
      const r = await post("/api/account", null, "DELETE");
      if (r.ok) window.location.href = "/";
    };

    if (!user) return <div className="auth-card">Loading…</div>;
    return (
      <div className="auth-card" style={{ maxWidth: "460px" }}>
        <Brand />
        <div className="auth-title">Account</div>
        <div className="auth-sub auth-meta">{user.email}</div>
        <form className="auth-form" onSubmit={save}>
          <Field label="Name" value={f.name} onChange={set("name")} autoComplete="name" />
          <Field label="Email" type="email" value={f.email} onChange={set("email")} autoComplete="email" />
          <Field label="New password (optional)" type="password" value={f.new_password}
            onChange={set("new_password")} placeholder="leave blank to keep" autoComplete="new-password" />
          <Field label="Current password (required to save)" type="password" value={f.current_password}
            onChange={set("current_password")} placeholder="••••••••" autoComplete="current-password" />
          {err && <div className="error-banner">{err}</div>}
          {msg && <div className="auth-success">{msg}</div>}
          <div className="auth-actions">
            <Button type="submit" variant="primary" size="lg" disabled={busy}>
              {busy ? "Saving…" : "Save changes"}
            </Button>
          </div>
        </form>
        <Tokens />
        <div className="auth-section" style={{ display: "flex", gap: "var(--space-3)", justifyContent: "space-between", alignItems: "center" }}>
          <a className="auth-foot" style={{ margin: 0 }} href="/dashboard">← Back to dashboard</a>
          <div style={{ display: "flex", gap: "var(--space-2)" }}>
            <Button variant="secondary" size="sm" onClick={logout}>Log out</Button>
            <Button variant="danger" size="sm" onClick={remove}>Delete account</Button>
          </div>
        </div>
      </div>
    );
  }

  function Tokens() {
    const [tokens, setTokens] = useState([]);
    const [name, setName] = useState("");
    const [created, setCreated] = useState(null);  // plaintext shown once
    const [busy, setBusy] = useState(false);

    const load = () => post("/api/account/tokens", null, "GET").then((r) => r.ok && setTokens(r.data.items));
    useEffect(() => { load(); }, []);

    const create = async (e) => {
      e.preventDefault(); setBusy(true);
      const r = await post("/api/account/tokens", { name: name || "token" });
      setBusy(false);
      if (r.ok) { setCreated(r.data); setName(""); load(); }
    };
    const revoke = async (id) => {
      await post("/api/account/tokens/" + id, null, "DELETE");
      load();
    };

    return (
      <div className="auth-section">
        <h3>API tokens</h3>
        <div className="auth-sub" style={{ margin: "0 0 var(--space-3)" }}>
          Authenticate the SDK or scripts as your account (send as <code>X-API-Key</code>).
        </div>
        <form className="auth-form" onSubmit={create} style={{ gridTemplateColumns: "1fr auto", gridAutoFlow: "column", alignItems: "end", gap: "var(--space-2)" }}>
          <div className="field"><label>Token name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="ci-pipeline" /></div>
          <Button type="submit" variant="secondary" size="md" disabled={busy}>Create</Button>
        </form>
        {created && (
          <div className="auth-success" style={{ wordBreak: "break-all", marginTop: "var(--space-3)" }}>
            Copy now — shown once:<br /><code>{created.token}</code>
          </div>
        )}
        <div style={{ marginTop: "var(--space-3)", display: "grid", gap: "var(--space-2)" }}>
          {tokens.length === 0 ? (
            <div className="auth-meta">No tokens yet.</div>
          ) : tokens.map((t) => (
            <div key={t.id} style={{ display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
              <span style={{ flex: 1 }}>{t.name} <span className="auth-meta">· {t.last_used ? "used" : "never used"}</span></span>
              <button className="link-btn auth-danger" onClick={() => revoke(t.id)}>revoke</button>
            </div>
          ))}
        </div>
      </div>
    );
  }

  const VIEWS = { login: Login, register: Register, account: Account };

  // Derive the view from the URL path (/login, /register, /account) — no inline
  // script needed, so the page can run under a strict `script-src 'self'` CSP.
  const seg = window.location.pathname.replace(/\/+$/, "").split("/").pop();
  const View = VIEWS[seg] || Login;
  ReactDOM.createRoot(document.getElementById("root")).render(
    <div className="auth-wrap"><View /></div>
  );
})();
