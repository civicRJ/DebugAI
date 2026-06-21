# DebugAI

[![CI](https://github.com/civicRJ/DebugAI/actions/workflows/ci.yml/badge.svg)](https://github.com/civicRJ/DebugAI/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-amber.svg)](LICENSE)

> A pip-installable LLM debugging SDK that tells you **why** an AI response failed, where the pipeline failed, and what fix to ship.

DebugAI is built around the Python SDK first. Wrap your LLM client or call
`debug_report()` directly, and DebugAI returns a product-level debug artifact:
failure type, failing layer, confidence, evidence, root cause, fix, verification
status, and a regression artifact. The hosted dashboard and traces are
supporting views, not the core workflow.

This repository includes the deterministic diagnosis core, the signal engine,
the rule engine, the `analyze()` API with an optional LLM explainer, the
`wrap_llm()` SDK wrapper, prompt vulnerability audit, pipeline trace analysis,
corpus evals, feedback calibration, and a web dashboard built on the
`Debug_AI/` design system.

## SDK quickstart

```bash
pip install debugerai
```

```python
from debugai import debug_report

report = debug_report(
    prompt="What is the refund policy for electronics?",
    output="Electronics can be returned within 90 days for a full cash refund.",
    chunks=["Our store hours are 9am to 5pm.", "Parking is behind the building."],
    similarity_scores=[0.42, 0.40],
    temperature=0.2,
)

print(report["failure"])       # retrieval_failure
print(report["evidence"])      # ['Mean similarity 0.41', ...]
print(report["fix"])           # specific repair guidance
```

Or wrap your existing client and diagnose calls in the background:

```python
from openai import OpenAI
from debugai import wrap_llm

client = wrap_llm(OpenAI(), on_diagnosis=lambda d: print(d["primary"]))
client.chat.completions.create(model="gpt-4o", messages=[...])
client.debugai.flush()
```

Try built-in debugger examples from the CLI:

```bash
debugai examples
debugai report --example schema_violation --json
debugai report cases.json --simulate
```

Debug an agent control loop with the SDK recorder:

```python
from debugai import agent_run

with agent_run(
    "refund-agent",
    goal="Check refund eligibility before answering",
    expected_tools=["lookup_policy"],
    max_steps=8,
) as run:
    run.plan("Need policy evidence before final answer.")
    run.tool_call("lookup_policy", {"sku": "opened-electronics"})
    run.tool_result("lookup_policy", "Opened electronics are not refundable.")
    run.final("Opened electronics can get a full refund.")

report = run.report()
print(report["primary"]["failure"])  # tool_result_ignored
print(report["fix"]["candidate"]["strategy"])
```

Audit a prompt before shipping it:

```python
from debugai import audit_prompt

audit = audit_prompt(
    system_prompt=system_prompt,
    use_case="Customer support RAG agent that can issue refunds",
    tools=["refund_order", "send_email"],
    retrieves_external_content=True,
    handles_secrets=True,
    high_risk_actions=["issue refunds", "send customer email"],
    dynamic=True,
)

print(audit["grade"], audit["risk_score"])
print(audit["issues"][0]["fix"])
print(audit["patched_prompt"])
```

## Architecture (implemented)

| Layer | Type | Module | What it does |
|------|------|--------|--------------|
| 1 — Signal Extraction | deterministic | `debugai/signals.py` | Computes the 8 core signals plus auxiliary pipeline/security fields (small CPU models + fallbacks, lazy eval) |
| 2 — Rule Engine | deterministic | `debugai/detectors.py`, `diagnosis.py` | Failure detectors across retrieval, grounding, tools, schema, prompt, safety, runtime → primary + secondary diagnosis |
| 3 — LLM Explainer | probabilistic | `debugai/explainer.py` | Translates the diagnosis into human-readable explanation + fix (Claude; deterministic fallback) |
| API | — | `debugai/analyze.py` | Level-1 single-call entry point |

**Detection is deterministic; only the explanation uses an LLM.** Healthy
requests fail open (no LLM tokens, no cost).

### Signal coverage
context-output overlap · entity coverage · retrieval similarity · contradiction
(NLI) · output variance (proxy) · latency · token-usage ratio · context-length
ratio.

Auxiliary fields add stage and safety visibility: retrieval top score/margin,
retrieval entropy, query drift, chunk redundancy, claim support, retrieval
coverage, context dilution, source conflict, freshness gap, tool-argument risk,
instruction conflict, and refusal behavior.

### Detector layers
runtime · schema · tool execution · retrieval · citation · knowledge-base gaps ·
grounding/hallucination · prompt brittleness/ambiguity · prompt injection ·
sensitive data leakage. All run; results are ranked by confidence; gate patterns
prevent nonsensical combinations.

### Prompt and pipeline debugging

- `audit_prompt()` scans system prompts for weak wording, answering/safety
  conflicts, missing trust boundaries, tool approval gaps, secret-handling gaps,
  schema gaps, and optional dynamic attack probes.
- `analyze_pipeline()` diagnoses query rewrite, retrieval, tool execution,
  generation, and validation traces so you can fix the first bad stage instead
  of only staring at the final answer.
- `agent_run()` records agent plans, tool calls, observations, approvals,
  handoffs, memory reads/writes, and final answers; `agent_report()` diagnoses
  loops, wrong tools, missing tools, ignored tool results, approval gaps,
  planner drift, memory contradictions, handoff failures, unsafe tool inputs,
  and runaway budgets.
- `evaluate_corpus_file()` scores a labeled failure corpus for CI and regression
  tracking.
- `FeedbackTracker` records whether users accepted a diagnosis and whether the
  proposed fix worked.

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
debugai report --example tool_call_failure
debugai examples                       # list built-in debugger cases
debugai fix cases.json --simulate      # diagnose + propose & verify a fix
debugai audit-prompt --system @prompt.txt --use-case "support RAG bot" --tool refund_order --dynamic
debugai eval failures.json             # score a labeled failure corpus
debugai pipeline trace.json --json     # find the failing stage in a pipeline trace
debugai agent agent_trace.json --json  # find the failing step in an agent loop
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

`debug_report()` returns the SDK-level artifact most apps should log or display:

```jsonc
{
  "status": "failing",
  "failure": "tool_call_failure",
  "confidence": 0.8,
  "severity": "critical",
  "root_cause": "The agent/tool contract failed...",
  "evidence": ["Expected one of ['search'] but no tool call was made."],
  "fix": "Constrain tool selection...",
  "diagnosis": { /* full analyze() result */ },
  "fix_report": { "verdict": "mitigated", "agent": "Tool Contract Agent" }
}
```

`analyze()` returns the lower-level diagnosis object:

```jsonc
{
  "healthy": false,
  "primary":   { "failure", "confidence", "severity", "root_cause", "fix", "evidence" },
  "secondary": [ /* other detected issues, ranked */ ],
  "signals":   { /* the 8-metric vector */ },
  "explanation": "human-readable text"
}
```

Pipeline and corpus APIs:

```python
from debugai import agent_report, analyze_pipeline, evaluate_corpus_file

pipeline = analyze_pipeline([
    {"id": "rewrite", "kind": "query_rewrite", "input": user_prompt, "output": retrieval_query},
    {"id": "retrieval", "kind": "retrieval", "input": retrieval_query, "chunks": chunks, "similarity_scores": scores},
    {"id": "generation", "kind": "generation", "output": llm_output, "chunks": chunks, "similarity_scores": scores},
], system_prompt=system_prompt, user_prompt=user_prompt)

agent = agent_report({
    "goal": "Resolve refund request",
    "expected_tools": ["lookup_policy"],
    "events": [
        {"type": "tool_call", "tool": "lookup_policy", "args": {"sku": "opened-electronics"}},
        {"type": "tool_result", "tool": "lookup_policy", "output": "Opened electronics are not refundable."},
        {"type": "final", "output": "Opened electronics can get a full refund."},
    ],
})

eval_result = evaluate_corpus_file("failures.json")
```

`debug_report()` also returns a `regression_artifact` containing a portable
test skeleton that teams can save in CI after applying a fix.

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

### SDK parameters

`analyze()` is the lowest-level diagnosis call. Only `prompt` and `output` are
required; everything else improves a specific signal or detector.

| Parameter | Type | Purpose |
|---|---|---|
| `prompt` | `str` | User prompt / query. Required. |
| `output` | `str` | LLM response to diagnose. Required. |
| `system_prompt` | `str` | System/developer rules; enables instruction-adherence judging when `judge=True`. |
| `chunks` | `list[str]` | Retrieved context chunks used for RAG grounding checks. |
| `similarity_scores` | `list[float]` | Retriever scores aligned with `chunks`; drives retrieval-failure signals. |
| `retrieval_query` | `str` | Query used by the retriever; useful when different from `prompt`. |
| `expected_output` | `str` | Optional expected answer/reference for comparison. |
| `model_name` | `str` | Model identifier attached to the diagnosis metadata. |
| `temperature` | `float` | Generation temperature; used by prompt-brittleness signals. |
| `max_tokens` | `int` | Requested output budget. |
| `context_window` | `int` | Model context limit; enables context-overflow detection. |
| `latency_ms` | `int` | End-to-end latency; contributes to capacity/overflow signals. |
| `token_usage` | `dict[str, int]` | Token counts, usually `{"prompt": n, "completion": n, "total": n}`. |
| `tool_calls` | `list[dict]` | Actual tool/function calls returned by the model. |
| `tools_expected` | `list[str]` | Tool/function names the model was expected to call. |
| `response_schema` | `dict` | JSON Schema used to detect structured-output violations. |
| `thresholds` | `Thresholds` | Override detector thresholds for this call. |
| `explain_with_llm` | `bool` | Run the optional LLM explainer. Defaults to `True` for `analyze()`. |
| `lazy` | `bool` | Skip expensive signals when cheap signals already look healthy. |
| `judge` | `bool` | Run instruction-adherence judge against `system_prompt`. |
| `judge_model` | `str` | Override the judge model. |
| `openai_api_key` | `str` | API key used by the judge. Falls back to env config. |
| `anthropic_api_key` | `str` | API key used by the explainer. Falls back to env config. |
| `variance_rerun` | `callable` | Callable used to re-run the model for measured variance. |
| `variance_runs` | `int` | Number of measured-variance re-runs. Defaults to `3`. |

`debug_report()` accepts the same capture fields as `analyze()` and adds:

| Parameter | Type | Purpose |
|---|---|---|
| `run_fix` | `bool` | Run the matching fix agent and include `fix_report`. Defaults to `True`. |
| `rerun` | `callable` | Optional model re-run function for fix verification. |
| `explain_with_llm` | `bool` | Pass through to `analyze()` for LLM-generated explanations. |

`wrap_llm()` accepts either individual kwargs or a `DebugAIConfig` object:

| Parameter | Type | Purpose |
|---|---|---|
| `client` | provider client | OpenAI-compatible, Anthropic, Cohere, or registered custom client. |
| `config` | `DebugAIConfig` | Full SDK configuration object. |
| `on_diagnosis` | `callable` | Callback receiving each diagnosis dict. |
| `on_trace` | `callable` | Callback receiving each trace object. |
| `session_id` | `str` | Default trace/session id for wrapped calls. |
| `explain_with_llm` | `bool` | Legacy shortcut for `DebugAIConfig(enable_explain=True)`. |
| `context_window` | `int` | Context window applied to wrapped-call diagnoses. |
| `thresholds` | `Thresholds` | Detector threshold override. |
| `sample_rate` | `float` | Fraction of calls to diagnose/trace, from `0.0` to `1.0`. |

`awrap_llm()` is the async equivalent. It accepts the same wrapper parameters
except `explain_with_llm`; set `DebugAIConfig(enable_explain=True)` when async
background explanations are needed.

`debugai.completion()` / `debugai.acompletion()` provide a universal provider
router:

| Parameter | Type | Purpose |
|---|---|---|
| `model` | `str` | Model name; routed by prefix such as `gpt-`, `claude-`, `groq/`, `ollama/`, `openrouter/`, etc. |
| `messages` | `list` | Chat messages passed to the provider. |
| `config` | `DebugAIConfig` | Per-call SDK configuration; falls back to `set_default_config(...)` or defaults. |
| `**kwargs` | provider kwargs | Forwarded to the provider, including `temperature`, `max_tokens`, `tools`, `response_format`, `stream`, and provider-specific options. |

Per-call `debugai_*` kwargs can be passed directly to the wrapped provider call;
DebugAI strips them before forwarding the request:

| Kwarg | Purpose |
|---|---|
| `debugai_chunks` | Retrieved chunks for this one call. |
| `debugai_similarity_scores` | Similarity scores aligned with `debugai_chunks`. |
| `debugai_retrieval_query` | Retriever query for this one call. |

Context helpers:

| Helper | Parameters | Purpose |
|---|---|---|
| `retrieval_context(...)` | `chunks`, `similarity_scores=None`, `retrieval_query=None` | Attach RAG context to all wrapped calls inside the block. |
| `session(...)` | `session_id` | Group wrapped calls into one conversation/session. |
| `http_trace_sink(...)` | `url`, `token=None`, `timeout=5.0` | Build an `on_trace` callback that POSTs traces to a DebugAI server. |

`DebugAIConfig` controls the background SDK behavior:

| Field | Default | Purpose |
|---|---:|---|
| `enable_diagnosis` | `True` | Run the signal engine and detectors. |
| `enable_traces` | `True` | Emit traces with spans, scores, latency, tokens, and cost. |
| `enable_judge` | `False` | Run instruction-adherence judge. |
| `enable_explain` | `False` | Run LLM explainer in background diagnoses. |
| `lazy` | `True` | Avoid expensive signals when not needed. |
| `sample_rate` | `1.0` | Diagnose/trace only a fraction of traffic. |
| `max_queue_depth` | `10000` | Drop excess background jobs instead of slowing LLM calls. |
| `track_tokens` | `True` | Accumulate token usage metrics. |
| `track_cost` | `True` | Estimate and accumulate request cost. |
| `track_latency` | `True` | Track latency metrics. |
| `on_diagnosis` | `None` | Diagnosis callback. |
| `on_trace` | `None` | Trace callback. |
| `on_metrics` | `None` | Per-request metrics callback. |
| `sink_url` | `None` | POST traces to a DebugAI server. |
| `sink_token` | `None` | API token for `sink_url`. |
| `session_id` | `None` | Default session id. |
| `tags` | `{}` | Tags attached to traces/diagnoses. |
| `thresholds` | defaults | Detector threshold overrides. |
| `ollama_base_url` | `http://localhost:11434/v1` | Local Ollama-compatible endpoint. |
| `model_prices` | `None` | Override pricing table for cost estimates. |
| `fallbacks` | `[]` | Fallback models for `debugai.completion()`. |
| `response_schema` | `None` | Schema validation for structured outputs. |
| `on_schema_violation` | `None` | Callback for schema violations. |
| `budget_usd` | `None` | Soft spend cap for `debugai.completion()`. |
| `on_budget_exceeded` | `None` | Callback when budget is exhausted. |
| `cache_ttl_seconds` | `None` | Cache identical `completion()` requests. |
| `max_retries` | `2` | Retry transient provider failures. |
| `retry_backoff_seconds` | `1.0` | Base retry backoff. |
| `latency_sla_ms` | `None` | Alert threshold for slow calls. |
| `on_sla_breach` | `None` | Callback for latency SLA breaches. |

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
  its own workspace and can never see another user's data. Sample data loads
  only when requested, so the dashboard does not spend first-page-load time
  diagnosing demo cases.
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

## Web app

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
  stats, an adaptive-calibration strip, and a per-card **Propose fix** button. The
  **Load sample data** button seeds representative cases, including schema, tool,
  citation, ambiguity, RAG, and grounding failures.

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

`/playground` is a live workbench with two modes:

- **Output debugger:** tweak the system prompt, query, output, chunks, scores,
  schema, tools, or temperature and the diagnosis + signal bars update as you
  type (`POST /api/playground`, non-storing). When a fix is proposed you can
  apply it to the system prompt in place and re-analyze.
- **Prompt audit:** paste a system prompt plus use-case context, tools, external
  content settings, secrets, schema, and high-risk actions. DebugAI returns
  vulnerabilities, attack probes, risk score, grade, and a patched prompt
  (`POST /api/prompt-audit`, non-storing).

### "Debug a bug" workbench

Hit **+ Debug a bug** on the dashboard (or `POST /api/debug`) to paste a real
failing case and get a one-shot diagnosis **and** verified fix:

> Describe the issue (e.g. *"my chatbot answers from outside the retrieved
> context"*), paste the system prompt, the user query, the bad output, and the
> retrieved chunks (+ optional similarity scores / temperature / context
> window). DebugAI computes the signals, names the failure, then the matching
> fix agent proposes a repair, runs the regression suite, and re-diagnoses — all
> shown inline. "Load example" fills a sample hallucination case.

Both pages load vendored React and the compiled design-system bundle from the
`/ds` mount, so the local app runs without CDN access.

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

### Adaptive thresholds

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
| `POST` | `/api/seed` | load sample debugging cases |

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

## Fix Agent Framework

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

**Built-in agents** (auto-selected by the registry):

| Agent | Handles | Strategy | Verdict behavior |
|---|---|---|---|
| Prompt Rule | hallucination | grounding constraints + "say not found" | verified when fabrication stops |
| Knowledge Base | retrieval failure | re-chunk + interim guard | **mitigated** (real fix is pipeline-side) |
| Constraint | prompt brittleness | lower temperature + format template + few-shot | verified when variance clears |
| Context Optimizer | context overflow | top-N chunks + summarize to fit window | verified when ratio drops |
| Document Patch | entity gap | flag the KB gap | **escalated** (no safe auto-fix) |
| Schema Repair | schema violation | strict JSON/schema mode + repair retry | verified when schema validation clears |
| Tool Contract | tool call failure | enforce allowed tools + validate arguments | **mitigated** unless a tool-capable rerun verifies it |
| Citation Verifier | citation failure | require retrieved chunk IDs only | verified when citation checks clear |
| Ambiguity Gate | ambiguous prompt | ask a clarifying question before answering | verified when the model clarifies |
| Socratic Tutor | instruction violation | tighten behavioral rules and re-judge | verified when the judge clears |

**Plugin architecture:** custom agents register at the front and win
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

Everything above is on by default. For a public/hosted instance, use account
login plus per-account API tokens for programmatic ingest. The local demo needs
none.

| Env var | Effect |
|---|---|
| `DEBUGAI_KEY_SECRET` | encrypts stored user LLM keys; required in production when users save provider keys. |
| `DEBUGAI_STRICT_CSRF` | require same-origin unsafe API requests when using session cookies. Enabled automatically with `DATABASE_URL`. |
| `DEBUGAI_RATE_LIMIT` | per-client `/api/*` requests per minute (default 240); over-limit → `429` + `Retry-After`. |
| `DEBUGAI_AUTH_RATE_LIMIT` | stricter auth endpoint rate limit (default 30/min; set `0` only for local testing). |
| `DEBUGAI_TRUST_PROXY` | use the first `X-Forwarded-For` hop for client identity behind a reverse proxy. |
| `DEBUGAI_SSL_CERT` / `DEBUGAI_SSL_KEY` | serve HTTPS directly (`./run.sh`), or terminate TLS at a proxy (nginx/Caddy). |

Security headers (CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`,
COOP) are sent on every response. The frontend is precompiled and uses vendored
React, so no CDN is required at runtime.

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

- **Measured variance:** pass `variance_rerun=<callable>` (and
  `variance_runs`) to `analyze()` to replace the temperature proxy with a real
  measure — it re-runs the model N times and scores `1 − mean pairwise
  similarity` (signal `variance_method` becomes `"measured"`). Opt-in (costs N
  calls), for async/CI.
- **NER fallback:** when spaCy + regex extract nothing, an LLM can
  extract entities — opt-in via `DEBUGAI_LLM_NER=1` (+ `OPENAI_API_KEY`), off by
  default so normal runs make no LLM calls.

## Tests

```bash
pytest -q
```

`tests/dataset/failures.json` holds 20 labeled failures. The suite asserts the
rule engine stays above the **80%** acceptance bar — it currently classifies
**20/20**, and reproduces the worked Scenario A (retrieval failure, confidence
0.95).
