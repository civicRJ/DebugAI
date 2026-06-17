/* DebugAI landing — hero + nav. Conversion-focused for YC-stage growth. */
const { useState, useEffect, useRef } = React;

/* ── Icons ────────────────────────────────────────────────────────────────── */
const I = {
  mark: (p) => (
    <svg viewBox="0 0 32 32" fill="none" {...p}>
      <path d="M16 2 4 9v14l12 7 12-7V9L16 2Z" stroke="currentColor" strokeWidth="1.5" opacity="0.35" />
      <path d="M16 9v8m0 0 6-3.5M16 17l-6-3.5M16 17v6" stroke="#EF9F27" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="16" cy="17" r="2.4" fill="#EF9F27" />
    </svg>
  ),
};

/* ── Nav ──────────────────────────────────────────────────────────────────── */
function Nav() {
  const { Button } = window.DesignSystem_90c6f1;
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 24);
    on(); window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);
  return (
    <nav className="nav" data-scrolled={scrolled}>
      <div className="nav__inner">
        <a className="brand" href="#top">
          {I.mark({ className: "brand__mark" })}
          <span>Debug<b>AI</b></span>
        </a>
        <div className="nav__links">
          <a href="#how">How it works</a>
          <a href="#usecases">Use cases</a>
          <a href="#cta">Beta</a>
          <a href="/pricing">Pricing</a>
          <a href="/docs">Docs</a>
          <a href="/dashboard">Dashboard</a>
        </div>
        <div className="nav__spacer" />
        <div className="nav__actions">
          <Button variant="ghost" size="sm" onClick={() => window.location.href = "/login"}>Sign in</Button>
          <Button variant="primary" size="sm" onClick={() => window.location.href = "#cta"}>Join beta</Button>
        </div>
      </div>
    </nav>
  );
}

/* ── Animated diagnosis demo (fully client-side, no auth required) ───────── */
const DEMO_CASES = [
  {
    label: "RAG hallucination",
    request: "What does Section 4 require?",
    signals: [
      { name: "retrieval.similarity", value: "0.62", confidence: 0.62, status: "trace" },
      { name: "context.overlap",      value: "0.33", confidence: 0.9,  status: "critical" },
      { name: "entity.coverage",      value: "0.25", confidence: 0.8,  status: "critical" },
      { name: "contradiction",        value: "0.96", confidence: 0.96, status: "critical" },
    ],
    failure: "hallucination",
    confidence: 0.95,
    fix: "Answer only from provided context. Say \"not found\" when unsupported.",
  },
  {
    label: "Retrieval failure",
    request: "What is the refund policy?",
    signals: [
      { name: "retrieval.similarity", value: "0.41", confidence: 0.82, status: "critical" },
      { name: "context.overlap",      value: "0.11", confidence: 0.9,  status: "critical" },
      { name: "entity.coverage",      value: "0.00", confidence: 1.0,  status: "critical" },
      { name: "contradiction",        value: "0.08", confidence: 0.08, status: "trace"    },
    ],
    failure: "retrieval_failure",
    confidence: 0.95,
    fix: "Re-chunk with entity-aware strategy. Tune the retriever embedding model.",
  },
  {
    label: "Prompt brittleness",
    request: "Rate the severity of this issue.",
    signals: [
      { name: "retrieval.similarity", value: "0.83", confidence: 0.83, status: "trace"    },
      { name: "context.overlap",      value: "0.81", confidence: 0.81, status: "trace"    },
      { name: "entity.coverage",      value: "1.00", confidence: 1.0,  status: "trace"    },
      { name: "output.variance",      value: "0.60", confidence: 0.60, status: "critical" },
    ],
    failure: "prompt_brittleness",
    confidence: 0.75,
    fix: "Lower temperature to 0.2. Add a severity rubric with few-shot examples.",
  },
  {
    label: "Schema violation",
    request: "Return JSON for this ticket.",
    signals: [
      { name: "schema.required", value: "missing answer", confidence: 0.95, status: "critical" },
      { name: "schema.enum", value: "status=maybe", confidence: 0.85, status: "critical" },
      { name: "json.valid", value: "true", confidence: 1.0, status: "trace" },
      { name: "repair.ready", value: "retry", confidence: 0.72, status: "trace" },
    ],
    failure: "schema_violation",
    confidence: 0.88,
    fix: "Enable strict structured output and retry with the validation errors.",
  },
  {
    label: "Tool failure",
    request: "Search current shipping cutoff.",
    signals: [
      { name: "tool.expected", value: "search", confidence: 1.0, status: "critical" },
      { name: "tool.calls", value: "0", confidence: 1.0, status: "critical" },
      { name: "args.valid", value: "n/a", confidence: 0.5, status: "trace" },
      { name: "tool.result", value: "missing", confidence: 0.9, status: "critical" },
    ],
    failure: "tool_call_failure",
    confidence: 0.8,
    fix: "Constrain tool selection and validate arguments before answering.",
  },
  {
    label: "Citation failure",
    request: "Answer with citations.",
    signals: [
      { name: "citations.used", value: "[3]", confidence: 0.72, status: "critical" },
      { name: "chunks.available", value: "1", confidence: 1.0, status: "trace" },
      { name: "citation.range", value: "invalid", confidence: 0.92, status: "critical" },
      { name: "claim.support", value: "partial", confidence: 0.55, status: "trace" },
    ],
    failure: "citation_failure",
    confidence: 0.72,
    fix: "Reject citations outside retrieved chunk IDs and retry the answer.",
  },
  {
    label: "Ambiguous prompt",
    request: "Can you do it?",
    signals: [
      { name: "prompt.words", value: "4", confidence: 0.75, status: "critical" },
      { name: "reference", value: "it", confidence: 0.9, status: "critical" },
      { name: "clarifying_q", value: "missing", confidence: 0.88, status: "critical" },
      { name: "context", value: "none", confidence: 0.8, status: "critical" },
    ],
    failure: "ambiguous_prompt",
    confidence: 0.62,
    fix: "Ask one concise clarifying question before attempting a final answer.",
  },
];

