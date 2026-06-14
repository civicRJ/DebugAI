# DebugAI Features

DebugAI is an AI observability and debugging platform for LLM applications. It diagnoses why an LLM response failed, explains the root cause, proposes a concrete fix, and records the request as an observability trace.

## Core Diagnosis Engine

- Single-call `analyze()` API for diagnosing a prompt/output pair.
- Unified `CaptureRecord` schema for core IO, retrieval context, model metadata, runtime metrics, context-window hints, tool-call metadata, and structured-output schema contracts.
- Deterministic signal extraction before classification.
- Healthy fail-open behavior: requests with no detected failure avoid unnecessary LLM explanation cost.
- Optional lazy mode that skips expensive model-backed checks when cheap signals are already healthy.
- Optional deep variance mode that reruns a model multiple times to measure output instability.

## Signal Extraction

DebugAI computes an eight-signal vector for each request:

- Context-output overlap.
- Entity coverage.
- Retrieval similarity.
- Contradiction probability.
- Output variance.
- Latency.
- Token-usage ratio.
- Context-length ratio.

Signal implementation features:

- Semantic overlap via sentence-transformer embeddings, with token-overlap fallback.
- Entity extraction via spaCy NER, regex fallback, and optional LLM NER fallback.
- Retrieval similarity from supplied scores or recomputed query/chunk embeddings.
- NLI contradiction detection via local cross-encoder or optional Hugging Face Inference API mode.
- Pure-Python fallbacks when models are unavailable.
- Runtime ratio calculations from supplied token usage or approximate token counts.

## Failure Detection

The deterministic rule engine runs all detectors and ranks fired failures by confidence:

- `context_overflow`
- `schema_violation`
- `tool_call_failure`
- `retrieval_failure`
- `citation_failure`
- `entity_gap`
- `hallucination`
- `prompt_brittleness`
- `ambiguous_prompt`
- `instruction_violation` through the optional instruction-adherence judge.

Each diagnosis returns:

- `healthy`
- `primary` failure
- `secondary` failures
- confidence
- severity
- root cause
- actionable fix
- evidence
- full signal vector
- explanation text

## LLM Explanation

- Optional Anthropic-powered explainer for human-readable root-cause summaries.
- Deterministic fallback explanation when no LLM key is configured.
- Per-user Anthropic key support in the hosted app.
- Explanation output can replace deterministic fix text when a live explainer is enabled.

## Instruction-Adherence Judge

- Optional LLM-as-judge mode for behavior and system-prompt compliance failures.
- OpenAI-backed JSON judge when a key is available.
- Deterministic heuristic fallback when no key is configured.
- Designed to catch failures that grounding signals cannot detect, such as Socratic tutors revealing answers too early.
- Merges judge results into the regular diagnosis ranking.

## Fix Agents

DebugAI includes built-in fix agents for diagnosed failure types:

- Prompt Rule Agent for hallucination.
- Knowledge Base Agent for retrieval failure.
- Constraint Agent for prompt brittleness.
- Context Optimizer Agent for context overflow.
- Document Patch Agent for entity gaps.
- Socratic Tutor Agent for instruction violations.
- Schema Repair Agent for invalid JSON or schema-breaking structured outputs.
- Tool Contract Agent for missing tools, malformed arguments, unexpected tools, and tool error states.
- Citation Verifier Agent for missing or out-of-range source references.
- Ambiguity Gate Agent for underspecified prompts where the model should ask a clarifying question.

Fix-agent capabilities:

- Generate deterministic fix candidates.
- Produce system prompt additions, temperature changes, chunk limits, or escalation notes.
- Build regression and variance test cases.
- Optionally rerun a model to verify whether the fix clears the diagnosis.
- Return fix reports with verdicts, diffs, tests passed, re-diagnosis output, and corrected output.

## SDK Wrappers

- `wrap_llm()` for synchronous SDK instrumentation.
- `awrap_llm()` for async SDK instrumentation.
- Transparent proxy around existing clients so call sites can remain unchanged.
- Background diagnosis worker so diagnosis does not block the original LLM request.
- `retrieval_context()` context manager for attaching RAG chunks and similarity scores.
- `session()` context manager for grouping traces into conversations.
- Inline `debugai_chunks`, `debugai_similarity_scores`, and `debugai_retrieval_query` kwargs.
- Automatic expected-tool extraction from OpenAI-style `tools` and legacy `functions` request parameters.
- Captured tool-call spans and tool-call failure diagnosis in the same background worker.
- Response-schema forwarding into diagnosis and post-fix re-verification.
- Recent diagnosis and trace inspection via `client.debugai.recent` and `client.debugai.recent_traces`.
- Queue flushing for tests and shutdown.

