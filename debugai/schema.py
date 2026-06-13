"""SDK capture schema (Architecture §3).

The unified payload every integration level produces. Only the Core IO group is
strictly required; retrieval and runtime groups unlock RAG-specific and
capacity signals respectively.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CaptureRecord:
    """Unified request payload: prompt + context + output + metadata.

    Groups (§3.1):
      Core IO          — minimum viable input (required).
      Retrieval        — RAG-specific signals.
      Metadata         — pipeline configuration.
      Runtime          — auto-captured metrics.
    """

    # --- Core IO (required) ---
    user_prompt: str
    llm_output: str
    system_prompt: str = ""
    expected_output: str | None = None

    # --- Retrieval context (RAG) ---
    retrieved_chunks: list[str] = field(default_factory=list)
    similarity_scores: list[float] = field(default_factory=list)
    retrieval_query: str | None = None
    chunk_sources: list[dict[str, Any]] = field(default_factory=list)

    # --- Pipeline metadata ---
    model_name: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    # --- Runtime metrics ---
    latency_ms: int | None = None
    token_usage: dict[str, int] = field(default_factory=dict)
    timestamp: str | None = None
    error_code: str | None = None

    # --- Optional capacity hints (used by ratio signals) ---
    context_window: int | None = None  # model's max context window in tokens

    def __post_init__(self) -> None:
        if not self.user_prompt:
            raise ValueError("user_prompt is required (Core IO)")
        if self.llm_output is None:
            raise ValueError("llm_output is required (Core IO)")

    @property
    def context_text(self) -> str:
        """Concatenated retrieved chunks — the 'grounding' the output should rest on."""
        return "\n".join(self.retrieved_chunks)

    @property
    def full_prompt(self) -> str:
        """System + user prompt combined (used for context-length accounting)."""
        return (self.system_prompt + "\n" + self.user_prompt).strip()
