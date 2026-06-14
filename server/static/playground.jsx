/* DebugAI playground — live-edit a case and watch the diagnosis update. */
(function () {
  const DS = window.DesignSystem_90c6f1;
  if (!DS) { document.getElementById("root").innerHTML = '<div class="boot">Design system failed to load.</div>'; return; }
  const { Button, Badge, DiagnosticCard, CodeBlock } = DS;
  const { useState, useEffect, useRef } = React;

  const SEV = { critical: "critical", warning: "warn", warn: "warn", ok: "ok" };
  const VERDICT_VARIANT = { verified: "ok", mitigated: "warn", escalated: "trace", failed: "critical" };

  const EXAMPLES = {
    rag_hallucination: {
      label: "RAG hallucination",
      system_prompt: "Answer only from the retrieved context and cite the source.",
      prompt: "What is the refund policy for opened electronics?",
      output: "Opened electronics can be returned within 90 days for a full cash refund, and Galaxy-brand items get a special 1-year no-questions guarantee.",
      chunks: "Returns: most items may be returned within 30 days with a receipt.\nSoftware and electronics follow the standard 30-day return window when unopened.",
      similarity_scores: "0.71, 0.66",
      temperature: "0.7",
      context_window: "",
      response_schema: "",
      tools_expected: "",
      tool_calls: "",
    },
    schema_violation: {
      label: "Schema violation",
      system_prompt: "Return only JSON matching the schema.",
      prompt: "Classify this ticket and return JSON.",
      output: '{"status": "maybe", "priority": 5}',
      chunks: "",
      similarity_scores: "",
      temperature: "",
      context_window: "",
      response_schema: JSON.stringify({
        type: "object",
        required: ["status", "answer"],
        properties: {
          status: { type: "string", enum: ["ok", "error"] },
          answer: { type: "string" },
        },
      }, null, 2),
      tools_expected: "",
      tool_calls: "",
    },
    tool_call_failure: {
      label: "Tool failure",
      system_prompt: "Use the search tool for current shipping cutoffs.",
      prompt: "Search for the current shipping cutoff and answer the customer.",
      output: "The cutoff is 5pm today.",
      chunks: "",
      similarity_scores: "",
      temperature: "",
      context_window: "",
      response_schema: "",
      tools_expected: "search",
      tool_calls: "[]",
    },
    citation_failure: {
      label: "Citation failure",
      system_prompt: "Cite every factual claim with retrieved chunk numbers.",
      prompt: "Answer with citations: what is the return window?",
      output: "The return window is 30 days [3].",
      chunks: "Returns are available within 30 days with a receipt.",
      similarity_scores: "0.91",
      temperature: "",
      context_window: "",
      response_schema: "",
      tools_expected: "",
      tool_calls: "",
    },
    ambiguous_prompt: {
      label: "Ambiguous prompt",
      system_prompt: "",
      prompt: "Can you do it?",
      output: "I will proceed with the requested task using reasonable assumptions I will proceed with the requested task using reasonable assumptions I will proceed with the requested task using reasonable assumptions I will proceed with the requested task using reasonable assumptions",
      chunks: "",
      similarity_scores: "",
      temperature: "",
      context_window: "",
      response_schema: "",
      tools_expected: "",
      tool_calls: "",
    },
  };
  const EXAMPLE = EXAMPLES.rag_hallucination;

  function parseJsonInput(value, fallback) {
    const raw = (value || "").trim();
    if (!raw) return fallback;
    try { return JSON.parse(raw); } catch (_) { return fallback; }
  }

  function buildBody(f) {
    const parsedToolCalls = parseJsonInput(f.tool_calls, null);
    return {
      system_prompt: f.system_prompt || "",
      prompt: f.prompt,
      output: f.output,
      chunks: f.chunks ? f.chunks.split("\n").filter(Boolean) : null,
      similarity_scores: f.similarity_scores
        ? f.similarity_scores.split(",").map(x => parseFloat(x.trim())).filter(x => !isNaN(x))
        : null,
      temperature: f.temperature ? parseFloat(f.temperature) : null,
      context_window: f.context_window ? parseInt(f.context_window) : null,
      response_schema: parseJsonInput(f.response_schema, null),
      tools_expected: f.tools_expected
        ? f.tools_expected.split(",").map(x => x.trim()).filter(Boolean)
        : null,
      tool_calls: Array.isArray(parsedToolCalls)
        ? parsedToolCalls
        : parsedToolCalls ? [parsedToolCalls] : null,
      run_fix: true, simulate: true,
    };
  }

  function evidenceLines(res) {
    const p = res && res.diagnosis && res.diagnosis.primary;
    if (!p) return [];
    const ev = p.evidence || {};
    if (p.failure === "schema_violation") return ev.violations || [];
    if (p.failure === "tool_call_failure") return ev.issues || [];
    if (p.failure === "citation_failure") return ev.issues || [];
    if (p.failure === "retrieval_failure") return [
      `similarity ${Number(ev.similarity || 0).toFixed(2)}`,
      `entity coverage ${Number(ev.entity_coverage || 0).toFixed(2)}`,
      `overlap ${Number(ev.overlap || 0).toFixed(2)}`,
    ];
    if (p.failure === "ambiguous_prompt") return [
      "prompt contains unresolved reference",
      "model answered instead of asking a clarifying question",
    ];
    return Object.entries(ev).slice(0, 5).map(([k, v]) => `${k}: ${JSON.stringify(v)}`);
  }

  function App() {
    const [f, setF] = useState(EXAMPLE);
    const [res, setRes] = useState(null);
    const [busy, setBusy] = useState(false);
    const [err, setErr] = useState(null);
    const [showAdvanced, setShowAdvanced] = useState(true);
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);
    const timer = useRef(null);
    const set = k => e => setF(p => ({ ...p, [k]: e.target.value }));

    // Debounced auto-analyze
    useEffect(() => {
      if (!f.prompt || !f.output) { setRes(null); return; }
      clearTimeout(timer.current);
      timer.current = setTimeout(async () => {
        setBusy(true);
        try {
          const resp = await fetch("/api/playground", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(buildBody(f)),
          });
          if (resp.status === 401) { window.location.href = "/login"; return; }
          const r = await resp.json();
          if (r && r.detail) { setErr("Couldn't analyze — check the inputs."); return; }
          setRes(r); setErr(null);
        } catch (e) { setErr("Couldn't reach the server."); }
        finally { setBusy(false); }
      }, 600);
      return () => clearTimeout(timer.current);
    }, [f]);

    const applyFix = () => {
      const add = res && res.fix && res.fix.candidate && res.fix.candidate.system_prompt_additions;
      if (add) setF(p => ({ ...p, system_prompt: (p.system_prompt + "\n\n" + add).trim() }));
    };

    const saveToDiagnoses = async () => {
      if (!f.prompt || !f.output) return;
      setSaving(true);
      try {
        await fetch("/api/analyze", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...buildBody(f), label: "playground" }),
        });
        setSaved(true);
        setTimeout(() => setSaved(false), 2000);
      } catch (_) {}
      finally { setSaving(false); }
    };

    const ui = res && res.ui;
    const fix = res && res.fix;

    return (
      <div className="shell pg">
        <div className="dash-head">
          <a className="dash-brand" href="/dashboard" aria-label="Back to dashboard">
            <div className="dash-logo">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12h4l3 8 4-16 3 8h4" /></svg>
            </div>
            <div>
              <div className="dash-title">Playground</div>
              <div className="dash-sub">← dashboard · edit a case, watch the diagnosis update live</div>
            </div>
          </a>
          <div style={{ display: "flex", gap: "var(--space-3)", alignItems: "center" }}>
            <button className="view-tab" onClick={() => setShowAdvanced(v => !v)} type="button">
              {showAdvanced ? "Simple view" : "Advanced view"}
            </button>
            <Button variant="ghost" size="sm" onClick={() => setF(EXAMPLE)}>reset example</Button>
          </div>
        </div>

        <div className="pg-layout">
          {/* Editor pane */}
          <div className="pg-editor">
            <div className="example-row">
              {Object.entries(EXAMPLES).map(([id, ex]) => (
                <button key={id} className="view-tab" type="button" onClick={() => setF(ex)}>
                  {ex.label}
                </button>
              ))}
            </div>
            {showAdvanced && (
              <div className="field">
                <label>System prompt</label>
                <textarea rows="3" value={f.system_prompt} onChange={set("system_prompt")}
                  placeholder="You are a helpful assistant…" />
              </div>
            )}
            <div className="field">
              <label>User prompt / query</label>
              <textarea rows="3" value={f.prompt} onChange={set("prompt")}
                placeholder="What is the refund policy for opened electronics?" />
            </div>
            <div className="field">
              <label>LLM output <span className="hint">(edit to see the diagnosis change)</span></label>
              <textarea rows="5" value={f.output} onChange={set("output")}
                placeholder="The LLM's response goes here…" />
            </div>
            {showAdvanced && (
              <>
                <div className="field">
                  <label>Retrieved chunks (one per line)</label>
                  <textarea rows="3" value={f.chunks} onChange={set("chunks")}
                    placeholder={"Returns within 30 days.\nStore hours 9 to 5."} />
                </div>
                <div className="run-grid">
                  <div className="field">
                    <label>Similarity scores</label>
                    <input value={f.similarity_scores} onChange={set("similarity_scores")} placeholder="0.71, 0.66" />
                  </div>
                  <div className="field">
                    <label>Temperature · context window</label>
                    <div style={{ display: "flex", gap: "8px" }}>
                      <input value={f.temperature} onChange={set("temperature")} style={{ flex: 1 }} placeholder="0.7" />
                      <input value={f.context_window} onChange={set("context_window")} style={{ flex: 1 }} placeholder="window" />
                    </div>
                  </div>
                </div>
                <div className="run-grid">
                  <div className="field">
                    <label>Expected tools</label>
                    <input value={f.tools_expected} onChange={set("tools_expected")} placeholder="search, lookup_policy" />
                  </div>
                  <div className="field">
                    <label>Tool calls JSON</label>
                    <textarea rows="3" value={f.tool_calls} onChange={set("tool_calls")}
                      placeholder={'[{"name":"search","input":"{\\"q\\":\\"refund\\"}"}]'} />
                  </div>
                </div>
                <div className="field">
                  <label>Response schema JSON</label>
                  <textarea rows="5" value={f.response_schema} onChange={set("response_schema")}
                    placeholder={'{"type":"object","required":["answer"],"properties":{"answer":{"type":"string"}}}'} />
                </div>
              </>
            )}
            <div className="run-actions" style={{ borderTop: "1px solid var(--border-faint)", paddingTop: "var(--space-3)", marginTop: "var(--space-1)" }}>
              <Button variant="secondary" size="sm" onClick={saveToDiagnoses}
                disabled={saving || !f.prompt || !f.output}>
                {saved ? "Saved ✓" : saving ? "Saving…" : "Save to diagnoses"}
              </Button>
              <span className="hint">
                {busy ? "Analyzing…" : res ? "Auto-analyzed · " + (600) + "ms debounce" : "Start typing to analyze."}
              </span>
            </div>
          </div>

          {/* Result pane */}
          <div className="pg-result">
            {err && <div className="error-banner" style={{ marginBottom: "var(--space-3)" }}>{err}</div>}
            {!ui ? (
              <div className="pg-empty">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
                  width="32" height="32" style={{ color: "var(--text-quaternary)" }}>
                  <path d="M3 12h4l3 8 4-16 3 8h4"/>
                </svg>
                <p>{f.prompt && f.output ? "Analyzing…" : "Start typing to see a live diagnosis."}</p>
              </div>
            ) : (
              <div style={{ display: "grid", gap: "var(--space-3)" }}>
                <DiagnosticCard
                  severity={SEV[ui.severity] || "warn"}
                  id={ui.id}
                  title={ui.title}
                  location={ui.explanation}
                  confidence={ui.confidence}
                  signals={ui.signals}
                  fix={null}
                />
                {evidenceLines(res).length > 0 && (
                  <div className="evidence-panel">
                    <div className="evidence-panel__title">Evidence</div>
                    {evidenceLines(res).map((line, i) => <div key={i} className="evidence-panel__line">{line}</div>)}
                  </div>
                )}
                {fix && fix.verdict !== "none" && (
                  <div className="fix" data-verdict={fix.verdict}>
                    <div className="fix__head">
                      <Badge variant={VERDICT_VARIANT[fix.verdict] || "neutral"} dot solid>
                        {fix.verdict.replace(/_/g, " ")}
                      </Badge>
                      <span className="fix__agent">{fix.agent}</span>
                      <span className="fix__mode" style={{ marginLeft: "auto" }}>
                        tests {fix.tests_passed}/{fix.tests_total}
                      </span>
                    </div>
                    <div className="fix__strategy">{fix.candidate.strategy}</div>
                    {fix.candidate.rationale && <div className="fix__notes">{fix.candidate.rationale}</div>}
                    {fix.diff && <CodeBlock filename="fix.diff" language="diff" showLineNumbers={false} code={fix.diff} />}
                    {fix.candidate.system_prompt_additions && (
                      <Button variant="secondary" size="sm" onClick={applyFix}>
                        ↑ apply fix to system prompt
                      </Button>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  ReactDOM.createRoot(document.getElementById("root")).render(<App />);
})();
