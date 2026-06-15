/* DebugAI landing — content sections (how it works, use cases, CTA, footer). */
const I = window.DebugAIIcons;

/* ── How it works ─────────────────────────────────────────────────────────── */
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
          <span className="ds-overline">How it works</span>
          <h2>One wrap. Every failure caught.</h2>
          <p>
            Detection is deterministic — no LLM, no guessing. The same input always
            produces the same diagnosis. Pin it in CI, diff it across deploys.
          </p>
        </div>
        <div className="flow reveal">
          <div className="stage">
            <div className="stage__num">01</div>
            <svg className="stage__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
              <path d="M2 12h3l2.5-7 4 16L18 9l1.5 3H22" />
            </svg>
            <h3>Capture every call</h3>
            <p>One line wraps your LLM client. Prompt, output, retrieved chunks, similarity scores, latency — all captured automatically in the background.</p>
            <div className="stage__vis">
              <div className="stream">
                {["prompt", "retrieved_chunks", "similarity_scores", "llm_output"].map((n, i) => (
                  <div className="stream__row" key={n}>
                    <span className="stream__dot" style={{ background: ["#3FB6CC","#EF9F27","#43C28A","#EF9F27"][i] }} />
                    {n}<span className="stream__track" />
                  </div>
                ))}
              </div>
            </div>
            {connector}
          </div>

          <div className="stage">
            <div className="stage__num">02</div>
            <svg className="stage__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 3 2 20h20L12 3Z" /><path d="M12 10v4" /><path d="M12 17.5h.01" />
            </svg>
            <h3>8 signals, 9 detectors</h3>
            <p>A deterministic engine computes 8 metrics — overlap, entity coverage, similarity, contradiction, variance — then runs 9 failure detectors ranked by confidence.</p>
            <div className="stage__vis" style={{ display: "grid", gap: "8px" }}>
              <SignalIndicator name="retrieval.similarity" value="0.41" confidence={0.82} status="critical" />
              <SignalIndicator name="context.overlap" value="0.11" confidence={0.9} status="critical" />
              <SignalIndicator name="entity.coverage" value="0.00" confidence={1.0} status="critical" />
            </div>
            {connector}
          </div>

          <div className="stage">
            <div className="stage__num">03</div>
            <svg className="stage__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
              <path d="m14.7 6.3 3 3M3 21l3.5-1 11-11a2.1 2.1 0 0 0-3-3l-11 11L3 21Z" /><path d="M15 7 9 13" />
            </svg>
            <h3>Named failure + specific fix</h3>
            <p>Not "something went wrong." You get the failure type, a confidence score, the signal evidence, and an exact fix — re-chunking strategy, temperature cap, grounding rule.</p>
            <div className="stage__vis" style={{ display: "flex", alignItems: "center", gap: "12px" }}>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: "2.2rem", fontWeight: 700, color: "var(--amber-base)", lineHeight: 1 }}>95<span style={{ fontSize: "1rem" }}>%</span></div>
              <div>
                <Badge variant="critical" dot>retrieval_failure</Badge>
                <div className="ds-sm" style={{ color: "var(--text-tertiary)", marginTop: "6px", fontFamily: "var(--font-mono)" }}>similarity 0.41 &lt; 0.50</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── Code snippet ─────────────────────────────────────────────────────────── */
function CodeSection() {
  const { CodeBlock, Badge } = window.DesignSystem_90c6f1;
  const T = (c, t) => React.createElement("span", { className: c }, t);

  const wrapLines = [
    [T("tok-com", "# Wrap once — every call auto-diagnosed in the background")],
    [T("tok-key", "from "), T("tok-fn", "openai"), T("tok-key", " import "), "OpenAI"],
    [T("tok-key", "import "), T("tok-fn", "debugai")],
    [""],
    ["client = ", T("tok-fn", "debugai"), ".wrap_llm(OpenAI(),"],
    ["    on_diagnosis=", T("tok-key", "lambda"), " d: alert(d) ", T("tok-com", "# your sink")],
    [")"],
    [""],
    [T("tok-com", "# Or run directly on any failing call")],
    ["result = ", T("tok-fn", "debugai"), ".analyze("],
    ["    prompt=user_prompt,"],
    ["    output=llm_output,"],
    ["    chunks=retrieved_docs,"],
    [")"],
    [""],
    [T("tok-key", "print"), "(result[", T("tok-str", '"primary"'), "][", T("tok-str", '"failure"'), "])  ", T("tok-com", "# retrieval_failure")],
    [T("tok-key", "print"), "(result[", T("tok-str", '"primary"'), "][", T("tok-str", '"fix"'), "])     ", T("tok-com", "# exact fix string")],
  ];

  return (
    <section className="section section--dark" id="install">
      <div className="shell">
        <div className="section__head reveal">
          <span className="ds-overline">Get started</span>
          <h2>Two lines. Full coverage.</h2>
          <p>No config files. No dashboards to set up first. Works with OpenAI, Anthropic, Gemini, Ollama, Groq, and any OpenAI-compatible endpoint.</p>
        </div>
        <div className="code-block-wrap reveal">
          <CodeBlock filename="your_app.py" language="python" showLineNumbers={false}>
            {wrapLines.map((parts, i) => (
              <span className="code-block__ln" key={i}>
                {parts.map((p, j) =>
                  React.isValidElement(p) ? React.cloneElement(p, { key: j }) : React.createElement(React.Fragment, { key: j }, p || " ")
                )}
              </span>
            ))}
          </CodeBlock>
        </div>
        <div className="install-badges reveal">
          <Badge variant="trace" dot>pip install debugerai</Badge>
          <Badge variant="ok" dot>214 tests</Badge>
          <Badge variant="neutral" dot>MIT license</Badge>
          <Badge variant="neutral" dot>Python 3.11+</Badge>
        </div>
      </div>
    </section>
  );
}

