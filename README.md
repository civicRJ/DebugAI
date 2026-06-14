# DebugAI

[![CI](https://github.com/civicRJ/DebugAI/actions/workflows/ci.yml/badge.svg)](https://github.com/civicRJ/DebugAI/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-amber.svg)](LICENSE)

> Diagnose **why** LLM outputs fail and get the **exact fix** — reducing hours of trial-and-error debugging to seconds.

DebugAI is a 3-layer root-cause engine for LLM applications (RAG systems,
chatbots, copilots). Unlike observability tools that stop at dashboards, it
classifies the failure and proposes a specific, actionable fix.

This repository implements **Phase 1 — the deterministic diagnosis core**
(Steps 1–3 of the roadmap in `debugai_architecture_v3.pdf`): the signal engine,
the rule engine, and the `analyze()` API with an LLM explainer — plus the
**Level 2 `wrap_llm()` SDK wrapper** (Step 5) and a **web dashboard** (Step 6)
built on the `Debug_AI/` design system.

## Architecture (implemented)

| Layer | Type | Module | What it does |
|------|------|--------|--------------|
| 1 — Signal Extraction | deterministic | `debugai/signals.py` | Computes the 8-metric signal vector (small CPU models + fallbacks, lazy eval) |
| 2 — Rule Engine | deterministic | `debugai/detectors.py`, `diagnosis.py` | 9 failure detectors → primary + secondary diagnosis |
| 3 — LLM Explainer | probabilistic | `debugai/explainer.py` | Translates the diagnosis into human-readable explanation + fix (Claude; deterministic fallback) |
| API | — | `debugai/analyze.py` | Level-1 single-call entry point |

**Detection is deterministic; only the explanation uses an LLM.** Healthy
requests fail open (no LLM tokens, no cost).

### The 8 signals
context-output overlap · entity coverage · retrieval similarity · contradiction
(NLI) · output variance (proxy) · latency · token-usage ratio · context-length
ratio.

### The 9 detectors (evaluation order)
context overflow → schema violation → tool call failure → retrieval failure →
citation failure → entity gap → hallucination → prompt brittleness → ambiguous
prompt. All run; results are ranked by confidence; gate patterns prevent
nonsensical combinations.

## Quickstart

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm

./run.sh                      # → http://127.0.0.1:8000  (home + dashboard)
# or: pytest -q               # run the test suite
```

Set `ANTHROPIC_API_KEY` to enable the live LLM explainer and the fix-agent
re-run; everything works without it (deterministic detection + a grounded-stub
re-run for the demo).

### Frontend build

The UI is React, **pre-compiled with esbuild** (no in-browser Babel, no CDN —
React is vendored locally, so pages load fast, work offline, and run under a
strict `script-src 'self'` CSP). The built bundles (`server/static/dist/`) and
vendored React (`server/static/vendor/`) are committed, so a plain
`pip install` + run works with no Node. To rebuild after editing any `.jsx`:

```bash
npm install && npm run build     # → server/static/dist/*.js
```

`./run.sh` builds automatically if the bundles are missing.

### CLI

Installs a `debugai` console command (`pip install debugerai` or `pip install -e .` for local dev):

```bash
debugai analyze --prompt "..." --output "..." --chunk "..." --score 0.41
debugai diagnose cases.json            # a capture dict, list, or {cases:[...]}
debugai fix cases.json --simulate      # diagnose + propose & verify a fix
debugai serve --port 8000              # launch the web app
```

## Install

Models used (all small, CPU, downloaded once): `all-MiniLM-L6-v2` (embeddings),
`en_core_web_sm` (NER), `cross-encoder/nli-deberta-v3-base` (NLI).

## Usage

```python
from debugai import analyze

result = analyze(
    prompt="What is the refund policy for electronics?",
    output="Electronics can be returned within 90 days for a full cash refund.",
    chunks=["Our store hours are 9am to 5pm.", "Parking is behind the building."],
    similarity_scores=[0.42, 0.40],
    temperature=0.2,
)

print(result["primary"]["failure"])      # retrieval_failure
print(result["primary"]["confidence"])    # 0.95
print(result["primary"]["fix"])           # specific, actionable fix
print(result["signals"])                  # full 8-metric vector
```

Only `prompt` and `output` are required (Core IO). Supplying retrieval
(`chunks`, `similarity_scores`) and runtime fields (`latency_ms`,
`temperature`, `context_window`, `token_usage`) unlocks the RAG and capacity
signals.

### Output contract

```jsonc
{
  "healthy": false,
  "primary":   { "failure", "confidence", "severity", "root_cause", "fix", "evidence" },
  "secondary": [ /* other detected issues, ranked */ ],
  "signals":   { /* the 8-metric vector */ },
  "explanation": "human-readable text"
}
```

## Level 2 — one-line SDK wrapper

Wrap your existing OpenAI or Anthropic client and every call is auto-diagnosed
in the background — no call-site changes, no added request latency
(~0.004ms overhead; diagnosis runs on a worker thread).

```python
from openai import OpenAI
from debugai import wrap_llm, retrieval_context

client = wrap_llm(OpenAI(), on_diagnosis=lambda d: print(d["primary"]))

# Attach RAG context either via a context manager around your retriever...
with retrieval_context(chunks, similarity_scores=scores):
    client.chat.completions.create(model="gpt-4o", messages=[...])

# ...or inline as debugai_* kwargs (stripped before the real SDK call):
client.chat.completions.create(
    model="gpt-4o", messages=[...],
    debugai_chunks=chunks, debugai_similarity_scores=scores,
)

# Inspect recent diagnoses without a callback:
client.debugai.recent          # list of diagnosis dicts
client.debugai.flush()         # block until the queue drains
```

`wrap_llm` auto-detects the provider (OpenAI `.chat.completions.create` /
Anthropic `.messages.create`) and captures the Core IO, metadata, and runtime
data groups; retrieval is attached via the mechanisms above. Pass
`explain_with_llm=True` to also run the Layer-3 explainer, `sample_rate` to
diagnose a fraction of traffic, and `context_window` to enable capacity signals.

## Deploy (Docker)

```bash
cp .env.example .env        # optional: add OPENAI_API_KEY / ANTHROPIC_API_KEY / hardening
docker compose up --build   # → http://localhost:8000
```

- **Multi-stage image:** a Node stage builds the frontend bundles; the Python
  runtime installs **CPU-only torch** and **bakes the signal models** in, so the
  container runs fully offline (no model downloads at start). Expect a large
  image (~2–3 GB) — it's an ML app.
- **Persistence:** all state (diagnoses, traces, calibration, **user accounts**)
  is written to `DEBUGAI_DATA_DIR` (`/data` in the image), mounted as the
  `debugai-data` volume — survives restarts and rebuilds.
- **TLS:** terminate at a reverse proxy (nginx/Caddy) or pass
  `DEBUGAI_SSL_CERT`/`DEBUGAI_SSL_KEY`. Set `DEBUGAI_TRUST_PROXY=1` behind a proxy.
- Config is via env (see `.env.example` and the **Security & robustness** table).

## Accounts & multi-tenancy

The web app has full authentication — register, log in, manage your account —
and every account's data is **private**.

- **Auth:** `server/auth.py` — users + server-side sessions in a stdlib
  `sqlite3` DB, passwords hashed with **scrypt** + per-user salt, an httpOnly
  `SameSite=Lax` session cookie (`Secure` under HTTPS). Logout and account
  deletion revoke sessions server-side.
- **Pages:** `/register`, `/login`, `/account` (update name/email/password,
  log out, delete account). `/dashboard` and `/playground` redirect to `/login`
  when signed out.
- **Per-user isolation:** diagnoses, traces, sessions, and adaptive calibration
  are all scoped to the signed-in account (`owner`); a new account starts with
  its own auto-seeded sample data and can never see another user's data.
  Deleting an account purges all of its data.
- **API:** `POST /api/auth/register|login|logout`, `GET /api/auth/me`,
  `PATCH /api/account`, `DELETE /api/account`. All `/api/*` data endpoints
  require a valid session (this supersedes the older `DEBUGAI_API_KEY` gate).

### API tokens (programmatic access)

Mint per-account tokens under **Account → API tokens** (or `POST
/api/account/tokens`). A token authenticates `/api/*` as your account via
`X-API-Key: <token>` or `Authorization: Bearer <token>` — only its hash is
stored, and the plaintext is shown once. This lets the SDK stream traces to your
own server:

```python
from openai import OpenAI
from debugai import wrap_llm, http_trace_sink

client = wrap_llm(OpenAI(), on_trace=http_trace_sink(
    "http://localhost:8000/api/traces", token="dbg_…"))
client.chat.completions.create(...)   # → diagnosis + trace land in your dashboard
```

Tokens are revocable (`DELETE /api/account/tokens/{id}`) and are purged when the
account is deleted.

## Web app (Step 6)

A FastAPI backend serves the site built entirely on the `Debug_AI/` design
system:

```bash
uvicorn server.app:app --reload
# home page → http://127.0.0.1:8000/         (public marketing page)
# register  → http://127.0.0.1:8000/register (create an account, then you're in)
# dashboard → http://127.0.0.1:8000/dashboard (requires login)
```

- **`/` — home / landing.** The marketing page (animated signal-flow hero, how-it-works
  pipeline, features, CTA) adapted to the real LLM product; every nav link and CTA
  routes into the dashboard.
- **`/dashboard` — the app.** Ranked diagnosis cards with the 8-signal breakdown +
  confidence + fix (`DiagnosticCard` + `SignalIndicator`), filter by failure type, live
  stats, an adaptive-calibration strip, and a per-card **Propose fix** button. Seeds the
  20 labeled cases on first run so the board isn't empty.

### Observability (traces · sessions · cost)

A native, Langfuse-style observability layer. The dashboard's **Traces** tab
shows each request as a trace with a span waterfall (retrieval → generation),
rolled-up latency / tokens / **estimated cost**, and DebugAI's diagnosis attached
as **scores** (`healthy`, `failure`, `confidence`). The **Sessions** tab groups
traces into conversations; a metrics strip shows p50/p95 latency, tokens, and cost.

| Endpoint | Purpose |
|---|---|
| `POST /api/traces` | ingest a trace (from the SDK or any client) |
| `GET /api/traces` · `/api/traces/{id}` | list / detail |
| `GET /api/sessions` | per-session rollups |
| `GET /api/observability/stats` | aggregate latency / tokens / cost |

**Auto-trace from the SDK** — one line gives you traces *and* diagnoses:

```python
from debugai import wrap_llm, session

client = wrap_llm(OpenAI(), on_trace=requests.post_to("/api/traces"))
with session("conv-42"):                       # group a conversation
    client.chat.completions.create(...)        # → trace + spans + scores, async
```

`debugai/tracing.py` is also usable standalone (`Tracer`, `Trace`, `Span`,
`Score`, cost table) for manual instrumentation.

### Playground

`/playground` is a live editor: tweak the system prompt, query, output, chunks,
scores, or temperature and the diagnosis + signal bars update as you type
(`POST /api/playground`, non-storing). When a fix is proposed you can **apply it
to the system prompt** in place and re-analyze — the interactive
diagnose → fix → re-check loop.

### "Debug a bug" workbench

Hit **+ Debug a bug** on the dashboard (or `POST /api/debug`) to paste a real
failing case and get a one-shot diagnosis **and** verified fix:

> Describe the issue (e.g. *"my chatbot answers from outside the retrieved
> context"*), paste the system prompt, the user query, the bad output, and the
> retrieved chunks (+ optional similarity scores / temperature / context
> window). DebugAI computes the signals, names the failure, then the matching
> fix agent proposes a repair, runs the regression suite, and re-diagnoses — all
> shown inline. "Load example" fills a sample hallucination case.

Both pages load React via CDN and the compiled design-system bundle from the `/ds`
mount — the same pattern as the original template.

### LangChain integration

Drop the callback handler onto any LangChain run to auto-diagnose it — it
captures the retrieved documents + the LLM prompt/output and runs `analyze()`:

```python
from debugai.integrations import DebugAICallbackHandler

handler = DebugAICallbackHandler(on_diagnosis=lambda d: print(d["primary"]))
chain.invoke(question, config={"callbacks": [handler]})
print(handler.last)          # the most recent diagnosis
```

Importable with or without `langchain` installed; diagnosis failures never
break the chain. (Without retriever scores it can't judge retrieval quality, but
it still catches ungrounded answers — hallucination / entity gap.)

### Adaptive thresholds (§7.2)

`debugai/calibration.py` provides a per-user `ThresholdStore` that learns a
"known good" baseline from healthy requests and tightens the gating thresholds
to that user's norms:

| Regime | Requests | Method |
|---|---|---|
| cold | < 50 | sensible defaults |
| warm | 50–500 | percentile (5th / 95th of healthy baseline) |
| hot | > 500 | rolling-window z-score (mean ± 2σ) |

A signal is only adapted after `MIN_SAMPLES` healthy observations, every value
is clamped to a sane band, and a signal that's never exercised (all-zero
baseline) keeps its default. The dashboard's **Adaptive thresholds** strip shows
the live regime and each `default → calibrated` shift; `GET /api/thresholds`
returns the full report. The server diagnoses each request with
`tstore.current()` and feeds the result back, so calibration improves online.

API:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/analyze` | run the engine on a request, store + return the diagnosis (+ `ui` props) |
| `GET` | `/api/diagnoses?failure=` | recent diagnoses, optionally filtered |
| `GET` | `/api/stats` | counts by failure type |
| `DELETE` | `/api/diagnoses` | clear history |
| `POST` | `/api/seed` | (re)seed from the labeled dataset |

`server/ui_adapter.py` maps each diagnosis to design-system props (severity,
per-signal anomaly status vs thresholds, normalized confidence bars), so the
frontend stays a thin renderer.

## Instruction-adherence judge (behavioural failures)

Some failures aren't about retrieval or hallucination — e.g. a Socratic tutor
that **reveals the answer in the first turn** or **re-asks the same guiding
question**. These violate the *system prompt's own rules*, which the grounding
signals can't see. `debugai/judge.py` adds an **LLM-as-judge** that scores an
output against its system-prompt rules and reports the violations as an
`instruction_violation` diagnosis.

```python
analyze(prompt, output, system_prompt=tutor_rules, judge=True)
```

- **Judge model:** OpenAI by default (`DEBUGAI_JUDGE_MODEL`, default `gpt-5.5`)
  via `OPENAI_API_KEY`; falls back to a deterministic heuristic (question count,
  reveal-too-much, paraphrase-of-student) when no key is set, so it runs offline.
- **`SocraticTutorAgent`** handles `instruction_violation`: it rewrites the
  system prompt to enforce the broken rules, regenerates the response, and
  **re-judges** to confirm the fix — the corrected reply is shown in the
  dashboard. (Server runs the judge automatically whenever a system prompt is
  supplied.)

## Fix Agent Framework (Phase 2, §8)

`debugai/agents/` implements the universal **diagnose → generate-fix →
regression-test → re-diagnose → review** loop. The agent (fix + test
generation) is the only probabilistic step; it's sandwiched between
deterministic verification — if Layer 1+2 still detects the failure after the
fix, the agent knows it failed.

```python
from debugai import analyze
from debugai.agents import propose_fix
from debugai.schema import CaptureRecord

diag = analyze(prompt, output, chunks=..., similarity_scores=...)
report = propose_fix(diag, CaptureRecord(...), rerun=my_llm_callable)
print(report.verdict)          # verified | mitigated | failed | escalated | pending_rerun
print(report.diff, report.tests_passed, report.after_diagnosis)
```

`rerun(system_prompt, user_prompt, chunks, temperature) -> output` is injected,
so the framework has no hard LLM dependency (pass `None` to get the proposal +
test suite without executing them).

**Five built-in agents** (auto-selected by the registry):

| Agent | Handles | Strategy | Verdict behavior |
|---|---|---|---|
| Prompt Rule | hallucination | grounding constraints + "say not found" | verified when fabrication stops |
| Knowledge Base | retrieval failure | re-chunk + interim guard | **mitigated** (real fix is pipeline-side) |
| Constraint | prompt brittleness | lower temperature + format template + few-shot | verified when variance clears |
| Context Optimizer | context overflow | top-N chunks + summarize to fit window | verified when ratio drops |
| Document Patch | entity gap | flag the KB gap | **escalated** (no safe auto-fix) |

**Plugin architecture (§8.5):** custom agents register at the front and win
over built-ins:

```python
from debugai.agents import FixAgentRegistry
reg = FixAgentRegistry()
reg.register(SyllabusAgent("class10_cbse.pdf"))   # checked before built-ins
```

In the dashboard, every failing diagnosis card has a **Propose fix** button that
runs the loop (`POST /api/fix/{id}`) and shows the verdict, the diff, the
regression suite (pass/fail), and the before → after re-diagnosis. With
`ANTHROPIC_API_KEY` set the re-run uses Claude; otherwise a labeled
grounded-stub model drives the loop for the offline demo.

### LLM explainer (optional)

Set `ANTHROPIC_API_KEY` to get LLM-generated explanations
(`DEBUGAI_EXPLAINER_MODEL` defaults to `claude-haiku-4-5`). Without a key, the
explainer falls back to the deterministic detector text — everything still
works offline.

## Security & robustness

The web app is hardened for safe local/self-hosted use:

- **No HTML injection** — model- and input-derived text is stripped of markup
  server-side before it reaches the one `innerHTML` slot (`ui_adapter._plain`);
  everything else renders as escaped React text.
- **Bounded inputs** — request bodies are validated Pydantic models with length
  and item caps; `limit` query params are clamped to `[1, 500]`; trace ingest
  uses a constrained model that drops unknown/oversized fields.
- **No internal leakage** — engine/LLM exceptions are logged server-side and
  returned to clients as generic messages.
- **Crash-safe persistence** — JSON stores write via a temp file + atomic
  `os.replace`, so an interrupted write can't corrupt history.
- **No `eval`/`exec`/`pickle`**, no path traversal (ids are server-assigned),
  and the LLM re-run only activates with an explicit `ANTHROPIC_API_KEY`.
- Frontend a11y: keyboard-operable controls, `:focus-visible` rings, and
  error/loading/empty states throughout.

### Hardening a hosted deployment

Everything above is on by default. For a public/hosted instance, set these env
vars (the local demo needs none):

| Env var | Effect |
|---|---|
| `DEBUGAI_API_KEY` | require a matching `X-API-Key` header on every `/api/*` call (constant-time compare). The dashboard prompts for the key via the 🔑 button and stores it in `localStorage`. |
| `DEBUGAI_RATE_LIMIT` | per-client `/api/*` requests per minute (default 240); over-limit → `429` + `Retry-After`. |
| `DEBUGAI_TRUST_PROXY` | use the first `X-Forwarded-For` hop for client identity behind a reverse proxy. |
| `DEBUGAI_SSL_CERT` / `DEBUGAI_SSL_KEY` | serve HTTPS directly (`./run.sh`), or terminate TLS at a proxy (nginx/Caddy). |

Security headers (CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`,
COOP) are sent on every response. The CSP allows the unpkg CDN + inline/eval
because the dashboard transforms JSX in-browser; for a strict CSP, pre-compile
the JSX and drop the Babel/CDN script tags.

## Accuracy benchmark

```bash
python scripts/benchmark.py     # tests/dataset/failures.json + eval.json
```

Runs every labeled case through the engine and reports **overall accuracy, a
confusion matrix, and per-class precision/recall/F1**. Current: **93.8% (30/32)**
on the seed + held-out eval set (`entity_gap` 4/4 after the DeBERTa-v3 NLI
upgrade — see below). A `test_benchmark.py` guard fails CI if combined accuracy
drops below 80%.

The NLI signal uses **`cross-encoder/nli-deberta-v3-base`** rather than the
smaller MiniLM2: the latter emitted confident false-positive contradictions on
neutral attribute-additions (e.g. an answer adding "boot space" to a spec),
which misclassified `entity_gap` as `hallucination`. DeBERTa scores those ~0.00
contradiction while still catching real contradictions ~0.99.

### Deep-mode variance & Tier-3 NER

- **Measured variance (§7.5 Tier 2):** pass `variance_rerun=<callable>` (and
  `variance_runs`) to `analyze()` to replace the temperature proxy with a real
  measure — it re-runs the model N times and scores `1 − mean pairwise
  similarity` (signal `variance_method` becomes `"measured"`). Opt-in (costs N
  calls), for async/CI.
- **Tier-3 NER fallback (§7.1):** when spaCy + regex extract nothing, an LLM can
  extract entities — opt-in via `DEBUGAI_LLM_NER=1` (+ `OPENAI_API_KEY`), off by
  default so normal runs make no LLM calls.

## Tests

```bash
pytest -q
```

`tests/dataset/failures.json` holds 20 labeled failures (Step 0). The suite
asserts the rule engine meets the roadmap's **≥16/20 (80%)** acceptance bar —
it currently classifies **20/20**, and reproduces the doc's worked Scenario A
(retrieval failure, confidence 0.95).

## Roadmap status

- [x] Step 0 — 20 labeled failures (`tests/dataset/failures.json`)
- [x] Step 1 — signal extraction layer
- [x] Step 2 — rule engine
- [x] Step 3 — `analyze()` + LLM explainer (this MVP)
- [ ] Step 4 — test with 5 real users
- [x] Step 5 — SDK wrapper (`wrap_llm()`, Level 2)
- [x] Step 6 — dashboard (`server/`) + adaptive thresholds (`debugai/calibration.py`)
- [x] Phase 2 — fix-agent framework (`debugai/agents/`)
- [x] Observability — native traces / spans / sessions / scores / cost (`debugai/tracing.py`)
- [x] Playground + `debugai` CLI
- [ ] Phase 2b — community plugin registry + fix-success data sharing
