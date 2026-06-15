/* DebugAI auth pages — login / register / account.
   Mounted via the URL path: /login, /register, /account. */
(function () {
  const DS = window.DesignSystem_90c6f1 || {};
  const Button = DS.Button || ((p) => React.createElement("button",
    { className: `btn btn--${p.variant || "primary"} btn--${p.size || "md"}`, ...p }));
  const Badge = DS.Badge || ((p) => React.createElement("span", { className: "badge", ...p }));
  const { useState, useEffect, useRef } = React;

  // ── Utilities ─────────────────────────────────────────────────────────────
  async function apiFetch(url, method = "GET", body) {
    const r = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = {};
    try { data = await r.json(); } catch (_) {}
    return { ok: r.ok, status: r.status, data };
  }

  function validateEmail(v) {
    return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test((v || "").trim())
      ? null : "Enter a valid email address.";
  }
  function validatePassword(v) {
    return (v || "").length >= 8 ? null : "Password must be at least 8 characters.";
  }
  function validateName(v) {
    return (v || "").trim() ? null : "Name is required.";
  }

  // ── Sub-components ────────────────────────────────────────────────────────

  function Brand() {
    return (
      <a className="auth-brand" href="/" aria-label="DebugAI home">
        <span className="auth-logo" aria-hidden="true">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 12h4l3 8 4-16 3 8h4" />
          </svg>
        </span>
        <span>Debug<b>AI</b></span>
      </a>
    );
  }

  function FieldGroup({ label, id, type, value, onChange, onBlur, error, autoFocus, autoComplete,
                        placeholder, showToggle, onToggle, showPassword }) {
    const inputType = showToggle ? (showPassword ? "text" : "password") : (type || "text");
    return (
      <div className={"auth-field" + (error ? " auth-field--error" : "")}>
        <label htmlFor={id}>{label}</label>
        <div className="auth-input-wrap">
          <input
            id={id}
            type={inputType}
            value={value}
            onChange={onChange}
            onBlur={onBlur}
            autoFocus={autoFocus}
            autoComplete={autoComplete}
            placeholder={placeholder}
            aria-invalid={!!error}
            aria-describedby={error ? id + "-err" : undefined}
          />
          {showToggle && (
            <button type="button" className="auth-pw-toggle" onClick={onToggle}
              aria-label={showPassword ? "Hide password" : "Show password"}>
              {showPassword
                ? /* eye-off */ <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
                    stroke="currentColor" strokeWidth="1.8"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
                : /* eye */ <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
                    stroke="currentColor" strokeWidth="1.8"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
              }
            </button>
          )}
        </div>
        {error && <p id={id + "-err"} className="auth-field__error" role="alert">{error}</p>}
      </div>
    );
  }

  // ── Login ─────────────────────────────────────────────────────────────────
  function Login() {
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [showPw, setShowPw] = useState(false);
    const [errors, setErrors] = useState({});
    const [formErr, setFormErr] = useState(null);
    const [mfaChallenge, setMfaChallenge] = useState(null);
    const [mfaCode, setMfaCode] = useState("");
    const [busy, setBusy] = useState(false);

    function validate(field, value) {
      const e = {};
      if (field === "email" || !field) { const v = validateEmail(value ?? email); if (v) e.email = v; }
      if (field === "password" || !field) { const v = validatePassword(value ?? password); if (v) e.password = v; }
      return e;
    }

    async function submit(ev) {
      ev.preventDefault();
      if (mfaChallenge) {
        if (!mfaCode.trim()) { setFormErr("Enter the 6-digit code from your authenticator app."); return; }
        setBusy(true); setFormErr(null);
        const r = await apiFetch("/api/auth/mfa/login", "POST", { challenge: mfaChallenge, code: mfaCode });
        if (r.ok) { window.location.href = "/dashboard"; return; }
        setFormErr(r.data.detail || "Invalid MFA code.");
        setBusy(false);
        return;
      }
      const e = validate();
      if (Object.keys(e).length) { setErrors(e); return; }
      setBusy(true); setFormErr(null);
      const r = await apiFetch("/api/auth/login", "POST", { email: email.trim(), password });
      if (r.data.mfa_required) {
        setMfaChallenge(r.data.challenge);
        setBusy(false);
        return;
      }
      if (r.ok) { window.location.href = "/dashboard"; return; }
      setFormErr(r.data.detail || "Wrong email or password. Try again.");
      setBusy(false);
    }

    return (
      <div className="auth-card">
        <Brand />
        <h1 className="auth-title">{mfaChallenge ? "Two-factor code" : "Sign in"}</h1>
        <p className="auth-sub">{mfaChallenge ? "Enter the code from your authenticator app." : "Welcome back to DebugAI."}</p>
        <form className="auth-form" onSubmit={submit} noValidate>
          {mfaChallenge ? (
            <FieldGroup label="Authenticator code" id="login-mfa" value={mfaCode}
              onChange={e => setMfaCode(e.target.value)} autoFocus autoComplete="one-time-code"
              placeholder="123456" />
          ) : (
          <>
          <FieldGroup label="Email" id="login-email" type="email" value={email}
            onChange={e => { setEmail(e.target.value); setErrors(prev => ({ ...prev, email: null })); }}
            onBlur={() => { const e = validate("email"); setErrors(prev => ({ ...prev, ...e })); }}
            error={errors.email} autoFocus autoComplete="email" placeholder="you@company.com" />
          <FieldGroup label="Password" id="login-pw" type="password" value={password}
            onChange={e => { setPassword(e.target.value); setErrors(prev => ({ ...prev, password: null })); }}
            onBlur={() => { const e = validate("password"); setErrors(prev => ({ ...prev, ...e })); }}
            error={errors.password} autoComplete="current-password" placeholder="••••••••"
            showToggle showPassword={showPw} onToggle={() => setShowPw(v => !v)} />
          </>
          )}
          {formErr && <p className="auth-form-error" role="alert">{formErr}</p>}
          <button type="submit" className={"auth-submit" + (busy ? " auth-submit--busy" : "")}
            disabled={busy}>
            {busy
              ? <><span className="auth-spinner" aria-hidden="true" />Signing in…</>
              : (mfaChallenge ? "Verify code" : "Sign in")}
          </button>
        </form>
        <p className="auth-foot">
          New here? <a href="/register">Create an account</a>
          <br /><a href="/reset-password">Forgot password?</a>
        </p>
      </div>
    );
  }

  // ── Register ──────────────────────────────────────────────────────────────
  function Register() {
    const [f, setF] = useState({ name: "", email: "", password: "", website: "" });
    const [showPw, setShowPw] = useState(false);
    const [errors, setErrors] = useState({});
    const [formErr, setFormErr] = useState(null);
    const [sent, setSent] = useState(false);
    const [busy, setBusy] = useState(false);
    const set = k => e => { setF(p => ({ ...p, [k]: e.target.value })); setErrors(p => ({ ...p, [k]: null })); };

    function validate(field) {
      const e = {};
      if (!field || field === "name") { const v = validateName(f.name); if (v) e.name = v; }
      if (!field || field === "email") { const v = validateEmail(f.email); if (v) e.email = v; }
      if (!field || field === "password") { const v = validatePassword(f.password); if (v) e.password = v; }
      return e;
    }

    async function submit(ev) {
      ev.preventDefault();
      const e = validate();
      if (Object.keys(e).length) { setErrors(e); return; }
      setBusy(true); setFormErr(null);
      const r = await apiFetch("/api/auth/register", "POST",
        { email: f.email.trim(), name: f.name.trim(), password: f.password, website: f.website });
      if (r.ok) {
        if (r.data.needs_verification || r.data.message) {
          setSent(true);
          setBusy(false);
          return;
        }
        try { window.debugaiTrack && window.debugaiTrack("signup", { method: "email" }); } catch(_) {}
        try { window.debugaiIdentify && window.debugaiIdentify(r.data.id, { email: r.data.email, name: r.data.name }); } catch(_) {}
        window.location.href = "/dashboard"; return;
      }
      const msg = r.data.detail || "Could not create account.";
      setFormErr(msg.includes("already") ? "Email already registered. Sign in instead?" : msg);
      setBusy(false);
    }

    return (
      <div className="auth-card">
        <Brand />
        <h1 className="auth-title">Create your account</h1>
        <p className="auth-sub">
          {sent ? "Check your email to finish creating the account." : "Diagnose and fix LLM failures — free."}
        </p>
        {sent && (
          <p className="auth-success" role="status">
            We sent a verification link to {f.email.trim() || "your email address"}.
          </p>
        )}
        {!sent && (
        <form className="auth-form" onSubmit={submit} noValidate>
          <input type="text" value={f.website} onChange={set("website")}
            tabIndex="-1" autoComplete="off" aria-hidden="true" style={{ display: "none" }} />
          <FieldGroup label="Name" id="reg-name" value={f.name} onChange={set("name")}
            onBlur={() => setErrors(p => ({ ...p, ...validate("name") }))}
            error={errors.name} autoFocus autoComplete="name" placeholder="Ada Lovelace" />
          <FieldGroup label="Email" id="reg-email" type="email" value={f.email}
            onChange={set("email")}
            onBlur={() => setErrors(p => ({ ...p, ...validate("email") }))}
            error={errors.email} autoComplete="email" placeholder="you@company.com" />
          <FieldGroup label="Password" id="reg-pw" type="password" value={f.password}
            onChange={set("password")}
            onBlur={() => setErrors(p => ({ ...p, ...validate("password") }))}
            error={errors.password} autoComplete="new-password" placeholder="at least 8 characters"
            showToggle showPassword={showPw} onToggle={() => setShowPw(v => !v)} />
          {formErr && (
            <p className="auth-form-error" role="alert">
              {formErr.includes("Sign in") ? (
                <>{formErr.split("Sign in")[0]}<a href="/login">Sign in</a>{formErr.split("Sign in")[1]}</>
              ) : formErr}
            </p>
          )}
          <button type="submit" className={"auth-submit" + (busy ? " auth-submit--busy" : "")}
            disabled={busy}>
            {busy ? <><span className="auth-spinner" aria-hidden="true" />Creating…</> : "Create account"}
          </button>
        </form>
        )}
        <p className="auth-foot">Already have an account? <a href="/login">Sign in</a></p>
      </div>
    );
  }

  function VerifyEmail() {
    const [state, setState] = useState({ status: "working", detail: "Verifying your email..." });
    useEffect(() => {
      const token = new URLSearchParams(window.location.search).get("token") || "";
      if (!token) {
        setState({ status: "error", detail: "Verification link is missing." });
        return;
      }
      apiFetch("/api/auth/verify", "POST", { token }).then(r => {
        if (r.ok) {
          setState({ status: "ok", detail: "Email verified. Redirecting..." });
          setTimeout(() => { window.location.href = "/dashboard"; }, 900);
        } else {
          setState({ status: "error", detail: r.data.detail || "Verification link is invalid or expired." });
        }
      });
    }, []);
    return (
      <div className="auth-card">
        <Brand />
        <h1 className="auth-title">Verify email</h1>
        <p className={state.status === "error" ? "auth-form-error" : "auth-success"} role="status">
          {state.detail}
        </p>
        {state.status === "error" && <p className="auth-foot"><a href="/login">Back to sign in</a></p>}
      </div>
    );
  }

  function ResetPassword() {
    const token = new URLSearchParams(window.location.search).get("token") || "";
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [showPw, setShowPw] = useState(false);
    const [msg, setMsg] = useState(null);
    const [err, setErr] = useState(null);
    const [busy, setBusy] = useState(false);

    async function request(ev) {
      ev.preventDefault();
      const e = validateEmail(email);
      if (e) { setErr(e); return; }
      setBusy(true); setErr(null);
      await apiFetch("/api/auth/password-reset/request", "POST", { email: email.trim() });
      setBusy(false);
      setMsg("If that email has an account, a reset link has been sent.");
    }

    async function confirm(ev) {
      ev.preventDefault();
      const e = validatePassword(password);
      if (e) { setErr(e); return; }
      setBusy(true); setErr(null);
      const r = await apiFetch("/api/auth/password-reset/confirm", "POST", { token, password });
      setBusy(false);
      if (r.ok) { window.location.href = "/dashboard"; return; }
      setErr(r.data.detail || "Reset link is invalid or expired.");
    }

    return (
      <div className="auth-card">
        <Brand />
        <h1 className="auth-title">{token ? "Choose new password" : "Reset password"}</h1>
        <p className="auth-sub">
          {token ? "Enter a new password for your account." : "We'll email you a reset link if the account exists."}
        </p>
        <form className="auth-form" onSubmit={token ? confirm : request} noValidate>
          {token ? (
            <FieldGroup label="New password" id="reset-pw" type="password" value={password}
              onChange={e => setPassword(e.target.value)}
              error={err} autoComplete="new-password" placeholder="at least 8 characters"
              showToggle showPassword={showPw} onToggle={() => setShowPw(v => !v)} />
          ) : (
            <FieldGroup label="Email" id="reset-email" type="email" value={email}
              onChange={e => setEmail(e.target.value)}
              error={err} autoFocus autoComplete="email" placeholder="you@company.com" />
          )}
          {msg && <p className="auth-success" role="status">{msg}</p>}
          {err && token && <p className="auth-form-error" role="alert">{err}</p>}
          <button type="submit" className={"auth-submit" + (busy ? " auth-submit--busy" : "")}
            disabled={busy}>
            {busy ? <><span className="auth-spinner" aria-hidden="true" />Sending…</> : (token ? "Reset password" : "Send reset link")}
          </button>
        </form>
        <p className="auth-foot"><a href="/login">Back to sign in</a></p>
      </div>
    );
  }

  // ── Tokens section (used inside Account) ──────────────────────────────────
  // ── LLM Keys section ──────────────────────────────────────────────────────
  const PROVIDERS = [
    { id: "openai", label: "OpenAI", placeholder: "sk-...", hint: "Used for the instruction-adherence judge and fix re-runs." },
    { id: "anthropic", label: "Anthropic", placeholder: "sk-ant-...", hint: "Used for the LLM explainer (human-readable diagnosis text)." },
  ];

  function LLMKeys() {
    const [keys, setKeys] = useState({});     // { openai: {set, updated_at}, ... }
    const [editing, setEditing] = useState({}); // { openai: "" }
    const [saving, setSaving] = useState({});
    const [showKey, setShowKey] = useState({});
    const [msg, setMsg] = useState(null);

    const load = () => apiFetch("/api/account/llm-keys").then(r => r.ok && setKeys(r.data));
    useEffect(() => { load(); }, []);

    async function save(provider) {
      const val = (editing[provider] || "").trim();
      if (!val) return;
      setSaving(p => ({ ...p, [provider]: true }));
      const r = await apiFetch(`/api/account/llm-keys/${provider}`, "PUT", { key: val });
      setSaving(p => ({ ...p, [provider]: false }));
      if (r.ok) {
        setEditing(p => ({ ...p, [provider]: "" }));
        setMsg("Key saved.");
        load();
        setTimeout(() => setMsg(null), 2000);
      }
    }

    async function remove(provider) {
      if (!window.confirm(`Remove your ${provider} key? LLM features requiring it will stop working.`)) return;
      await apiFetch(`/api/account/llm-keys/${provider}`, "DELETE");
      load();
    }

    return (
      <div className="auth-section">
        <h3>LLM Keys</h3>
        <p className="auth-section-desc">
          Your keys are encrypted and stored per-account. They're used only for your requests — never shared.
          The server has no keys; LLM features are unavailable until you add yours.
        </p>
        {msg && <p className="auth-success" role="status">{msg}</p>}
        {PROVIDERS.map(({ id, label, placeholder, hint }) => (
          <div key={id} className="llm-key-row">
            <div className="llm-key-header">
              <span className="llm-key-label">{label}</span>
              {keys[id]?.set
                ? <span className="llm-key-badge llm-key-badge--set">✓ Key set</span>
                : <span className="llm-key-badge llm-key-badge--missing">Not set</span>}
            </div>
            <p className="auth-meta" style={{ margin: "2px 0 var(--space-2)" }}>{hint}</p>
            <div className="llm-key-input-row">
              <div className="auth-input-wrap" style={{ flex: 1 }}>
                <input
                  type={showKey[id] ? "text" : "password"}
                  value={editing[id] || ""}
                  onChange={e => setEditing(p => ({ ...p, [id]: e.target.value }))}
                  placeholder={keys[id]?.set ? "Enter new key to replace" : placeholder}
                  autoComplete="off"
                  style={{ width: "100%" }}
                />
                <button type="button" className="auth-pw-toggle"
                  onClick={() => setShowKey(p => ({ ...p, [id]: !p[id] }))}
                  aria-label={showKey[id] ? "Hide key" : "Show key"}>
                  {showKey[id]
                    ? <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
                    : <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                  }
                </button>
              </div>
              <button className="auth-submit auth-submit--sm"
                onClick={() => save(id)} disabled={saving[id] || !editing[id]}>
                {saving[id] ? "Saving…" : "Save"}
              </button>
              {keys[id]?.set && (
                <button className="auth-revoke" onClick={() => remove(id)}>Remove</button>
              )}
            </div>
          </div>
        ))}
      </div>
    );
  }


  function Tokens() {
    const [tokens, setTokens] = useState([]);
    const [name, setName] = useState("");
    const [modal, setModal] = useState(null); // { token, name } shown once
    const [busy, setBusy] = useState(false);
    const [revoking, setRevoking] = useState(null);

    const load = () => apiFetch("/api/account/tokens").then(r => r.ok && setTokens(r.data.items || []));
    useEffect(() => { load(); }, []);

    async function create(ev) {
      ev.preventDefault();
      if (!name.trim()) return;
      setBusy(true);
      const r = await apiFetch("/api/account/tokens", "POST", { name: name.trim() });
      setBusy(false);
      if (r.ok) { setModal(r.data); setName(""); load(); }
    }

    async function revoke(id) {
      if (!window.confirm("Revoke this token? Any apps using it will lose access.")) return;
      setRevoking(id);
      await apiFetch(`/api/account/tokens/${id}`, "DELETE");
      setRevoking(null);
      load();
    }

    function copy(text) {
      navigator.clipboard?.writeText(text).catch(() => {});
    }

    return (
      <div className="auth-section">
        <h3>API tokens</h3>
        <p className="auth-section-desc">
          Authenticate the SDK or scripts as your account via <code>X-API-Key</code>.
        </p>
        <form className="auth-token-form" onSubmit={create}>
          <input className="auth-token-input" value={name} onChange={e => setName(e.target.value)}
            placeholder="Token name, e.g. ci-pipeline" maxLength={80} />
          <button type="submit" className="auth-submit auth-submit--sm" disabled={busy || !name.trim()}>
            {busy ? "Creating…" : "Create token"}
          </button>
        </form>
        {modal && (
          <div className="auth-token-modal" role="dialog" aria-modal="true" aria-label="New API token">
            <div className="auth-token-modal__inner">
              <p className="auth-token-modal__title">Copy this token — it won't be shown again.</p>
              <div className="auth-token-modal__value">
                <code>{modal.token}</code>
                <button className="auth-token-copy" onClick={() => copy(modal.token)}
                  aria-label="Copy token">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                </button>
              </div>
              <button className="auth-submit auth-submit--sm" onClick={() => setModal(null)}>
                I've copied it
              </button>
            </div>
          </div>
        )}
        {tokens.length === 0
          ? <p className="auth-meta" style={{ marginTop: "var(--space-3)" }}>No tokens yet.</p>
          : (
          <ul className="auth-token-list">
            {tokens.map(t => (
              <li key={t.id} className="auth-token-row">
                <span className="auth-token-name">{t.name}</span>
                <span className="auth-meta">{t.last_used ? "Used recently" : "Never used"}</span>
                <button className="auth-revoke" disabled={revoking === t.id}
                  onClick={() => revoke(t.id)} aria-label={`Revoke ${t.name}`}>
                  {revoking === t.id ? "Revoking…" : "Revoke"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  function Sessions() {
    const [items, setItems] = useState([]);
    const [msg, setMsg] = useState(null);
    const load = () => apiFetch("/api/auth/sessions").then(r => r.ok && setItems(r.data.items || []));
    useEffect(() => { load(); }, []);

    async function logoutOthers() {
      await apiFetch("/api/auth/logout-others", "POST");
      setMsg("Other sessions signed out.");
      load();
      setTimeout(() => setMsg(null), 2000);
    }

    async function revoke(id) {
      await apiFetch(`/api/auth/sessions/${id}`, "DELETE");
      load();
    }

    function when(ts) {
      if (!ts) return "unknown";
      return new Date(ts * 1000).toLocaleString();
    }

    return (
      <div className="auth-section">
        <h3>Sessions</h3>
        <p className="auth-section-desc">Review active browser sessions and sign out devices you no longer use.</p>
        {msg && <p className="auth-success" role="status">{msg}</p>}
        <button type="button" className="auth-submit auth-submit--sm" onClick={logoutOthers}>
          Log out other sessions
        </button>
        <ul className="auth-token-list">
          {items.map(s => (
            <li key={s.id} className="auth-token-row">
              <span className="auth-token-name">{s.current ? "Current session" : "Browser session"}</span>
              <span className="auth-meta">Last used {when(s.last_used)}</span>
              {!s.current && <button className="auth-revoke" onClick={() => revoke(s.id)}>Revoke</button>}
            </li>
          ))}
        </ul>
      </div>
    );
  }

  function MFA() {
    const [status, setStatus] = useState({ enabled: false });
    const [setup, setSetup] = useState(null);
    const [code, setCode] = useState("");
    const [msg, setMsg] = useState(null);
    const [err, setErr] = useState(null);
    const load = () => apiFetch("/api/account/mfa").then(r => r.ok && setStatus(r.data));
    useEffect(() => { load(); }, []);

    async function startSetup() {
      setErr(null); setMsg(null);
      const r = await apiFetch("/api/account/mfa/setup", "POST");
      if (r.ok) { setSetup(r.data); setCode(""); return; }
      setErr(r.data.detail || "Could not start MFA setup.");
    }

    async function enable() {
      setErr(null);
      const r = await apiFetch("/api/account/mfa/enable", "POST", { code });
      if (r.ok) {
        setStatus(r.data); setSetup(null); setCode(""); setMsg("MFA enabled.");
        return;
      }
      setErr(r.data.detail || "Invalid code.");
    }

    async function disable() {
      setErr(null);
      const r = await apiFetch("/api/account/mfa/disable", "POST", { code });
      if (r.ok) {
        setStatus(r.data); setSetup(null); setCode(""); setMsg("MFA disabled.");
        return;
      }
      setErr(r.data.detail || "Invalid code.");
    }

    return (
      <div className="auth-section">
        <h3>Multi-factor authentication</h3>
        <p className="auth-section-desc">
          Add a one-time code from an authenticator app to protect sign-in.
        </p>
        {msg && <p className="auth-success" role="status">{msg}</p>}
        {err && <p className="auth-form-error" role="alert">{err}</p>}
        {setup && (
          <div className="auth-token-modal" role="dialog" aria-modal="true" aria-label="MFA setup">
            <div className="auth-token-modal__inner">
              <p className="auth-token-modal__title">Add this key to your authenticator app.</p>
              <div className="auth-token-modal__value"><code>{setup.secret}</code></div>
              <p className="auth-meta">Then enter the 6-digit code it generates.</p>
            </div>
          </div>
        )}
        <div className="auth-token-form">
          <input className="auth-token-input" value={code} onChange={e => setCode(e.target.value)}
            placeholder={status.enabled ? "Current 6-digit code" : "6-digit code"} maxLength={20}
            autoComplete="one-time-code" />
          {status.enabled ? (
            <button type="button" className="auth-revoke" onClick={disable} disabled={!code.trim()}>
              Disable
            </button>
          ) : setup ? (
            <button type="button" className="auth-submit auth-submit--sm" onClick={enable} disabled={!code.trim()}>
              Enable MFA
            </button>
          ) : (
            <button type="button" className="auth-submit auth-submit--sm" onClick={startSetup}>
              Set up MFA
            </button>
          )}
        </div>
      </div>
    );
  }

  // ── Account ────────────────────────────────────────────────────────────────
  function Account() {
    const [user, setUser] = useState(null);
    const [f, setF] = useState({ name: "", email: "", new_password: "", current_password: "" });
    const [showNewPw, setShowNewPw] = useState(false);
    const [showCurPw, setShowCurPw] = useState(false);
    const [msg, setMsg] = useState(null);
    const [err, setErr] = useState(null);
    const [busy, setBusy] = useState(false);
    const [deleteStep, setDeleteStep] = useState(0); // 0=hidden 1=confirm data 2=confirm account
    const [deleteText, setDeleteText] = useState("");
    const set = k => e => setF(p => ({ ...p, [k]: e.target.value }));

    useEffect(() => {
      apiFetch("/api/auth/me").then(r => {
        if (!r.ok) { window.location.href = "/login"; return; }
        setUser(r.data);
        setF(p => ({ ...p, name: r.data.name, email: r.data.email }));
      });
    }, []);

    async function save(ev) {
      ev.preventDefault();
      if (!f.current_password) { setErr("Enter your current password to save changes."); return; }
      setBusy(true); setErr(null); setMsg(null);
      const r = await apiFetch("/api/account", "PATCH", {
        name: f.name || undefined,
        email: f.email || undefined,
        new_password: f.new_password || null,
        current_password: f.current_password,
      });
      setBusy(false);
      if (r.ok) {
        setMsg("Profile updated.");
        setUser(r.data);
        setF(p => ({ ...p, new_password: "", current_password: "" }));
      } else {
        setErr(r.data.detail || "Update failed. Check your current password.");
      }
    }

    async function logout() {
      await apiFetch("/api/auth/logout", "POST");
      window.location.href = "/";
    }

    async function deleteData() {
      // Delete just diagnoses/traces, keep account
      await apiFetch("/api/diagnoses", "DELETE");
      setDeleteStep(0);
      setMsg("All diagnoses and traces deleted. Your account is still active.");
    }

    async function deleteAccount() {
      if (deleteText !== "DELETE") return;
      await apiFetch("/api/account", "DELETE");
      window.location.href = "/";
    }

    if (!user) return (
      <div className="auth-card" style={{ minHeight: 200, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <span className="auth-spinner" style={{ width: 24, height: 24 }} aria-label="Loading" />
      </div>
    );

    return (
      <div className="auth-card auth-card--wide">
        <div className="auth-account-header">
          <Brand />
          <div className="auth-account-nav">
            <a href="/dashboard" className="auth-back">← Dashboard</a>
            <button onClick={logout} className="auth-logout-btn" type="button">Log out</button>
          </div>
        </div>

        {/* 1 ── Profile */}
        <section aria-labelledby="profile-heading">
          <h2 id="profile-heading" className="auth-title" style={{ marginTop: "var(--space-6)" }}>Profile</h2>
          <form className="auth-form" onSubmit={save}>
            <FieldGroup label="Name" id="acc-name" value={f.name} onChange={set("name")}
              autoComplete="name" />
            <FieldGroup label="Email" id="acc-email" type="email" value={f.email}
              onChange={set("email")} autoComplete="email" />
            <FieldGroup label="New password" id="acc-newpw" type="password" value={f.new_password}
              onChange={set("new_password")} autoComplete="new-password"
              placeholder="Leave blank to keep current"
              showToggle showPassword={showNewPw} onToggle={() => setShowNewPw(v => !v)} />
            <FieldGroup label="Current password (required to save)" id="acc-curpw"
              type="password" value={f.current_password}
              onChange={set("current_password")} autoComplete="current-password"
              placeholder="••••••••"
              showToggle showPassword={showCurPw} onToggle={() => setShowCurPw(v => !v)} />
            {err && <p className="auth-form-error" role="alert">{err}</p>}
            {msg && <p className="auth-success" role="status">{msg}</p>}
            <button type="submit" className={"auth-submit" + (busy ? " auth-submit--busy" : "")}
              disabled={busy}>
              {busy ? <><span className="auth-spinner" aria-hidden="true" />Saving…</> : "Save changes"}
            </button>
          </form>
        </section>

        {/* 2 ── API Tokens */}
        <LLMKeys />
        <Tokens />
        <MFA />
        <Sessions />

        {/* 3 ── Danger zone */}
        <section className="auth-danger-zone" aria-labelledby="danger-heading">
          <h3 id="danger-heading">Danger zone</h3>
          <div className="auth-danger-actions">
            <div className="auth-danger-action">
              <div>
                <p className="auth-danger-label">Delete all my data</p>
                <p className="auth-meta">Removes all diagnoses and traces. Your account stays active.</p>
              </div>
              <button type="button" className="auth-danger-btn auth-danger-btn--secondary"
                onClick={() => setDeleteStep(1)}>
                Delete data
              </button>
            </div>
            <div className="auth-danger-action">
              <div>
                <p className="auth-danger-label">Delete account</p>
                <p className="auth-meta">Permanently deletes your account and all data. Cannot be undone.</p>
              </div>
              <button type="button" className="auth-danger-btn"
                onClick={() => setDeleteStep(2)}>
                Delete account
              </button>
            </div>
          </div>

          {deleteStep === 1 && (
            <div className="auth-confirm-dialog" role="dialog" aria-modal="true"
              aria-label="Confirm data deletion">
              <p className="auth-confirm-msg">
                Delete all diagnoses and traces? Your account stays active.
              </p>
              <div className="auth-confirm-actions">
                <button className="auth-danger-btn" onClick={deleteData}>Delete all data</button>
                <button className="auth-cancel-btn" onClick={() => setDeleteStep(0)}>Keep them</button>
              </div>
            </div>
          )}

          {deleteStep === 2 && (
            <div className="auth-confirm-dialog" role="dialog" aria-modal="true"
              aria-label="Confirm account deletion">
              <p className="auth-confirm-msg">
                This permanently deletes your account and all data. Type <code>DELETE</code> to confirm.
              </p>
              <input className="auth-confirm-input" value={deleteText}
                onChange={e => setDeleteText(e.target.value)}
                placeholder="Type DELETE" aria-label="Type DELETE to confirm" />
              <div className="auth-confirm-actions">
                <button className="auth-danger-btn" onClick={deleteAccount}
                  disabled={deleteText !== "DELETE"}>
                  Delete account
                </button>
                <button className="auth-cancel-btn"
                  onClick={() => { setDeleteStep(0); setDeleteText(""); }}>
                  Cancel
                </button>
              </div>
            </div>
          )}
        </section>
      </div>
    );
  }

  // ── Router ────────────────────────────────────────────────────────────────
  const VIEWS = {
    login: Login,
    register: Register,
    account: Account,
    "verify-email": VerifyEmail,
    "reset-password": ResetPassword,
  };
  const seg = window.location.pathname.replace(/\/+$/, "").split("/").pop();
  const View = VIEWS[seg] || Login;
  ReactDOM.createRoot(document.getElementById("root")).render(
    <div className="auth-wrap"><View /></div>
  );
})();
