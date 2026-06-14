/* DebugAI dashboard — renders live diagnoses with the design system. */
(function () {
  const DS = window.DesignSystem_90c6f1;
  if (!DS) {
    document.getElementById("root").innerHTML =
      '<div class="boot">Design system bundle failed to load (/ds/_ds_bundle.js).</div>';
    return;
  }
  const { Button, Badge, CodeBlock, DiagnosticCard } = DS;
  const { useState, useEffect, useCallback, useRef } = React;

  // ── Utilities ─────────────────────────────────────────────────────────────
  async function dfetch(url, opts = {}) {
    const headers = { ...(opts.headers || {}) };
    if (opts.body) headers["Content-Type"] = "application/json";
    const r = await fetch(url, { ...opts, headers });
    if (r.status === 401) { window.location.href = "/login"; const e = new Error("unauthorized"); e.code = 401; throw e; }
    return r.json();
  }

  const api = {
    me: () => dfetch("/api/auth/me"),
    stats: () => dfetch("/api/stats"),
    thresholds: () => dfetch("/api/thresholds"),
    list: (failure, q) => { const p = new URLSearchParams(); if (failure) p.set("failure", failure); if (q) p.set("q", q); const qs = p.toString(); return dfetch("/api/diagnoses" + (qs ? "?" + qs : "")); },
    analyze: (body) => dfetch("/api/analyze", { method: "POST", body: JSON.stringify(body) }),
    fix: (id) => dfetch("/api/fix/" + id + "?simulate=true", { method: "POST" }),
    debug: (body) => dfetch("/api/debug", { method: "POST", body: JSON.stringify(body) }),
    seed: () => dfetch("/api/seed", { method: "POST" }),
    clearAll: () => dfetch("/api/diagnoses", { method: "DELETE" }),
    traces: () => dfetch("/api/traces"),
    sessions: () => dfetch("/api/sessions"),
    obsStats: () => dfetch("/api/observability/stats"),
    playground: (body) => dfetch("/api/playground", { method: "POST", body: JSON.stringify(body) }),
    logout: () => dfetch("/api/auth/logout", { method: "POST" }),
  };

  const fmtMs = (ms) => (ms >= 1000 ? (ms / 1000).toFixed(2) + "s" : Math.round(ms) + "ms");
  const fmtCost = (c) => "$" + (c || 0).toFixed(4);
  const fmtTokens = (n) => n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n || 0);

  function timeAgo(iso) {
    if (!iso) return "";
    const d = new Date(iso), now = Date.now(), diff = now - d.getTime();
    if (diff < 60000) return "just now";
    if (diff < 3600000) return Math.floor(diff / 60000) + "m ago";
    if (diff < 86400000) return Math.floor(diff / 3600000) + "h ago";
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  }

  function copyToClipboard(text, cb) {
    navigator.clipboard?.writeText(text).then(() => cb && cb()).catch(() => {});
  }

  // ── Toast system ──────────────────────────────────────────────────────────
  const _toastListeners = [];
  function addToastListener(fn) { _toastListeners.push(fn); }
  function removeToastListener(fn) { const i = _toastListeners.indexOf(fn); if (i > -1) _toastListeners.splice(i, 1); }
  function toast(msg, type = "success") { _toastListeners.forEach(fn => fn({ msg, type, id: Date.now() })); }

  function ToastContainer() {
    const [toasts, setToasts] = useState([]);
    useEffect(() => {
      const fn = (t) => {
        setToasts(ts => [...ts, t]);
        setTimeout(() => setToasts(ts => ts.filter(x => x.id !== t.id)), 3500);
      };
      addToastListener(fn);
      return () => removeToastListener(fn);
    }, []);
    if (!toasts.length) return null;
    return (
      <div className="toast-rack" role="status" aria-live="polite">
        {toasts.map(t => (
          <div key={t.id} className={"toast toast--" + t.type}>
            <span className="toast__dot" aria-hidden="true" />
            {t.msg}
          </div>
        ))}
      </div>
    );
  }

  // ── Sparkline ─────────────────────────────────────────────────────────────
  function Sparkline({ values, label, color }) {
    const v = (values || []).filter(x => typeof x === "number" && isFinite(x));
    if (v.length < 2) return null;
    const W = 120, H = 28, max = Math.max(...v), min = Math.min(...v);
    const span = max - min || 1;
    const pts = v.map((y, i) => `${(i / (v.length - 1)) * W},${H - ((y - min) / span) * (H - 4) - 2}`).join(" ");
    return (
      <div className="spark">
        <div className="spark__label">{label}</div>
        <svg className="spark__svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
          <polyline points={pts} fill="none" stroke={color || "var(--amber-base)"} strokeWidth="1.5" />
        </svg>
      </div>
    );
  }

  // ── Failure breakdown chart (horizontal bars SVG) ─────────────────────────
  const FAILURE_COLORS = {
    retrieval_failure: "var(--critical-base)",
    hallucination: "var(--critical-bright)",
    context_overflow: "var(--warn-base)",
    entity_gap: "var(--amber-300)",
    prompt_brittleness: "var(--trace-base)",
    healthy: "var(--ok-base)",
  };
  const FAILURE_LABELS = {
    retrieval_failure: "Retrieval", hallucination: "Hallucination",
    context_overflow: "Overflow", entity_gap: "Entity gap",
    prompt_brittleness: "Brittleness", healthy: "Healthy",
  };
  const FAILURE_ORDER = ["retrieval_failure", "hallucination", "context_overflow", "entity_gap", "prompt_brittleness", "healthy"];

  function FailureChart({ byFailure, total }) {
    if (!byFailure || total === 0) return null;
    const entries = FAILURE_ORDER.filter(k => byFailure[k]).map(k => ({ key: k, count: byFailure[k] }));
    if (!entries.length) return null;
    const max = Math.max(...entries.map(e => e.count));
    return (
      <div className="failure-chart" aria-label="Failure breakdown chart">
        {entries.map(({ key, count }) => (
          <div key={key} className="failure-chart__row">
            <span className="failure-chart__label">{FAILURE_LABELS[key] || key}</span>
            <div className="failure-chart__bar-wrap">
              <div className="failure-chart__bar"
                style={{ width: `${(count / max) * 100}%`, background: FAILURE_COLORS[key] || "var(--text-tertiary)" }}
                aria-label={`${count} ${key}`} />
            </div>
            <span className="failure-chart__count">{count}</span>
          </div>
        ))}
      </div>
    );
  }

  // ── Stat card ─────────────────────────────────────────────────────────────
  function StatCard({ value, label, accent }) {
    return (
      <div className={"stat-card" + (accent ? " stat-card--" + accent : "")}>
        <div className="stat-card__val">{value}</div>
        <div className="stat-card__label">{label}</div>
      </div>
    );
  }

  // ── Metrics strip ─────────────────────────────────────────────────────────
  function ObsMetrics({ stats, obsStats, traces }) {
    if (!stats && !obsStats) return null;
    const failPct = stats && stats.total ? Math.round((stats.failing / stats.total) * 100) : 0;
    const failAccent = failPct > 20 ? "fail" : failPct > 5 ? "warn" : "ok";
    const chrono = [...(traces || [])].reverse();
    return (
      <div style={{ marginBottom: "var(--space-5)" }}>
        <div className="stat-row">
          {stats && <StatCard value={stats.total} label="Diagnoses" />}
          {stats && <StatCard value={failPct + "%"} label="Failing" accent={failAccent} />}
          {obsStats && <StatCard value={fmtMs(obsStats.latency_p50_ms)} label="Latency p50" />}
          {obsStats && <StatCard value={fmtCost(obsStats.cost_usd)} label="Est. cost" />}
        </div>
        {chrono.length > 1 && (
          <div className="spark-row">
            <Sparkline values={chrono.map(t => t.duration_ms || 0)} label="latency / trace" color="var(--trace-base)" />
            <Sparkline values={chrono.map(t => t.total_tokens || 0)} label="tokens / trace" color="var(--amber-base)" />
          </div>
        )}
      </div>
    );
  }

  // ── Fix report panel ───────────────────────────────────────────────────────
  const VERDICT_VARIANT = { verified: "ok", mitigated: "warn", escalated: "trace", failed: "critical", pending_rerun: "neutral" };

  function FixPanel({ report }) {
    if (!report || report.verdict === "none") {
      const msg = (report && report.error) || "No fix agent handles this diagnosis.";
      return <div className="fix fix--none">{msg}</div>;
    }
    const c = report.candidate || {};
    const before = report.before_confidence;
    const after = report.after_diagnosis;
    const afterLabel = after ? (after.healthy ? "healthy" : (after.primary && after.primary.failure) || "—") : null;
    return (
      <div className="fix" data-verdict={report.verdict}>
        <div className="fix__head">
          <Badge variant={VERDICT_VARIANT[report.verdict] || "neutral"} dot solid>
            {report.verdict.replace(/_/g, " ")}
          </Badge>
          <span className="fix__agent">{report.agent}</span>
          {report.rerun_mode && <span className="fix__mode">rerun: {report.rerun_mode}</span>}
        </div>
        <div className="fix__strategy">{c.strategy}</div>
        {report.diff && <CodeBlock filename="fix.diff" language="diff" showLineNumbers={false} code={report.diff} />}
        {report.tests_total > 0 && (
          <div className="fix__tests">
            <div className="fix__tests-head">Regression suite · <b>{report.tests_passed}/{report.tests_total}</b> passed</div>
            {report.test_results.map((t, i) => (
              <div className="fix-test" data-pass={t.passed} key={i}>
                <span className="fix-test__dot" />
                <span className="fix-test__cat">{t.category}</span>
                <span className="fix-test__in">{t.input}</span>
                {t.runs > 1 && <span className="fix-test__runs">×{t.runs}</span>}
              </div>
            ))}
          </div>
        )}
        {report.reverified && (
          <div className="fix__verify">
            Re-diagnosis: <b>{report.failure}</b> ({before != null ? Math.round(before * 100) : "—"}%)
            <span className="arr"> → </span>
            <b>{afterLabel}</b> · {report.reverified_cleared ? "cleared" : "still detected"}
          </div>
        )}
        {report.after_output && (
          <div className="fix__after">
            <div className="fix__after-label">Corrected response (regenerated with the fix)</div>
            <div className="fix__after-body">{report.after_output}</div>
          </div>
        )}
        {c.notes && <div className="fix__notes">▸ {c.notes}</div>}
      </div>
    );
  }

  // ── Diagnosis card ─────────────────────────────────────────────────────────
  function DiagCard({ rec, initialFix = null }) {
    const [open, setOpen] = useState(false);
    const [fix, setFix] = useState(initialFix);
    const [fixBusy, setFixBusy] = useState(false);
    const [copied, setCopied] = useState(false);
    const ui = rec.ui;

    const proposeFix = async () => {
      if (fix) { setFix(null); return; }
      setFixBusy(true);
      try {
        const r = await api.fix(rec.id);
        const fr = r && r.detail ? { verdict: "none", error: r.detail } : r;
        setFix(fr);
        try { fr && window.debugaiTrack && window.debugaiTrack("fix_proposed", { agent: fr.agent, verdict: fr.verdict }); } catch(_) {}
      } catch (e) { setFix({ verdict: "none", error: "Fix request failed." }); }
      finally { setFixBusy(false); }
    };

    const copyId = () => {
      copyToClipboard(rec.id, () => { setCopied(true); setTimeout(() => setCopied(false), 1200); });
    };

    const sevVariant = ui.severity === "ok" ? "ok" : ui.severity === "warn" ? "warn" : "critical";
    const secondary = (ui.secondary || []).map((s, i) => (
      <Badge key={i} variant={s.severity === "warn" ? "warn" : "critical"} dot>
        {s.title} · {Math.round(s.confidence * 100)}%
      </Badge>
    ));

    const code = (rec.issue ? "issue:   " + rec.issue + "\n\n" : "") +
      "prompt:  " + (rec.input.prompt || "") +
      "\noutput:  " + (rec.input.output || "") +
      (rec.input.chunks && rec.input.chunks.length
        ? "\nchunks:  " + rec.input.chunks.map((c, i) => "\n  [" + i + "] " + c).join("") : "");

    const actions = (
      <div className="diag-actions">
        <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", alignItems: "center" }}>
          {secondary.length > 0 ? secondary : <span className="diag-no-secondary">no secondary issues</span>}
        </div>
        <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
          {rec.timestamp && <span className="diag-timestamp">{timeAgo(rec.timestamp)}</span>}
          <button className="diag-copy-id" onClick={copyId}
            aria-label="Copy diagnosis ID" title={copied ? "Copied!" : rec.id}>
            {copied ? "✓" : <svg width="11" height="11" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2"/>
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>}
          </button>
          {ui.id !== "healthy" && (
            <Button variant={fix ? "secondary" : "primary"} size="sm"
              onClick={proposeFix} disabled={fixBusy}>
              {fixBusy ? "Running…" : fix ? "Hide fix" : "Propose fix"}
            </Button>
          )}
          <Button variant="ghost" size="sm" mono onClick={() => setOpen(o => !o)}>
            {open ? "Hide input" : "View input"}
          </Button>
        </div>
      </div>
    );

    return (
      <div>
        <DiagnosticCard severity={sevVariant} id={ui.id} title={ui.title}
          location={ui.explanation} confidence={ui.confidence}
          signals={ui.signals} fix={ui.fix} actions={actions} />
        {open && (
          <div style={{ marginTop: "8px" }}>
            <CodeBlock filename={(rec.label || rec.id) + (rec.input.model_name ? " · " + rec.input.model_name : "")}
              language="request" showLineNumbers={false} code={code} />
          </div>
        )}
        {fix && <FixPanel report={fix} />}
      </div>
    );
  }

  // ── Calibration strip ──────────────────────────────────────────────────────
  const REGIME_COPY = { cold: "using defaults — not enough data yet", warm: "percentile-calibrated to your traffic", hot: "rolling z-score, adapting continuously" };
  function CalibrationStrip({ data }) {
    if (!data) return null;
    const variant = data.regime === "cold" ? "neutral" : data.regime === "warm" ? "trace" : "ok";
    const adapted = (data.signals || []).filter(s => s.adapted);
    const progress = data.next_regime_at ? Math.min(100, Math.round((data.total_requests / data.next_regime_at) * 100)) : 100;
    return (
      <div className="calib">
        <div className="calib__lead">
          <Badge variant={variant} dot solid>{data.regime.toUpperCase()}</Badge>
          <div>
            <div className="calib__title">Adaptive thresholds</div>
            <div className="calib__sub">{REGIME_COPY[data.regime]}</div>
          </div>
          <div className="calib__counts">
            <span><b>{data.total_requests}</b> requests</span>
            <span><b>{data.healthy_baseline}</b> baseline</span>
            {data.next_regime_at && <span className="calib__next">{progress}% → calibrating</span>}
          </div>
        </div>
        {adapted.length > 0 && (
          <div className="calib__chips">
            {adapted.map(s => (
              <div className="calib-chip" key={s.field} title={`mean ${s.baseline_mean} ± ${s.baseline_std} (n=${s.n})`}>
                <span className="calib-chip__name">{s.field.replace(/_/g, " ")}</span>
                <span className="calib-chip__val">
                  <span className="was">{s.default}</span>
                  <span className="arr">→</span>
                  <span className="now">{s.value}</span>
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  // ── Trace waterfall ────────────────────────────────────────────────────────
  function TraceRow({ t }) {
    const [open, setOpen] = useState(false);
    const total = Math.max(1, t.duration_ms || 1);
    const t0 = t.start_ms || (t.spans && t.spans[0] && t.spans[0].start_ms) || 0;
    return (
      <div className="trace" data-status={t.status}>
        <button className="trace__row" onClick={() => setOpen(o => !o)}
          aria-expanded={open} aria-label={"trace " + t.name}>
          <span className="trace__status" data-status={t.status} />
          <span className="trace__name">{t.name}</span>
          {t.session_id && <span className="trace__sess">{t.session_id}</span>}
          <span className="trace__spacer" />
          {(t.scores || []).filter(s => s.name === "failure").map((s, i) => (
            <Badge key={i} variant="critical" dot>{s.value}</Badge>
          ))}
          <span className="trace__metric">{fmtMs(t.duration_ms)}</span>
          <span className="trace__metric">{fmtTokens(t.total_tokens)} tok</span>
          <span className="trace__metric">{fmtCost(t.cost_usd)}</span>
          <span className="trace__chev">{open ? "▾" : "▸"}</span>
        </button>
        {open && (
          <div className="trace__detail">
            <div className="waterfall">
              {(t.spans || []).map((s, i) => {
                const left = total ? ((s.start_ms - t0) / total) * 100 : 0;
                const width = total ? Math.max(2, (s.duration_ms / total) * 100) : 100;
                return (
                  <div className="wf-row" key={i}>
                    <span className="wf-label" data-kind={s.kind}>{s.kind}</span>
                    <div className="wf-track">
                      <div className="wf-bar" data-kind={s.kind}
                        style={{ left: left + "%", width: width + "%" }} />
                    </div>
                    <span className="wf-dur">{fmtMs(s.duration_ms)}</span>
                  </div>
                );
              })}
            </div>
            <div className="trace__scores">
              {(t.scores || []).map((s, i) => (
                <Badge key={i} variant={s.name === "healthy" ? "ok" : s.name === "failure" ? "critical" : "warn"}>
                  {s.name}: {typeof s.value === "number" ? s.value : String(s.value)}
                </Badge>
              ))}
              {t.model && <span className="trace__model">{t.model}</span>}
            </div>
          </div>
        )}
      </div>
    );
  }

  function TraceList({ traces }) {
    // Group by session_id
    const groups = {};
    (traces || []).forEach(t => {
      const key = t.session_id || "(no session)";
      if (!groups[key]) groups[key] = [];
      groups[key].push(t);
    });
    if (!Object.keys(groups).length) return <div className="empty"><p>No traces yet.</p></div>;
    return (
      <div className="trace-list">
        {Object.entries(groups).map(([sid, ts]) => {
          const failing = ts.filter(t => t.status === "failing").length;
          return (
            <details key={sid} className="trace-group" open>
              <summary className="trace-group__header">
                <span className="trace-group__id">{sid}</span>
                <span className="trace-group__meta">{ts.length} traces</span>
                {failing > 0 && <Badge variant="critical" dot>{failing} failing</Badge>}
              </summary>
              {ts.map(t => <TraceRow key={t.id} t={t} />)}
            </details>
          );
        })}
      </div>
    );
  }

  function SessionList({ sessions }) {
    if (!sessions.length) return <div className="empty"><p>No sessions yet.</p></div>;
    return (
      <div className="trace-list">
        {sessions.map((s, i) => (
          <div className={"session-row" + (s.failing > 0 ? " session-row--fail" : " session-row--ok")} key={i}>
            <span className="trace__name" style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-sm)" }}>{s.session_id}</span>
            <span className="trace__spacer" />
            <span className="trace__metric">{s.traces} traces</span>
            {s.failing > 0 && <Badge variant="critical" dot>{s.failing} failing</Badge>}
            <span className="trace__metric">{fmtTokens(s.total_tokens)} tok</span>
            <span className="trace__metric">{fmtCost(s.cost_usd)}</span>
          </div>
        ))}
      </div>
    );
  }

  // ── Debug-a-bug workbench (Simple / Advanced tabs + live preview) ──────────
  const DEBUG_EXAMPLE = {
    issue: "Retrieval worked but my chatbot still answers from outside the context, inventing guarantees.",
    system_prompt: "You are a helpful customer support assistant.",
    prompt: "What is the refund policy for opened electronics?",
    output: "Opened electronics can be returned within 90 days for a full cash refund, and Galaxy-brand items get a special 1-year no-questions guarantee.",
    chunks: "Returns: most items may be returned within 30 days with a receipt.\nSoftware and electronics follow the standard 30-day return window when unopened.",
    similarity_scores: "0.71, 0.66",
    temperature: "0.7",
    context_window: "",
  };

  function buildBody(f, extra) {
    return {
      issue: f.issue || null,
      system_prompt: f.system_prompt || "",
      prompt: f.prompt,
      output: f.output,
      chunks: f.chunks ? f.chunks.split("\n").filter(Boolean) : null,
      similarity_scores: f.similarity_scores
        ? f.similarity_scores.split(",").map(x => parseFloat(x.trim())).filter(x => !isNaN(x))
        : null,
      temperature: f.temperature ? parseFloat(f.temperature) : null,
      context_window: f.context_window ? parseInt(f.context_window) : null,
      ...extra,
    };
  }

  function DebugPanel({ onResult, onDone }) {
    const blank = { issue: "", system_prompt: "", prompt: "", output: "", chunks: "", similarity_scores: "", temperature: "0.2", context_window: "" };
    const [f, setF] = useState(blank);
    const [tab, setTab] = useState("simple"); // simple | advanced
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    const [preview, setPreview] = useState(null); // live playground result
    const previewTimer = useRef(null);
    const set = k => e => setF(p => ({ ...p, [k]: e.target.value }));

    // Live preview via /api/playground (non-storing, debounced)
    useEffect(() => {
      if (!f.prompt || !f.output) { setPreview(null); return; }
      clearTimeout(previewTimer.current);
      previewTimer.current = setTimeout(async () => {
        try {
          const r = await api.playground(buildBody(f, {}));
          if (!r.detail) setPreview(r);
        } catch (_) {}
      }, 500);
      return () => clearTimeout(previewTimer.current);
    }, [f.prompt, f.output, f.chunks, f.similarity_scores]);

    const submit = async () => {
      setBusy(true); setError(null);
      try {
        const res = await api.debug(buildBody(f, { label: "debug", run_fix: true, simulate: true }));
        if (res && res.detail) throw new Error(res.detail);
        onResult(res);
        onDone();
        toast("Diagnosis saved.");
        try { const p = (res.record?.diagnosis?.primary); window.debugaiTrack && window.debugaiTrack("diagnosis_run", { failure: p?.failure || "healthy", has_system_prompt: !!f.system_prompt, source: "debug_workbench" }); } catch(_) {}
      } catch (e) { setError("Could not run diagnosis — check the inputs and try again."); }
      finally { setBusy(false); }
    };

    const canSubmit = f.prompt && f.output;

    return (
      <div className="debug-panel">
        <div className="debug-panel__left">
          <div className="debug-tabs" role="tablist">
            <button role="tab" aria-selected={tab === "simple"} className={"debug-tab" + (tab === "simple" ? " active" : "")} onClick={() => setTab("simple")}>Simple</button>
            <button role="tab" aria-selected={tab === "advanced"} className={"debug-tab" + (tab === "advanced" ? " active" : "")} onClick={() => setTab("advanced")}>Advanced</button>
          </div>

          {tab === "advanced" && (
            <div className="field">
              <label>Describe the issue</label>
              <textarea rows="2" value={f.issue} onChange={set("issue")}
                placeholder="e.g. My chatbot answers from outside the retrieved context / invents facts." />
            </div>
          )}
          {tab === "advanced" && (
            <div className="field">
              <label>System prompt</label>
              <textarea rows="2" value={f.system_prompt} onChange={set("system_prompt")}
                placeholder="You are a helpful assistant…" />
            </div>
          )}

          <div className="run-grid">
            <div className="field">
              <label>User prompt / query</label>
              <textarea rows="3" value={f.prompt} onChange={set("prompt")}
                placeholder="What is the refund policy?" />
            </div>
            <div className="field">
              <label>LLM output (the bad answer)</label>
              <textarea rows="3" value={f.output} onChange={set("output")}
                placeholder="Electronics can be returned within 90 days…" />
            </div>
          </div>

          {tab === "advanced" && (
            <>
              <div className="field">
                <label>Retrieved chunks (one per line)</label>
                <textarea rows="3" value={f.chunks} onChange={set("chunks")}
                  placeholder={"Returns: within 30 days.\nStore hours 9 to 5."} />
              </div>
              <div className="run-grid">
                <div className="field">
                  <label>Similarity scores (comma-sep)</label>
                  <input value={f.similarity_scores} onChange={set("similarity_scores")} placeholder="0.71, 0.66" />
                </div>
                <div className="field">
                  <label>Temperature · context window</label>
                  <div style={{ display: "flex", gap: "8px" }}>
                    <input value={f.temperature} onChange={set("temperature")} placeholder="0.7" style={{ flex: 1 }} />
                    <input value={f.context_window} onChange={set("context_window")} placeholder="window" style={{ flex: 1 }} />
                  </div>
                </div>
              </div>
            </>
          )}

          <div className="run-actions">
            <Button variant="primary" onClick={submit} disabled={busy || !canSubmit}>
              {busy ? "Running…" : "Run & Save"}
            </Button>
            <button className="link-btn" onClick={() => setF(DEBUG_EXAMPLE)}>load example</button>
            <span className="hint">Detection is deterministic. Run & Save stores the diagnosis and runs a fix agent.</span>
          </div>
          {error && <div className="error-banner">{error}</div>}
        </div>

        {/* Live preview pane */}
        <div className="debug-panel__right">
          <div className="debug-preview__label">Live preview <span className="hint">(updates as you type, not saved)</span></div>
          {preview && preview.ui ? (
            <div>
              <div className={"debug-preview__badge badge badge--" + (preview.ui.severity === "ok" ? "ok" : preview.ui.severity === "warn" ? "warn" : "critical")}>
                {preview.ui.id} · {preview.ui.confidence != null ? Math.round(preview.ui.confidence * 100) + "%" : ""}
              </div>
              <div className="debug-preview__explanation">{preview.ui.explanation}</div>
              <div className="debug-preview__signals">
                {(preview.ui.signals || []).slice(0, 4).map((s, i) => (
                  <div key={i} className="debug-signal-row">
                    <span className="debug-signal-name">{s.name}</span>
                    <div className="debug-signal-bar">
                      <div className="debug-signal-fill" data-status={s.status}
                        style={{ width: (s.confidence * 100) + "%" }} />
                    </div>
                    <span className={"debug-signal-val" + (s.status === "critical" ? " is-critical" : "")}>{s.value}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="debug-preview__empty">
              {f.prompt && f.output ? <><span className="hint">Analyzing…</span></> : <span className="hint">Start typing to see a live diagnosis.</span>}
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── Confirmation dialog ────────────────────────────────────────────────────
  function ConfirmDialog({ msg, confirmLabel, onConfirm, onCancel, dangerous }) {
    return (
      <div className="confirm-overlay" role="dialog" aria-modal="true" aria-label={msg}>
        <div className="confirm-box">
          <p className="confirm-msg">{msg}</p>
          <div className="confirm-actions">
            <button className={"confirm-ok" + (dangerous ? " confirm-ok--danger" : "")} onClick={onConfirm}>{confirmLabel}</button>
            <button className="confirm-cancel" onClick={onCancel}>Keep them</button>
          </div>
        </div>
      </div>
    );
  }

  // ── Workspace switcher ────────────────────────────────────────────────────
  function WorkspaceSwitcher({ workspace, onSwitch }) {
    const [open, setOpen] = useState(false);
    if (!workspace || !workspace.orgs || workspace.orgs.length === 0) return null;
    const active = workspace.active_org_id
      ? workspace.orgs.find(o => o.id === workspace.active_org_id)
      : null;
    const label = active ? active.name : "Personal";

    async function switchTo(orgId) {
      setOpen(false);
      try {
        await dfetch("/api/user/workspace", { method: "PATCH",
          body: JSON.stringify({ org_id: orgId }) });
        onSwitch();
        window.location.reload();
      } catch (_) {}
    }

    return (
      <div className="ws-switcher">
        <button className="ws-switcher__btn" onClick={() => setOpen(o => !o)}
          type="button" aria-expanded={open} aria-haspopup="listbox">
          <span className="ws-switcher__label">{label}</span>
          <span className="ws-switcher__chevron">▾</span>
        </button>
        {open && (
          <div className="ws-switcher__menu" role="listbox">
            <button className={"ws-switcher__item" + (!workspace.active_org_id ? " active" : "")}
              type="button" onClick={() => switchTo(null)}>
              Personal workspace
            </button>
            {workspace.orgs.map(o => (
              <button key={o.id} type="button"
                className={"ws-switcher__item" + (workspace.active_org_id === o.id ? " active" : "")}
                onClick={() => switchTo(o.id)}>
                {o.name}
                <span className="ws-switcher__role">{o.role}</span>
              </button>
            ))}
            <div className="ws-switcher__divider" />
            <a href="/account" className="ws-switcher__item ws-switcher__item--link">
              Manage organisations ↗
            </a>
          </div>
        )}
      </div>
    );
  }

  // ── App ────────────────────────────────────────────────────────────────────
  function App() {
    const [user, setUser] = useState(null);
    const [stats, setStats] = useState({ total: 0, failing: 0, healthy: 0, by_failure: {} });
    const [workspace, setWorkspace] = useState({ active_org_id: null, orgs: [] });
    const [thresholds, setThresholds] = useState(null);
    const [items, setItems] = useState([]);
    const [filter, setFilter] = useState(null);
    const [query, setQuery] = useState("");
    const [view, setView] = useState("diagnoses");
    const [traces, setTraces] = useState([]);
    const [sessions, setSessions] = useState([]);
    const [obsStats, setObsStats] = useState(null);
    const [showRun, setShowRun] = useState(false);
    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState(null);
    const [seeding, setSeeding] = useState(false);
    const [confirmClear, setConfirmClear] = useState(false);

    // Fetch user identity + workspace on mount
    useEffect(() => {
      api.me().then(u => {
        setUser(u);
        try { window.debugaiIdentify && window.debugaiIdentify(u.id, { email: u.email, name: u.name }); } catch(_) {}
      }).catch(() => { window.location.href = "/login"; });
      dfetch("/api/user/workspace").then(setWorkspace).catch(() => {});
    }, []);

    const refresh = useCallback(async () => {
      try {
        const [s, t, l, tr, se, os] = await Promise.all([
          api.stats(), api.thresholds(), api.list(filter, query),
          api.traces(), api.sessions(), api.obsStats(),
        ]);
        setStats(s); setThresholds(t); setItems(l.items);
        setTraces(tr.items); setSessions(se.items); setObsStats(os);
        setLoadError(null);
      } catch (e) {
        if (e.code !== 401) setLoadError("Couldn't reach the DebugAI server. Is it running?");
      } finally { setLoading(false); }
    }, [filter, query]);

    useEffect(() => { refresh(); }, [refresh]);

    async function loadSampleData() {
      setSeeding(true);
      try { await api.seed(); await refresh(); toast("Sample data loaded."); }
      catch (_) { toast("Failed to load sample data.", "error"); }
      finally { setSeeding(false); }
    }

    async function clearAll() {
      setConfirmClear(false);
      try { await api.clearAll(); await refresh(); toast("All diagnoses deleted."); }
      catch (_) { toast("Failed to delete diagnoses.", "error"); }
    }

    async function logout() {
      await api.logout();
      window.location.href = "/";
    }

    const Filter = ({ id, label }) => {
      const count = id ? stats.by_failure[id] || 0 : stats.total;
      return (
        <button className="filter-btn" data-active={filter === id}
          onClick={() => setFilter(id)} type="button">
          {label}<span className="count">{count}</span>
        </button>
      );
    };

    const isEmptyDiagnoses = !loading && items.length === 0 && view === "diagnoses";

    return (
      <div className="shell">
        <ToastContainer />
        {confirmClear && (
          <ConfirmDialog
            msg={`Delete all ${stats.total} diagnoses? This can't be undone.`}
            confirmLabel="Delete all"
            dangerous
            onConfirm={clearAll}
            onCancel={() => setConfirmClear(false)}
          />
        )}

        {/* Header */}
        <div className="dash-head">
          <a className="dash-brand" href="/" aria-label="DebugAI home">
            <div className="dash-logo">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 12h4l3 8 4-16 3 8h4" />
              </svg>
            </div>
            <div>
              <div className="dash-title">
                DebugAI <span className="dash-title__suffix">/ dashboard</span>
              </div>
              <div className="dash-sub">signal → diagnosis → fix · live request feed</div>
            </div>
          </a>
          <div className="dash-nav">
            <WorkspaceSwitcher workspace={workspace} onSwitch={() => {}} />
            {["diagnoses", "traces", "sessions"].map(v => (
              <button key={v} className="view-tab" data-active={view === v} onClick={() => setView(v)} type="button">{v}</button>
            ))}
            <a className="view-tab" href="/playground">playground ↗</a>
            <a className="view-tab" href="/account" title="Account settings">account ↗</a>
            {user && <span className="dash-user">{user.name}</span>}
            <button className="view-tab" onClick={logout} title="Log out" type="button" aria-label="Log out">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
            </button>
          </div>
        </div>

        {/* Toolbar */}
        <div className="dash-toolbar">
          {view === "diagnoses" ? (
            <>
              <Filter id={null} label="all" />
              {FAILURE_ORDER.map(id => <Filter key={id} id={id} label={FAILURE_LABELS[id]} />)}
              <input className="dash-search" type="search" value={query}
                placeholder="search…" onChange={e => setQuery(e.target.value)}
                aria-label="Search diagnoses" />
              {items.length > 0 && (
                <button className="link-btn link-btn--danger" onClick={() => setConfirmClear(true)} type="button">
                  Clear all
                </button>
              )}
            </>
          ) : (
            <span className="dash-sub" style={{ fontFamily: "var(--font-mono)" }}>
              {view === "traces" ? "request traces · spans · scores" : "grouped conversations"}
            </span>
          )}
          <span className="spacer" />
          <Button variant={showRun ? "secondary" : "primary"} size="sm"
            onClick={() => setShowRun(v => !v)}>
            {showRun ? "Close" : "+ Debug a bug"}
          </Button>
        </div>

        {/* Metrics */}
        {view === "diagnoses"
          ? <CalibrationStrip data={thresholds} />
          : <ObsMetrics stats={stats} obsStats={obsStats} traces={traces} />}

        {/* Debug workbench */}
        {showRun && <DebugPanel onResult={setResult} onDone={refresh} />}

        {/* Debug result band */}
        {result && result.record && (
          <div className="debug-result">
            <div className="debug-result__label">
              Diagnosed &amp; saved
              <button className="link-btn" onClick={() => setResult(null)} type="button">dismiss</button>
            </div>
            <div className="diag-grid">
              <DiagCard rec={result.record} initialFix={result.fix} />
            </div>
          </div>
        )}

        {/* Error banner */}
        {loadError && (
          <div className="error-banner">
            {loadError}
            <button className="link-btn" onClick={refresh} type="button">retry</button>
          </div>
        )}

        {/* Main content */}
        {loading ? (
          <div className="loading-state">
            <div className="loading-dots" aria-label="Loading"><span/><span/><span/></div>
          </div>
        ) : view === "traces" ? (
          <TraceList traces={traces} />
        ) : view === "sessions" ? (
          <SessionList sessions={sessions} />
        ) : isEmptyDiagnoses ? (
          <div className="empty-state">
            <svg className="empty-state__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="1.5" width="40" height="40" aria-hidden="true">
              <path d="M3 12h4l3 8 4-16 3 8h4"/>
            </svg>
            <h3>No diagnoses yet</h3>
            <p>Paste a failing LLM call into "+ Debug a bug" to get a ranked diagnosis and a specific fix.</p>
            <div style={{ display: "flex", gap: "12px", justifyContent: "center", flexWrap: "wrap" }}>
              <Button variant="primary" size="sm" onClick={() => setShowRun(true)}>+ Debug a bug</Button>
              <Button variant="secondary" size="sm" onClick={loadSampleData} disabled={seeding}>
                {seeding ? "Loading…" : "Load sample data"}
              </Button>
            </div>
          </div>
        ) : (
          <>
            {view === "diagnoses" && stats.total > 0 && (
              <>
                <ObsMetrics stats={stats} obsStats={null} traces={[]} />
                <FailureChart byFailure={stats.by_failure} total={stats.total} />
              </>
            )}
            <div className="diag-grid">
              {items.map(rec => <DiagCard key={rec.id} rec={rec} />)}
            </div>
          </>
        )}
      </div>
    );
  }

  ReactDOM.createRoot(document.getElementById("root")).render(<App />);
})();
