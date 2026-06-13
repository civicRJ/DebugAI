/* DebugAI landing — content sections. Relies on icons (I) from sections-hero.jsx. */
const I = window.DebugAIIcons;

/* ============================================================
   HOW IT WORKS
   ============================================================ */
function HowItWorks() {
  const { Badge, SignalIndicator } = window.DesignSystem_90c6f1;
  const connector = (
    <svg className="flow__connector" viewBox="0 0 26 8" fill="none" preserveAspectRatio="none">
      <path d="M0 4h20m0 0-4-3m4 3-4 3" stroke="var(--border-strong)" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
  return (
    <section className="section" id="how">
      <div className="shell">
        <div className="section__head reveal">
          <span className="ds-overline">The pipeline</span>
          <h2>Signal in. Diagnosis out.</h2>
          <p>
            DebugAI sits on your LLM calls and runs the same deterministic pass every time —
            so the answer to a bad output is a verdict, not a vibe. Layers 1 and 2 use no LLM.
          </p>
        </div>
        <div className="flow reveal">
          <div className="stage">
            <div className="stage__num">01</div>
            {I.capture({ className: "stage__icon" })}
            <h3>Capture the request</h3>
            <p>Prompt, output, retrieved chunks, similarity scores, and runtime metadata. Every call becomes a structured signal set — one line with <code>wrap_llm()</code>.</p>
            <div className="stage__vis">
              <div className="stream">
                {["prompt", "retrieved_chunks", "similarity_scores", "llm_output"].map((n, i) => (
                  <div className="stream__row" key={n}>
                    <span className="stream__dot" style={{ background: ["#3FB6CC", "#EF9F27", "#43C28A", "#EF9F27"][i] }} />
                    {n}<span className="stream__track" />
                  </div>
                ))}
              </div>
            </div>
            {connector}
          </div>

          <div className="stage">
            <div className="stage__num">02</div>
            {I.correlate({ className: "stage__icon" })}
            <h3>Compute &amp; classify</h3>
            <p>Eight signals computed via small CPU models, then five deterministic detectors run — ranked into a primary failure plus secondary issues.</p>
            <div className="stage__vis" style={{ display: "grid", gap: "8px" }}>
              <SignalIndicator name="retrieval.similarity" value="0.41" confidence={0.82} status="critical" />
              <SignalIndicator name="entity.coverage" value="0.17" confidence={0.7} status="warn" />
            </div>
            {connector}
          </div>

          <div className="stage">
            <div className="stage__num">03</div>
            {I.diagnose({ className: "stage__icon" })}
            <h3>Diagnose &amp; fix</h3>
            <p>Out comes a ranked diagnosis: the failure type, a confidence score, the signal evidence, and the exact fix to apply.</p>
            <div className="stage__vis" style={{ display: "flex", alignItems: "center", gap: "12px" }}>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: "2rem", fontWeight: 700, color: "var(--amber-base)", lineHeight: 1 }}>95<span style={{ fontSize: "1rem" }}>%</span></div>
              <div>
                <Badge variant="critical" dot>retrieval failure</Badge>
                <div className="ds-sm" style={{ color: "var(--text-tertiary)", marginTop: "6px", fontFamily: "var(--font-mono)" }}>similarity 0.41 &lt; 0.50</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ============================================================
   FEATURES
   ============================================================ */
function Features() {
  const { CodeBlock, SignalIndicator, Badge } = window.DesignSystem_90c6f1;
  const T = (c, t) => <span className={c}>{t}</span>;
  const cliLines = [
    [T("tok-punc", ">>> "), T("tok-fn", "analyze"), "(prompt, output, chunks=", T("tok-str", "..."), ")"],
    [T("tok-com", "  → 8 signals computed · 2 anomalous")],
    [""],
    [T("tok-key", "PRIMARY  "), T("tok-err", "retrieval_failure"), "  ", T("tok-num", "conf 0.95")],
    [T("tok-punc", "  similarity "), T("tok-num", "0.41"), " < 0.50 — irrelevant chunks"],
    [T("tok-key", "FIX      "), "re-chunk entity-aware · constrain prompt to context"],
  ];

  return (
    <section className="section" id="features">
      <div className="shell">
        <div className="section__head reveal">
          <span className="ds-overline">What you get</span>
          <h2>Built like a debugger, not a dashboard.</h2>
          <p>Every surface is high-signal and reproducible. No charts you have to interpret — just the diagnosis and the evidence behind it.</p>
        </div>

        <div className="features">
          <div className="feat feat--wide reveal">
            <div style={{ display: "flex", gap: "var(--space-6)", flexWrap: "wrap", alignItems: "center" }}>
              <div style={{ flex: "1 1 280px", minWidth: 0 }}>
                {I.determinism({ className: "feat__icon" })}
                <h3 style={{ marginTop: "var(--space-3)" }}>Deterministic by design</h3>
                <p style={{ marginTop: "var(--space-2)" }}>
                  Detection uses no LLM — the same request always yields the same diagnosis,
                  byte for byte. Pin a verdict in CI, diff it across prompt changes, and trust it
                  in a postmortem. From Python or the dashboard.
                </p>
                <div style={{ marginTop: "var(--space-4)", display: "flex", gap: "var(--space-2)" }}>
                  <Badge variant="ok" dot>reproducible</Badge>
                  <Badge variant="trace" dot>CI-ready</Badge>
                </div>
              </div>
              <div style={{ flex: "1 1 360px", minWidth: 0 }}>
                <CodeBlock filename="terminal" language="sh" showLineNumbers={false}>
                  {cliLines.map((parts, i) => (
                    <span className={"code-block__ln" + (i === 3 ? " code-block__ln--hl" : "")} key={i}>
                      {parts.map((p, j) =>
                        React.isValidElement(p)
                          ? React.cloneElement(p, { key: j })
                          : <React.Fragment key={j}>{p || "\u00a0"}</React.Fragment>
                      )}
                    </span>
                  ))}
                </CodeBlock>
              </div>
            </div>
          </div>

          <div className="feat feat--third reveal">
            {I.trace({ className: "feat__icon" })}
            <h3>Signal-level breakdown</h3>
            <p>See exactly which signals fired, how strongly, and why each one mattered to the verdict.</p>
            <div className="feat__demo" style={{ display: "grid", gap: "8px" }}>
              <SignalIndicator name="context.overlap" value="0.11" confidence={0.9} status="critical" />
              <SignalIndicator name="output.variance" value="0.47" confidence={0.47} status="warn" />
            </div>
          </div>

          <div className="feat feat--third reveal">
            {I.shield({ className: "feat__icon" })}
            <h3>Confidence scoring</h3>
            <p>Every diagnosis ships a calibrated score. Triage by certainty, never by hunch.</p>
            <div className="feat__demo" style={{ display: "flex", alignItems: "flex-end", gap: "10px" }}>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: "2.6rem", fontWeight: 700, lineHeight: 0.9, color: "var(--text-primary)" }}>92<span style={{ fontSize: "1.1rem", color: "var(--text-tertiary)" }}>%</span></div>
              <div style={{ paddingBottom: "6px" }}><Badge variant="critical" dot>high</Badge></div>
            </div>
          </div>

          <div className="feat feat--third reveal">
            {I.fix({ className: "feat__icon" })}
            <h3>Ships the fix</h3>
            <p>Not just the cause — the patch. Apply inline, open a PR, or copy the diff.</p>
            <div className="feat__demo">
              <div className="diag__fix" style={{ marginTop: 0 }}>
                <div className="diag__fix-head">{I.fix({ style: { width: 15, height: 15 } })}Suggested fix</div>
                <div className="diag__fix-body">Add grounding constraints: answer only from <code>context</code>, cite sources.</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ============================================================
   CTA + FOOTER
   ============================================================ */
function CTA() {
  const { Button } = window.DesignSystem_90c6f1;
  return (
    <section className="section" id="cta">
      <div className="shell">
        <div className="cta reveal">
          <h2>Diagnose your next LLM failure in seconds.</h2>
          <p>Wrap your OpenAI or Anthropic client in one line and watch the diagnoses stream in. Free for solo developers, no card required.</p>
          <div className="cta__actions">
            <Button variant="primary" size="lg" onClick={() => (window.location.href = "/dashboard")}>Open the dashboard</Button>
            <Button variant="secondary" size="lg" mono leadingIcon={I.github({ style: { width: 16, height: 16 } })}>Star on GitHub</Button>
          </div>
        </div>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="footer">
      <div className="shell footer__inner">
        <a className="brand" href="#top" style={{ fontSize: "var(--text-body)" }}>
          {I.mark({ className: "brand__mark", style: { width: 22, height: 22 } })}
          <span>Debug<b>AI</b></span>
        </a>
        <span className="ds-sm" style={{ marginLeft: "var(--space-4)" }}>© 2026 DebugAI · signal → diagnosis</span>
        <div className="footer__links">
          <a href="/dashboard">Dashboard</a><a href="#how">How it works</a><a href="#features">Features</a><a href="#cta">Pricing</a>
        </div>
      </div>
    </footer>
  );
}

window.DebugAIHowItWorks = HowItWorks;
window.DebugAIFeatures = Features;
window.DebugAICTA = CTA;
window.DebugAIFooter = Footer;