Supported SDK adapters:

- OpenAI chat completions.
- Anthropic messages.
- OpenAI-compatible clients.
- Cohere ClientV2.
- Custom adapters via `register_adapter()`.

## Universal Completion API

- `completion()` helper for provider-routed LLM calls.
- `acompletion()` async helper.
- Normalized `CompletionResponse` with text, usage, cost, latency, model, raw response, cache status, retry count, and correlation ID.
- Model comparison with `compare()`.
- Custom provider registration with `register_provider()`.
- Default configuration via `set_default_config()`.

Provider routing supports:

- OpenAI.
- Anthropic.
- Google Gemini through OpenAI-compatible endpoint.
- Groq.
- Together AI.
- Mistral AI.
- OpenRouter.
- Azure OpenAI.
- Cohere.
- Ollama and local model families such as Qwen, Llama, Phi, DeepSeek, Gemma, Mixtral, Vicuna, and CodeLlama.

## SDK Controls

`DebugAIConfig` controls:

- Diagnosis enablement.
- Trace enablement.
- Judge enablement.
- LLM explanation enablement.
- Lazy signal evaluation.
- Sampling rate.
- Worker queue depth.
- Token, cost, and latency tracking.
- Diagnosis, trace, and metrics callbacks.
- HTTP trace sink URL and token.
- Session ID and tags.
- Custom thresholds.
- Ollama base URL.
- Custom model pricing.
- Fallback models.
- Response schema validation.
- Expected tool-call validation.
- Budget limit.
- TTL response cache.
- Retries and backoff.
- Latency SLA alert callback.

## Observability

- Native `Trace`, `Span`, `Score`, and `Tracer` primitives.
- Generation, retrieval, tool, and generic spans.
- Session grouping for conversations.
- Diagnosis converted into trace scores.
- Trace status derived from diagnosis health.
- Cost estimation from built-in model pricing table.
- Token, cost, latency, failure, and cache rollups.
- `http_trace_sink()` for sending SDK traces to a DebugAI server.

## Metrics

- Thread-safe global metrics ledger.
- Per-model request counts.
- Prompt, completion, and total token counters.
- Cost accumulation.
- Failure counts.
- Cache hit/miss counts.
- p50 and p95 latency.
- JSON-serializable snapshots.
- Reset support for tests and reporting windows.

## LangChain Integration

- `DebugAICallbackHandler` for LangChain runs.
- Captures retrieved documents.
- Captures prompt and generated output.
- Runs `analyze()` when the LLM completes.
- Exposes the most recent diagnosis.
- Supports diagnosis callbacks.
- Works as a LangChain callback when LangChain is installed and as a plain object otherwise.

## CLI

The `debugai` command provides:

- `debugai analyze` for diagnosing one prompt/output pair.
- `debugai diagnose` for diagnosing JSON case files.
- `debugai fix` for diagnose/fix/verify workflows.
- `debugai serve` for launching the web app.
- JSON output mode for diagnosis commands.
- Simulated fix reruns for offline demos.

## Web Application

The FastAPI app includes:

- Public home page.
- Pricing page.
- Register page.
- Login page.
- Account page.
- Dashboard.
- Playground.
- Admin page for staff users.
- Invite acceptance page.
- Static design system mount.
- Static frontend bundle serving.

Dashboard and workbench features:

- Recent diagnosis list.
- Failure filtering and search.
- Failure counts and stats.
- Observability stats.
- Trace list and sessions.
- Threshold calibration details.
- One-shot debug endpoint that can diagnose and propose fixes.
- Live playground analysis without storing every edit.
- Save playground cases to diagnoses.
- Seed sample data.
- Clear personal diagnosis and trace history.

## Server API

Authentication and account:

- Register.
- Login.
- Logout.
- Current user lookup.
- Account update.
- Account deletion.
- API token creation, listing, and revocation.
- Programmatic auth via `X-API-Key` or `Authorization: Bearer`.
- Encrypted per-user OpenAI and Anthropic key storage.