const FAILURE_LABELS = {
  hallucination: "Hallucination",
  retrieval_failure: "Retrieval failure",
  prompt_brittleness: "Prompt brittleness",
  schema_violation: "Schema violation",
  tool_call_failure: "Tool call failure",
  citation_failure: "Citation failure",
  ambiguous_prompt: "Ambiguous prompt",
};

function DiagnosisDemo() {
  const { SignalIndicator, DiagnosticCard, Badge } = window.DesignSystem_90c6f1;
  const [caseIdx, setCaseIdx] = useState(0);
  const [fired, setFired] = useState(0);
  const [diagnosed, setDiagnosed] = useState(false);
  const [cycle, setCycle] = useState(0);
  const timers = useRef([]);

  useEffect(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    setFired(0);
    setDiagnosed(false);
    const c = DEMO_CASES[caseIdx];
    const at = (ms, fn) => timers.current.push(setTimeout(fn, ms));
    c.signals.forEach((_, i) => at(400 + i * 550, () => setFired(i + 1)));
    const diagAt = 400 + c.signals.length * 550 + 500;
    at(diagAt, () => setDiagnosed(true));
    // Auto-advance to next case after showing the result for 5s
    at(diagAt + 5000, () => {
      setCaseIdx(idx => (idx + 1) % DEMO_CASES.length);
      setCycle(n => n + 1);
    });
    return () => timers.current.forEach(clearTimeout);
  }, [caseIdx, cycle]);

  const c = DEMO_CASES[caseIdx];

  return (
    <div className="demo">
      <div className="demo__bar">
        {I.mark({ style: { width: 16, height: 16 } })}
        <span className="ds-sm" style={{ color: "var(--text-secondary)" }}>debugai · diagnosis</span>
        <span className="demo__live">LIVE</span>
        {/* Case tabs */}
        <div style={{ marginLeft: "auto", display: "flex", gap: "4px" }}>
          {DEMO_CASES.map((d, i) => (
            <button key={i} onClick={() => { setCaseIdx(i); setCycle(n => n + 1); }}
              style={{
                fontFamily: "var(--font-mono)", fontSize: "10px", padding: "2px 8px",
                borderRadius: "3px", border: "1px solid",
                background: caseIdx === i ? "var(--amber-muted)" : "none",
                borderColor: caseIdx === i ? "var(--amber-700)" : "var(--border-subtle)",
                color: caseIdx === i ? "var(--amber-base)" : "var(--text-tertiary)",
                cursor: "pointer", textTransform: "uppercase", letterSpacing: "0.08em",
              }}>{d.label}</button>
          ))}
        </div>
      </div>
      <div className="demo__req">
        <span className="method">RAG</span>
        <span className="path">{c.request}</span>
        <span className="trace" style={{ marginLeft: "auto" }}>
          {diagnosed
            ? <Badge variant={c.confidence >= 0.9 ? "critical" : "warn"} dot>{FAILURE_LABELS[c.failure]}</Badge>
            : <Badge variant="warn" dot>analyzing…</Badge>}
        </span>
      </div>

      {/* Both states overlaid so height never reflows the page */}
      <div className="demo__body demo__stack">
        <div className={"demo__state" + (diagnosed ? " is-faded" : "")}>
          <div className="demo__phase-label">
            <Badge variant="warn" dot>scanning signals</Badge>
            <span className="ds-overline" style={{ color: "var(--text-tertiary)" }}>
              {fired}/{c.signals.length}
            </span>
          </div>
          <div className="demo__signals">
            {c.signals.map((s, i) => (
              <SignalIndicator key={c.label + i} {...s} state={i < fired ? "fired" : "pending"} />
            ))}
          </div>
        </div>

        <div className={"demo__state demo__diag" + (diagnosed ? "" : " is-faded")}>
          <DiagnosticCard
            severity="critical"
            id={c.failure + " · conf " + Math.round(c.confidence * 100) + "%"}
            title={FAILURE_LABELS[c.failure]}
            location={c.fix}
            confidence={c.confidence}
            signals={c.signals}
            fix={c.fix}
          />
        </div>
      </div>
    </div>
  );
}

