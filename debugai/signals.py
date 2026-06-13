"""Layer 1 — Signal Computation Engine (Architecture §4).

Computes the 8 deterministic signals that form the universal signal vector. Each
signal has a primary method (small ML model) and a deterministic fallback, per
the layered-computation design (§7.1). Signals that don't apply to a request
(e.g. retrieval signals on a non-RAG call) return a *healthy* sentinel so
downstream detectors don't misfire.

Lazy evaluation (§7.4): cheap signals compute first; expensive model-backed
signals (semantic overlap, NER, NLI) are skipped when the cheap signals already
look healthy and ``lazy=True``.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from dataclasses import asdict, dataclass

from debugai import models
from debugai.schema import CaptureRecord

log = logging.getLogger("debugai.signals")


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)

_WORD_RE = re.compile(r"[A-Za-z0-9']+")
# Fallback "entity" heuristic: capitalised tokens, numbers, and units/currency.
_ENTITY_RE = re.compile(r"\b([A-Z][A-Za-z0-9]+|\$?\d[\d,.]*%?)\b")
# Prompt-constraint markers that suppress output variance.
_CONSTRAINT_RE = re.compile(
    r"\b(only|must|exactly|do not|don't|never|always|format|json|"
    r"bullet|numbered|step[- ]by[- ]step|schema|template)\b",
    re.IGNORECASE,
)


@dataclass
class SignalVector:
    """The universal 8-metric interface (§6). Every request produces one."""

    overlap: float            # 0-1   context-output overlap
    entity_coverage: float    # 0-1   fraction of output entities grounded in context
    similarity: float         # 0-1   mean retrieval cosine
    contradiction: float      # 0-1   NLI contradiction probability
    variance: float           # 0-1   output variance (proxy estimate)
    latency_ms: float         # 0-inf end-to-end latency
    token_ratio: float        # 0-1   total tokens / model max
    context_ratio: float      # 0-1   prompt tokens / context window

    # Provenance flags (which path produced overlap / variance).
    overlap_method: str = "hybrid"
    variance_method: str = "estimated"

    # Auxiliary entity accounting (drives entity-gap confidence, §5.1.3).
    entities_total: int = 0
    entities_missing: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Tokenisation helpers
# --------------------------------------------------------------------------- #
def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _WORD_RE.findall(text or "")}


def _approx_token_count(text: str) -> int:
    """~4 chars/token rough estimate when no tokenizer/usage data is available."""
    return max(1, math.ceil(len(text or "") / 4))


# --------------------------------------------------------------------------- #
# Signal 1 — Context-output overlap (0.35 token Jaccard + 0.65 semantic cosine)
# --------------------------------------------------------------------------- #
def compute_overlap(output: str, context: str) -> tuple[float, str]:
    if not context.strip():
        # No grounding context → can't assess fabrication; treat as grounded.
        return 1.0, "no-context"

    out_tok, ctx_tok = _tokens(output), _tokens(context)
    union = out_tok | ctx_tok
    jaccard = len(out_tok & ctx_tok) / len(union) if union else 0.0

    embed = models.embedder()
    if embed is None:
        return round(jaccard, 4), "token-jaccard"  # fallback (§4.1)

    try:
        import numpy as np

        vecs = embed.encode([output, context], normalize_embeddings=True)
        cosine = float(np.clip(np.dot(vecs[0], vecs[1]), 0.0, 1.0))
        score = 0.35 * jaccard + 0.65 * cosine
        return round(score, 4), "hybrid"
    except Exception as e:  # model inference failed → degrade to token overlap
        log.warning("overlap embedding failed (%s); using token Jaccard", e)
        return round(jaccard, 4), "token-jaccard"


# --------------------------------------------------------------------------- #
# Signal 2 — Entity coverage (spaCy NER + regex fallback)
# --------------------------------------------------------------------------- #
def _extract_entities(text: str) -> set[str]:
    text = text if isinstance(text, str) else ("" if text is None else str(text))
    nlp = models.ner()
    if nlp is not None:
        try:
            ents = {e.text.lower() for e in nlp(text).ents}
            if ents:
                return ents
            # spaCy found nothing → fall through to regex so we still get signal.
        except Exception as e:
            log.warning("spaCy NER failed (%s); using regex fallback", e)
    regex_ents = {m.group(1).lower() for m in _ENTITY_RE.finditer(text)}
    if regex_ents:
        return regex_ents
    return _llm_entities(text)  # Tier-3 (opt-in): LLM NER when nothing else matched


def _llm_entities(text: str) -> set[str]:
    """Tier-3 NER (§7.1): only when spaCy + regex found nothing AND the user
    opted in via DEBUGAI_LLM_NER (+ an OpenAI key). Costs an LLM call, so off
    by default."""
    if not (os.environ.get("DEBUGAI_LLM_NER") and os.environ.get("OPENAI_API_KEY") and text.strip()):
        return set()
    try:
        from openai import OpenAI

        client = OpenAI(timeout=20.0, max_retries=1)
        r = client.chat.completions.create(
            model=os.environ.get("DEBUGAI_JUDGE_MODEL", "gpt-5.5"),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Extract the named entities (people, "
                 "organisations, products, places, numbers, dates) from the text. "
                 'Respond as JSON: {"entities": ["..."]}.'},
                {"role": "user", "content": text[:2000]},
            ],
        )
        data = json.loads(r.choices[0].message.content or "{}")
        return {str(e).lower() for e in data.get("entities", []) if e}
    except Exception as e:  # pragma: no cover - network dependent
        log.warning("LLM NER fallback failed (%s)", e)
        return set()


def compute_entity_coverage(output: str, context: str) -> tuple[float, int, int]:
    """Return (coverage_ratio, total_entities, missing_entities)."""
    out_ents = _extract_entities(output)
    if not out_ents:
        return 1.0, 0, 0  # nothing claimed → nothing missing
    ctx_blob = (context or "").lower()
    covered = sum(1 for e in out_ents if e in ctx_blob)
    total = len(out_ents)
    return round(covered / total, 4), total, total - covered


# --------------------------------------------------------------------------- #
# Signal 3 — Similarity (mean retrieval cosine)
# --------------------------------------------------------------------------- #
def compute_similarity(rec: CaptureRecord) -> float:
    # Trust only finite numeric scores (a client may pass None/strings/NaN).
    numeric = [float(s) for s in (rec.similarity_scores or []) if _finite(s)]
    if numeric:
        return round(sum(numeric) / len(numeric), 4)
    # No usable scores. If we have a query + chunks, compute the cosine ourselves.
    embed = models.embedder()
    if embed is not None and rec.retrieval_query and rec.retrieved_chunks:
        try:
            import numpy as np

            q = embed.encode(rec.retrieval_query, normalize_embeddings=True)
            cs = embed.encode(rec.retrieved_chunks, normalize_embeddings=True)
            sims = np.clip(cs @ q, 0.0, 1.0)
            return round(float(sims.mean()), 4)
        except Exception as e:
            log.warning("similarity recompute failed (%s); treating as healthy", e)
    return 1.0  # non-RAG request → retrieval not applicable, treat as healthy


# --------------------------------------------------------------------------- #
# Signal 4 — Contradiction (cross-encoder NLI)
# --------------------------------------------------------------------------- #
def compute_contradiction(output: str, chunks: list[str]) -> float:
    if not chunks:
        return 0.0
    model = models.nli_model()
    if model is None:
        return 0.0  # fallback: no NLI available

    try:
        import numpy as np

        pairs = [(c, output) for c in chunks]  # (premise=chunk, hypothesis=output)
        logits = np.atleast_2d(model.predict(pairs))
        if logits.shape[1] < 3:   # unexpected label layout → can't read contradiction
            return 0.0
        exp = np.exp(logits - logits.max(axis=1, keepdims=True))
        probs = exp / exp.sum(axis=1, keepdims=True)
        return round(float(probs[:, 0].max()), 4)  # label 0 = contradiction
    except Exception as e:
        log.warning("NLI contradiction failed (%s); defaulting to 0.0", e)
        return 0.0


# --------------------------------------------------------------------------- #
# Signal 5 — Output variance (proxy estimation, §7.5)
# --------------------------------------------------------------------------- #
def estimate_variance(rec: CaptureRecord) -> tuple[float, str]:
    temp = rec.temperature
    if not _finite(temp):
        return 0.0, "estimated"  # no/invalid temperature → assume deterministic
    # Base scales with sampling temperature (temp 1.5 ≈ full variance).
    base = max(0.0, min(temp / 1.5, 1.0))
    # Output-format / grounding constraints reduce realised variance.
    if _CONSTRAINT_RE.search(rec.system_prompt or "") or _CONSTRAINT_RE.search(
        rec.user_prompt or ""
    ):
        base *= 0.5
    return round(base, 4), "estimated"


def measure_variance(rerun, system_prompt: str, user_prompt: str,
                     chunks: list[str], temperature, runs: int = 3) -> float:
    """Deep-mode variance (§7.5 Tier 2): actually run the model `runs` times and
    measure output (in)stability as 1 − mean pairwise similarity. Costs N LLM
    calls, so it's opt-in (async/CI). Returns 0-1; 0.0 if it can't sample."""
    outs = []
    for _ in range(max(2, runs)):
        try:
            outs.append(rerun(system_prompt, user_prompt, chunks, temperature) or "")
        except Exception as e:
            log.warning("variance rerun failed (%s)", e)
    outs = [o for o in outs if o]
    if len(outs) < 2:
        return 0.0
    embed = models.embedder()
    if embed is not None:
        try:
            import numpy as np

            v = embed.encode(outs, normalize_embeddings=True)
            sims = np.clip(v @ v.T, 0.0, 1.0)
            n = len(outs)
            mean_pair = (sims.sum() - n) / (n * n - n)  # off-diagonal mean cosine
            return round(max(0.0, min(1.0 - float(mean_pair), 1.0)), 4)
        except Exception as e:
            log.warning("variance embedding failed (%s); using token overlap", e)
    # token fallback: mean pairwise Jaccard dissimilarity
    toks = [_tokens(o) for o in outs]
    pairs, total = 0, 0.0
    for i in range(len(toks)):
        for j in range(i + 1, len(toks)):
            u = toks[i] | toks[j]
            total += (len(toks[i] & toks[j]) / len(u)) if u else 1.0
            pairs += 1
    return round(1.0 - (total / pairs if pairs else 1.0), 4)


# --------------------------------------------------------------------------- #
# Signals 6-8 — cheap runtime / ratio signals (pure math)
# --------------------------------------------------------------------------- #
def compute_token_ratio(rec: CaptureRecord) -> float:
    usage = rec.token_usage or {}
    total = usage.get("total") or (
        usage.get("prompt", 0) + usage.get("completion", 0)
    )
    if not total:
        total = _approx_token_count(rec.full_prompt) + _approx_token_count(rec.llm_output)
    cap = rec.max_tokens or rec.context_window
    if not cap:
        return 0.0  # unknown cap → can't flag a limit
    return round(min(total / cap, 1.0), 4)


def compute_context_ratio(rec: CaptureRecord) -> float:
    window = rec.context_window
    if not window:
        return 0.0  # unknown window → capacity signal not applicable
    prompt_tokens = (
        (rec.token_usage or {}).get("prompt")
        or _approx_token_count(rec.full_prompt) + _approx_token_count(rec.context_text)
    )
    return round(min(prompt_tokens / window, 1.0), 4)


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
def compute_signals(rec: CaptureRecord, lazy: bool = False) -> SignalVector:
    """Compute the full 8-signal vector for a capture record.

    With ``lazy=True`` the expensive model-backed signals (overlap, entity
    coverage, contradiction) are skipped when the cheap signals already look
    healthy — the fail-open path described in §2.3 / §7.4.
    """
    similarity = compute_similarity(rec)
    latency = float(rec.latency_ms or 0.0)
    token_ratio = compute_token_ratio(rec)
    context_ratio = compute_context_ratio(rec)
    variance, var_method = estimate_variance(rec)

    cheap_healthy = (
        similarity >= 0.50
        and context_ratio <= 0.85
        and token_ratio <= 0.80
        and variance <= 0.30
    )
    if lazy and cheap_healthy:
        # Fail open: skip the expensive stage, assume grounded output.
        return SignalVector(
            overlap=1.0,
            entity_coverage=1.0,
            similarity=similarity,
            contradiction=0.0,
            variance=variance,
            latency_ms=latency,
            token_ratio=token_ratio,
            context_ratio=context_ratio,
            overlap_method="skipped-lazy",
            variance_method=var_method,
        )

    overlap, overlap_method = compute_overlap(rec.llm_output, rec.context_text)
    entity_coverage, ent_total, ent_missing = compute_entity_coverage(
        rec.llm_output, rec.context_text
    )
    contradiction = compute_contradiction(rec.llm_output, rec.retrieved_chunks)

    return SignalVector(
        overlap=overlap,
        entity_coverage=entity_coverage,
        similarity=similarity,
        contradiction=contradiction,
        variance=variance,
        latency_ms=latency,
        token_ratio=token_ratio,
        context_ratio=context_ratio,
        overlap_method=overlap_method,
        variance_method=var_method,
        entities_total=ent_total,
        entities_missing=ent_missing,
    )
