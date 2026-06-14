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
          <a href="/pricing">Pricing</a>
          <a href="/dashboard">Dashboard</a>
        </div>
        <div className="nav__spacer" />
        <div className="nav__actions">
          <Button variant="ghost" size="sm" onClick={() => window.location.href = "/login"}>Sign in</Button>
          <Button variant="primary" size="sm" onClick={() => window.location.href = "/register"}>Start free</Button>
        </div>
      </div>
    </nav>
  );
}

/* ── Inline playground demo ───────────────────────────────────────────────── */
const DEMO_CASES = [
  {
    label: "RAG hallucination",
    prompt: "What does Section 4 of the contract require?",
    output: "Section 4 requires arbitration in Delaware under the Marbury Clause and a $50,000 penalty.",
    chunks: ["Section 4 covers confidentiality.", "Governed by California law."],
    scores: [0.66, 0.59],
    temp: 0.75,
    expected: { failure: "hallucination", confidence: 0.95, fix: "Add grounding constraints: answer only from provided context; cite sources; say 'not found' when unsupported." },
  },
  {
    label: "Retrieval failure",
    prompt: "What is the refund policy for electronics?",
    output: "Electronics can be returned within 90 days for a full cash refund.",
    chunks: ["Store hours are 9am to 5pm.", "Parking is behind the building."],
    scores: [0.42, 0.40],
    temp: 0.2,
    expected: { failure: "retrieval_failure", confidence: 0.95, fix: "Re-chunk source documents with an entity-aware strategy and tune the retriever." },
  },
  {
    label: "Prompt brittleness",
    prompt: "Summarize the meeting notes.",
    output: "The team agreed on Q4 timeline and assigned design review to platform group.",
    chunks: ["Meeting: team agreed on Q4 timeline.", "Action: design review to platform group."],
    scores: [0.85, 0.82],
    temp: 0.9,
    expected: { failure: "prompt_brittleness", confidence: 0.75, fix: "Lower temperature to 0.2, add explicit output-format template, and insert few-shot examples." },
  },
];

const FAILURE_COLORS = {
  hallucination: "var(--critical-base)",
  retrieval_failure: "var(--critical-bright)",
  prompt_brittleness: "var(--amber-base)",
  entity_gap: "var(--amber-300)",
  healthy: "var(--ok-base)",
};
const FAILURE_LABELS = {
  hallucination: "Hallucination",
  retrieval_failure: "Retrieval failure",
  prompt_brittleness: "Prompt brittleness",
  entity_gap: "Entity gap",
};

function HeroDemo() {
  const { Badge, Button } = window.DesignSystem_90c6f1;
  const [active, setActive] = useState(0);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  async function run(idx) {
    const c = DEMO_CASES[idx];
    setRunning(true); setResult(null); setError(null);
    try {
      const r = await fetch("/api/playground", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: c.prompt, output: c.output,
          chunks: c.chunks, similarity_scores: c.scores, temperature: c.temp,
          run_fix: false,
        }),
      });
      if (r.status === 401) {
        // Not logged in — show the pre-computed expected result
        setResult({ ui: { id: c.expected.failure, title: FAILURE_LABELS[c.expected.failure],
          severity: "critical", confidence: c.expected.confidence,
          explanation: c.expected.fix }, diagnosis: { healthy: false } });
        return;
      }
      const data = await r.json();
      setResult(data);
    } catch (_) {
      setResult({ ui: { id: DEMO_CASES[active].expected.failure,
        title: FAILURE_LABELS[DEMO_CASES[active].expected.failure],
        severity: "critical", confidence: DEMO_CASES[active].expected.confidence,
        explanation: DEMO_CASES[active].expected.fix }, diagnosis: { healthy: false } });
    } finally { setRunning(false); }
  }

  useEffect(() => { run(active); }, [active]);

  const c = DEMO_CASES[active];
  const ui = result && result.ui;

  return (
    <div className="hero-demo">
      <div className="hero-demo__bar">
        {I.mark({ style: { width: 14, height: 14 } })}
        <span className="hero-demo__title">Live diagnosis</span>
        <div className="hero-demo__tabs">
          {DEMO_CASES.map((d, i) => (
            <button key={i} className={"hero-demo__tab" + (active === i ? " active" : "")}
              onClick={() => setActive(i)}>{d.label}</button>
          ))}
        </div>
      </div>
      <div className="hero-demo__body">
        <div className="hero-demo__input">
          <div className="hero-demo__label">PROMPT</div>
          <div className="hero-demo__text">{c.prompt}</div>
          <div className="hero-demo__label" style={{ marginTop: "var(--space-3)" }}>LLM OUTPUT</div>
          <div className="hero-demo__text hero-demo__text--output">{c.output}</div>
        </div>
        <div className="hero-demo__arrow">→</div>
        <div className="hero-demo__result">
          {running ? (
            <div className="hero-demo__loading">
              <div className="loading-dots"><span/><span/><span/></div>
              <span style={{ color: "var(--text-tertiary)", fontSize: "var(--text-xs)" }}>Analyzing…</span>
            </div>
          ) : ui ? (
            <div>
              <div className="hero-demo__verdict" style={{ background: FAILURE_COLORS[ui.id] || "var(--critical-base)" }}>
                {FAILURE_LABELS[ui.id] || ui.id} · {ui.confidence != null ? Math.round(ui.confidence * 100) + "%" : ""}
              </div>
              <div className="hero-demo__fix">{ui.explanation}</div>
            </div>
          ) : (
            <div className="hero-demo__empty">Select a case →</div>
          )}
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
            <div className="hero__proof-item"><b>5</b> failure detectors</div>
            <div className="hero__proof-sep" />
            <div className="hero__proof-item"><b>&lt;5ms</b> healthy-path overhead</div>
          </div>
          <div className="hero__cta">
            <Button variant="primary" size="lg"
              onClick={() => window.location.href = "/register"}>
              Start debugging free
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
          <HeroDemo />
        </div>
      </div>
    </header>
  );
}

window.DebugAINav = Nav;
window.DebugAIHero = Hero;
window.DebugAIIcons = I;