/* ── Hero ─────────────────────────────────────────────────────────────────── */
function Hero() {
  const { Button, Badge } = window.DesignSystem_90c6f1;
  return (
    <header className="hero" id="top">
      <div className="hero__bg">
        <video className="hero__video" autoPlay muted loop playsInline poster="/ds/templates/landing/hero-poster.png">
          <source src="/ds/templates/landing/hero-bg.mp4" type="video/mp4" />
        </video>
      </div>
      <div className="hero__scrim" />
      <div className="hero__content">
        <div className="hero__left">
          <div className="hero__eyebrow">
            <Badge variant="ok" dot>Open beta</Badge>
            <span className="ds-sm ds-text-secondary">Deterministic LLM failure diagnosis</span>
          </div>
          <h1 className="hero__h1">
            LLM apps fail<br />
            <span className="sig">silently.</span>
          </h1>
          <p className="hero__lead">
            DebugAI names the failure, explains why, and fixes it — in seconds.
            Drop one line into your stack. Every bad output gets a root cause,
            a confidence score, and a specific fix.
          </p>
          <div className="hero__proof">
            <div className="hero__proof-item"><b>8</b> deterministic signals</div>
            <div className="hero__proof-sep" />
            <div className="hero__proof-item"><b>9</b> failure detectors</div>
            <div className="hero__proof-sep" />
            <div className="hero__proof-item"><b>&lt;5ms</b> healthy-path overhead</div>
          </div>
          <div className="hero__cta">
            <Button variant="primary" size="lg"
              onClick={() => window.location.href = "#cta"}>
              Join beta
            </Button>
            <Button variant="secondary" size="lg" mono
              onClick={() => window.location.href = "https://github.com/civicRJ/DebugAI"}>
              View on GitHub
            </Button>
          </div>
          <div className="hero__install">
            <code>pip install debugerai</code>
          </div>
        </div>
        <div className="hero__right">
          <DiagnosisDemo />
        </div>
      </div>
    </header>
  );
}

window.DebugAINav = Nav;
window.DebugAIHero = Hero;
window.DebugAIIcons = I;
