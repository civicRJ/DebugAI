/* DebugAI landing — section components. Assigned to window for main.jsx. */
const { useState, useEffect, useRef } = React;

/* ---------- icons ---------- */
const I = {
  mark: (p) => (
    <svg viewBox="0 0 32 32" fill="none" {...p}>
      <path d="M16 2 4 9v14l12 7 12-7V9L16 2Z" stroke="currentColor" strokeWidth="1.5" opacity="0.35" />
      <path d="M16 9v8m0 0 6-3.5M16 17l-6-3.5M16 17v6" stroke="#EF9F27" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="16" cy="17" r="2.4" fill="#EF9F27" />
    </svg>
  ),
  capture: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M2 12h3l2.5-7 4 16L18 9l1.5 3H22" />
    </svg>
  ),
  correlate: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <circle cx="6" cy="6" r="2.4" /><circle cx="18" cy="7" r="2.4" /><circle cx="12" cy="18" r="2.4" />
      <path d="M7.6 7.6 10.4 16M16.6 8.7 13.3 16.5M8.2 6.4h7.4" />
    </svg>
  ),
  diagnose: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M12 3 2 20h20L12 3Z" /><path d="M12 10v4" /><path d="M12 17h.01" />
    </svg>
  ),
  determinism: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <rect x="3" y="3" width="18" height="18" rx="2" /><path d="M8 8h8M8 12h8M8 16h5" />
    </svg>
  ),
  trace: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M4 4v16M4 8h10a3 3 0 0 1 0 6H8m0 0 3-3m-3 3 3 3" />
    </svg>
  ),
  fix: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="m14.7 6.3 3 3M3 21l3.5-1 11-11a2.1 2.1 0 0 0-3-3l-11 11L3 21Z" /><path d="M15 7 9 13" />
    </svg>
  ),
  shield: (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M12 2 4 5v6c0 5 3.5 8.5 8 11 4.5-2.5 8-6 8-11V5l-8-3Z" /><path d="m9 12 2 2 4-4" />
    </svg>
  ),
  github: (p) => (
    <svg viewBox="0 0 24 24" fill="currentColor" {...p}>
      <path d="M12 2C6.5 2 2 6.6 2 12.3c0 4.5 2.9 8.3 6.8 9.7.5.1.7-.2.7-.5v-1.7c-2.8.6-3.4-1.4-3.4-1.4-.5-1.2-1.1-1.5-1.1-1.5-.9-.6.1-.6.1-.6 1 .1 1.5 1 1.5 1 .9 1.6 2.4 1.1 3 .8.1-.7.3-1.1.6-1.4-2.2-.3-4.6-1.1-4.6-5 0-1.1.4-2 1-2.7-.1-.3-.4-1.3.1-2.7 0 0 .8-.3 2.7 1a9.3 9.3 0 0 1 5 0c1.9-1.3 2.7-1 2.7-1 .5 1.4.2 2.4.1 2.7.6.7 1 1.6 1 2.7 0 3.9-2.4 4.7-4.6 5 .4.3.7.9.7 1.9v2.8c0 .3.2.6.7.5 3.9-1.4 6.8-5.2 6.8-9.7C22 6.6 17.5 2 12 2Z" />
    </svg>
  ),
};

/* ============================================================
   NAV
   ============================================================ */
function Nav() {
  const { Button } = window.DesignSystem_90c6f1;
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 24);
    on();
    window.addEventListener("scroll", on, { passive: true });
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
          <a href="#features">Features</a>
          <a href="/dashboard">Dashboard</a>
          <a href="#cta">Pricing</a>
        </div>
        <div className="nav__spacer" />
        <div className="nav__actions">
          <Button variant="ghost" size="sm" onClick={() => (window.location.href = "/login")}>Sign in</Button>
          <Button variant="primary" size="sm" onClick={() => (window.location.href = "/register")}>Get started</Button>
        </div>
      </div>
    </nav>
  );
}

/* ============================================================
   LIVE DIAGNOSIS DEMO  (signature animated element)
   ============================================================ */
const DEMO_SIGNALS = [
  { name: "retrieval.similarity", value: "0.41", confidence: 0.82, status: "critical" },
  { name: "context.overlap", value: "0.11", confidence: 0.9, status: "critical" },
  { name: "entity.coverage", value: "0.00", confidence: 1.0, status: "critical" },
  { name: "contradiction", value: "0.55", confidence: 0.55, status: "warn" },
];

