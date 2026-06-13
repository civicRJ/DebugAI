/* DebugAI dashboard — renders live diagnoses with the design system. */
(function () {
  const DS = window.DesignSystem_90c6f1;
  if (!DS) {
    document.getElementById("root").innerHTML =
      '<div class="boot">Design system bundle failed to load (/ds/_ds_bundle.js).</div>';
    return;
  }
  const { Button, Badge, CodeBlock, DiagnosticCard } = DS;
  const { useState, useEffect, useCallback } = React;

  // Build the /api/debug|playground body from the workbench form fields.
  function buildBody(f, extra) {
    return {
      issue: f.issue || null,
      system_prompt: f.system_prompt || "",
      prompt: f.prompt,
      output: f.output,
      chunks: f.chunks ? f.chunks.split("\n").filter(Boolean) : null,
      similarity_scores: f.similarity_scores
        ? f.similarity_scores.split(",").map((x) => parseFloat(x.trim())).filter((x) => !isNaN(x))
        : null,
      temperature: f.temperature ? parseFloat(f.temperature) : null,
      context_window: f.context_window ? parseInt(f.context_window) : null,
      ...extra,
    };
  }

  const FAILURE_ORDER = [
    "retrieval_failure", "hallucination", "context_overflow",
    "entity_gap", "prompt_brittleness", "healthy",
  ];
  const LABELS = {
    retrieval_failure: "Retrieval", hallucination: "Hallucination",
    context_overflow: "Overflow", entity_gap: "Entity gap",
    prompt_brittleness: "Brittleness", healthy: "Healthy",
  };

  // fetch wrapper: same-origin session cookie travels automatically; a 401 means
  // the session expired → bounce to the login page.
  async function dfetch(url, opts = {}) {
    const headers = { ...(opts.headers || {}) };
    if (opts.body) headers["Content-Type"] = "application/json";
    const r = await fetch(url, { ...opts, headers });
    if (r.status === 401) { window.location.href = "/login"; const e = new Error("unauthorized"); e.code = 401; throw e; }
    return r.json();
  }

  const api = {
    stats: () => dfetch("/api/stats"),
    thresholds: () => dfetch("/api/thresholds"),
    fix: (id) => dfetch("/api/fix/" + id + "?simulate=true", { method: "POST" }),
    debug: (body) => dfetch("/api/debug", { method: "POST", body: JSON.stringify(body) }),
    list: (failure, q) => {
      const p = new URLSearchParams();
      if (failure) p.set("failure", failure);
      if (q) p.set("q", q);
      const qs = p.toString();
      return dfetch("/api/diagnoses" + (qs ? "?" + qs : ""));
    },
    analyze: (body) => dfetch("/api/analyze", { method: "POST", body: JSON.stringify(body) }),
    traces: () => dfetch("/api/traces"),
    sessions: () => dfetch("/api/sessions"),
    obsStats: () => dfetch("/api/observability/stats"),
  };

  const fmtMs = (ms) => (ms >= 1000 ? (ms / 1000).toFixed(2) + "s" : Math.round(ms) + "ms");
  const fmtCost = (c) => "$" + (c || 0).toFixed(4);

  // Tiny dependency-free SVG sparkline from an array of numbers.
  function Sparkline({ values, label, color }) {
    const v = (values || []).filter((x) => typeof x === "number" && isFinite(x));
    if (v.length < 2) return null;
    const W = 120, H = 28, max = Math.max(...v), min = Math.min(...v);
    const span = max - min || 1;
    const pts = v.map((y, i) =>
      `${(i / (v.length - 1)) * W},${H - ((y - min) / span) * (H - 4) - 2}`).join(" ");
    return (
      <div className="spark">
        <div className="spark__label">{label}</div>
        <svg className="spark__svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
          <polyline points={pts} fill="none" stroke={color || "var(--amber-base)"} strokeWidth="1.5" />
        </svg>
      </div>
    );
  }

  const REGIME_COPY = {
    cold: "using default thresholds — not enough data to calibrate",
    warm: "percentile-calibrated to your healthy baseline",
    hot: "rolling-window z-score, adapting continuously",
  };

  // --- adaptive calibration strip ------------------------------------------
  function CalibrationStrip({ data }) {
    if (!data) return null;
    const variant = data.regime === "cold" ? "neutral" : data.regime === "warm" ? "trace" : "ok";
    const adapted = (data.signals || []).filter((s) => s.adapted);
    const progress = data.next_regime_at
      ? Math.min(100, Math.round((data.total_requests / data.next_regime_at) * 100))
      : 100;
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
            {adapted.map((s) => (
              <div className="calib-chip" key={s.field} title={"mean " + s.baseline_mean + " ± " + s.baseline_std + " (n=" + s.n + ")"}>
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

  const VERDICT_VARIANT = {
    verified: "ok", mitigated: "warn", escalated: "trace",
    failed: "critical", pending_rerun: "neutral",
  };

  // --- fix-agent report panel ----------------------------------------------
  function FixPanel({ report }) {
    if (!report || report.verdict === "none") {
      const msg = (report && report.error) || "No fix agent handles this diagnosis.";
      return <div className="fix fix--none">{msg}</div>;
    }
    const c = report.candidate || {};
    const before = report.before_confidence;
    const after = report.after_diagnosis;
    const afterLabel = after
      ? (after.healthy ? "healthy" : (after.primary && after.primary.failure) || "—")
      : null;
    return (
      <div className="fix" data-verdict={report.verdict}>
        <div className="fix__head">
          <Badge variant={VERDICT_VARIANT[report.verdict] || "neutral"} dot solid>
            {report.verdict.replace("_", " ")}
          </Badge>
          <span className="fix__agent">{report.agent}</span>
          {report.rerun_mode && <span className="fix__mode">rerun: {report.rerun_mode}</span>}
        </div>
        <div className="fix__strategy">{c.strategy}</div>
        {report.diff && (
          <CodeBlock filename="fix.diff" language="diff" showLineNumbers={false} code={report.diff} />
        )}
        {report.tests_total > 0 && (
          <div className="fix__tests">
            <div className="fix__tests-head">
              Regression suite · <b>{report.tests_passed}/{report.tests_total}</b> passed
            </div>
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

  // --- one diagnosis card ---------------------------------------------------
  function DiagCard({ rec, initialFix = null }) {
    const [open, setOpen] = useState(false);
    const [fix, setFix] = useState(initialFix);
    const [fixBusy, setFixBusy] = useState(false);
    const ui = rec.ui;

    const proposeFix = async () => {
      if (fix) { setFix(null); return; }
      setFixBusy(true);
      try {
        const r = await api.fix(rec.id);
        setFix(r && r.detail ? { verdict: "none", error: r.detail } : r);
      } catch (e) {
        setFix({ verdict: "none", error: "Fix request failed." });
      } finally { setFixBusy(false); }
    };
    const sevVariant = ui.severity === "ok" ? "ok" : ui.severity === "warn" ? "warn" : "critical";

    const secondary = (ui.secondary || []).map((s, i) => (
      <Badge key={i} variant={s.severity === "warn" ? "warn" : "critical"} dot>
        {s.title} · {Math.round(s.confidence * 100)}%
      </Badge>
    ));

    const actions = (
      <div className="diag-meta" style={{ width: "100%", justifyContent: "space-between" }}>
        <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
          {secondary.length > 0 ? secondary : <span>no secondary issues</span>}
        </div>
        <div style={{ display: "flex", gap: "6px" }}>
          {ui.id !== "healthy" && (
            <Button variant={fix ? "secondary" : "primary"} size="sm" onClick={proposeFix} disabled={fixBusy}>
              {fixBusy ? "running…" : fix ? "hide fix" : "Propose fix"}
            </Button>
          )}
          <Button variant="ghost" size="sm" mono onClick={() => setOpen((o) => !o)}>
            {open ? "hide input" : "view input"}
          </Button>
        </div>
      </div>
    );

    const code =
      (rec.issue ? "issue:   " + rec.issue + "\n\n" : "") +
      "prompt:  " + (rec.input.prompt || "") +
      "\noutput:  " + (rec.input.output || "") +
      (rec.input.chunks && rec.input.chunks.length
        ? "\nchunks:  " + rec.input.chunks.map((c, i) => "\n  [" + i + "] " + c).join("")
        : "");

    return (
      <div>
        <DiagnosticCard
          severity={sevVariant}
          id={ui.id}
          title={ui.title}
          location={ui.explanation}
          confidence={ui.confidence}
          signals={ui.signals}
          fix={ui.fix}
          actions={actions}
        />
        {open && (
          <div style={{ marginTop: "8px" }}>
            <CodeBlock
              filename={(rec.label || rec.id) + (rec.input.model_name ? " · " + rec.input.model_name : "")}
              language="request"
              showLineNumbers={false}
              code={code}
            />
          </div>
        )}
        {fix && <FixPanel report={fix} />}
      </div>
    );
  }

  // --- debug-a-bug workbench ------------------------------------------------
  const DEBUG_EXAMPLE = {
    issue: "My support chatbot is answering from outside the retrieved context — it invents policy details that aren't in the docs.",
    system_prompt: "You are a helpful customer support assistant.",
    prompt: "What is the refund policy for opened electronics?",
    output: "Opened electronics can be returned within 90 days for a full cash refund, and Galaxy-brand items get a special 1-year no-questions guarantee.",
    chunks: "Returns: most items may be returned within 30 days with a receipt.\nSoftware and electronics follow the standard 30-day return window when unopened.",
    similarity_scores: "0.71, 0.66",
    temperature: "0.7",
    context_window: "",
  };

  function DebugPanel({ onResult, onDone }) {
    const blank = { issue: "", system_prompt: "", prompt: "", output: "",
                    chunks: "", similarity_scores: "", temperature: "0.2", context_window: "" };
    const [f, setF] = useState(blank);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

    const submit = async () => {
      setBusy(true);
      setError(null);
      try {
        const res = await api.debug(buildBody(f, { label: "debug", run_fix: true, simulate: true }));
        if (res && res.detail) throw new Error(res.detail);
        onResult(res);
        onDone();
      } catch (e) {
        setError("Could not run diagnosis — check the inputs and try again.");
      } finally {
        setBusy(false);
      }
    };

    return (
      <div className="run-panel">
        <div className="field">
          <label>Describe the issue</label>
          <textarea rows="2" value={f.issue} onChange={set("issue")}
            placeholder="e.g. My chatbot answers from outside the retrieved context / invents facts not in the docs." />
        </div>
        <div className="field">
          <label>System prompt</label>
          <textarea rows="2" value={f.system_prompt} onChange={set("system_prompt")}
            placeholder="You are a helpful assistant…" />
        </div>
        <div className="run-grid">
          <div className="field">
            <label>User prompt / query</label>
            <textarea rows="3" value={f.prompt} onChange={set("prompt")}
              placeholder="What is the refund policy for electronics?" />
          </div>
          <div className="field">
            <label>LLM output (the bad answer)</label>
            <textarea rows="3" value={f.output} onChange={set("output")}
              placeholder="Electronics can be returned within 90 days…" />
          </div>
        </div>
        <div className="field">
          <label>Retrieved chunks (one per line)</label>
          <textarea rows="3" value={f.chunks} onChange={set("chunks")}
            placeholder={"Returns: most items may be returned within 30 days with a receipt.\nStore hours are 9 to 5."} />
        </div>
        <div className="run-grid">
          <div className="field">
            <label>Similarity scores (comma-sep, optional)</label>
            <input value={f.similarity_scores} onChange={set("similarity_scores")} placeholder="0.44, 0.31" />
          </div>
          <div className="field">
            <label>Temperature · context window</label>
            <div style={{ display: "flex", gap: "8px" }}>
              <input value={f.temperature} onChange={set("temperature")} placeholder="0.7" style={{ flex: 1 }} />
              <input value={f.context_window} onChange={set("context_window")} placeholder="window" style={{ flex: 1 }} />
            </div>
          </div>
        </div>
        <div className="run-actions">
          <Button variant="primary" onClick={submit} disabled={busy || !f.prompt || !f.output}>
            {busy ? "Diagnosing & fixing…" : "Diagnose & propose fix"}
          </Button>
          <button className="link-btn" onClick={() => setF(DEBUG_EXAMPLE)}>load example</button>
          <span className="hint">Detection is deterministic; the fix agent then proposes & verifies a repair.</span>
        </div>
        {error && <div className="error-banner">{error}</div>}
      </div>
    );
  }

  // --- stat tile ------------------------------------------------------------
  function Stat({ value, label, kind }) {
    return (
      <div className={"stat" + (kind ? " stat--" + kind : "")}>
        <div className="stat__val">{value}</div>
        <div className="stat__label">{label}</div>
      </div>
    );
  }

  // --- observability: metrics strip ----------------------------------------
  function ObsMetrics({ data, traces }) {
    if (!data) return null;
    const tiles = [
      { v: data.traces, l: "traces" },
      { v: data.failing, l: "failing", kind: "fail" },
      { v: data.sessions, l: "sessions" },
      { v: fmtMs(data.latency_p50_ms), l: "p50 latency" },
      { v: fmtMs(data.latency_p95_ms), l: "p95 latency" },
      { v: (data.total_tokens || 0).toLocaleString(), l: "tokens" },
      { v: fmtCost(data.cost_usd), l: "est. cost" },
    ];
    // traces come newest-first → reverse for chronological sparklines.
    const chrono = [...(traces || [])].reverse();
    const latency = chrono.map((t) => t.duration_ms || 0);
    const tokens = chrono.map((t) => t.total_tokens || 0);
    return (
      <div style={{ marginBottom: "var(--space-6)" }}>
        <div className="dash-stats">
          {tiles.map((t, i) => <Stat key={i} value={t.v} label={t.l} kind={t.kind} />)}
        </div>
        <div className="spark-row">
          <Sparkline values={latency} label="latency / trace" color="var(--trace-base)" />
          <Sparkline values={tokens} label="tokens / trace" color="var(--amber-base)" />
        </div>
      </div>
    );
  }

  const SCORE_VARIANT = { healthy: "ok", failure: "critical", confidence: "warn" };

  // --- observability: one trace (row + expandable waterfall) ----------------
  function TraceRow({ t }) {
    const [open, setOpen] = useState(false);
    const total = Math.max(1, t.duration_ms || 1);
    const t0 = t.start_ms || (t.spans[0] && t.spans[0].start_ms) || 0;
    const failBadge = t.status === "failing";
    return (
      <div className="trace" data-status={t.status}>
        <button className="trace__row" onClick={() => setOpen((o) => !o)}
          aria-expanded={open} aria-label={"trace " + t.name}>
          <span className="trace__status" data-status={t.status} />
          <span className="trace__name">{t.name}</span>
          {t.session_id && <span className="trace__sess">{t.session_id}</span>}
          <span className="trace__spacer" />
          {(t.scores || []).filter((s) => s.name === "failure").map((s, i) => (
            <Badge key={i} variant="critical" dot>{s.value}</Badge>
          ))}
          <span className="trace__metric">{fmtMs(t.duration_ms)}</span>
          <span className="trace__metric">{(t.total_tokens || 0).toLocaleString()} tok</span>
          <span className="trace__metric">{fmtCost(t.cost_usd)}</span>
          <span className="trace__chev">{open ? "▾" : "▸"}</span>
        </button>
        {open && (
          <div className="trace__detail">
            <div className="waterfall">
              {t.spans.map((s, i) => {
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
                <Badge key={i} variant={SCORE_VARIANT[s.name] || "trace"}>
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
    if (!traces.length) return <div className="empty">No traces yet.</div>;
    return <div className="trace-list">{traces.map((t) => <TraceRow key={t.id} t={t} />)}</div>;
  }

  // --- observability: sessions ----------------------------------------------
  function SessionList({ sessions }) {
    if (!sessions.length) return <div className="empty">No sessions yet.</div>;
    return (
      <div className="trace-list">
        {sessions.map((s, i) => (
          <div className="session-row" key={i}>
            <span className="trace__name">{s.session_id}</span>
            <span className="trace__spacer" />
            <span className="trace__metric">{s.traces} traces</span>
            {s.failing > 0 && <Badge variant="critical" dot>{s.failing} failing</Badge>}
            <span className="trace__metric">{(s.total_tokens || 0).toLocaleString()} tok</span>
            <span className="trace__metric">{fmtCost(s.cost_usd)}</span>
          </div>
        ))}
      </div>
    );
  }

  // --- app ------------------------------------------------------------------
  function App() {
    const [stats, setStats] = useState({ total: 0, failing: 0, healthy: 0, by_failure: {} });
    const [thresholds, setThresholds] = useState(null);
    const [items, setItems] = useState([]);
    const [filter, setFilter] = useState(null);
    const [query, setQuery] = useState("");
    const [view, setView] = useState("diagnoses");  // diagnoses | traces | sessions
    const [traces, setTraces] = useState([]);
    const [sessions, setSessions] = useState([]);
    const [obsStats, setObsStats] = useState(null);
    const [showRun, setShowRun] = useState(false);
    const [result, setResult] = useState(null);  // latest debug workbench result
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState(null);

    const refresh = useCallback(async () => {
      try {
        const [s, t, l, tr, se, os] = await Promise.all([
          api.stats(), api.thresholds(), api.list(filter, query),
          api.traces(), api.sessions(), api.obsStats(),
        ]);
        setStats(s);
        setThresholds(t);
        setItems(l.items);
        setTraces(tr.items);
        setSessions(se.items);
        setObsStats(os);
        setLoadError(null);
      } catch (e) {
        setLoadError(e.code === 401
          ? "Unauthorized — this server requires an API key."
          : "Couldn't reach the DebugAI server. Is it running?");
      } finally {
        setLoading(false);
      }
    }, [filter, query]);

    useEffect(() => { refresh(); }, [refresh]);

    const Filter = ({ id, label }) => {
      const count = id ? stats.by_failure[id] || 0 : stats.total;
      return (
        <button className="filter-btn" data-active={filter === id}
          onClick={() => setFilter(id)}>
          {label}<span className="count">{count}</span>
        </button>
      );
    };

    return (
      <div className="shell">
        <div className="dash-head">
          <a className="dash-brand" href="/" aria-label="DebugAI home">
            <div className="dash-logo">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 12h4l3 8 4-16 3 8h4" />
              </svg>
            </div>
            <div>
              <div className="dash-title">DebugAI <span style={{ fontSize: "var(--text-2xs)", color: "var(--text-quaternary)", fontFamily: "var(--font-mono)", fontWeight: 400 }}>/ dashboard</span></div>
              <div className="dash-sub">← back to home · signal → diagnosis → fix</div>
            </div>
          </a>
          <div className="dash-nav">
            {["diagnoses", "traces", "sessions"].map((v) => (
              <button key={v} className="view-tab" data-active={view === v}
                onClick={() => setView(v)}>{v}</button>
            ))}
            <a className="view-tab" href="/playground">playground ↗</a>
            <a className="view-tab" href="/account" title="Account">account ↗</a>
            <button className="view-tab" onClick={async () => {
              await fetch("/api/auth/logout", { method: "POST" });
              window.location.href = "/login";
            }}>log out</button>
          </div>
        </div>

        <div className="dash-toolbar">
          {view === "diagnoses" ? (
            <>
              <Filter id={null} label="all" />
              {FAILURE_ORDER.map((id) => <Filter key={id} id={id} label={LABELS[id]} />)}
              <input className="dash-search" type="search" value={query}
                placeholder="search…" onChange={(e) => setQuery(e.target.value)} />
            </>
          ) : (
            <span className="dash-sub" style={{ fontFamily: "var(--font-mono)" }}>
              {view === "traces" ? "request traces · spans · scores" : "grouped conversations"}
            </span>
          )}
          <span className="spacer" />
          <Button variant={showRun ? "secondary" : "primary"} size="sm"
            onClick={() => setShowRun((v) => !v)}>
            {showRun ? "Close" : "+ Debug a bug"}
          </Button>
        </div>

        {view === "diagnoses"
          ? <CalibrationStrip data={thresholds} />
          : <ObsMetrics data={obsStats} traces={traces} />}

        {showRun && <DebugPanel onResult={setResult} onDone={refresh} />}

        {result && result.record && (
          <div className="debug-result">
            <div className="debug-result__label">
              ✓ Diagnosed &amp; fixed — also added to the feed below
              <button className="link-btn" onClick={() => setResult(null)}>dismiss</button>
            </div>
            <div className="diag-grid">
              <DiagCard rec={result.record} initialFix={result.fix} />
            </div>
          </div>
        )}

        {loadError ? (
          <div className="error-banner">
            {loadError}
            <button className="link-btn" onClick={refresh}>retry</button>
          </div>
        ) : loading ? (
          <div className="empty">Loading…</div>
        ) : view === "traces" ? (
          <TraceList traces={traces} />
        ) : view === "sessions" ? (
          <SessionList sessions={sessions} />
        ) : items.length === 0 ? (
          <div className="empty">No diagnoses{filter ? " for this filter" : ""} yet.</div>
        ) : (
          <div className="diag-grid">
            {items.map((rec) => <DiagCard key={rec.id} rec={rec} />)}
          </div>
        )}
      </div>
    );
  }

  ReactDOM.createRoot(document.getElementById("root")).render(<App />);
})();
