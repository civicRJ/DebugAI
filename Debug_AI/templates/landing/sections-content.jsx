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
          <h2>One wrap. Every failure traced.</h2>
          <p>
            Detection is deterministic — no LLM, no guessing. The same input always
            produces the same diagnosis. Pin it in CI, inspect the pipeline stage,
            and diff detector behavior across deploys.
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
            <h3>Signals + detectors</h3>
            <p>A deterministic engine computes core grounding metrics plus pipeline and security signals, then runs detectors for retrieval, grounding, schema, tools, citations, prompts, runtime, and safety.</p>
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
            <h3>Named failure + verified fix</h3>
            <p>Not "something went wrong." You get the failure type, confidence, evidence, a fix agent proposal, and a regression artifact you can keep in CI.</p>
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
    [T("tok-com", "# Diagnose a bad LLM output and keep the regression artifact")],
    [T("tok-key", "from "), T("tok-fn", "debugai"), T("tok-key", " import "), "debug_report, analyze_pipeline"],
    [""],
    ["report = debug_report("],
    ["    prompt=user_prompt,"],
    ["    output=bad_output,"],
    ["    chunks=retrieved_docs,"],
    ["    similarity_scores=scores,"],
    [")"],
    [T("tok-key", "print"), "(report[", T("tok-str", '"failure"'), "])              ", T("tok-com", "# hallucination")],
    [T("tok-key", "print"), "(report[", T("tok-str", '"regression_artifact"'), "])  ", T("tok-com", "# pytest skeleton")],
    [""],
    [T("tok-com", "# Trace the pipeline stage that failed")],
    ["pipeline = analyze_pipeline(stages, user_prompt=user_prompt)"],
    [T("tok-key", "print"), "(pipeline[", T("tok-str", '"primary"'), "][", T("tok-str", '"stage_id"'), "])  ", T("tok-com", "# retrieval")],
  ];

  const capabilities = [
    ["Failure diagnosis", "Names retrieval, grounding, schema, tool, citation, runtime, prompt, and safety failures with confidence and evidence."],
    ["Pipeline trace analysis", "Pinpoints whether query rewrite, retrieval, context packing, tool execution, generation, or validation failed first."],
    ["Prompt vulnerability audit", "Finds weak rules, conflicting priorities, missing RAG boundaries, tool abuse paths, and patched prompt rules."],
    ["Corpus evals", "Score labeled failure corpora and fail CI if detector accuracy drops."],
    ["Fix artifacts", "Returns fix-agent output plus portable regression tests for the bad case."],
    ["Feedback calibration", "Track accepted diagnoses and fix success so confidence can improve from real usage."],
  ];

  return (
    <section className="section section--dark" id="install">
      <div className="shell">
        <div className="section__head reveal">
          <span className="ds-overline">Get started</span>
          <h2>SDK first. Dashboard second.</h2>
          <p>Start locally with Python. Add the dashboard when you want stored diagnoses, traces, sessions, prompt audits, and account-scoped API tokens.</p>
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
          <Badge variant="ok" dot>265 tests</Badge>
          <Badge variant="neutral" dot>MIT license</Badge>
          <Badge variant="neutral" dot>Python 3.11+</Badge>
        </div>
        <div className="usecases-grid reveal" style={{ marginTop: "var(--space-8)" }}>
          {capabilities.map(([title, body]) => (
            <div key={title} className="usecase-card">
              <h3 className="usecase-card__title">{title}</h3>
              <p className="usecase-card__what">{body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── Use cases ────────────────────────────────────────────────────────────── */
const USE_CASES = [
  {
    icon: "RAG",
    title: "RAG / document Q&A",
    problem: "Your chatbot answers confidently from outside the retrieved context — inventing policy details, citing non-existent clauses.",
    what: "DebugAI catches hallucination (0.95 confidence) and tells you exactly which retrieved chunks failed to ground the output.",
    fix: "Add grounding constraints to the system prompt. Re-chunk with entity-aware strategy.",
  },
  {
    icon: "EDU",
    title: "Socratic tutors / education AI",
    problem: "Your tutor reveals 80% of the answer in the first response, or asks the same guiding question reworded.",
    what: "The instruction-adherence judge scores the output against the system prompt's pedagogical rules.",
    fix: "Strengthened system prompt with strict Socratic constraints — verified by re-running and re-judging.",
  },
  {
    icon: "SUP",
    title: "Customer support bots",
    problem: "The bot gives the generic return policy when the user asked specifically about electronics exceptions.",
    what: "Retrieval failure detected: similarity 0.41, entity coverage 0.00 — the retriever returned irrelevant chunks.",
    fix: "Re-embed with domain-specific chunking. Add an 'information not found' fallback guard.",
  },
  {
    icon: "DEV",
    title: "Code review copilots",
    problem: "The same code snippet gets 'critical' severity in one run and 'medium' the next — inconsistent across reviewers.",
    what: "Prompt brittleness detected: variance 0.60 with temperature 0.8.",
    fix: "Lower temperature to 0.2. Add severity rubric to system prompt with few-shot examples.",
  },
  {
    icon: "SEC",
    title: "Prompt security reviews",
    problem: "A system prompt says to always answer, use any tool when needed, and handle sensitive customer data carefully.",
    what: "Prompt audit detects priority conflicts, missing approval gates, weak wording, missing secret handling, and untrusted RAG boundaries.",
    fix: "Append deterministic security rules or run dynamic attack probes against your app before shipping.",
  },
  {
    icon: "CI",
    title: "Regression gates",
    problem: "A detector improvement accidentally weakens retrieval or tool-failure classification.",
    what: "Corpus evals compare expected failures against actual diagnoses and produce a confusion matrix.",
    fix: "Run `debugai eval failures.json` in CI and keep fix-agent regression artifacts beside repaired bugs.",
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
  const [form, setForm] = React.useState({
    email: "",
    name: "",
    company: "",
    role: "RAG / agent builder",
    use_case: "",
    website: "",
  });
  const [state, setState] = React.useState({ busy: false, ok: false, error: "" });

  function update(key) {
    return (event) => setForm((prev) => ({ ...prev, [key]: event.target.value }));
  }

  async function submit(event) {
    event.preventDefault();
    if (!form.email.trim()) {
      setState({ busy: false, ok: false, error: "Enter your work email." });
      return;
    }
    setState({ busy: true, ok: false, error: "" });
    try {
      const res = await fetch("/api/beta/leads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...form, source: "landing-cta" }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Could not join the beta.");
      setState({ busy: false, ok: true, error: "" });
    } catch (err) {
      setState({ busy: false, ok: false, error: err.message || "Could not join the beta." });
    }
  }

  return (
    <section className="section" id="cta">
      <div className="shell">
        <div className="cta cta--beta reveal">
          <div className="cta__copy">
            <span className="ds-overline">Private beta</span>
            <h2>Send one failing LLM trace. Get the root cause.</h2>
            <p>
              DebugAI is onboarding teams building RAG apps, support bots, and AI agents.
              Join the beta and we will help diagnose your first production-style failure.
            </p>
            <div className="cta__actions">
              <Button variant="secondary" size="lg" onClick={() => window.location.href = "/register"}>
                Create account
              </Button>
              <Button variant="ghost" size="lg" onClick={() => window.location.href = "/docs"}>
                Read docs
              </Button>
            </div>
            <p className="cta__install">
              SDK: <code>pip install debugerai</code>
            </p>
          </div>
          <form className="beta-form" onSubmit={submit}>
            <input
              aria-label="Website"
              className="beta-form__hp"
              value={form.website}
              onChange={update("website")}
              tabIndex="-1"
              autoComplete="off"
            />
            <label>
              Work email
              <input type="email" value={form.email} onChange={update("email")} placeholder="you@company.com" autoComplete="email" required />
            </label>
            <div className="beta-form__row">
              <label>
                Name
                <input value={form.name} onChange={update("name")} placeholder="Your name" autoComplete="name" />
              </label>
              <label>
                Company
                <input value={form.company} onChange={update("company")} placeholder="Company" autoComplete="organization" />
              </label>
            </div>
            <label>
              Role
              <select value={form.role} onChange={update("role")}>
                <option>RAG / agent builder</option>
                <option>Founder / engineering lead</option>
                <option>AI product engineer</option>
                <option>ML platform / infra</option>
                <option>Other</option>
              </select>
            </label>
            <label>
              What are you trying to debug?
              <textarea value={form.use_case} onChange={update("use_case")} placeholder="Example: support bot gives wrong policy answers even when retrieval looks good." rows="3" />
            </label>
            {state.error && <p className="beta-form__error" role="alert">{state.error}</p>}
            {state.ok && <p className="beta-form__ok" role="status">You are on the beta list. We will follow up with a trace-debugging slot.</p>}
            <button className="beta-form__submit" type="submit" disabled={state.busy || state.ok}>
              {state.ok ? "Joined beta" : state.busy ? "Joining..." : "Join beta"}
            </button>
          </form>
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
