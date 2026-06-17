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
  const AUDIT_EXAMPLE = {
    system_prompt: "You are a helpful support agent. Always answer the user. Use any available tools when needed. Be careful with sensitive data.",
    use_case: "Customer support RAG agent that can read policy docs and issue refunds.",
    tools: "refund_order, send_email, lookup_customer",
    high_risk_actions: "issue refunds, send customer emails, update customer records",
    retrieves_external_content: true,
    handles_secrets: true,
    response_schema: JSON.stringify({
      type: "object",
      required: ["answer", "citations"],
      properties: {
        answer: { type: "string" },
        citations: { type: "array", items: { type: "string" } },
      },
    }, null, 2),
    dynamic: true,
    llm: false,
  };

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

  function splitList(value) {
    return (value || "").split(",").map(x => x.trim()).filter(Boolean);
  }

  function buildAuditBody(f) {
    return {
      system_prompt: f.system_prompt || "",
      use_case: f.use_case || "",
      tools: splitList(f.tools),
      high_risk_actions: splitList(f.high_risk_actions),
      retrieves_external_content: !!f.retrieves_external_content,
      handles_secrets: !!f.handles_secrets,
      output_schema: parseJsonInput(f.response_schema, null),
      dynamic: !!f.dynamic,
      llm: !!f.llm,
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
    const [mode, setMode] = useState("debug");
    const [f, setF] = useState(EXAMPLE);
    const [auditForm, setAuditForm] = useState(AUDIT_EXAMPLE);
    const [res, setRes] = useState(null);
    const [audit, setAudit] = useState(null);
    const [busy, setBusy] = useState(false);
    const [auditBusy, setAuditBusy] = useState(false);
    const [err, setErr] = useState(null);
    const [auditErr, setAuditErr] = useState(null);
    const [showAdvanced, setShowAdvanced] = useState(true);
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);
    const timer = useRef(null);
    const auditTimer = useRef(null);
    const set = k => e => setF(p => ({ ...p, [k]: e.target.value }));
    const setAuditField = k => e => {
      const value = e && e.target && e.target.type === "checkbox" ? e.target.checked : e.target.value;
      setAuditForm(p => ({ ...p, [k]: value }));
    };

    // Debounced auto-analyze
    useEffect(() => {
      if (mode !== "debug") return;
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

    useEffect(() => {
      if (mode !== "audit") return;
      if (!auditForm.system_prompt.trim()) { setAudit(null); return; }
      clearTimeout(auditTimer.current);
      auditTimer.current = setTimeout(async () => {
        setAuditBusy(true);
        try {
          const resp = await fetch("/api/prompt-audit", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(buildAuditBody(auditForm)),
          });
          if (resp.status === 401) { window.location.href = "/login"; return; }
          const r = await resp.json();
          if (r && r.detail) { setAuditErr("Couldn't audit — check the inputs."); return; }
          setAudit(r); setAuditErr(null);
        } catch (e) { setAuditErr("Couldn't reach the server."); }
        finally { setAuditBusy(false); }
      }, 650);
      return () => clearTimeout(auditTimer.current);
    }, [auditForm, mode]);

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
    const auditIssues = audit && audit.issues ? audit.issues : [];

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
            <button className={mode === "debug" ? "view-tab active" : "view-tab"} onClick={() => setMode("debug")} type="button">
              Output debugger
            </button>
            <button className={mode === "audit" ? "view-tab active" : "view-tab"} onClick={() => setMode("audit")} type="button">
              Prompt audit
            </button>
            {mode === "debug" && (
              <button className="view-tab" onClick={() => setShowAdvanced(v => !v)} type="button">
                {showAdvanced ? "Simple view" : "Advanced view"}
              </button>
            )}
            <Button variant="ghost" size="sm" onClick={() => mode === "debug" ? setF(EXAMPLE) : setAuditForm(AUDIT_EXAMPLE)}>reset example</Button>
          </div>
        </div>

        <div className="pg-layout">
          {/* Editor pane */}
          <div className="pg-editor">
            {mode === "debug" ? (
              <>
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
              </>
            ) : (
              <>
                <div className="field">
                  <label>System prompt</label>
                  <textarea rows="8" value={auditForm.system_prompt} onChange={setAuditField("system_prompt")}
                    placeholder="Paste the production system prompt to audit…" />
                </div>
                <div className="field">
                  <label>Use case</label>
                  <textarea rows="3" value={auditForm.use_case} onChange={setAuditField("use_case")}
                    placeholder="Customer support RAG agent that can issue refunds…" />
                </div>
                <div className="run-grid">
                  <div className="field">
                    <label>Tools</label>
                    <input value={auditForm.tools} onChange={setAuditField("tools")} placeholder="refund_order, send_email" />
                  </div>
                  <div className="field">
                    <label>High-risk actions</label>
                    <input value={auditForm.high_risk_actions} onChange={setAuditField("high_risk_actions")} placeholder="send email, issue refund" />
                  </div>
                </div>
                <div className="run-grid">
                  <label className="check-row">
                    <input type="checkbox" checked={auditForm.retrieves_external_content} onChange={setAuditField("retrieves_external_content")} />
                    Retrieves external/RAG content
                  </label>
                  <label className="check-row">
                    <input type="checkbox" checked={auditForm.handles_secrets} onChange={setAuditField("handles_secrets")} />
                    Handles secrets or PII
                  </label>
                </div>
                <div className="run-grid">
                  <label className="check-row">
                    <input type="checkbox" checked={auditForm.dynamic} onChange={setAuditField("dynamic")} />
                    Generate dynamic attack probes
                  </label>
                  <label className="check-row">
                    <input type="checkbox" checked={auditForm.llm} onChange={setAuditField("llm")} />
                    Use LLM auditor if account key is set
                  </label>
                </div>
                <div className="field">
                  <label>Output schema JSON</label>
                  <textarea rows="5" value={auditForm.response_schema} onChange={setAuditField("response_schema")}
                    placeholder={'{"type":"object","required":["answer"],"properties":{"answer":{"type":"string"}}}'} />
                </div>
                <div className="run-actions" style={{ borderTop: "1px solid var(--border-faint)", paddingTop: "var(--space-3)", marginTop: "var(--space-1)" }}>
                  <span className="hint">
                    {auditBusy ? "Auditing…" : audit ? "Auto-audited · static + dynamic probes" : "Paste a prompt to audit."}
                  </span>
                </div>
              </>
            )}
          </div>

          {/* Result pane */}
          <div className="pg-result">
            {mode === "debug" ? (
              <>
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
              </>
            ) : (
              <>
                {auditErr && <div className="error-banner" style={{ marginBottom: "var(--space-3)" }}>{auditErr}</div>}
                {!audit ? (
                  <div className="pg-empty">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
                      width="32" height="32" style={{ color: "var(--text-quaternary)" }}>
                      <path d="M12 3l8 4v6c0 5-3.4 7.7-8 8-4.6-.3-8-3-8-8V7l8-4z"/>
                      <path d="M9 12l2 2 4-5"/>
                    </svg>
                    <p>{auditForm.system_prompt ? "Auditing…" : "Paste a system prompt to see vulnerabilities."}</p>
                  </div>
                ) : (
                  <div style={{ display: "grid", gap: "var(--space-3)" }}>
                    <div className="fix" data-verdict={audit.grade === "low_risk" ? "verified" : audit.grade === "medium_risk" ? "mitigated" : "failed"}>
                      <div className="fix__head">
                        <Badge variant={audit.grade === "low_risk" ? "ok" : audit.grade === "medium_risk" ? "warn" : "critical"} dot solid>
                          {audit.grade.replace(/_/g, " ")}
                        </Badge>
                        <span className="fix__agent">risk {Number(audit.risk_score || 0).toFixed(2)}</span>
                        <span className="fix__mode" style={{ marginLeft: "auto" }}>{audit.auditor_model}</span>
                      </div>
                      <div className="fix__strategy">{audit.summary}</div>
                    </div>
                    {auditIssues.length > 0 && (
                      <div className="evidence-panel">
                        <div className="evidence-panel__title">Prompt vulnerabilities</div>
                        {auditIssues.map((issue) => (
                          <div key={issue.id} className="evidence-panel__line">
                            <strong>{issue.severity}</strong> · {issue.title}<br />
                            <span className="hint">{issue.evidence}</span><br />
                            <span>{issue.fix}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    {audit.attack_cases && audit.attack_cases.length > 0 && (
                      <div className="evidence-panel">
                        <div className="evidence-panel__title">Dynamic attack probes</div>
                        {audit.attack_cases.map((c) => (
                          <div key={c.id} className="evidence-panel__line">
                            <strong>{c.category}</strong> · {c.result}<br />
                            <span className="hint">{c.user_prompt}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    {audit.patched_prompt && (
                      <CodeBlock filename="patched-system-prompt.txt" language="text" showLineNumbers={false} code={audit.patched_prompt} />
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