Diagnosis:

- `POST /api/analyze`
- `GET /api/diagnoses`
- `GET /api/stats`
- `GET /api/thresholds`
- `DELETE /api/diagnoses`
- `POST /api/debug`
- `POST /api/playground`
- `POST /api/fix/{diagnosis_id}`
- `POST /api/seed`

Tracing:

- `POST /api/traces`
- `GET /api/traces`
- `GET /api/traces/{trace_id}`
- `GET /api/sessions`
- `GET /api/observability/stats`

Organizations and workspaces:

- Create organizations.
- List organizations.
- Get organization members.
- Remove organization members.
- Invite organization members.
- Accept organization invites.
- Switch between personal and organization workspaces.
- Read active workspace.

Admin:

- Staff-only admin page.
- Staff-only aggregate user, diagnosis, and trace stats.

Health and debugging:

- Public health check.
- Dev-only auth debug endpoint when `DEBUG` is set.

## Authentication And Multi-Tenancy

- SQLite-backed auth locally, PostgreSQL-backed auth when `DATABASE_URL` is set.
- Server-side sessions.
- HTTP-only `SameSite=Lax` session cookie.
- Secure cookie handling behind trusted proxies.
- Password hashing with scrypt and per-user salt.
- Per-user data isolation for diagnoses, traces, sessions, calibration, and keys.
- Account deletion purges owned data.
- Organization workspaces with owner, admin, and member roles.
- Invite tokens with expiration.
- Optional invite and welcome email support through Resend.

## Storage

- JSON-file diagnosis and trace stores for local development.
- PostgreSQL diagnosis and trace stores in production when `DATABASE_URL` is configured.
- Rolling 500-item window per store.
- Atomic JSON writes.
- Per-owner filtering.
- Failure filtering.
- Text search over prompt, output, issue, label, and failure type.
- Purge and clear operations.

## Adaptive Calibration

- Per-user `ThresholdStore`.
- Cold, warm, and hot calibration regimes.
- Healthy-request baseline learning.
- Percentile-based thresholds in warm mode.
- Rolling-window z-score thresholds in hot mode.
- Threshold clamp bands to prevent runaway calibration.
- Dashboard details for regime, request counts, baselines, and adapted signals.
- Reset support.

## Security And Robustness

- Security headers middleware.
- Strict content security policy for self-hosted scripts.
- Body size limit middleware.
- General API rate limiting.
- Stricter auth endpoint rate limiting.
- Optional legacy coarse `DEBUGAI_API_KEY` gate.
- Trusted proxy support for forwarded IP and cookie security.
- Input size caps for prompts, outputs, chunks, and metadata.
- Chunk length truncation on API input.
- Background workers protect request latency.
- Diagnosis worker queue drops jobs under backpressure instead of slowing production requests.

## Frontend

- React UI compiled with esbuild.
- Vendored React and ReactDOM for offline loading and strict CSP compatibility.
- No in-browser Babel.
- Design-system components under `Debug_AI/`.
- Dashboard, playground, auth, account, admin, invite, home, and pricing pages.
- Static bundles committed under `server/static/dist`.
- Build command: `npm run build`.

## Deployment

- FastAPI server via `debugai serve` or `uvicorn server.app:app`.
- Dockerfile and Docker Compose support.
- Render and Railway config files.
- Caddyfile for reverse proxy/TLS setups.
- Configurable data directory through `DEBUGAI_DATA_DIR`.
- PostgreSQL support through `DATABASE_URL`.
- Optional model-lite modes for constrained environments.
- Optional Hugging Face NLI API mode to avoid local NLI model memory use.

## Documentation And Examples

- README quickstart and architecture overview.
- Mintlify docs under `docs/`.
- SDK docs for `analyze`.
- Docker self-hosting docs.
- Failure overview docs.
- Demo script.
- Benchmark script.
- Test datasets for evaluation and sample data.

## Test Coverage

The test suite covers:

- Signal computation.
- Detector logic.
- Diagnosis ranking.
- Robustness edge cases.
- LLM judge behavior.
- Providers and universal completion routing.
- SDK wrapper behavior.
- Tracing and metrics.
- Calibration.
- Fix agents.
- LangChain integration.
- CLI commands.
- Server API.
- Auth and multi-tenancy.
- UI adapter behavior.
- Benchmark behavior.
