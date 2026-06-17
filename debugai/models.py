"""Lazy-loaded small ML models (Architecture §8.2).

These are NOT LLMs — they are tiny, fast, task-specific models that run on CPU:
  - sentence-transformers/all-MiniLM-L6-v2  (embeddings, ~80MB)
  - spaCy en_core_web_sm                    (NER, ~12MB)
  - cross-encoder/nli-MiniLM2-L6-H768       (NLI, ~120MB)

Each loader is a cached singleton so model weights load once per process. If a
model is unavailable, the loader returns ``None`` and signal computations fall
back to their deterministic pure-Python methods (per the doc's layered design).
"""

from __future__ import annotations

import functools
import logging
import os

log = logging.getLogger("debugai.models")

EMBED_MODEL = "all-MiniLM-L6-v2"
SPACY_MODEL = "en_core_web_sm"

# Three NLI modes (set via env var):
#
#   default              → cross-encoder/nli-deberta-v3-base  local (~500 MB RAM)
#                          Most accurate. Best for self-hosted VPS with ≥1 GB RAM.
#
#   DEBUGAI_LITE=1       → cross-encoder/nli-MiniLM2-L6-H768  local (~120 MB RAM)
#                          Fits in free-tier PaaS (512 MB RAM).  Slightly more
#                          false-positive contradictions but good enough.
#
#   DEBUGAI_NLI_API=1    → HuggingFace Inference API           zero local RAM
#                          Sends (premise, hypothesis) to api-inference.huggingface.co.
#                          Set HF_TOKEN for higher rate limits (free account works).
#                          Best choice for Render / Railway free tier.
_LITE    = bool(os.environ.get("DEBUGAI_LITE"))
_NLI_API = bool(os.environ.get("DEBUGAI_NLI_API"))
_DISABLE_LOCAL_MODELS = bool(os.environ.get("DEBUGAI_DISABLE_LOCAL_MODELS"))
NLI_MODEL = ("cross-encoder/nli-MiniLM2-L6-H768" if _LITE
             else "cross-encoder/nli-deberta-v3-base")
NLI_HF_MODEL_ID = "cross-encoder/nli-deberta-v3-base"  # used by the API path


@functools.lru_cache(maxsize=1)
def embedder():
    """SentenceTransformer for semantic cosine. None if unavailable."""
    if _DISABLE_LOCAL_MODELS:
        return None
    try:
        from sentence_transformers import SentenceTransformer

        log.info("loading embedding model %s", EMBED_MODEL)
        return SentenceTransformer(EMBED_MODEL)
    except Exception as e:  # pragma: no cover - environment dependent
        log.warning("embedder unavailable (%s); using token-overlap fallback", e)
        return None


@functools.lru_cache(maxsize=1)
def nli_model():
    """CrossEncoder NLI model. Returns label-ordered logits. None if unavailable.

    When DEBUGAI_NLI_API=1 this returns a special sentinel object that tells
    compute_contradiction() to call the HuggingFace Inference API instead.
    """
    if _DISABLE_LOCAL_MODELS and not _NLI_API:
        return None
    if _NLI_API:
        return _HFNLISentinel()
    try:
        from sentence_transformers import CrossEncoder

        log.info("loading NLI model %s", NLI_MODEL)
        return CrossEncoder(NLI_MODEL)
    except Exception as e:  # pragma: no cover - environment dependent
        log.warning("NLI model unavailable (%s); contradiction set to 0.0", e)
        return None


class _HFNLISentinel:
    """Marker returned by nli_model() when DEBUGAI_NLI_API=1.
    compute_contradiction() detects this and calls the HF Inference API."""
    is_hf_api = True


@functools.lru_cache(maxsize=1)
def ner():
    """spaCy NER pipeline. None if unavailable (regex fallback used instead)."""
    if _DISABLE_LOCAL_MODELS:
        return None
    try:
        import spacy

        log.info("loading spaCy model %s", SPACY_MODEL)
        return spacy.load(SPACY_MODEL)
    except Exception as e:  # pragma: no cover - environment dependent
        log.warning("spaCy model unavailable (%s); using regex NER fallback", e)
        return None