/* ── Use cases ────────────────────────────────────────────────────────────── */
const USE_CASES = [
  {
    icon: "🗂️",
    title: "RAG / document Q&A",
    problem: "Your chatbot answers confidently from outside the retrieved context — inventing policy details, citing non-existent clauses.",
    what: "DebugAI catches hallucination (0.95 confidence) and tells you exactly which retrieved chunks failed to ground the output.",
    fix: "Add grounding constraints to the system prompt. Re-chunk with entity-aware strategy.",
  },
  {
    icon: "🎓",
    title: "Socratic tutors / education AI",
    problem: "Your tutor reveals 80% of the answer in the first response, or asks the same guiding question reworded.",
    what: "The instruction-adherence judge scores the output against the system prompt's pedagogical rules.",
    fix: "Strengthened system prompt with strict Socratic constraints — verified by re-running and re-judging.",
  },
  {
    icon: "💬",
    title: "Customer support bots",
    problem: "The bot gives the generic return policy when the user asked specifically about electronics exceptions.",
    what: "Retrieval failure detected: similarity 0.41, entity coverage 0.00 — the retriever returned irrelevant chunks.",
    fix: "Re-embed with domain-specific chunking. Add an 'information not found' fallback guard.",
  },
  {
    icon: "🛠️",
    title: "Code review copilots",
    problem: "The same code snippet gets 'critical' severity in one run and 'medium' the next — inconsistent across reviewers.",
    what: "Prompt brittleness detected: variance 0.60 with temperature 0.8.",
    fix: "Lower temperature to 0.2. Add severity rubric to system prompt with few-shot examples.",
  },
];

function UseCases() {
  return (
    <section className="section" id="usecases">
      <div className="shell">
        <div className="section__head reveal">
          <span className="ds-overline">Use cases</span>
          <h2>Every LLM failure has a name.</h2>
          <p>DebugAI doesn't say "something went wrong." It tells you which failure type occurred, why, and what to do.</p>
        </div>
        <div className="usecases-grid reveal">
          {USE_CASES.map((u, i) => (
            <div key={i} className="usecase-card">
              <div className="usecase-card__icon">{u.icon}</div>
              <h3 className="usecase-card__title">{u.title}</h3>
              <p className="usecase-card__problem"><b>Problem:</b> {u.problem}</p>
              <p className="usecase-card__what"><b>What DebugAI sees:</b> {u.what}</p>
              <p className="usecase-card__fix"><b>Fix:</b> {u.fix}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── CTA ──────────────────────────────────────────────────────────────────── */
function CTA() {
  const { Button } = window.DesignSystem_90c6f1;
  return (
    <section className="section" id="cta">
      <div className="shell">
        <div className="cta reveal">
          <h2>Stop guessing. Start diagnosing.</h2>
          <p>
            Free for solo developers. No credit card. Takes 2 minutes to see your first diagnosis.
          </p>
          <div className="cta__actions">
            <Button variant="primary" size="lg" onClick={() => window.location.href = "/register"}>
              Start debugging free
            </Button>
            <Button variant="secondary" size="lg" onClick={() => window.location.href = "/pricing"}>
              See pricing
            </Button>
          </div>
          <p style={{ marginTop: "var(--space-4)", fontSize: "var(--text-sm)", color: "var(--text-tertiary)" }}>
            Or install the SDK: <code style={{ fontFamily: "var(--font-mono)", color: "var(--amber-300)" }}>pip install debugerai</code>
          </p>
        </div>
      </div>
    </section>
  );
}

/* ── Footer ───────────────────────────────────────────────────────────────── */
function Footer() {
  return (
    <footer className="footer">
      <div className="shell footer__inner">
        <a className="brand" href="#top" style={{ fontSize: "var(--text-body)" }}>
          {I.mark({ className: "brand__mark", style: { width: 22, height: 22 } })}
          <span>Debug<b>AI</b></span>
        </a>
        <span className="ds-sm" style={{ marginLeft: "var(--space-4)", color: "var(--text-tertiary)" }}>
          © 2026 DebugAI · Built by engineers, for engineers
        </span>
        <div className="footer__links">
          <a href="/dashboard">Dashboard</a>
          <a href="/pricing">Pricing</a>
          <a href="https://github.com/civicRJ/DebugAI">GitHub</a>
          <a href="/docs">Docs</a>
        </div>
      </div>
    </footer>
  );
}

window.DebugAIHowItWorks = HowItWorks;
window.DebugAIFeatures = CodeSection;
window.DebugAICTA = CTA;
window.DebugAIFooter = Footer;
window.DebugAIUseCases = UseCases;