function DiagnosisDemo() {
  const { SignalIndicator, DiagnosticCard, Button, Badge } = window.DesignSystem_90c6f1;
  const [fired, setFired] = useState(0);
  const [diagnosed, setDiagnosed] = useState(false);
  const [cycle, setCycle] = useState(0);
  const timers = useRef([]);

  useEffect(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    setFired(0);
    setDiagnosed(false);
    const at = (ms, fn) => timers.current.push(setTimeout(fn, ms));
    DEMO_SIGNALS.forEach((_, i) => at(550 + i * 620, () => setFired(i + 1)));
    at(550 + DEMO_SIGNALS.length * 620 + 650, () => setDiagnosed(true));
    at(550 + DEMO_SIGNALS.length * 620 + 650 + 5200, () => setCycle((c) => c + 1));
    return () => timers.current.forEach(clearTimeout);
  }, [cycle]);

  const fix = (
    <React.Fragment>
      Retrieval returned irrelevant chunks. Re-chunk the source docs with an
      entity-aware strategy and constrain the prompt to answer only from
      provided context — say <code>not found</code> when unsupported.
    </React.Fragment>
  );

  return (
    <div className="demo">
      <div className="demo__bar">
        {I.mark({ style: { width: 16, height: 16 } })}
        <span className="ds-sm" style={{ color: "var(--text-secondary)" }}>debugai · session</span>
        <span className="demo__live">LIVE</span>
      </div>
      <div className="demo__req">
        <span className="method">RAG</span>
        <span className="path">/support/answer</span>
        <span className="trace">0x9af2c1</span>
      </div>
      {/* Both states are always mounted and overlaid in the same grid cell, so
          the panel is sized to the taller one and never reflows the page. */}
      <div className="demo__body demo__stack">
        <div className={"demo__state" + (diagnosed ? " is-faded" : "")} aria-hidden={diagnosed}>
          <div className="demo__phase-label">
            <Badge variant="warn" dot>analyzing</Badge>
            <span className="ds-overline" style={{ color: "var(--text-tertiary)" }}>
              {fired}/{DEMO_SIGNALS.length} signals
            </span>
          </div>
          <div className="demo__signals">
            {DEMO_SIGNALS.map((s, i) => (
              <div key={i}>
                <SignalIndicator {...s} state={!diagnosed && i < fired ? "fired" : "pending"} />
              </div>
            ))}
          </div>
        </div>
        <div className={"demo__state demo__diag" + (diagnosed ? "" : " is-faded")} aria-hidden={!diagnosed}>
          <DiagnosticCard
            severity="critical"
            id="retrieval_failure · trace 0x9af2c1"
            title="Retrieved chunks don't ground the answer"
            location={'mean similarity <b>0.41 &lt; 0.50</b> · entity coverage 0.00'}
            confidence={0.95}
            signals={DEMO_SIGNALS}
            fix={fix}
            actions={
              <React.Fragment>
                <Button variant="primary" size="sm" onClick={() => (window.location.href = "/dashboard")}>Open in dashboard</Button>
                <Button variant="secondary" size="sm">View signals</Button>
                <span className="diag__foot-spacer" />
                <Button variant="ghost" size="sm">Dismiss</Button>
              </React.Fragment>
            }
          />
        </div>
      </div>
    </div>
  );
}

/* ============================================================
   HERO
   ============================================================ */
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
      <div className="hero__grid">
        <div>
          <span className="hero__eyebrow">
            <Badge variant="ok" dot>v3.0</Badge>
            <span className="ds-sm ds-text-secondary">Deterministic LLM failure diagnosis</span>
          </span>
          <h1>Stop guessing why<br />the <span className="sig">LLM</span> failed.</h1>
          <p className="hero__lead">
            DebugAI turns every LLM call into a ranked, reproducible diagnosis — eight
            deterministic signals, five failure detectors, scored by confidence and
            shipped with the exact fix. Retrieval failure, hallucination, prompt
            brittleness — named, not guessed.
          </p>
          <div className="hero__cta">
            <Button variant="primary" size="lg" onClick={() => (window.location.href = "/dashboard")} trailingIcon={
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
            }>Open the dashboard</Button>
            <Button variant="secondary" size="lg" mono leadingIcon={
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m4 17 6-6-6-6M12 19h8" /></svg>
            }>pip install debugai</Button>
          </div>
          <div className="hero__stats">
            <div className="hero__stat"><div className="n">8</div><div className="l">signals / request</div></div>
            <div className="hero__stat"><div className="n">5</div><div className="l">failure detectors</div></div>
            <div className="hero__stat"><div className="n">&lt;5ms</div><div className="l">healthy-path latency</div></div>
          </div>
        </div>
        <DiagnosisDemo />
      </div>
    </header>
  );
}

window.DebugAINav = Nav;
window.DebugAIHero = Hero;
window.DebugAIIcons = I;
