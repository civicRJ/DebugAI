"""The five built-in fix agents (Architecture §8.3).

Each targets one failure type and ships a deterministic fix template. (Fix text
can be LLM-drafted when a key is present, but the templates make the framework
work — and verify — offline.) Generation is the only probabilistic step; the
loop in ``base.FixAgent.run`` verifies every fix deterministically.
"""

from __future__ import annotations

from debugai.agents.base import FixAgent
from debugai.agents.types import FixCandidate, TestCase
from debugai.detectors import (
    CONTEXT_OVERFLOW, ENTITY_GAP, HALLUCINATION, PROMPT_BRITTLENESS, RETRIEVAL_FAILURE,
)
from debugai.schema import CaptureRecord


def _first(xs: list[str], n: int) -> list[str]:
    return [x for x in xs[:n] if x]


# --------------------------------------------------------------------------- #
# 1. Prompt Rule Agent — hallucination
# --------------------------------------------------------------------------- #
class PromptRuleAgent(FixAgent):
    name = "Prompt Rule Agent"
    handles = HALLUCINATION

    GROUNDING = (
        "Answer ONLY using the provided context. If the context does not contain "
        "the answer, reply exactly: \"I don't have that information.\" Never invent "
        "names, numbers, dates, clauses, or citations. For every specific claim, the "
        "supporting text must appear in the context."
    )

    def generate_fix(self, diagnosis, record):
        return FixCandidate(
            agent=self.name, failure=self.handles,
            strategy="Add grounding constraints + an out-of-context fallback to the system prompt.",
            rationale="Retrieval succeeded but the output is ungrounded — constrain "
                      "generation to the supplied context.",
            system_prompt_additions=self.GROUNDING,
        )

    def build_test_cases(self, diagnosis, record):
        fab = self._fabricated_entities(record)
        grounded = self._grounded_entities(record)
        tests = [
            TestCase(input=record.user_prompt, must_not_contain=_first(fab, 4),
                     category="original"),
            TestCase(input=record.user_prompt, must_not_contain=_first(fab, 4),
                     category="variance", runs=3),
        ]
        if grounded:
            tests.append(TestCase(input=record.user_prompt,
                                  must_contain=_first(grounded, 1), category="regression"))
        return tests


# --------------------------------------------------------------------------- #
# 2. Knowledge Base Agent — retrieval failure
# --------------------------------------------------------------------------- #
class KnowledgeBaseAgent(FixAgent):
    name = "Knowledge Base Agent"
    handles = RETRIEVAL_FAILURE
    verifiable_by_rerun = False  # real fix is re-chunking/re-embedding the corpus

    GUARD = (
        "If the retrieved context does not address the question, reply exactly: "
        "\"The knowledge base does not contain this information.\" Do not answer "
        "from prior knowledge."
    )

    def generate_fix(self, diagnosis, record):
        sim = ((diagnosis.get("signals") or {}).get("similarity"))
        return FixCandidate(
            agent=self.name, failure=self.handles,
            strategy="Re-chunk source docs entity-aware + add an interim 'not in KB' guard.",
            rationale=f"Mean retrieval similarity {sim} is below threshold — the "
                      "retriever returned irrelevant chunks.",
            system_prompt_additions=self.GUARD,
            notes="Re-chunk the source corpus with an entity-aware strategy and "
                  "re-embed; verify the target document is actually indexed.",
        )

    def build_test_cases(self, diagnosis, record):
        fab = self._fabricated_entities(record)
        return [
            TestCase(input=record.user_prompt, must_not_contain=_first(fab, 4),
                     category="original"),
            TestCase(input=record.user_prompt, must_not_contain=_first(fab, 4),
                     category="variance", runs=3),
        ]


# --------------------------------------------------------------------------- #
# 3. Constraint Agent — prompt brittleness
# --------------------------------------------------------------------------- #
class ConstraintAgent(FixAgent):
    name = "Constraint Agent"
    handles = PROMPT_BRITTLENESS

    TEMPLATE = (
        "Be deterministic and consistent across runs. Follow a fixed output format "
        "and do not vary phrasing, ordering, or structure between identical inputs."
    )

    def generate_fix(self, diagnosis, record):
        return FixCandidate(
            agent=self.name, failure=self.handles,
            strategy="Lower temperature, add an output-format template, and pin behavior with a few-shot example.",
            rationale="Grounding signals are healthy but output variance is high — "
                      "constrain sampling and format.",
            new_temperature=0.2,
            system_prompt_additions=self.TEMPLATE,
            few_shot_examples=[{"input": record.user_prompt, "output": record.llm_output}],
        )

    def build_test_cases(self, diagnosis, record):
        grounded = self._grounded_entities(record)
        mc = _first(grounded, 1)
        return [
            TestCase(input=record.user_prompt, must_contain=mc, category="regression"),
            TestCase(input=record.user_prompt, must_contain=mc, category="variance", runs=3),
        ]


# --------------------------------------------------------------------------- #
# 4. Context Optimizer Agent — context overflow
# --------------------------------------------------------------------------- #
class ContextOptimizerAgent(FixAgent):
    name = "Context Optimizer Agent"
    handles = CONTEXT_OVERFLOW

    def generate_fix(self, diagnosis, record):
        return FixCandidate(
            agent=self.name, failure=self.handles,
            strategy="Reduce to the top-N most relevant chunks and summarize each to fit the window.",
            rationale="The prompt overflows the context window; trim and compress "
                      "the retrieved context.",
            max_chunks=8,
            chunk_char_budget=240,
            notes="Summarize prior conversation history; consider a larger-context model.",
        )

    def build_test_cases(self, diagnosis, record):
        grounded = self._grounded_entities(record)
        return [
            TestCase(input=record.user_prompt, must_contain=_first(grounded, 1),
                     category="regression"),
        ]


# --------------------------------------------------------------------------- #
# 5. Document Patch Agent — entity gap (escalates)
# --------------------------------------------------------------------------- #
class DocumentPatchAgent(FixAgent):
    name = "Document Patch Agent"
    handles = ENTITY_GAP

    def generate_fix(self, diagnosis, record):
        missing = self._fabricated_entities(record)  # entities not in the corpus
        names = ", ".join(_first(missing, 6)) or "the requested entities"
        return FixCandidate(
            agent=self.name, failure=self.handles,
            strategy="Identify missing entities and flag the knowledge-base gap for human review.",
            rationale="Retrieval is healthy but the corpus lacks coverage for these "
                      "entities — content cannot be safely auto-generated.",
            notes=f"Knowledge base needs articles covering: {names}.",
            escalate=True,
        )

    def build_test_cases(self, diagnosis, record):
        return []  # escalated before tests run


BUILTIN_AGENTS = [
    PromptRuleAgent,
    KnowledgeBaseAgent,
    ConstraintAgent,
    ContextOptimizerAgent,
    DocumentPatchAgent,
]
