/* DebugAI playground — live-edit a case and watch the diagnosis update. */
(function () {
  const DS = window.DesignSystem_90c6f1;
  if (!DS) {
    document.getElementById("root").innerHTML =
      '<div class="boot">Design system failed to load.</div>';
    return;
  }
  const { Button, Badge, DiagnosticCard, CodeBlock } = DS;
  const { useState, useEffect, useRef, useCallback } = React;

  const SEV = { critical: "critical", warning: "warn", warn: "warn", ok: "ok" };
  const VERDICT_VARIANT = { verified: "ok", mitigated: "warn", escalated: "trace", failed: "critical" };

  const EXAMPLE = {
    system_prompt: "You are a helpful customer support assistant.",
    prompt: "What is the refund policy for opened electronics?",
    output: "Opened electronics can be returned within 90 days for a full cash refund, and Galaxy-brand items get a special 1-year no-questions guarantee.",
    chunks: "Returns: most items may be returned within 30 days with a receipt.\nSoftware and electronics follow the standard 30-day return window when unopened.",
    similarity_scores: "0.71, 0.66",
    temperature: "0.7",
    context_window: "",
  };

  function App() {
    const [f, setF] = useState(EXAMPLE);
    const [res, setRes] = useState(null);
    const [busy, setBusy] = useState(false);
    const [err, setErr] = useState(null);
    const timer = useRef(null);
    const set = (k) => (e) => setF((prev) => ({ ...prev, [k]: e.target.value }));

    const analyze = useCallback(async () => {
      if (!f.prompt || !f.output) return;
      setBusy(true);
      const body = {
        system_prompt: f.system_prompt || "",
        prompt: f.prompt,
        output: f.output,
        chunks: f.chunks ? f.chunks.split("\n").filter(Boolean) : null,
        similarity_scores: f.similarity_scores
          ? f.similarity_scores.split(",").map((x) => parseFloat(x.trim())).filter((x) => !isNaN(x))
          : null,
        temperature: f.temperature ? parseFloat(f.temperature) : null,
        context_window: f.context_window ? parseInt(f.context_window) : null,
        run_fix: true, simulate: true,
      };
      try {
        const resp = await fetch("/api/playground", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (resp.status === 401) { window.location.href = "/login"; return; }
        const r = await resp.json();
        if (r && r.detail) { setErr("Couldn't analyze — check the inputs."); return; }
        setRes(r); setErr(null);
      } catch (e) {
        setErr("Couldn't reach the server.");
      } finally { setBusy(false); }
    }, [f]);

    // Debounced auto-analyze as you type.
    useEffect(() => {
      clearTimeout(timer.current);
      timer.current = setTimeout(analyze, 600);
      return () => clearTimeout(timer.current);
    }, [analyze]);

    const applyFix = () => {
      const add = res && res.fix && res.fix.candidate && res.fix.candidate.system_prompt_additions;
      if (add) setF((prev) => ({ ...prev, system_prompt: (prev.system_prompt + "\n\n" + add).trim() }));
    };

    const ui = res && res.ui;
    const fix = res && res.fix;

    return (
      <div className="shell pg">
        <div className="dash-head">
          <a className="dash-brand" href="/dashboard" style={{ textDecoration: "none", color: "inherit" }}>
            <div className="dash-logo">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12h4l3 8 4-16 3 8h4" /></svg>
            </div>
            <div>
              <div className="dash-title">Playground</div>
              <div className="dash-sub">← dashboard · edit a case, watch the diagnosis update live</div>
            </div>
          </a>
          <Button variant="ghost" size="sm" onClick={() => setF(EXAMPLE)}>reset example</Button>
        </div>

        <div className="pg-layout">
          {/* editor */}
          <div className="pg-editor">
            <div className="field"><label>System prompt</label>
              <textarea rows="3" value={f.system_prompt} onChange={set("system_prompt")} /></div>
            <div className="field"><label>User prompt / query</label>
              <textarea rows="2" value={f.prompt} onChange={set("prompt")} /></div>
            <div className="field"><label>LLM output (edit to see the diagnosis change)</label>
              <textarea rows="4" value={f.output} onChange={set("output")} /></div>
            <div className="field"><label>Retrieved chunks (one per line)</label>
              <textarea rows="4" value={f.chunks} onChange={set("chunks")} /></div>
            <div className="run-grid">
              <div className="field"><label>Similarity scores</label>
                <input value={f.similarity_scores} onChange={set("similarity_scores")} /></div>
              <div className="field"><label>Temperature · context window</label>
                <div style={{ display: "flex", gap: "8px" }}>
                  <input value={f.temperature} onChange={set("temperature")} style={{ flex: 1 }} />
                  <input value={f.context_window} onChange={set("context_window")} placeholder="window" style={{ flex: 1 }} />
                </div></div>
            </div>
            <div className="run-actions">
              <Button variant="primary" onClick={analyze} disabled={busy}>{busy ? "Analyzing…" : "Analyze"}</Button>
              <span className="hint">Auto-analyzes as you type.</span>
            </div>
          </div>

          {/* live result */}
          <div className="pg-result">
            {err && <div className="error-banner">{err}</div>}
            {!ui ? (
              <div className="empty">Edit the case to see a live diagnosis.</div>
            ) : (
              <>
                <DiagnosticCard
                  severity={SEV[ui.severity] || "warn"}
                  id={ui.id}
                  title={ui.title}
                  location={ui.explanation}
                  confidence={ui.confidence}
                  signals={ui.signals}
                  fix={null}
                />
                {fix && (
                  <div className="fix" data-verdict={fix.verdict} style={{ marginTop: "12px" }}>
                    <div className="fix__head">
                      <Badge variant={VERDICT_VARIANT[fix.verdict] || "neutral"} dot solid>{fix.verdict}</Badge>
                      <span className="fix__agent">{fix.agent}</span>
                      <span className="fix__mode" style={{ marginLeft: "auto" }}>tests {fix.tests_passed}/{fix.tests_total}</span>
                    </div>
                    <div className="fix__strategy">{fix.candidate.strategy}</div>
                    {fix.diff && <CodeBlock filename="fix.diff" language="diff" showLineNumbers={false} code={fix.diff} />}
                    {fix.candidate.system_prompt_additions && (
                      <Button variant="secondary" size="sm" onClick={applyFix}>↑ apply fix to system prompt</Button>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    );
  }

  ReactDOM.createRoot(document.getElementById("root")).render(<App />);
})();
