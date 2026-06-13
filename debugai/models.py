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

log = logging.getLogger("debugai.models")

EMBED_MODEL = "all-MiniLM-L6-v2"
# DeBERTa-v3 NLI: far fewer false-positive contradictions than MiniLM2 on
# neutral attribute-additions (§7.1), which fixes entity_gap↔hallucination mixups.
NLI_MODEL = "cross-encoder/nli-deberta-v3-base"
SPACY_MODEL = "en_core_web_sm"


@functools.lru_cache(maxsize=1)
def embedder():
    """SentenceTransformer for semantic cosine. None if unavailable."""
    try:
        from sentence_transformers import SentenceTransformer

        log.info("loading embedding model %s", EMBED_MODEL)
        return SentenceTransformer(EMBED_MODEL)
    except Exception as e:  # pragma: no cover - environment dependent
        log.warning("embedder unavailable (%s); using token-overlap fallback", e)
        return None


@functools.lru_cache(maxsize=1)
def nli_model():
    """CrossEncoder NLI model. Returns label-ordered logits. None if unavailable."""
    try:
        from sentence_transformers import CrossEncoder

        log.info("loading NLI model %s", NLI_MODEL)
        return CrossEncoder(NLI_MODEL)
    except Exception as e:  # pragma: no cover - environment dependent
        log.warning("NLI model unavailable (%s); contradiction set to 0.0", e)
        return None


@functools.lru_cache(maxsize=1)
def ner():
    """spaCy NER pipeline. None if unavailable (regex fallback used instead)."""
    try:
        import spacy

        log.info("loading spaCy model %s", SPACY_MODEL)
        return spacy.load(SPACY_MODEL)
    except Exception as e:  # pragma: no cover - environment dependent
        log.warning("spaCy model unavailable (%s); using regex NER fallback", e)
        return None
